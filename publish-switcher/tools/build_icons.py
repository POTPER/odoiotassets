"""Render the software icon. Pillow is needed only when rebuilding artwork."""
from pathlib import Path

from PIL import Image, ImageDraw


def build():
    output = Path(__file__).resolve().parents[1] / "icons"
    output.mkdir(exist_ok=True)
    scale = 4
    image = Image.new("RGBA", (256 * scale, 256 * scale))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8 * scale, 8 * scale, 248 * scale, 248 * scale),
                           radius=56 * scale, fill="#2563eb")
    arrows = (
        ((59, 79), (158, 79), (158, 57), (199, 98), (158, 139), (158, 117), (59, 117)),
        ((197, 139), (98, 139), (98, 117), (57, 158), (98, 199), (98, 177), (197, 177)),
    )
    for arrow in arrows:
        draw.polygon([(x * scale, y * scale) for x, y in arrow], fill="white")
    for size in (16, 24, 32, 48, 64, 128, 256):
        image.resize((size, size), Image.Resampling.LANCZOS).save(output / f"swicher-{size}.png")


if __name__ == "__main__":
    build()
