"""Generate the project thumbnail.

    python scripts/make_thumbnail.py

Devpost wants JPG/PNG/GIF, 5 MB max, 3:2 for best results -- hence 1200x800.
The headline auto-fits the column left of the memory pane rather than assuming
a point size, so changing the wording cannot push it under the pane.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 800                       # 3:2
BG      = (11, 13, 16)
SURFACE = (19, 23, 28)
BORDER  = (37, 44, 53)
TEXT    = (230, 234, 239)
MUTED   = (141, 151, 165)
ACCENT  = (118, 185, 0)                # NVIDIA green
SOFT    = (26, 38, 10)

HEL = "/System/Library/Fonts/Helvetica.ttc"
MEN = "/System/Library/Fonts/Menlo.ttc"


def f(path: str, size: int, idx: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size, index=idx)


img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)
d.rectangle([0, 0, W, 7], fill=ACCENT)

# ---- memory pane on the right: what the product actually is ----
PX, PY, PW, PH = 742, 136, 396, 528
d.rounded_rectangle([PX, PY, PX + PW, PY + PH], radius=18, fill=SURFACE, outline=BORDER)
d.text((PX + 28, PY + 26), "Memory", font=f(HEL, 24, 1), fill=TEXT)
d.rounded_rectangle([PX + 124, PY + 26, PX + 160, PY + 52], radius=13, fill=BG, outline=BORDER)
d.text((PX + 135, PY + 30), "3", font=f(HEL, 18), fill=MUTED)

rows = [
    ("#3 · PROJECT",    "Building a self-balancing", "robot on an ESP32.",   True),
    ("#2 · PREFERENCE", "Prefers terse answers",     "with no preamble.",    False),
    ("#1 · TASK",       "Hackathon demo due",        "30 October.",          False),
]
ry = PY + 82
for tag, l1, l2, pinned in rows:
    d.rounded_rectangle(
        [PX + 22, ry, PX + PW - 22, ry + 126], radius=12,
        fill=SOFT if pinned else BG, outline=ACCENT if pinned else BORDER,
    )
    d.text((PX + 40, ry + 18), tag, font=f(HEL, 16), fill=ACCENT if pinned else MUTED)
    d.text((PX + 40, ry + 50), l1, font=f(HEL, 22), fill=TEXT)
    d.text((PX + 40, ry + 82), l2, font=f(HEL, 22), fill=TEXT)
    ry += 142

# ---- the pitch on the left ----
x = 76
COL = PX - x - 56                      # room before the pane

d.rounded_rectangle([x, 120, x + 56, 176], radius=14, fill=ACCENT)
d.text((x + 76, 126), "Mnemo", font=f(HEL, 46, 1), fill=TEXT)

lines = ["A personal AI", "whose memory is", "a file you own."]
size = 72
while size > 28:
    fnt = f(HEL, size, 1)
    if max(d.textlength(ln, font=fnt) for ln in lines) <= COL:
        break
    size -= 2
fnt = f(HEL, size, 1)
ly = 246
for ln in lines:
    d.text((x, ly), ln, font=fnt, fill=TEXT)
    ly += int(size * 1.17)

sub_y = ly + 34
d.text((x, sub_y), "Every fact it keeps is a row", font=f(HEL, 27), fill=MUTED)
d.text((x, sub_y + 38), "you can read, edit or delete.", font=f(HEL, 27), fill=MUTED)

chip_y = sub_y + 100
cx = x
for c in ("Nemotron 3.5 Lightning", "Nemotron 3 Ultra 550B"):
    w = d.textlength(c, font=f(HEL, 21)) + 36
    d.rounded_rectangle([cx, chip_y, cx + w, chip_y + 46], radius=23, fill=SOFT, outline=ACCENT)
    d.text((cx + 18, chip_y + 12), c, font=f(HEL, 21), fill=ACCENT)
    cx += w + 15

d.text((x, chip_y + 82), "NVIDIA open models · served by Nebius Token Factory",
       font=f(HEL, 23), fill=MUTED)
d.text((x, chip_y + 120), "github.com/AkashPerumalla/mnemo",
       font=f(MEN, 20), fill=(92, 102, 114))

out = Path(__file__).resolve().parent.parent / "assets" / "thumbnail.png"
out.parent.mkdir(exist_ok=True)
img.save(out, "PNG", optimize=True)
kb = out.stat().st_size / 1024
print(f"{out.name}  {img.size[0]}x{img.size[1]}  ratio {img.size[0]/img.size[1]:.2f}:1  {kb:.0f} KB")
print(f"headline fitted at {size}px (column {COL}px)")
