"""Gravity Rush look for the launcher: Hekseville's colors, from the port's icon.

The fonts are read from the player's own copy of the game (its paks) the first time the launcher
sees it, cached in the launcher's settings folder and registered for this process only. They are
never shipped with the port. Without a game folder the launcher uses Windows fonts.

The drawn pieces (logo, PLAY button, check boxes, heading ornament, banner fade) are made with
Pillow at the window's DPI.
"""
import sys
from pathlib import Path

# Hekseville at dusk: night-black cat, teal sky, stone, the clock tower's gold.
NIGHT = '#0b0f1a'      # window background, sidebar
STONE = '#121a24'      # pages
CARD = '#1b2633'       # fields, list boxes
EDGE = '#2f4152'       # borders
BRONZE = '#7a6438'     # ornate borders
BONE = '#efe6cc'       # text
MIST = '#93a7ae'       # secondary text
GOLD = '#e8c063'       # headings, selection
EMBER = '#c9893a'      # the logo's lower half
SOUL = '#6fc3c9'       # teal highlights (the sky)
SOUL_DARK = '#2a5f66'  # filled controls

# gravityrush.ini-independent roles -> (pak file, family name inside the font)
GAME_FONTS = {}  # Gravity Rush ships no Unreal paks: Windows fonts (FALLBACK)
FALLBACK = {'logo': 'Georgia', 'head': 'Georgia', 'body': 'Segoe UI'}


class Fonts:
    """Font families by role, and the font files (for Pillow) when the game's were loaded."""

    def __init__(self):
        self.family = dict(FALLBACK)
        self.file = {}

    @property
    def from_game(self):
        return bool(self.file)


def load_fonts(game_dir, cache_dir):
    """The game's fonts (extracted once to cache_dir/fonts), else Windows fonts."""
    fonts = Fonts()
    if sys.platform != 'win32':
        return fonts
    cache = Path(cache_dir) / 'fonts'
    for role, (pak_name, family) in GAME_FONTS.items():
        path = cache / Path(pak_name).name.replace('.ufont', '.ttf')
        if not path.is_file() and game_dir:
            try:
                import ue4_override
                data = ue4_override.read_file(Path(game_dir), pak_name)
                if data[:4] in (b'\x00\x01\x00\x00', b'OTTO', b'true'):
                    cache.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
            except (ImportError, OSError, ValueError, FileNotFoundError):
                pass
        if path.is_file() and register(path):
            fonts.family[role] = family
            fonts.file[role] = path
    return fonts


def register(path):
    """Makes a font file usable by this process (GDI private font, as Tk draws with GDI)."""
    try:
        import ctypes
        FR_PRIVATE = 0x10
        return ctypes.windll.gdi32.AddFontResourceExW(str(path), FR_PRIVATE, 0) > 0
    except (AttributeError, OSError):
        return False


def _hex(color, alpha=255):
    color = color.lstrip('#')
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4)) + (alpha,)


def _font(fonts, role, size):
    from PIL import ImageFont
    path = fonts.file.get(role)
    try:
        return ImageFont.truetype(str(path) if path else ('georgiab.ttf' if role != 'body' else 'segoeuib.ttf'),
                                  size)
    except OSError:
        return ImageFont.load_default()


def gold_text(fonts, text, size, role='logo', glow=SOUL, outline=2):
    """Text in the logo's gold-to-ember gradient, dark outline and a soft green glow (Pillow RGBA)."""
    from PIL import Image, ImageDraw, ImageFilter
    font = _font(fonts, role, size)
    box = ImageDraw.Draw(Image.new('L', (1, 1))).textbbox((0, 0), text, font=font)
    pad = max(6, size // 4)
    w, h = box[2] - box[0] + 2 * pad, box[3] - box[1] + 2 * pad
    origin = (pad - box[0], pad - box[1])
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).text(origin, text, font=font, fill=255)
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    if glow:
        halo = mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(max(2, size // 6)))
        out.paste(Image.new('RGBA', (w, h), _hex(glow, 150)), (0, 0), halo)
    edge = mask.filter(ImageFilter.MaxFilter(2 * outline + 1))
    out.paste(Image.new('RGBA', (w, h), _hex('#1a0f06')), (0, 0), edge)
    top, bottom = _hex(GOLD), _hex(EMBER)
    grad = Image.new('RGBA', (w, h))
    for y in range(h):
        f = min(1.0, max(0.0, (y - pad) / max(1, h - 2 * pad)))
        grad.paste(tuple(int(top[i] + (bottom[i] - top[i]) * f) for i in range(4)), (0, y, w, y + 1))
    out.paste(grad, (0, 0), mask)
    return out


def play_button(fonts, text, width, height, state):
    """The PLAY button: a carved stone tablet with a bronze frame and gold lettering.
    state: 'normal', 'hover' or 'disabled'."""
    from PIL import Image, ImageDraw, ImageFilter
    scale = 2  # drawn larger, then reduced: smooth edges
    W, H = width * scale, height * scale
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = H // 5
    if state == 'hover':
        glow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(glow).rounded_rectangle((4, 4, W - 5, H - 5), r, fill=_hex(SOUL, 170))
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(7 * scale)))
    m = 7 * scale
    d.rounded_rectangle((m, m, W - m, H - m), r, fill=_hex('#2a2238') if state != 'disabled' else _hex('#1d1826'),
                        outline=_hex(BRONZE if state != 'hover' else GOLD), width=3 * scale)
    d.rounded_rectangle((m + 6 * scale, m + 6 * scale, W - m - 6 * scale, H - m - 6 * scale), r - 4 * scale,
                        outline=_hex('#4a3a28' if state != 'hover' else '#8a6a2a'), width=scale)
    # Stone shading: lighter at the top.
    shade = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(m, H // 2):
        sd.line((m + 4, y, W - m - 4, y), fill=(255, 255, 255, int(18 * (1 - (y - m) / (H / 2 - m)))))
    img.alpha_composite(shade)
    label = gold_text(fonts, text, int(H * 0.40), role='head', glow=SOUL if state == 'hover' else None)
    if state == 'disabled':
        label = Image.blend(Image.new('RGBA', label.size, (0, 0, 0, 0)), label, 0.35)
    img.alpha_composite(label, ((W - label.width) // 2, (H - label.height) // 2))
    return img.resize((width, height), Image.LANCZOS)


def check_box(size, checked):
    """A gold-framed box with a green tick."""
    from PIL import Image, ImageDraw
    scale = 4
    S = size * scale
    img = Image.new('RGBA', (S + 8 * scale, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((scale, scale, S - scale, S - scale), 3 * scale,
                        fill=_hex(SOUL_DARK if checked else CARD), outline=_hex(GOLD if checked else BRONZE),
                        width=max(scale, S // 12))
    if checked:
        pts = [(.24 * S, .52 * S), (.43 * S, .72 * S), (.78 * S, .28 * S)]
        d.line(pts, fill=_hex('#eaffd0'), width=max(scale, S // 8), joint='curve')
    return img.resize((size + 8, size), Image.LANCZOS)


def divider(width, height):
    """A heading ornament: a small gold diamond and a line that fades out to the right."""
    from PIL import Image, ImageDraw
    img = Image.new('RGBA', (max(1, width), max(3, height)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cy = height // 2
    gold = _hex(GOLD)
    for x in range(height + 2, width):
        a = int(200 * (1 - (x - height) / max(1, width - height)) ** 1.6)
        d.point((x, cy), fill=gold[:3] + (a,))
    s = max(2, height // 2 - 1)
    d.polygon([(s, cy - s), (2 * s, cy), (s, cy + s), (0, cy)], fill=_hex(GOLD))
    return img


def banner_fade(image, width, height, bottom_color=STONE):
    """The key art fitted to width x height, fading into the page at the bottom with green mist."""
    from PIL import Image, ImageDraw, ImageFilter
    art = image.convert('RGB')
    scale = max(width / art.width, height / art.height)
    art = art.resize((max(1, round(art.width * scale)), max(1, round(art.height * scale))), Image.LANCZOS)
    top = max(0, int((art.height - height) * 0.35))  # keep the logo (upper part) in view
    left = (art.width - width) // 2
    art = art.crop((left, top, left + width, top + height)).convert('RGBA')
    fade = Image.new('L', (width, height), 0)
    fd = ImageDraw.Draw(fade)
    start = int(height * 0.55)
    for y in range(start, height):
        fd.line((0, y, width, y), fill=int(255 * ((y - start) / max(1, height - start)) ** 1.4))
    art.paste(Image.new('RGBA', (width, height), _hex(bottom_color)), (0, 0), fade)
    mist = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(mist).ellipse((-width * 0.2, height * 0.78, width * 1.2, height * 1.25), fill=_hex(SOUL, 38))
    art.alpha_composite(mist.filter(ImageFilter.GaussianBlur(height // 10)))
    return art


def sidebar_glow(width, height):
    """The selected menu item's mark: a green soul flame fading to the right."""
    from PIL import Image, ImageDraw, ImageFilter
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for x in range(width):
        a = int(70 * (1 - x / width) ** 2)
        d.line((x, 2, x, height - 3), fill=_hex(SOUL, a))
    d.rectangle((0, 3, 3, height - 4), fill=_hex(SOUL, 255))
    return img.filter(ImageFilter.GaussianBlur(1))
