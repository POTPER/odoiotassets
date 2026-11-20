"""Render the project's own vector geometry to desktop PNG/ICO sizes."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def build():
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
<rect x="8" y="8" width="240" height="240" rx="54" fill="#111b2b"/>
<rect x="43" y="52" width="170" height="155" rx="25" fill="#1d3046" stroke="#8ba9c5" stroke-width="7"/>
<path d="M47 100H209" stroke="#8ba9c5" stroke-width="6"/>
<g fill="#4addd5"><circle cx="67" cy="77" r="6"/><circle cx="87" cy="77" r="6"/></g>
<path d="M104 124L104 180L151 152Z" fill="#4addd5" stroke="#4addd5" stroke-linejoin="round" stroke-width="6"/>
<path d="M211 137H230V177H211" fill="none" stroke="#4addd5" stroke-width="8" stroke-linejoin="round"/>
<path d="M75 207V225M110 207V225M145 207V225M180 207V225" stroke="#8ba9c5" stroke-width="8" stroke-linecap="round"/>
</svg>'''
    (assets / "workbench-icon.svg").write_text(svg + "\n", encoding="utf-8")
    scale = 4
    image = Image.new("RGBA", (256 * scale, 256 * scale))
    draw = ImageDraw.Draw(image)
    def box(bounds): return tuple(round(v * scale) for v in bounds)
    def line(points, color, width):
        draw.line([(x * scale, y * scale) for x, y in points], fill=color, width=width * scale, joint="curve")
    draw.rounded_rectangle(box((8, 8, 248, 248)), radius=54 * scale, fill="#111b2b")
    # Pins and bus are behind the control panel, keeping a clean small-size silhouette.
    for x in (75, 110, 145, 180):
        line([(x, 202), (x, 225)], "#8ba9c5", 8)
        draw.ellipse(box((x - 4, 221, x + 4, 229)), fill="#8ba9c5")
    line([(208, 137), (230, 137), (230, 177), (208, 177)], "#4addd5", 8)
    draw.rounded_rectangle(box((43, 52, 213, 207)), radius=25 * scale, fill="#1d3046", outline="#8ba9c5", width=7 * scale)
    line([(47, 100), (209, 100)], "#8ba9c5", 6)
    for x in (67, 87):
        draw.ellipse(box((x - 6, 71, x + 6, 83)), fill="#4addd5")
    draw.polygon([(104 * scale, 124 * scale), (104 * scale, 180 * scale), (151 * scale, 152 * scale)], fill="#4addd5")
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    master = image.resize((512, 512), resampling)
    master.save(assets / "workbench-icon.png")
    master.save(ROOT / "launcher/assets/icon.png")
    master.save(ROOT / "launcher/assets/sidebar-icon.png")
    icons = ROOT / "engineer/icons"
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        master.resize((size, size), resampling).save(icons / ("publish-switcher-{}.png".format(size)))
    master.save(assets / "workbench.ico", sizes=[(s, s) for s in (16, 32, 48, 64, 128, 256)])
    (icons / "publish-switcher.svg").write_text(svg + "\n", encoding="utf-8")
    (icons / "publish-switcher.ico").write_bytes((assets / "workbench.ico").read_bytes())
    print(assets / "workbench-icon.png")


if __name__ == "__main__":
    build()
