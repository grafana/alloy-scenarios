"""Draw the zone coordinate grid used by the replay and Grafana's XYZ tiles."""
from functools import lru_cache
from io import BytesIO
from math import atan, degrees, pi, sinh

from PIL import Image, ImageDraw

# Preserve the viewport and projection of recorded simulator coordinates.
WIDTH, HEIGHT = 1002, 668
TOP = (WIDTH - HEIGHT) // 2


@lru_cache(maxsize=1)
def grid():
    image = Image.new("RGB", (WIDTH, HEIGHT), "#24312f")
    draw = ImageDraw.Draw(image)
    for percent in range(0, 101, 5):
        x = round(percent * (WIDTH - 1) / 100)
        y = round(percent * (HEIGHT - 1) / 100)
        color = "#51625c" if percent % 10 == 0 else "#374741"
        draw.line((x, 0, x, HEIGHT - 1), fill=color)
        draw.line((0, y, WIDTH - 1, y), fill=color)
    for x in range(0, 100, 20):
        for y in range(0, 100, 20):
            draw.text((WIDTH * x / 100 + 4, HEIGHT * y / 100 + 3),
                      f"{x}%, {y}%", fill="#a0aea5")
    return image


def webp(image):
    output = BytesIO()
    image.save(output, format="WEBP", lossless=True)
    return output.getvalue()


@lru_cache(maxsize=1)
def grid_webp():
    return webp(grid())


@lru_cache(maxsize=1)
def atlas():
    world = Image.new("RGB", (WIDTH, WIDTH), "#1c2523")
    world.paste(grid(), (0, TOP))
    return world


def map_position(x, y):
    fraction_y = (TOP + y / 100 * HEIGHT) / WIDTH
    return {"latitude": degrees(atan(sinh(pi * (1 - 2 * fraction_y)))), "longitude": x * 3.6 - 180}


@lru_cache(maxsize=160)
def tile(z, x, y):
    edge = WIDTH / (2 ** z)
    bounds = (x * edge, y * edge, (x + 1) * edge, (y + 1) * edge)
    return webp(atlas().resize((256, 256), Image.Resampling.LANCZOS, box=bounds))
