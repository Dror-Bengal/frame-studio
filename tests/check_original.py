"""Exercise the original two-step editor against its running HTTP entry point."""
import argparse
import base64
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
PHOTO = ROOT / "editor/example/chelsea.png"
PIXELS = """(cv) => {
    const ctx = cv.getContext('2d');
    return [[180,150], [410,420], [530,250], [690,530]].map(([x,y]) =>
        Array.from(ctx.getImageData(x,y,1,1).data));
}"""


def verify(browser, url, mobile, output):
    context = browser.new_context(
        viewport={"width": 438 if mobile else 1200, "height": 920},
        accept_downloads=True, has_touch=mobile, is_mobile=mobile
    )
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def local_only(route):
        u = urlsplit(route.request.url)
        if u.scheme in ("blob", "data") or (u.netloc == urlsplit(url).netloc and route.request.method == "GET"):
            route.continue_()
        else:
            errors.append(f"Unexpected network request: {route.request.method} {u.netloc}")
            route.abort()
    context.route("**/*", local_only)
    page.goto(url)
    upload = page.get_by_label("Choose a photo", exact=True)
    with page.expect_file_chooser() as picker:
        upload.click()
    picker.value.set_files(PHOTO)
    download = page.get_by_role("button", name="Download PNG")
    expect(download).to_be_enabled()
    canvas = page.locator("#cv")
    # Independently cover-fit the source photo to a reference canvas.
    reference = page.evaluate("""async () => {
        const im=new Image();
        im.src='example/chelsea.png';
        await im.decode();
        const cv=document.createElement('canvas');
        cv.width=cv.height=833;
        const scale=833/im.height;
        cv.getContext('2d').drawImage(im,(833-im.width*scale)/2,0,im.width*scale,833);
        return (""" + PIXELS + """)(cv);
    }""")
    assert canvas.evaluate(PIXELS) == reference

    def export_frame(name, color):
        button = page.get_by_role("button", name=name + " frame")
        (button.tap if mobile else button.click)()
        expect(button).to_have_attribute("aria-pressed", "true")
        expect(download).to_be_enabled()
        with page.expect_download() as saved:
            (download.tap if mobile else download.click)()
        file = saved.value
        assert file.suggested_filename == "framed-photo.png"
        path = output / (name.lower() + ".png")
        file.save_as(path)
        raw = path.read_bytes()
        assert raw.startswith(b"\x89PNG\r\n\x1a\n")
        # Read the downloaded file into a separate image. Verify its decoded
        # dimensions, border and photo pixels; compare the full file to the canvas.
        encoded = base64.b64encode(raw).decode()
        assert encoded == canvas.evaluate("c => c.toDataURL('image/png').split(',')[1]")
        result = page.evaluate("""async b64 => {
            const im=new Image();
            im.src='data:image/png;base64,'+b64;
            await im.decode();
            const cv=document.createElement('canvas');
            cv.width=im.width; cv.height=im.height;
            const ctx=cv.getContext('2d'); ctx.drawImage(im,0,0);
            return [[im.width,im.height], Array.from(ctx.getImageData(4,4,1,1).data),
                    (""" + PIXELS + """)(cv)];
        }""", encoded)
        assert result[0] == [833, 833] and result[1] == color, result[:2]
        return result[2]

    assert export_frame("Ivory", [248, 237, 210, 255]) == reference
    zoom = page.get_by_role("slider", name="Photo zoom")
    zoom.focus()
    for _ in range(4):
        zoom.press("ArrowRight")
    cropped = canvas.evaluate(PIXELS)
    assert cropped != reference
    assert export_frame("Teal", [36, 71, 76, 255]) == cropped
    expect(zoom).to_have_value("1.2")
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=output / "editor.png", full_page=True, animations="disabled")
    page.get_by_role("button", name="Start over").click()
    expect(download).to_be_disabled()
    upload.set_input_files({"name":"broken.png","mimeType":"image/png","buffer":b"not an image"})
    expect(page.get_by_role("status")).to_contain_text("could not be opened")
    upload.set_input_files(PHOTO)
    expect(download).to_be_enabled()
    assert canvas.evaluate(PIXELS) == reference
    assert not errors, errors
    context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18796")
    parser.add_argument("--mobile", action="store_true")
    parser.add_argument("--capture", type=Path)
    options = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        output = options.capture or Path(tmp)
        output.mkdir(exist_ok=True, parents=True)
        engine = getattr(pw, os.environ.get("BROWSER_ENGINE", "chromium"))
        browser = engine.launch()
        verify(browser, options.url, options.mobile, output)
        browser.close()
    print("PASS: photo upload, both 833 x 833 PNG downloads, crop, border and photo pixels, reset and recovery.")
