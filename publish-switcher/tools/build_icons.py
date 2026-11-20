"""Rebuild the SVG design as antialiased PNG/ICO assets (developer-only Pillow)."""
from pathlib import Path

from PIL import Image, ImageDraw


def build():
    directory = Path(__file__).resolve().parents[1] / "icons"
    scale = 4
    edge = 512 * scale
    image = Image.new("RGBA", (edge, edge))
    mask = Image.new("L", (edge, edge))
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((24 * scale, 24 * scale, 488 * scale, 488 * scale),
                           radius=108 * scale, fill=255)
    gradient = Image.new("RGBA", (edge, edge))
    pixels = ImageDraw.Draw(gradient)
    top, bottom = (38, 50, 72), (16, 16, 20)
    for y in range(edge):
        fraction = max(0, min(1, (y / scale - 24) / 464))
        colour = tuple(round(a + (b - a) * fraction) for a, b in zip(top, bottom))
        pixels.line((0, y, edge, y), fill=colour + (255,))
    image.paste(gradient, (0, 0), mask)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((24 * scale, 24 * scale, 488 * scale, 488 * scale),
                           radius=108 * scale, outline="#42516b", width=4 * scale)

    def stroke(points, colour):
        points = [(round(x * scale), round(y * scale)) for x, y in points]
        draw.line(points, fill=colour, width=36 * scale, joint="curve")
        for x, y in points:
            r = 18 * scale
            draw.ellipse((x - r, y - r, x + r, y + r), fill=colour)

    # Quadratic elbow, sampled from the same geometry as the editable SVG.
    bend = [(152 + 24 * (i / 32) ** 2, 182 + 24 * (1 - i / 32) ** 2)
            for i in range(33)]
    upper = [(152, 244), (152, 206)] + bend + [(360, 182)]
    stroke(upper, "#f5f5f7")
    stroke([(316, 138), (360, 182), (316, 226)], "#f5f5f7")
    stroke([(512 - x, 512 - y) for x, y in upper], "#a8ceff")
    stroke([(196, 286), (152, 330), (196, 374)], "#a8ceff")
    master = image.resize((512, 512), Image.Resampling.LANCZOS)
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        master.resize((size, size), Image.Resampling.LANCZOS).save(
            directory / "publish-switcher-{}.png".format(size))
    master.save(directory / "publish-switcher.ico", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    print("PNG / ICO icons rebuilt:", directory)


if __name__ == "__main__":
    build()
