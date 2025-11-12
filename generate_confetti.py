#!/usr/bin/env python3
"""
Generate 3 colorful confetti PNGs using Cairo.
Output: confetti1.png, confetti2.png, confetti3.png
Size: 24x24, transparent background
"""

import cairo
import math
import random
import os

# Configuration
SIZE = 64
FILENAME = "confetti{}.png"
OUTPUT_DIR = "."  # Change if needed

os.makedirs(OUTPUT_DIR, exist_ok=True)

def create_surface():
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, SIZE, SIZE)
    ctx = cairo.Context(surface)
    # Transparent background
    ctx.set_source_rgba(0, 0, 0, 0)
    ctx.paint()
    return surface, ctx

def draw_rectangle_confetti(ctx):
    # Bright random color
    hue = random.random()
    r = (math.cos(hue * 6.28) * 0.5 + 0.5) * 0.8 + 0.2
    g = (math.cos((hue + 0.33) * 6.28) * 0.5 + 0.5) * 0.8 + 0.2
    b = (math.cos((hue + 0.66) * 6.28) * 0.5 + 0.5) * 0.8 + 0.2
    #ctx.set_source_rgb(r, g, b)
    ctx.set_source_rgb(15/255, 244/255, 252/255)

    w, h = SIZE, SIZE/4
    x = (SIZE - w) / 2
    y = (SIZE - h) / 2

    # Rounded rectangle
    radius = 2
    ctx.move_to(x + radius, y)
    ctx.line_to(x + w - radius, y)
    ctx.curve_to(x + w, y, x + w, y, x + w, y + radius)
    ctx.line_to(x + w, y + h - radius)
    ctx.curve_to(x + w, y + h, x + w, y + h, x + w - radius, y + h)
    ctx.line_to(x + radius, y + h)
    ctx.curve_to(x, y + h, x, y + h, x, y + h - radius)
    ctx.line_to(x, y + radius)
    ctx.curve_to(x, y, x, y, x + radius, y)
    ctx.close_path()
    ctx.fill()

# Adjust this value to make the border thicker/thinner
LINE_WIDTH = 4.0

def draw_triangle_confetti(ctx):
    hue = random.random()
    r = max(0.3, (math.sin(hue * 6.28) * 0.5 + 0.5))
    g = max(0.3, (math.sin((hue + 0.33) * 6.28) * 0.5 + 0.5))
    b = max(0.3, (math.sin((hue + 0.66) * 6.28) * 0.5 + 0.5))

    # ---- outer triangle (transparent fill, thick colored stroke) ----
    s = SIZE*0.8
    h = s * math.sqrt(3) / 2
    cx, cy = SIZE // 2, SIZE // 2

    ctx.move_to(cx, cy - h * 0.6)
    ctx.line_to(cx - s / 2, cy + h * 0.4)
    ctx.line_to(cx + s / 2, cy + h * 0.4)
    ctx.close_path()

    ctx.set_source_rgb(r, g, b)
    ctx.set_line_width(LINE_WIDTH)   # <-- thicker line
    ctx.stroke()                     # draw only the outline

    # ---- small inner white highlight (still filled) ----
    ctx.set_source_rgb(1, 1, 1)
    ctx.move_to(cx, cy - h * 0.5)
    ctx.line_to(cx - s / 3, cy + h * 0.2)
    ctx.line_to(cx + s / 3, cy + h * 0.2)
    ctx.close_path()
    ctx.fill()

LINE_WIDTH = 5.0   # <-- same as triangle for consistency

def draw_star_confetti(ctx):
    hue = random.random()
    r = max(0.4, abs(math.sin(hue * 6.28)) * 0.8 + 0.2)
    g = max(0.4, abs(math.sin((hue + 0.33) * 6.28)) * 0.8 + 0.2)
    b = max(0.4, abs(math.sin((hue + 0.66) * 6.28)) * 0.8 + 0.2)

    cx, cy = SIZE // 2, SIZE // 2
    outer = 21
    inner = 6
    points = 5

    # ---- Draw star outline only (no fill) ----
    ctx.move_to(cx, cy - outer)
    for i in range(1, points * 2 + 1):
        angle = i * math.pi / points
        radius = outer if i % 2 == 0 else inner
        x = cx + radius * math.sin(angle)
        y = cy - radius * math.cos(angle)
        ctx.line_to(x, y)
    ctx.close_path()

    # Stroke with thick colored line
    ctx.set_source_rgb(r, g, b)
    ctx.set_line_width(LINE_WIDTH)
    ctx.stroke()  # <-- only outline

# Generate 3 confetti images
random.seed(1)  # Consistent but varied output

# Confetti 1: Rounded Rectangle
surface, ctx = create_surface()
draw_rectangle_confetti(ctx)
surface.write_to_png(os.path.join(OUTPUT_DIR, FILENAME.format(0)))

# Confetti 2: Triangle
surface, ctx = create_surface()
draw_triangle_confetti(ctx)
surface.write_to_png(os.path.join(OUTPUT_DIR, FILENAME.format(1)))

# Confetti 3: Star
surface, ctx = create_surface()
draw_star_confetti(ctx)
surface.write_to_png(os.path.join(OUTPUT_DIR, FILENAME.format(2)))

print("Generated: confetti0.png, confetti1.png, confetti2.png")
