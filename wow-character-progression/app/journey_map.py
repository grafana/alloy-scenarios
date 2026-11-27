"""Place the zone image in a square XYZ map without stretching its aspect ratio."""
from functools import lru_cache
from io import BytesIO
from math import atan, degrees, pi, sinh
from pathlib import Path

from PIL import Image

ART = Path(__file__).parent / "static" / "tirisfal.webp"


@lru_cache(maxsize=1)
def atlas():
    with Image.open(ART) as source:
        size = source.width
        world = Image.new("RGB", (size, size), "#242920")
        world.paste(source, (0, (size - source.height) // 2))
        return world, source.height


def map_position(x, y):
    world, height = atlas()
    fraction_y = ((world.width - height) // 2 + y / 100 * height) / world.width
    return {"latitude": degrees(atan(sinh(pi * (1 - 2 * fraction_y)))), "longitude": x * 3.6 - 180}


@lru_cache(maxsize=160)
def tile(z, x, y):
    world, _ = atlas()
    edge = world.width / (2 ** z)
    bounds = (x * edge, y * edge, (x + 1) * edge, (y + 1) * edge)
    image = world.resize((256, 256), Image.Resampling.LANCZOS, box=bounds)
    output = BytesIO()
    image.save(output, format="WEBP", quality=90)
    return output.getvalue()
