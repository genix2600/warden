"""Derive every icon Warden needs from one source image.

The logo arrives as a mark floating in a 1920x1080 frame. Windows wants a square
multi-resolution ``.ico`` for the taskbar and File Explorer, the desktop
interface wants a PNG it can scale, and the website wants its own copy. Doing
that by hand once means doing it again badly the next time the logo changes, so
it is a script.

Run it after replacing ``assets/wardenlogo.png``::

    .venv\\Scripts\\python.exe scripts/make-icons.py

Requires Pillow, which is a build-time dependency only -- nothing Warden ships
imports it.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "wardenlogo.png"
ASSETS = ROOT / "assets"

#: Windows picks the nearest size and scales the rest, so shipping the small
#: ones matters more than the large: a 256 downscaled to 16 by the shell turns
#: into mush, while a purpose-made 16 stays legible in the taskbar.
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

#: Where the derived copies land. Each consumer bundles from its own tree, so
#: the file has to exist inside each rather than be referenced across.
PNG_TARGETS = {
    ASSETS / "warden-512.png": 512,
    ROOT / "ui" / "public" / "warden.png": 256,
    ROOT / "site" / "app" / "icon.png": 256,
}


def square(image: Image.Image) -> Image.Image:
    """Crop to the visible mark, then pad back to a square with a little air.

    The source has the mark centred in a widescreen frame, so cropping to the
    alpha bounding box is what turns it into an icon rather than a mark with
    two-thirds empty space either side -- which at 16 pixels would leave the
    actual logo about five pixels across.
    """
    bbox = image.getbbox()
    if bbox is None:
        raise SystemExit(f"{SOURCE} is fully transparent")
    mark = image.crop(bbox)

    # A small margin, because Windows draws icons flush to their bounds and a
    # mark touching the edge reads as clipped.
    side = int(max(mark.size) * 1.10)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(mark, ((side - mark.width) // 2, (side - mark.height) // 2), mark)
    return canvas


def main() -> int:
    if not SOURCE.is_file():
        raise SystemExit(f"no source logo at {SOURCE}")

    source = Image.open(SOURCE).convert("RGBA")
    mark = square(source)
    print(f"source {source.size[0]}x{source.size[1]} -> mark {mark.size[0]}x{mark.size[1]}")

    ico = ASSETS / "warden.ico"
    mark.save(ico, format="ICO", sizes=ICO_SIZES)
    print(f"  {ico.relative_to(ROOT)}  ({', '.join(str(w) for w, _ in ICO_SIZES)})")

    for target, size in PNG_TARGETS.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        mark.resize((size, size), Image.LANCZOS).save(target, format="PNG", optimize=True)
        print(f"  {target.relative_to(ROOT)}  ({size}px)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
