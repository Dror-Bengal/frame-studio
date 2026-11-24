"""Browser acceptance tests. Run with python -m unittest discover -s tests -v."""
import base64
import os
import struct
import tempfile
import unittest
import zlib
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(os.environ.get("EDITOR_ROOT", Path(__file__).resolve().parents[1]))


def fixture():
    """Generate a striped RGB image so a change in crop changes the pixels."""
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    row = bytes([0]) + b"".join(bytes((x, 48, 80)) for x in range(200))
    header = struct.pack(">2I5B", 200, 100, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(row * 100)) + chunk(b"IEND", b"")


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class EditorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(ROOT)))
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"
        cls.pw = sync_playwright().start()
        engine = getattr(cls.pw, os.environ.get("BROWSER_ENGINE", "chromium"))
        cls.browser = engine.launch(channel=os.environ.get("BROWSER_CHANNEL") or None)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.ctx = self.browser.new_context(locale="de-DE", viewport={"width": 1100, "height": 850})
        self.p = self.ctx.new_page()
        self.external = []
        self.errors = []
        def route(req):
            if urlsplit(req.request.url).netloc == urlsplit(self.origin).netloc:
                req.continue_()
            else:
                self.external.append(req.request.url)
                req.abort()
        self.ctx.route(r"**/*", lambda req: route(req) if req.request.url.startswith(("http:", "https:")) else req.continue_())
        self.p.on("pageerror", lambda exc: self.errors.append(str(exc)))
        self.p.goto(self.origin)
        self.p.set_default_timeout(3500)

    def tearDown(self):
        self.ctx.close()
        self.assertEqual([], self.errors)
        self.assertEqual([], self.external)

    def upload(self):
        self.p.locator('input[type=file]').set_input_files({"name":"fixture.png", "mimeType":"image/png", "buffer":fixture()})
        self.p.get_by_text("Photo ready.", exact=True).wait_for()
        self.assertEqual(self.p.locator('#cv').evaluate("c=>c.getContext('2d').getImageData(416,416,1,1).data[1]"), 48)

    def snapshot(self):
        return self.p.locator("#cv").evaluate("c => c.toDataURL()")

    def verify_download(self, button):
        expected = base64.b64decode(self.snapshot().split(",")[1])
        with self.p.expect_download(timeout=3500) as event:
            button.click()
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "result.png"
            event.value.save_as(file)
            png = file.read_bytes()
        self.assertEqual(expected, png)
        self.assertEqual(struct.unpack(">II", png[16:24]), (833,833))
        self.assertEqual(event.value.suggested_filename, "framed-photo.png")

    def test_share_fallback_downloads_the_composed_image(self):
        self.upload()
        self.p.evaluate("Object.defineProperty(navigator,'canShare',{configurable:true,value:()=>false})")
        self.verify_download(self.p.get_by_role("button", name="Share image"))
        self.assertIn("attach", self.p.locator("#status").inner_text().lower())

    def test_crop_two_frames_and_download(self):
        self.upload()
        first = self.snapshot()
        def corner():
            return self.p.locator("#cv").evaluate("c=>Array.from(c.getContext('2d').getImageData(2,2,1,1).data)")
        self.assertEqual(corner(), [255,242,217,255])
        self.p.get_by_role("button", name="Orbit", exact=True).click()
        self.assertNotEqual(first, self.snapshot())
        self.assertEqual(corner(), [37,56,67,255])
        self.verify_download(self.p.get_by_role("button", name="Download PNG"))
        before = self.snapshot()
        rect = self.p.locator("#cv").bounding_box()
        x, y = rect["x"]+rect["width"]/2, rect["y"]+rect["height"]/2
        self.p.mouse.move(x,y)
        self.p.mouse.down()
        self.p.mouse.move(x+36,y+10)
        self.p.mouse.up()
        self.assertNotEqual(before, self.snapshot())
        self.p.locator("input[type=range]").focus()
        self.p.keyboard.press("ArrowRight")
        self.assertNotEqual("100%", self.p.locator("output").inner_text())
        self.p.get_by_role("button", name="Reset crop").click()
        self.assertEqual(before, self.snapshot())
        self.p.get_by_role("button", name="Mat", exact=True).click()
        self.assertEqual(first, self.snapshot())
        self.verify_download(self.p.get_by_role("button", name="Download PNG"))

    def test_native_share_receives_the_png(self):
        self.upload()
        self.p.evaluate("""() => {
            Object.defineProperty(navigator,'canShare',{value:()=>true});
            Object.defineProperty(navigator,'share',{value:async data=>{
                const reader = new FileReader();
                reader.onload = () => {
                    window.shared = [data.files[0].name,reader.result];
                    document.documentElement.dataset.shared = 'ready';
                };
                reader.readAsDataURL(data.files[0]);
            }});
        }""")
        self.p.get_by_role("button", name="Share image").click()
        self.p.locator("html[data-shared=ready]").wait_for()
        self.assertEqual(self.p.evaluate("window.shared"), ["framed-photo.png",self.snapshot()])

    def test_share_cancellation_and_permission_failure(self):
        self.upload()
        self.p.evaluate("""() => {
            Object.defineProperty(navigator,'canShare',{value:()=>true});
            window.shareError='AbortError';
            Object.defineProperty(navigator,'share',{value:async()=>{throw new DOMException('Test',window.shareError)}});
        }""")
        downloads = []
        self.p.on("download", lambda event: downloads.append(event))
        self.p.get_by_role("button", name="Share image").click()
        self.assertIn("cancel", self.p.locator("#status").inner_text().lower())
        self.assertFalse(downloads)
        self.p.evaluate("window.shareError='NotAllowedError'")
        self.verify_download(self.p.get_by_role("button", name="Share image"))

    def test_invalid_replacement_preserves_current_image(self):
        self.upload()
        before = self.snapshot()
        self.p.locator('input[type=file]').set_input_files({"name":"broken.png","mimeType":"image/png","buffer":b"invalid"})
        self.p.get_by_text("Could not open that image.", exact=False).wait_for()
        self.assertEqual(before,self.snapshot())
        self.verify_download(self.p.get_by_role("button", name="Download PNG"))

    def test_mobile_sample_works_offline(self):
        self.p.set_viewport_size({"width":360,"height":740})
        self.ctx.set_offline(True)
        self.assertEqual("en",self.p.locator("html").get_attribute("lang"))
        self.assertTrue(self.p.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        self.verify_download(self.p.get_by_role("button", name="Download PNG"))

    def test_drop_and_restore_sample(self):
        initial = self.snapshot()
        png = base64.b64encode(fixture()).decode()
        self.p.evaluate("""data => {
            const transfer = new DataTransfer();
            const bytes = Uint8Array.from(atob(data), c=>c.charCodeAt(0));
            transfer.items.add(new File([bytes],'drop.png',{type:'image/png'}));
            document.querySelector('#board').dispatchEvent(new DragEvent('drop',{bubbles:true,dataTransfer:transfer}));
        }""", png)
        self.p.get_by_text("Photo ready.", exact=True).wait_for()
        self.assertNotEqual(initial, self.snapshot())
        self.p.get_by_role("button", name="Use sample").click()
        self.assertEqual(initial, self.snapshot())

    def test_direct_file_export_without_server(self):
        # WebKit's offline emulator also blocks local image loads on file URLs.
        # Deny every HTTP(S) request while allowing the local document and image data.
        def deny_http(route):
            self.external.append(route.request.url)
            route.abort()
        self.p.route("http*/**", deny_http)
        self.p.goto((ROOT / "index.html").as_uri(), wait_until="domcontentloaded")
        self.upload()
        self.verify_download(self.p.get_by_role("button", name="Download PNG"))
