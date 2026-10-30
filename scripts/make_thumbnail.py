from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 675
BG      = (11, 13, 16)
SURFACE = (19, 23, 28)
BORDER  = (37, 44, 53)
TEXT    = (230, 234, 239)
MUTED   = (141, 151, 165)
ACCENT  = (118, 185, 0)      # NVIDIA green
SOFT    = (26, 38, 10)

HEL = "/System/Library/Fonts/Helvetica.ttc"
MEN = "/System/Library/Fonts/Menlo.ttc"
def f(path, size, idx=0):
    return ImageFont.truetype(path, size, index=idx)

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

# subtle top accent bar
d.rectangle([0, 0, W, 6], fill=ACCENT)

# ---- left: the pitch ----
x = 72
d.rounded_rectangle([x, 92, x + 52, 144], radius=13, fill=ACCENT)
d.text((x + 70, 97), "Mnemo", font=f(HEL, 44, 1), fill=TEXT)

# Fit the headline to the space left of the memory pane instead of guessing.
MAXW = 760 - x - 48
lines = ["A personal AI whose", "memory is a file", "you own."]
size = 64
while size > 28:
    fnt = f(HEL, size, 1)
    if max(d.textlength(l, font=fnt) for l in lines) <= MAXW:
        break
    size -= 2
fnt = f(HEL, size, 1)
ly = 186
for l in lines:
    d.text((x, ly), l, font=fnt, fill=TEXT)
    ly += int(size * 1.16)
print(f"headline fitted at {size}px, widest {max(d.textlength(l, font=fnt) for l in lines):.0f}px / {MAXW}px")

d.text((x, 424), "Every fact it keeps is a row you can read,", font=f(HEL, 26), fill=MUTED)
d.text((x, 460), "edit, pin or delete. Nothing is hidden.", font=f(HEL, 26), fill=MUTED)

# model chips
chips = ["Nemotron 3.5 Lightning", "Nemotron 3 Ultra 550B"]
cx = x
for c in chips:
    w = d.textlength(c, font=f(HEL, 20)) + 34
    d.rounded_rectangle([cx, 506, cx + w, 548], radius=21, fill=SOFT, outline=ACCENT)
    d.text((cx + 17, 517), c, font=f(HEL, 20), fill=ACCENT)
    cx += w + 14

d.text((x, 584), "NVIDIA open models  ·  served by Nebius Token Factory",
       font=f(HEL, 23), fill=MUTED)
d.text((x, 622), "github.com/AkashPerumalla/mnemo", font=f(MEN, 20), fill=(90, 100, 112))

# ---- right: a stylised memory pane ----
px, py, pw = 760, 118, 376
d.rounded_rectangle([px, py, px + pw, py + 440], radius=16, fill=SURFACE, outline=BORDER)
d.text((px + 26, py + 24), "Memory", font=f(HEL, 22, 1), fill=TEXT)
d.rounded_rectangle([px + 112, py + 24, px + 146, py + 48], radius=12, fill=BG, outline=BORDER)
d.text((px + 122, py + 28), "3", font=f(HEL, 17), fill=MUTED)

rows = [
    ("#3 · PROJECT", "Building a self-balancing", "robot on an ESP32.", True),
    ("#2 · PREFERENCE", "Prefers terse answers", "with no preamble.", False),
    ("#1 · TASK", "Hackathon demo due", "30 October.", False),
]
ry = py + 74
for tag, l1, l2, pinned in rows:
    fill = SOFT if pinned else BG
    edge = ACCENT if pinned else BORDER
    d.rounded_rectangle([px + 20, ry, px + pw - 20, ry + 112], radius=11, fill=fill, outline=edge)
    d.text((px + 36, ry + 15), tag, font=f(HEL, 15), fill=ACCENT if pinned else MUTED)
    d.text((px + 36, ry + 44), l1, font=f(HEL, 21), fill=TEXT)
    d.text((px + 36, ry + 72), l2, font=f(HEL, 21), fill=TEXT)
    ry += 126

img.save("assets/thumbnail.png", "PNG")
print("wrote assets/thumbnail.png", img.size)
