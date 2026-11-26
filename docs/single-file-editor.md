# Frame Studio

Frame a photo and save a square, 833 × 833 PNG. Open **index.html** directly in a browser. The editor includes a generated sample and two frame styles. It works offline and needs no account, build step, or runtime dependencies.

## Try it

1. Choose a JPG, PNG, or WebP, or drop it on the editor.
2. Choose **Mat** or **Orbit**. Drag the picture to position it. Use the zoom slider, scroll wheel, or pinch gesture to scale it. With the preview focused, the arrow keys move the picture. **Reset crop** restores the centered crop.
3. Use **Download PNG** to save the preview. **Share image** opens the native share sheet on supported browsers. If file sharing is unavailable or denied, the editor downloads the same PNG for attachment. Cancelling the picker keeps the current edit.

The photo and its filename stay on the device during editing. The exported file is named **framed-photo.png**. Choosing a destination in the operating system's share sheet transfers the file to that destination.

## Serve locally

To test HTTP or native sharing on localhost, run the following in the project directory, then open <http://127.0.0.1:8000/>.

```sh
python3 -m http.server 8000 --bind 127.0.0.1
```

## Browser tests

Python 3.10+ and Playwright are needed only for the tests. From the project directory on macOS or Linux:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r tests/requirements.txt
python -m playwright install chromium webkit
python -m unittest discover -s tests -v
BROWSER_ENGINE=webkit python -m unittest discover -s tests -v
```

Tests generate their own image, compare downloaded PNG bytes with the preview, and verify frame colors and dimensions. They cover crop, zoom, reset, dropping files, invalid images, mobile layout and direct file use. They exercise the browser share API with a test double so they can check the file payload, cancellation and permission failure without sending an image.
