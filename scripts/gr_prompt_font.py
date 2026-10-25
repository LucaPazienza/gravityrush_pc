#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Keyboard and mouse button prompts for Gravity Rush.

The game draws its button prompts as text in its own font Gravity_Gaiji.ttf (font/ in the
first archive), where letters are PS4 button glyphs: "e Close  h Hold to Upgrade" shows
Circle and Cross. This script writes a copy of that font whose button glyphs are keycaps and
mouse buttons for the current bindings; the runtime hands it to the game in place of the
original when the player uses keyboard and mouse (GOW3_PROMPT_FONT, GOW3_PROMPTS).

    gr_prompt_font.py --game <CUSA01113 folder> --out <file.ttf>

Bindings come from the same variables the runtime reads: GOW3_KEY_MAP and GOW3_MOUSE_MAP
(defaults below match src/runtime_pad.c). Needs fontTools.
"""
import argparse
import lzma
import os
from pathlib import Path
import struct
import sys
import zlib

PORT = Path(__file__).resolve().parent.parent

# Gaiji letter of each PS4 button (and the sticks' and d-pad's glyphs).
GLYPHS = {'circle': 'e', 'triangle': 'f', 'square': 'g', 'cross': 'h', 'l1': 'i', 'r1': 'j',
          'l2': 'A', 'r2': 'B', 'l3': 'C', 'r3': 'D', 'options': 'n',
          'up': 'o', 'down': 'p', 'left': 'q', 'right': 'r'}
LEFT_STICK, RIGHT_STICK = 'k', 'l'

# Defaults of src/runtime_pad.c (key_map, mouse_map), as SDL key names.
DEFAULT_KEYS = {'cross': 'Space', 'circle': 'Left Shift', 'square': 'E', 'triangle': 'Q', 'l1': '1',
                'r1': '3', 'l2': 'R', 'r2': 'F', 'l3': 'Z', 'r3': 'C', 'options': 'Return',
                'up': 'I', 'down': 'K', 'left': 'J', 'right': 'L'}
DEFAULT_MOUSE = {'left': 'square', 'middle': 'l1', 'right': 'r1', 'x1': 'l2', 'x2': 'r2'}
# Mouse buttons drawn as a mouse; the side buttons (not on every mouse) leave the key's prompt.
DRAWN_MOUSE = ('left', 'middle', 'right')

SHORT = {'left shift': 'Shift', 'right shift': 'Shift', 'left ctrl': 'Ctrl', 'right ctrl': 'Ctrl',
         'left alt': 'Alt', 'right alt': 'Alt', 'return': 'Enter', 'keypad enter': 'Enter',
         'backspace': 'Bksp', 'escape': 'Esc', 'capslock': 'Caps', 'delete': 'Del',
         'insert': 'Ins', 'pageup': 'PgUp', 'pagedown': 'PgDn', 'space': 'Space'}


def parse_map(spec):
    """'a=b, c=d' -> {'a': 'b', 'c': 'd'} (lower-case keys, values kept; bad entries skipped)."""
    out = {}
    for entry in (spec or '').split(','):
        if '=' in entry:
            name, value = entry.split('=', 1)
            if name.strip():
                out[name.strip().casefold()] = value.strip()
    return out


def bindings(env=os.environ):
    """{ps4 button: ('mouse', button) or ('key', label)} for the prompts."""
    keys = dict(DEFAULT_KEYS)
    keys.update({b: k for b, k in parse_map(env.get('GOW3_KEY_MAP')).items() if b in keys})
    mouse = dict(DEFAULT_MOUSE)
    mouse.update({m: b.casefold() for m, b in parse_map(env.get('GOW3_MOUSE_MAP')).items() if m in mouse})
    shown = {}
    for button in GLYPHS:
        drawn = [m for m in DRAWN_MOUSE if mouse.get(m) == button]
        if drawn:
            shown[button] = ('mouse', drawn[0])
        elif keys.get(button):
            shown[button] = ('key', key_label(keys[button]))
    return shown


def key_label(name):
    short = SHORT.get(name.casefold())
    if short:
        return short
    return name if len(name) <= 5 else name[:5]


# --- PSARC (the game's archives): only what is needed to read one file. ---
def psarc_file(path, wanted):
    with open(path, 'rb') as f:
        magic, _version, _comp, toc_len, entry_size, count, block_size, _flags = \
            struct.unpack('>4sI4sIIIII', f.read(32))
        if magic != b'PSAR':
            raise ValueError(f'{path}: not a PSARC archive')
        toc = f.read(toc_len - 32)
        entries = []
        for i in range(count):
            e = toc[i * entry_size:(i + 1) * entry_size]
            entries.append((struct.unpack('>I', e[16:20])[0], int.from_bytes(e[20:25], 'big'),
                            int.from_bytes(e[25:30], 'big')))
        width = {65536: 2, 16777216: 3}.get(block_size, 4)
        table = toc[count * entry_size:]
        blocks = [int.from_bytes(table[i:i + width], 'big') for i in range(0, len(table) - width + 1, width)]

        def read(entry):
            first, size, offset = entry
            out, block = bytearray(), first
            f.seek(offset)
            while len(out) < size:
                length = blocks[block]
                block += 1
                data = f.read(length or block_size)
                if length == 0 or (len(data) == min(block_size, size - len(out)) and data[:1] != b'\x78'):
                    out += data
                else:
                    try:
                        out += zlib.decompress(data)
                    except zlib.error:
                        out += lzma.decompress(data)
            return bytes(out[:size])
        names = read(entries[0]).decode('utf-8', 'replace').split('\n')
        for name, entry in zip(names, entries[1:]):
            if name.casefold() == wanted.casefold():
                return read(entry)
    return None


def original_font(game):
    for archive in sorted(Path(game, 'arc').glob('*.psarc')):
        data = psarc_file(archive, 'font/gravity_gaiji.ttf')
        if data:
            return data
    raise FileNotFoundError(f'font/gravity_gaiji.ttf not found in {game}/arc')


# --- Glyph drawing (TrueType: outer contours clockwise, holes counter-clockwise). ---
BOTTOM, TOP = -100, 830     # the PS4 glyphs' box
HEIGHT = TOP - BOTTOM


def rounded_rect(pen, x0, y0, x1, y1, r, hole=False):
    """A rounded rectangle; quadratic corners. Clockwise unless hole."""
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    # Clockwise in y-up space: left edge up, top edge right, right edge down, bottom edge left.
    path = [('line', (x0, y0 + r)), ('line', (x0, y1 - r)), ('qcurve', (x0, y1), (x0 + r, y1)),
            ('line', (x1 - r, y1)), ('qcurve', (x1, y1), (x1, y1 - r)), ('line', (x1, y0 + r)),
            ('qcurve', (x1, y0), (x1 - r, y0)), ('line', (x0 + r, y0)), ('qcurve', (x0, y0), (x0, y0 + r))]
    if hole:
        path = reverse_path(path)
    start = path[0][1]
    pen.moveTo(start)
    for item in path[1:]:
        if item[0] == 'line':
            pen.lineTo(item[1])
        else:
            pen.qCurveTo(*item[1:])
    pen.closePath()


def reverse_path(path):
    """Reverses a closed path of ('line', p) / ('qcurve', ctrl, p) items starting at path[0]."""
    points = [path[0][1]]
    segments = []
    for item in path[1:]:
        segments.append(item)
        points.append(item[-1])
    out = [('line', points[-1])]
    for i in range(len(segments) - 1, -1, -1):
        seg = segments[i]
        end = points[i]
        out.append(('line', end) if seg[0] == 'line' else ('qcurve', seg[1], end))
    return out


class Painter:
    def __init__(self, label_font):
        from fontTools.ttLib import TTFont
        self.font = TTFont(label_font)
        self.cmap = self.font.getBestCmap()
        self.glyphs = self.font.getGlyphSet()
        self.upm = self.font['head'].unitsPerEm
        self.cap = getattr(self.font['OS/2'], 'sCapHeight', 0) or int(self.upm * 0.7)

    def text_width(self, text, scale):
        return sum(self.font['hmtx'][self.cmap[ord(c)]][0] for c in text if ord(c) in self.cmap) * scale

    def text(self, pen, text, x, y, scale):
        """Draws text as holes (reversed contours) with its baseline at y."""
        from fontTools.pens.reverseContourPen import ReverseContourPen
        from fontTools.pens.transformPen import TransformPen
        for c in text:
            name = self.cmap.get(ord(c))
            if not name:
                continue
            self.glyphs[name].draw(TransformPen(ReverseContourPen(pen), (scale, 0, 0, scale, x, y)))
            x += self.font['hmtx'][name][0] * scale

    def keycap(self, pen, label):
        """A solid key with the label cut out; returns the advance width."""
        size = 0.42 if len(label) > 1 else 0.55
        scale = HEIGHT * size / self.cap
        width = max(HEIGHT, self.text_width(label, scale) + HEIGHT * 0.45)
        x0 = 40
        rounded_rect(pen, x0, BOTTOM, x0 + width, TOP, HEIGHT * 0.22)
        tx = x0 + (width - self.text_width(label, scale)) / 2
        ty = BOTTOM + (HEIGHT - self.cap * scale) / 2
        self.text(pen, label, tx, ty, scale)
        return int(x0 * 2 + width)

    @staticmethod
    def mouse(pen, button):
        """A mouse with the pressed button cut out ('left', 'right', 'middle' or None: moving)."""
        w = HEIGHT * 0.66
        x0, x1 = 60, 60 + w
        mid = (x0 + x1) / 2
        rounded_rect(pen, x0, BOTTOM, x1, TOP, w * 0.48)
        split = TOP - HEIGHT * 0.42
        gap = HEIGHT * 0.035
        if button in ('left', 'right'):
            bx0, bx1 = (x0 + gap * 2.2, mid - gap) if button == 'left' else (mid + gap, x1 - gap * 2.2)
            rounded_rect(pen, bx0, split + gap, bx1, TOP - gap * 2.2, w * 0.14, hole=True)
        elif button == 'middle':
            rounded_rect(pen, mid - w * 0.09, split + HEIGHT * 0.08, mid + w * 0.09, TOP - HEIGHT * 0.1,
                         w * 0.09, hole=True)
        else:  # moving: the two buttons' split line and the body line
            rounded_rect(pen, mid - gap, split, mid + gap, TOP - gap * 2.5, gap, hole=True)
            rounded_rect(pen, x0 + gap * 2.5, split - gap, x1 - gap * 2.5, split + gap, gap, hole=True)
        return int(x1 + 60)


def build(original, out, env=os.environ, label_font=None):
    from io import BytesIO
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import TTFont
    font = TTFont(BytesIO(original))
    cmap = font.getBestCmap()
    painter = Painter(label_font or PORT / 'launcher' / 'fonts' / 'Cabin.ttf')
    glyf, hmtx = font['glyf'], font['hmtx']

    def replace(letter, draw):
        name = cmap[ord(letter)]
        pen = TTGlyphPen(None)
        advance = draw(pen)
        glyph = pen.glyph()
        glyph.recalcBounds(glyf)
        glyf[name] = glyph
        hmtx[name] = (advance, glyph.xMin)

    shown = bindings(env)
    for button, (kind, value) in shown.items():
        if kind == 'mouse':
            replace(GLYPHS[button], lambda pen, v=value: painter.mouse(pen, v))
        else:
            replace(GLYPHS[button], lambda pen, v=value: painter.keycap(pen, v))
    replace(LEFT_STICK, lambda pen: painter.keycap(pen, 'WASD'))
    replace(RIGHT_STICK, lambda pen: painter.mouse(pen, None))
    # The replaced glyphs have no hinting program; the font's own hinting stays for the rest.
    font['maxp'].recalc(font)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(out) + '.tmp')
    font.save(str(tmp))
    os.replace(tmp, out)
    return shown


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--game', required=True, help='game folder (with arc/*.psarc)')
    parser.add_argument('--out', required=True, help='font file to write')
    args = parser.parse_args()
    try:
        shown = build(original_font(args.game), args.out)
    except ImportError:
        print('Prompts: fontTools is missing, the game keeps its controller prompts', file=sys.stderr)
        return 1
    print('Prompts: keyboard and mouse font written:',
          ', '.join(f'{b}={v}' for b, (_k, v) in shown.items()), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
