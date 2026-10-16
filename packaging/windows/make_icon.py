#!/usr/bin/env python3
"""Builds the port's icon (launcher/gravityrush.ico and .png) from packaging/windows/icon_source.png:
the whole picture with rounded corners for the large sizes, the cat alone for the small ones (16 to
48 px, where the city would be a blur). Needs Pillow.

Usage: python packaging/windows/make_icon.py [new source image]   (a new image replaces icon_source.png)
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'packaging' / 'windows' / 'icon_source.png'
# The cat's head and body in the source, as fractions of its side (left, top, right, bottom).
SMALL_CROP = (0.13, 0.09, 0.60, 0.56)
SIZES = (16, 24, 32, 48, 64, 128, 256)


def rounded(image, radius=0.12):
    side = image.width
    mask = Image.new('L', (side, side), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, side - 1, side - 1), int(side * radius), fill=255)
    out = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    out.paste(image, (0, 0), mask)
    return out


def square(image):
    side = min(image.size)
    left, top = (image.width - side) // 2, (image.height - side) // 2
    return image.crop((left, top, left + side, top + side))


def main():
    if len(sys.argv) > 1:
        square(Image.open(sys.argv[1]).convert('RGB')).resize((512, 512), Image.LANCZOS).save(SOURCE, optimize=True)
    full = square(Image.open(SOURCE).convert('RGBA'))
    side = full.width
    cat = full.crop(tuple(int(f * side) for f in SMALL_CROP))
    frames = [rounded((cat if size <= 48 else full).resize((size, size), Image.LANCZOS)) for size in SIZES]
    frames[-1].save(ROOT / 'launcher' / 'gravityrush.png')
    frames[-1].save(ROOT / 'launcher' / 'gravityrush.ico', sizes=[(s, s) for s in SIZES],
                    append_images=frames[:-1], bitmap_format='png')
    print('launcher/gravityrush.ico, launcher/gravityrush.png')


if __name__ == '__main__':
    main()
