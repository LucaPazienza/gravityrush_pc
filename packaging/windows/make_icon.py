#!/usr/bin/env python3
"""Builds the port's icon (launcher/gravityrush.ico and .png) from packaging/windows/icon_source.png:
the whole picture at every size, neither cropped nor with cut corners. Needs Pillow.

Usage: python packaging/windows/make_icon.py [new source image]   (a new image replaces icon_source.png)
"""
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'packaging' / 'windows' / 'icon_source.png'
SIZES = (16, 24, 32, 48, 64, 128, 256)


def square(image):
    side = min(image.size)
    left, top = (image.width - side) // 2, (image.height - side) // 2
    return image.crop((left, top, left + side, top + side))


def main():
    if len(sys.argv) > 1:
        square(Image.open(sys.argv[1]).convert('RGB')).resize((512, 512), Image.LANCZOS).save(SOURCE, optimize=True)
    full = square(Image.open(SOURCE).convert('RGBA'))
    frames = [full.resize((size, size), Image.LANCZOS) for size in SIZES]
    frames[-1].save(ROOT / 'launcher' / 'gravityrush.png')
    frames[-1].save(ROOT / 'launcher' / 'gravityrush.ico', sizes=[(s, s) for s in SIZES],
                    append_images=frames[:-1], bitmap_format='png')
    print('launcher/gravityrush.ico, launcher/gravityrush.png')


if __name__ == '__main__':
    main()
