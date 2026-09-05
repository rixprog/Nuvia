"""Pixel-accurate preview of the Nuvia OLED screens.

Reimplements the Adafruit_GFX primitives the sketch uses, driven by the real
5x7 font table from the installed library, so the rendered PNG matches what
the panel will actually show.
"""
import re
from PIL import Image

W, H = 128, 64
WHITE, BLACK = 1, 0

# ---- real GFX font ----------------------------------------------------
src = open("/home/rix/Arduino/libraries/Adafruit_GFX_Library/glcdfont.c").read()
body = src[src.index("{") + 1: src.rindex("}")]
FONT = [int(x, 16) for x in re.findall(r"0[xX]([0-9a-fA-F]{2})", body)]
assert len(FONT) >= 1280, len(FONT)


class Canvas:
    def __init__(self):
        self.px = [[0] * W for _ in range(H)]

    def pixel(self, x, y, c):
        if 0 <= x < W and 0 <= y < H:
            self.px[int(y)][int(x)] = c

    def fill_rect(self, x, y, w, h, c):
        for yy in range(int(y), int(y + h)):
            for xx in range(int(x), int(x + w)):
                self.pixel(xx, yy, c)

    def draw_rect(self, x, y, w, h, c):
        self.fast_hline(x, y, w, c); self.fast_hline(x, y + h - 1, w, c)
        self.fast_vline(x, y, h, c); self.fast_vline(x + w - 1, y, h, c)

    def fast_vline(self, x, y, h, c): self.fill_rect(x, y, 1, h, c)
    def fast_hline(self, x, y, w, c): self.fill_rect(x, y, w, 1, c)

    def line(self, x0, y0, x1, y1, c):
        x0, y0, x1, y1 = map(int, (x0, y0, x1, y1))
        steep = abs(y1 - y0) > abs(x1 - x0)
        if steep: x0, y0, x1, y1 = y0, x0, y1, x1
        if x0 > x1: x0, x1, y0, y1 = x1, x0, y1, y0
        dx, dy = x1 - x0, abs(y1 - y0)
        err = dx // 2
        ystep = 1 if y0 < y1 else -1
        y = y0
        for x in range(x0, x1 + 1):
            self.pixel(y, x, c) if steep else self.pixel(x, y, c)
            err -= dy
            if err < 0:
                y += ystep; err += dx

    def fill_circle(self, x0, y0, r, c):
        for yy in range(int(y0 - r), int(y0 + r + 1)):
            for xx in range(int(x0 - r), int(x0 + r + 1)):
                if (xx - x0) ** 2 + (yy - y0) ** 2 <= r * r + r * 0.4:
                    self.pixel(xx, yy, c)

    def draw_circle(self, x0, y0, r, c):
        for yy in range(int(y0 - r), int(y0 + r + 1)):
            for xx in range(int(x0 - r), int(x0 + r + 1)):
                d = (xx - x0) ** 2 + (yy - y0) ** 2
                if (r - 1) ** 2 < d <= r * r + r * 0.4:
                    self.pixel(xx, yy, c)

    def fill_triangle(self, x0, y0, x1, y1, x2, y2, c):
        pts = [(x0, y0), (x1, y1), (x2, y2)]
        ymin, ymax = min(p[1] for p in pts), max(p[1] for p in pts)
        for yy in range(int(ymin), int(ymax) + 1):
            xs = []
            for i in range(3):
                ax, ay = pts[i]; bx, by = pts[(i + 1) % 3]
                if ay == by: continue
                if min(ay, by) <= yy <= max(ay, by):
                    xs.append(ax + (bx - ax) * (yy - ay) / (by - ay))
            if xs:
                self.fast_hline(min(xs), yy, max(xs) - min(xs) + 1, c)

    def draw_triangle(self, x0, y0, x1, y1, x2, y2, c):
        self.line(x0, y0, x1, y1, c); self.line(x1, y1, x2, y2, c); self.line(x2, y2, x0, y0, c)

    def fill_round_rect(self, x, y, w, h, r, c):
        self.fill_rect(x + r, y, w - 2 * r, h, c)
        self.fill_circle(x + r, y + r, r, c);         self.fill_circle(x + w - r - 1, y + r, r, c)
        self.fill_circle(x + r, y + h - r - 1, r, c); self.fill_circle(x + w - r - 1, y + h - r - 1, r, c)
        self.fill_rect(x, y + r, r, h - 2 * r, c);    self.fill_rect(x + w - r, y + r, r, h - 2 * r, c)

    def draw_round_rect(self, x, y, w, h, r, c):
        self.fast_hline(x + r, y, w - 2 * r, c); self.fast_hline(x + r, y + h - 1, w - 2 * r, c)
        self.fast_vline(x, y + r, h - 2 * r, c); self.fast_vline(x + w - 1, y + r, h - 2 * r, c)
        for cx, cy in ((x + r, y + r), (x + w - r - 1, y + r),
                       (x + r, y + h - r - 1), (x + w - r - 1, y + h - r - 1)):
            self.draw_circle(cx, cy, r, c)

    def char(self, x, y, ch, size, c):
        idx = ord(ch) * 5
        for col in range(5):
            bits = FONT[idx + col]
            for row in range(8):
                if bits & (1 << row):
                    self.fill_rect(x + col * size, y + row * size, size, size, c)

    def text(self, x, y, s, size, c):
        for i, ch in enumerate(s):
            self.char(x + i * 6 * size, y, ch, size, c)

    def center_text(self, s, y, size, c=WHITE):
        self.text((W - len(s) * 6 * size) // 2, y, s, size, c)

    def png(self, scale=5):
        img = Image.new("RGB", (W * scale, H * scale), (8, 10, 14))
        pix = img.load()
        for y in range(H):
            for x in range(W):
                if self.px[y][x]:
                    for dy in range(scale - 1):
                        for dx in range(scale - 1):
                            pix[x * scale + dx, y * scale + dy] = (150, 225, 255)
        return img
