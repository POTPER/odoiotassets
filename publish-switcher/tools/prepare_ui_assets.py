"""Export deployment-sized PNGs from generated artwork; Pillow is build-time only."""
import base64
from pathlib import Path
from PIL import Image


def build():
    root = Path(__file__).resolve().parents[1]
    source = root.parent / "design-assets/swicher-v10"
    ui = root / "assets/ui"
    ui.mkdir(parents=True, exist_ok=True)
    icons = root / "icons"
    resample = getattr(Image, "Resampling", Image).LANCZOS

    def square(name, size, destination):
        with Image.open(source / name) as original:
            image = original.convert("RGBA")
            image.thumbnail((size, size), resample)
            canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            canvas.paste(image, ((size-image.width)//2, (size-image.height)//2))
            canvas.save(destination, optimize=True)

    with Image.open(source / "sidebar-background.png") as original:
        original.resize((256, 768), resample).save(ui / "sidebar-background-v10.png", optimize=True)
    for size in (64, 112):
        square("update-hero.png", size, ui / "update-hero-{}.png".format(size))
    for kind in ("update", "config"):
        for size in (24, 40):
            square(kind + "-icon.png", size, ui / "{}-icon-{}.png".format(kind, size))
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        square("app-icon.png", size, icons / "swicher-v10-{}.png".format(size))
    payload = base64.b64encode((icons / "swicher-v10-512.png").read_bytes()).decode("ascii")
    (icons / "swicher-v10.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="512" height="512" viewBox="0 0 512 512">'
        '<image width="512" height="512" xlink:href="data:image/png;base64,' + payload + '"/></svg>\n', encoding="utf-8")
    print("Prepared bundled PNG assets and window/desktop icon sizes.")


if __name__ == "__main__":
    build()
