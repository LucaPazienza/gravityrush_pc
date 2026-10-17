#!/usr/bin/env python3
"""Builds the port's icon (launcher/gravityrush.ico and .png) from packaging/windows/icon_source.png:
the whole picture at every size, nothing of it cut. A transparent background stays transparent, and
its empty margins are trimmed so the subject is centred in a square with a small border. Needs Pillow.

Usage: python packaging/windows/make_icon.py [new source image]   (a new image replaces icon_source.png)
"""
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'packaging' / 'windows' / 'icon_source.png'
SIZES = (16, 24, 32, 48, 64, 128, 256)
MARGIN = 0.04   # border around the subject, as a fraction of the side


def fit_square(image):
    """The subject (non-transparent pixels) centred in a transparent square with a small border."""
    box = image.getchannel('A').getbbox() or (0, 0, image.width, image.height)
    subject = image.crop(box)
    side = round(max(subject.size) / (1 - 2 * MARGIN))
    canvas = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    canvas.paste(subject, ((side - subject.width) // 2, (side - subject.height) // 2), subject)
    return canvas


def main():
    if len(sys.argv) > 1:
        fit_square(Image.open(sys.argv[1]).convert('RGBA')).resize((512, 512), Image.LANCZOS).save(SOURCE, optimize=True)
    full = fit_square(Image.open(SOURCE).convert('RGBA'))
    frames = [full.resize((size, size), Image.LANCZOS) for size in SIZES]
    frames[-1].save(ROOT / 'launcher' / 'gravityrush.png')
    # The game window's icon: a BMP SDL loads by itself (run.py then needs no Pillow).
    full.resize((64, 64), Image.LANCZOS).save(ROOT / 'launcher' / 'gravityrush.bmp')
    frames[-1].save(ROOT / 'launcher' / 'gravityrush.ico', sizes=[(s, s) for s in SIZES],
                    append_images=frames[:-1], bitmap_format='png')
    print('launcher/gravityrush.ico, launcher/gravityrush.png')


if __name__ == '__main__':
    main()
