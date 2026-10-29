"""Draw docs/images/logo.png: the AICAD mark (an isometric solid with a
section cut and the AI spark, as in the favicon) and the name."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent


def main():
    S = 22                       # pixels per unit of the 24-unit icon
    W, H = 1500, 560
    img = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    ox, oy = 20, 15

    def P(pts):
        return [(ox + x * S, oy + y * S) for x, y in pts]
    d.polygon(P([(12, 1.6), (21.2, 6.9), (21.2, 17.3), (12, 22.6), (2.8, 17.3), (2.8, 6.9)]), fill="#0b62c4")
    d.polygon(P([(12, 1.6), (21.2, 6.9), (12, 12.2), (2.8, 6.9)]), fill="#5fa2ea")
    d.polygon(P([(12, 12.2), (21.2, 6.9), (21.2, 17.3), (12, 22.6)]), fill="#084c98")
    d.polygon(P([(7.4, 9.55), (12, 12.2), (12, 17.5), (7.4, 14.85)]), fill=(255, 255, 255, 235))
    spark = [(17.6, 1.4), (18.35, 3.25), (20.2, 4.0), (18.35, 4.75), (17.6, 6.6), (16.85, 4.75), (15.0, 4.0), (16.85, 3.25)]
    d.polygon(P(spark), fill="#8250df", outline="white")
    f = ImageFont.truetype("seguisb.ttf", 250) if Path("C:/Windows/Fonts/seguisb.ttf").exists() else ImageFont.truetype("arialbd.ttf", 250)
    fs = ImageFont.truetype("segoeui.ttf", 62) if Path("C:/Windows/Fonts/segoeui.ttf").exists() else ImageFont.truetype("arial.ttf", 62)
    x = ox + 24 * S + 40
    d.text((x, 95), "AI", font=f, fill="#8250df")
    x2 = x + d.textlength("AI", font=f)
    d.text((x2, 95), "CAD", font=f, fill="#1f2328")
    d.text((x + 8, 395), "AI-assisted CAD Modelling", font=fs, fill="#57606a")
    bbox = img.getbbox()
    img = img.crop((0, 0, bbox[2] + 20, H))
    out = ROOT / "docs" / "images"
    out.mkdir(parents=True, exist_ok=True)
    img.save(out / "logo.png")
    print(out / "logo.png", img.size)


if __name__ == "__main__":
    main()
