"""Regenerate the app icons (assets/icon.png + assets/icon.ico).

Dev tool only, not shipped: run `.venv/bin/python assets/make_icon.py` from
the repo root. Requires Pillow (installed with the dev extras).
"""

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 256
OUT = Path(__file__).resolve().parent


def draw() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Rounded-square backdrop.
    d.rounded_rectangle([8, 8, SIZE - 8, SIZE - 8], radius=56, fill="#242933")
    # Two viewers (simple dots) above the play glyph.
    d.ellipse([76, 44, 116, 84], fill="#E6E6E6")
    d.ellipse([140, 44, 180, 84], fill="#9DC3E6")
    # Play triangle.
    d.polygon([(88, 108), (88, 204), (196, 156)], fill="#4CAF50")
    return img


def main() -> None:
    img = draw()
    img.save(OUT / "icon.png")
    img.save(
        OUT / "icon.ico",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("wrote", OUT / "icon.png", "and", OUT / "icon.ico")


if __name__ == "__main__":
    main()
