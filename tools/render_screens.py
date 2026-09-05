"""Port of the sketch's screen functions, so the PNG matches the panel."""
import math
from PIL import Image, ImageDraw
from gfx_preview import Canvas, WHITE, BLACK, W, H

LONG_BREATH_MS, IDLE_TIMEOUT_MS, METER_FULL_MS = 1000, 5000, 2000
WAVE = [0, 2, 5, 7, 8, 10, 11, 12, 12, 12, 11, 10, 8, 7, 5, 2,
        0, -2, -5, -7, -8, -10, -11, -12, -12, -12, -11, -10, -8, -7, -5, -2]

WORDS = ["FOOD", "WATER", "EMERGENCY", "TOILET", "MEDICINE", "YES", "NO"]


def header(c, pattern, count):
    c.fill_rect(0, 0, W, 11, WHITE)
    c.text(3, 2, "RespTalk", 1, BLACK)
    for i in range(3):
        sx = 84 + i * 14
        if i < count:
            if pattern[i] == '.': c.fill_rect(sx + 4, 3, 4, 5, BLACK)
            else:                 c.fill_rect(sx, 4, 11, 3, BLACK)
        else:
            c.draw_rect(sx, 3, 11, 5, BLACK)


def icon_food(c, x, y):
    cx = x + 14
    c.fill_circle(cx, y + 16, 12, WHITE)
    c.fill_rect(x, y, 28, 16, BLACK)
    c.fill_rect(cx - 13, y + 14, 26, 3, WHITE)
    for i in (-1, 0, 1): c.fill_rect(cx + i * 7 - 1, y + 1, 2, 9, WHITE)

def icon_water(c, x, y):
    cx = x + 14
    c.fill_triangle(cx, y + 1, x + 5, y + 18, x + 23, y + 18, WHITE)
    c.fill_circle(cx, y + 18, 9, WHITE)

def icon_emergency(c, x, y):
    cx = x + 14
    c.draw_triangle(cx, y + 1, x + 1, y + 26, x + 27, y + 26, WHITE)
    c.draw_triangle(cx, y + 3, x + 3, y + 25, x + 25, y + 25, WHITE)
    c.fill_rect(cx - 1, y + 11, 3, 8, WHITE)
    c.fill_rect(cx - 1, y + 21, 3, 3, WHITE)

def icon_toilet(c, x, y):
    c.fill_rect(x + 3, y + 3, 6, 12, WHITE)
    c.fill_round_rect(x + 9, y + 8, 16, 10, 4, WHITE)
    c.fill_rect(x + 13, y + 18, 7, 6, WHITE)
    c.fill_rect(x + 9, y + 24, 15, 3, WHITE)

def icon_medicine(c, x, y):
    c.fill_round_rect(x + 1, y + 9, 26, 11, 5, WHITE)
    c.fill_rect(x + 14, y + 10, 12, 9, BLACK)
    c.draw_round_rect(x + 1, y + 9, 26, 11, 5, WHITE)
    c.fast_vline(x + 14, y + 9, 11, WHITE)

def icon_yes(c, x, y):
    for t in range(3):
        c.line(x + 4, y + 14 + t, x + 11, y + 21 + t, WHITE)
        c.line(x + 11, y + 21 + t, x + 24, y + 7 + t, WHITE)

def icon_no(c, x, y):
    for t in range(3):
        c.line(x + 5 + t, y + 7, x + 22 + t, y + 24, WHITE)
        c.line(x + 22 - t, y + 7, x + 5 - t, y + 24, WHITE)

ICONS = dict(zip(WORDS, [icon_food, icon_water, icon_emergency,
                         icon_toilet, icon_medicine, icon_yes, icon_no]))


def fmt_seconds(ms):
    t = ms // 100
    return f"{t // 10}.{t % 10}s"


def screen_idle(phase=0):
    c = Canvas(); header(c, "", 0)
    mid = 32
    for px in range(W):
        v = WAVE[((px + phase) >> 1) & 31]
        c.pixel(px, mid + v, WHITE); c.pixel(px, mid + v + 1, WHITE)
    c.center_text("breathe to speak", 52, 1)
    return c


def screen_measuring(elapsed, pattern, count):
    c = Canvas(); header(c, pattern, count)
    if elapsed >= LONG_BREATH_MS: c.fill_rect(46, 17, 36, 8, WHITE)
    else:                         c.fill_circle(64, 21, 7, WHITE)
    shown = min(elapsed, METER_FULL_MS)
    w = (shown * 124) // METER_FULL_MS
    c.draw_rect(1, 38, 126, 10, WHITE)
    c.fill_rect(2, 39, w, 8, WHITE)
    tx = 2 + (124 * LONG_BREATH_MS) // METER_FULL_MS
    c.fill_triangle(tx - 3, 32, tx + 3, 32, tx, 37, WHITE)
    c.text(2, 52, "short", 1, WHITE); c.text(103, 52, "long", 1, WHITE)
    c.center_text(fmt_seconds(elapsed), 52, 1)
    return c


def screen_word(word, age=0):
    c = Canvas(); header(c, "", 0)
    ICONS[word](c, 50, 13)
    c.center_text(word, 44, 2)
    left = IDLE_TIMEOUT_MS - age
    c.fill_rect(0, 62, (left * W) // IDLE_TIMEOUT_MS, 2, WHITE)
    return c


def draw_big_pattern(c, pattern, y):
    for i in range(3):
        x = 15 + i * 36
        if pattern[i] == '.': c.fill_circle(x + 13, y + 5, 5, WHITE)
        else:                 c.fill_rect(x, y + 2, 26, 6, WHITE)

def screen_unknown(pattern):
    c = Canvas(); header(c, pattern, 3)
    c.center_text("?", 14, 3)
    draw_big_pattern(c, pattern, 44)
    return c


def sheet(items, cols=3, scale=4, pad=14):
    tiles = [(lbl, cv.png(scale)) for lbl, cv in items]
    tw, th = tiles[0][1].size
    rows = (len(tiles) + cols - 1) // cols
    out = Image.new("RGB", (cols * (tw + pad) + pad, rows * (th + pad + 16) + pad), (26, 28, 34))
    d = ImageDraw.Draw(out)
    for i, (lbl, im) in enumerate(tiles):
        x = pad + (i % cols) * (tw + pad)
        y = pad + (i // cols) * (th + pad + 16)
        d.rectangle([x - 2, y - 2, x + tw + 1, y + th + 1], outline=(70, 76, 90))
        out.paste(im, (x, y))
        d.text((x + 2, y + th + 3), lbl, fill=(190, 200, 215))
    return out


screens = [
    ("idle", screen_idle(0)),
    ("measuring 0.5s -> dot", screen_measuring(500, ".", 1)),
    ("measuring 1.4s -> dash", screen_measuring(1400, ".-", 2)),
    ("unknown pattern", screen_unknown("..-")),
]
screens += [(w, screen_word(w, 1200)) for w in WORDS]

sheet(screens, cols=4, scale=4).save("preview.png")
print("wrote preview.png")
