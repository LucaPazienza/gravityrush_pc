# SPDX-License-Identifier: GPL-2.0-or-later
"""Inkfall: the Gravity Rush launcher window (Tkinter), after the design in DESIGN-launcher.md.

Comic-book look: the background picture fills the window, the menu is a column of ink-outlined
capsules with a point on the right, pages open in a paper panel with a hard shadow and a tilted
tab. Shapes are drawn with Pillow (Tk has no clip paths or skew), the rest is Tk widgets on the
paper. Only what the port really does is shown.

The logic (settings, run.py environment, saves, game process) is the one of
gravityrush_launcher.py, passed in as `logic`.
"""
import ctypes
import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time

from PIL import Image, ImageDraw, ImageFont, ImageTk

# Frozen (GravityRush.exe), the code runs from PyInstaller's temporary folder: the files live in
# the launcher folder beside the executable.
HERE = Path(sys.executable).resolve().parent / 'launcher' if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
FONT_FILE = HERE / 'fonts' / 'Cabin.ttf'
BACKGROUND = HERE / 'assets' / 'background.png'   # the player's own picture, never in the repository

# Design size (DESIGN-launcher.md); everything is scaled from it.
W, H = 1120, 700

INK, PAPER, PAPER2 = '#1b1d1e', '#f4efd5', '#e3ddb9'
OR, OR2, BL, BL2 = '#c8473a', '#9b3328', '#1d7d70', '#8fdcc4'
GD, GR, CUBE = '#d4a83c', '#5cbf63', '#4b9fd1'
MU, SD, TX = '#5a5f58', '#2c302e', '#171a26'
SHADOW = (10, 14, 13, 153)
DASH = '#b8b5a0'      # the dashed row line: ink at 28 % over paper

# ---------------------------------------------------------------------------------------------
# Texts: English with the Italian next to it (the launcher follows the Windows language).

TEXTS = {
    'Play': 'Avvia', 'Game': 'Gioco', 'Video': 'Video', 'Controls': 'Controlli', 'Advanced': 'Avanzate',
    'Log & diagnostics': 'Log e diagnostica', 'Quit': 'Esci', 'VERSION {}': 'VERSIONE {}',
    'FOLDERS': 'CARTELLE', 'Game folder': 'Cartella del gioco',
    'Your game dump (eboot.bin, sce_module, sce_sys).': 'Il tuo dump del gioco (eboot.bin, sce_module, sce_sys).',
    'Saves folder': 'Cartella dei salvataggi',
    'Empty: the launcher data folder (it also holds the shader cache).':
        'Se vuota usa la cartella dei dati del launcher (contiene anche la cache degli shader).',
    'Browse…': 'Sfoglia…', 'Open': 'Apri', 'SHORTCUTS': 'COLLEGAMENTI',
    'Start without opening the launcher': 'Avvia senza aprire il launcher',
    'The game starts at once with the saved settings. Hold Shift to open the launcher again.':
        'Il gioco parte subito con le impostazioni salvate. Per riaprire il launcher tieni premuto Maiusc.',
    'Create desktop shortcut': 'Crea collegamento sul desktop', 'SAVES': 'SALVATAGGI',
    'Save backups': 'Backup dei salvataggi', 'Restore': 'Ripristina', 'Refresh': 'Aggiorna',
    'Made before every start, newest first: the last {} are kept. Restoring backs up the current saves first.':
        'Creati prima di ogni avvio, dal più recente: ne restano {}. Il ripristino salva prima i dati attuali.',
    'LANGUAGE': 'LINGUA', 'Game language': 'Lingua del gioco',
    'English': 'Inglese', 'Italian': 'Italiano', 'French': 'Francese', 'German': 'Tedesco',
    'Spanish': 'Spagnolo', 'Japanese': 'Giapponese',
    'SCREEN': 'SCHERMO', 'Window mode': 'Modalità finestra', 'Windowed': 'Finestra',
    'Fullscreen': 'Schermo intero', 'Borderless': 'Senza bordi', 'Vertical sync': 'Sincronia verticale',
    'FPS limit': 'Limite FPS', 'Unlimited': 'Libero',
    'The game is made for 60 FPS; other values can change physics and animations.':
        'Il gioco è pensato per 60 FPS: valori diversi possono alterare fisica e animazioni.',
    'Reset': 'Ripristina', 'Apply': 'Applica', 'Reset all': 'Ripristina tutto',
    'COMMAND': 'COMANDO', 'CONTROLLER': 'CONTROLLER', 'KEYBOARD': 'TASTIERA', 'BUTTONS': 'TASTI',
    'D-PAD': 'CROCE DIREZIONALE', 'GYROSCOPE': 'GIROSCOPIO', 'Sensitivity': 'Sensibilità',
    'Aiming by moving a DualSense or DualShock 4.': 'Per mirare muovendo un DualSense o un DualShock 4.',
    'Click a key, then press the new one (Esc cancels).': 'Clicca un tasto, poi premi quello nuovo (Esc annulla).',
    'Press a key…': 'Premi un tasto…',
    'LAUNCHER': 'LAUNCHER', 'Launcher language': 'Lingua del launcher', 'System': 'Sistema',
    'IN GAME': 'IN GIOCO', 'Performance overlay': 'Overlay prestazioni',
    'Shows the FPS while you play.': 'Mostra gli FPS mentre giochi.',
    'In-game menu': 'Menu in gioco',
    'Opens the settings while you play: Ins on the keyboard, or R3 + L2 on the controller.':
        'Apre le impostazioni durante la partita: Ins sulla tastiera, oppure R3 + L2 sul controller.',
    'PERFORMANCE': 'PRESTAZIONI', 'Shader cache': 'Cache degli shader', 'Clear': 'Svuota',
    'DEVELOPMENT': 'SVILUPPO', 'Validation layer': 'Strato di validazione',
    'Vulkan checks for bug reports; slower.': 'Controlli di Vulkan per le segnalazioni di errori; più lento.',
    'DATA': 'DATI', 'Launcher data folder': 'Cartella dei dati del launcher',
    'Export settings': 'Esporta configurazione', 'Import settings': 'Importa configurazione',
    'Copy log': 'Copia log', 'Open log folder': 'Apri cartella log',
    'Game messages': 'Messaggi del gioco', 'No game started yet.': 'Nessuna partita avviata finora.',
    'Game found · all ready': 'Gioco rilevato · tutto pronto', 'Choose the game folder': 'Scegli la cartella del gioco',
    'Last save · {}': 'Ultimo salvataggio · {}', 'No saves yet': 'Nessun salvataggio',
    'VSync': 'VSync', 'Limit {} FPS': 'Limite {} FPS', 'Unlimited FPS': 'FPS libero',
    'Settings applied': 'Impostazioni applicate', 'Defaults restored': 'Valori predefiniti ripristinati',
    'Quit?': 'Uscire?', 'Close Inkfall?': 'Vuoi chiudere Inkfall?', 'Cancel': 'Annulla',
    'The game keeps running.': 'Il gioco resta aperto.',
    'Starting…': 'Avvio in corso…', 'Preparing the game': 'Preparazione del gioco',
    'The game is starting': 'Il gioco si sta aprendo', 'In game': 'In gioco',
    'The game is running in its own window.': 'Il gioco è aperto nella sua finestra.',
    'Stop the game': 'Chiudi il gioco', 'Close the launcher': 'Chiudi il launcher',
    'The game exited.': 'Il gioco si è chiuso.',
    'Choose the game folder first.': 'Prima scegli la cartella del gioco.',
    'Restore saves?': 'Ripristinare?', 'The current saves are backed up first.': 'Prima verranno salvati i dati attuali.',
    'Saves restored': 'Salvataggi ripristinati', 'Close the game first.': 'Prima chiudi il gioco.',
    'Shortcut created on the desktop': 'Collegamento creato sul desktop',
    'Shader cache cleared': 'Cache degli shader svuotata', 'Log copied': 'Log copiato',
    'Settings exported': 'Configurazione esportata', 'Settings imported': 'Configurazione importata',
    'Could not: {}': 'Non riuscito: {}', 'empty': 'vuota', 'Minimize': 'Riduci a icona', 'Close': 'Chiudi',
}
LANG = 'en'


def t(text):
    return TEXTS.get(text, text) if LANG == 'it' else text


# PS4 button names, per row of the logic's CONTROLS.
BUTTON_NAMES = {'cross': ('Cross', 'Croce'), 'circle': ('Circle', 'Cerchio'), 'square': ('Square', 'Quadrato'),
                'triangle': ('Triangle', 'Triangolo'), 'l1': ('L1',), 'r1': ('R1',), 'l2': ('L2',), 'r2': ('R2',),
                'l3': ('L3',), 'r3': ('R3',), 'options': ('Options',), 'touchpad': ('Touchpad',),
                'up': ('Up', 'Su'), 'down': ('Down', 'Giù'), 'left': ('Left', 'Sinistra'), 'right': ('Right', 'Destra')}
# Controller button names in Italian (the logic's PAD_STYLES are English).
PAD_NAMES = {'Cross': 'Croce', 'Circle': 'Cerchio', 'Square': 'Quadrato', 'Triangle': 'Triangolo',
             'Share / Create': 'Share / Create', 'Touchpad click': 'Clic touchpad', 'D-pad up': 'Croce su',
             'D-pad down': 'Croce giù', 'D-pad left': 'Croce sinistra', 'D-pad right': 'Croce destra',
             'Trigger': 'Grilletto'}
# Tk key names -> the SDL key names the runtime's key map uses (src/runtime_pad.c).
TK_KEYS = {'space': 'Space', 'Shift_L': 'Left Shift', 'Shift_R': 'Right Shift', 'Control_L': 'Left Ctrl',
           'Control_R': 'Right Ctrl', 'Alt_L': 'Left Alt', 'Alt_R': 'Right Alt', 'Return': 'Return', 'Tab': 'Tab',
           'BackSpace': 'Backspace', 'Up': 'Up', 'Down': 'Down', 'Left': 'Left', 'Right': 'Right',
           'Caps_Lock': 'CapsLock', 'Insert': 'Insert', 'Delete': 'Delete', 'Home': 'Home', 'End': 'End',
           'Prior': 'PageUp', 'Next': 'PageDown'}
GAME_LANGUAGES = [('5', 'Italian'), ('1', 'English'), ('2', 'French'), ('4', 'German'), ('3', 'Spanish'),
                  ('0', 'Japanese')]
WINDOW_MODES = [('windowed', 'Windowed'), ('fullscreen', 'Fullscreen'), ('borderless', 'Borderless')]
FPS_CHOICES = [('30', '30'), ('60', '60'), ('120', '120'), ('0', 'Unlimited')]


# ---------------------------------------------------------------------------------------------
# Drawing (Pillow). Shapes are drawn at twice the size and scaled down for smooth edges.

def rgba(color, alpha=255):
    if isinstance(color, tuple):
        return color
    color = color.lstrip('#')
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4)) + (alpha,)


_fonts = {}


def pil_font(size, weight=700):
    key = (round(size), weight)
    if key not in _fonts:
        try:
            font = ImageFont.truetype(str(FONT_FILE), max(1, round(size)))
            font.set_variation_by_axes([weight, 100])
        except (OSError, ValueError):
            font = ImageFont.load_default(size)
        _fonts[key] = font
    return _fonts[key]


def text_width(text, font, spacing):
    return sum(font.getlength(c) for c in text) + spacing * max(0, len(text) - 1)


def draw_text(draw, x, y, text, font, fill, spacing=0.0, stroke=0, stroke_fill=None):
    """Text with letter spacing (Pillow has none), from the top-left of its ink box."""
    for c in text:
        draw.text((x, y), c, font=font, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
        x += font.getlength(c) + spacing


def text_top(font, height):
    """The y that centres capital letters in `height`."""
    box = font.getbbox('H')
    return (height - (box[3] - box[1])) / 2 - box[1]


def capsule(w, h, point):
    return [(0, 0), (w - point, 0), (w, h / 2), (w - point, h), (0, h)]


class Painter:
    """Every picture of the window, at the window's scale."""

    def __init__(self, scale):
        self.s = scale

    def px(self, v):
        return max(1, round(v * self.s))

    def canvas(self, w, h):
        return Image.new('RGBA', (self.px(w) * 2, self.px(h) * 2), (0, 0, 0, 0))

    def done(self, image):
        return image.resize((image.width // 2, image.height // 2), Image.LANCZOS)

    def nav_button(self, w, h, label, look, small=False, go=False):
        """A menu capsule: ink outline with a point, paper inside, hard shadow (4 px)."""
        k = self.s * 2
        img = self.canvas(w + 4, h + 4)
        d = ImageDraw.Draw(img)
        outer = [(x * k, y * k) for x, y in capsule(w, h, 20)]
        d.polygon([(x + 4 * k, y + 4 * k) for x, y in outer], fill=SHADOW)
        d.polygon(outer, fill=rgba(INK))
        fill = {'normal': PAPER, 'hover': PAPER2, 'on': BL, 'go': OR, 'go_hover': '#d9574a'}[look]
        inner = [(3 * k, 3 * k), ((w - 4 - 18) * k, 3 * k), ((w - 4) * k, h / 2 * k), ((w - 4 - 18) * k, (h - 3) * k),
                 (3 * k, (h - 3) * k)]
        d.polygon(inner, fill=rgba(fill))
        color = rgba('#ffffff') if go else rgba(PAPER) if look == 'on' else rgba(INK)
        if go:
            size, spacing, left = (17, .12, 14) if small else (20, .16, 18)
        else:
            size, spacing, left = (12, .03, 14) if small else (14.5, .1, 18)
        font = pil_font(size * k)
        x = (3 + left) * k
        if go:  # play triangle
            tri = 16 * k
            y0 = (h - 16) / 2 * k
            d.polygon([(x, y0 + 1 * k), (x + tri * 0.86, y0 + tri / 2), (x, y0 + tri - 1 * k)], fill=color)
            x += tri + 10 * k
        draw_text(d, x, text_top(font, h * k), label.upper(), font, color, spacing * size * k)
        return self.done(img)

    def brand(self, scale):
        """The ribbon and the title (Cabin Bold with an ink outline and a red shadow)."""
        k = self.s * scale * 2
        ribbon_font, title_font = pil_font(12.5 * k), pil_font(58 * k)
        title = 'GRAVITY RUSH'
        tw = text_width(title, title_font, .03 * 58 * k)
        rw = text_width('REMASTERED', ribbon_font, .36 * 12.5 * k) + 42 * k
        rh = 23 * k
        width, height = max(tw + 20 * k, rw) + 10 * k, rh + 8 * k + 66 * k + 10 * k
        img = Image.new('RGBA', (int(width), int(height)), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.polygon([(0, 0), (rw - 12 * k, 0), (rw, rh / 2), (rw - 12 * k, rh), (0, rh)], fill=rgba(GD))
        draw_text(d, 14 * k, text_top(ribbon_font, rh), 'REMASTERED', ribbon_font, rgba(INK), .36 * 12.5 * k)
        y = rh + 8 * k
        stroke = max(1, round(4 * k))
        draw_text(d, 4 * k + 4 * k, y + 5 * k, title, title_font, rgba(OR), .03 * 58 * k, stroke, rgba(OR))
        draw_text(d, 4 * k, y, title, title_font, rgba(PAPER), .03 * 58 * k, stroke, rgba(INK))
        return img.resize((max(1, img.width // 2), max(1, img.height // 2)), Image.LANCZOS)

    def panel(self, w, h, tab=None):
        """The paper panel: ink border, 6 px corners, hard shadow 8 px, halftone dots, tilted tab."""
        k = self.s * 2
        top = 24 if tab else 0
        img = self.canvas(w + 8, h + 8 + top)
        d = ImageDraw.Draw(img)
        y0 = top * k
        d.rounded_rectangle((8 * k, y0 + 8 * k, (w + 8) * k, y0 + (h + 8) * k), 6 * k, fill=SHADOW)
        d.rounded_rectangle((0, y0, w * k, y0 + h * k), 6 * k, fill=rgba(PAPER), outline=rgba(INK), width=round(3 * k))
        # Halftone dots, fading from the top-right corner.
        dots = Image.new('RGBA', img.size, (0, 0, 0, 0))
        dd = ImageDraw.Draw(dots)
        step, r = 10 * k, 1.6 * k
        x_start = (w - 190) * k
        for row in range(int(120 * k // step) + 1):
            for col in range(int(190 * k // step) + 1):
                cx, cy = x_start + col * step + step / 2, y0 + 3 * k + row * step + step / 2
                if cx > (w - 4) * k or cy > y0 + 120 * k:
                    continue
                # 225 degree gradient: strongest at the top-right corner, gone at 70 %.
                fx, fy = ((w * k) - cx) / (190 * k), (cy - y0) / (120 * k)
                fade = max(0.0, 1 - (fx + fy) / 1.4)
                if fade > 0:
                    dd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=rgba(OR, int(51 * fade)))
        img.alpha_composite(dots)
        if tab:
            font = pil_font(15 * k)
            tw = text_width(tab.upper(), font, .14 * 15 * k)
            tx, th = 22 * k, 34 * k
            ty = y0 - 19 * k
            skew = th * math.tan(math.radians(10))
            pts = [(tx + skew, ty), (tx + tw + 48 * k + skew, ty), (tx + tw + 48 * k, ty + th), (tx, ty + th)]
            d.polygon([(x + 3 * k, y + 3 * k) for x, y in pts], fill=SHADOW)
            d.polygon(pts, fill=rgba(OR), outline=rgba(INK), width=round(3 * k))
            draw_text(d, tx + 24 * k + skew / 2, ty + text_top(font, th), tab.upper(), font, rgba(PAPER), .14 * 15 * k)
        return self.done(img)

    def toggle(self, on):
        k = self.s * 2
        img = self.canvas(48, 26)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((k, k, 47 * k, 25 * k), 13 * k, fill=rgba(BL if on else '#cfcdb0'), outline=rgba(INK),
                            width=round(2.5 * k))
        cx = (48 - 4 - 10) * k if on else (4 + 10) * k
        d.ellipse((cx - 8 * k, 5 * k, cx + 8 * k, 21 * k), fill=rgba(PAPER if on else INK))
        return self.done(img)

    def pill(self, text, on, size=12.5, height=36, padding=10):
        k = self.s * 2
        font = pil_font(size * k)
        w = text_width(text, font, 0) / k + padding * 2 + 6
        img = self.canvas(w, height)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((k, k, (w - 1) * k, (height - 1) * k), height / 2 * k, fill=rgba(BL if on else '#ffffff'),
                            outline=rgba(INK), width=round(2.5 * k))
        draw_text(d, (padding + 3) * k, text_top(font, height * k), text, font, rgba(PAPER if on else SD))
        return self.done(img)

    def button(self, text, kind, look):
        """pri / gh / sm buttons: ink border, hard shadow that grows on hover and goes on press."""
        k = self.s * 2
        size = {'pri': 12.5, 'gh': 12.5, 'sm': 13.5, 'chip': 12}[kind]
        height = {'pri': 44, 'gh': 44, 'sm': 38, 'chip': 28}[kind]
        upper = kind in ('pri', 'gh')
        label = text.upper() if upper else text
        font = pil_font(size * k)
        spacing = .04 * size * k if upper else 0
        pad = 9 if kind == 'chip' else 14
        w = text_width(label, font, spacing) / k + pad * 2 + 6
        sh = {'pri': 3, 'gh': 3, 'sm': 2, 'chip': 0}[kind]
        grow = {'normal': 0, 'hover': 2, 'press': -sh}[look]
        off = {'normal': 0, 'hover': -1, 'press': sh}[look]
        img = self.canvas(w + 6, height + 6)
        d = ImageDraw.Draw(img)
        x0, y0 = (1 + off) * k + k, (1 + off) * k + k
        x1, y1 = x0 + w * k, y0 + height * k
        if sh + grow > 0:
            d.rounded_rectangle((x0 + (sh + grow) * k, y0 + (sh + grow) * k, x1 + (sh + grow) * k, y1 + (sh + grow) * k),
                                7 * k, fill=rgba(INK))
        fill = rgba(OR if kind == 'pri' else '#ffffff')
        border = 2 if kind == 'chip' else 2.5 if kind == 'sm' else 3
        d.rounded_rectangle((x0, y0, x1, y1), 7 * k, fill=fill, outline=rgba(INK), width=round(border * k))
        if kind == 'chip':  # thicker bottom edge
            d.rectangle((x0 + 4 * k, y1 - 3 * k, x1 - 4 * k, y1), fill=rgba(INK))
        color = rgba('#ffffff' if kind == 'pri' else INK)
        draw_text(d, x0 + (pad + 3) * k, y0 + text_top(font, (height - (2 if kind == 'chip' else 0)) * k), label,
                  font, color, spacing)
        return self.done(img)

    def label(self, text, size, color, weight=700, spacing=0.0, upper=False, shadow=None):
        k = self.s * 2
        text = text.upper() if upper else text
        font = pil_font(size * k, weight)
        w = text_width(text, font, spacing * size * k) / k + 4
        h = size * 1.5
        img = self.canvas(w, h)
        d = ImageDraw.Draw(img)
        if shadow:
            draw_text(d, 2 * k, text_top(font, h * k) + 1 * k, text, font, rgba(shadow), spacing * size * k)
        draw_text(d, 2 * k, text_top(font, h * k), text, font, rgba(color), spacing * size * k)
        return self.done(img)

    def section(self, text):
        """Section title: gold diamond, red-brown spaced capitals."""
        k = self.s * 2
        font = pil_font(12.5 * k)
        w = text_width(text, font, .22 * 12.5 * k) / k + 26
        h = 20
        img = self.canvas(w, h)
        d = ImageDraw.Draw(img)
        cx, cy, r = 7.5 * k, h / 2 * k - 1 * k, 6.4 * k
        d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=rgba(GD), outline=rgba(INK),
                  width=round(2 * k))
        draw_text(d, 20 * k, text_top(font, h * k), text, font, rgba(OR2), .22 * 12.5 * k)
        return self.done(img)

    def status(self, text, icon):
        """Bottom status pill: dark, thin light inner edge, crystal or cube icon."""
        k = self.s * 2
        font = pil_font(13.5 * k, 600)
        w = text_width(text, font, 0) / k + 9 + 17 + 8 + 14
        h = 30
        img = self.canvas(w, h)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, w * k, h * k), h / 2 * k, fill=(27, 29, 30, 230))
        d.rounded_rectangle((1.5 * k, 1.5 * k, (w - 1.5) * k, (h - 1.5) * k), (h / 2 - 1.5) * k,
                            outline=(244, 239, 213, 56), width=round(1.5 * k))
        cx, cy = (9 + 8.5) * k, h / 2 * k
        if icon == 'ok':
            pts = [(cx, cy - 7 * k), (cx + 5.5 * k, cy - 2 * k), (cx, cy + 7 * k), (cx - 5.5 * k, cy - 2 * k)]
            d.polygon(pts, fill=rgba(GR), outline=rgba(INK), width=round(1.6 * k))
        elif icon == 'warn':
            d.polygon([(cx, cy - 7 * k), (cx + 7 * k, cy + 6 * k), (cx - 7 * k, cy + 6 * k)], fill=rgba(OR),
                      outline=rgba(INK), width=round(1.6 * k))
        else:  # the blue cube
            top = [(cx, cy - 7 * k), (cx + 6 * k, cy - 3.5 * k), (cx, cy), (cx - 6 * k, cy - 3.5 * k)]
            d.polygon([(cx, cy - 7 * k), (cx + 6 * k, cy - 3.5 * k), (cx + 6 * k, cy + 3.5 * k), (cx, cy + 7 * k),
                       (cx - 6 * k, cy + 3.5 * k), (cx - 6 * k, cy - 3.5 * k)], fill=rgba(CUBE), outline=rgba(INK),
                      width=round(1.6 * k))
            d.line(top + [top[0]], fill=rgba(INK), width=round(1.1 * k))
            d.line([(cx, cy), (cx, cy + 7 * k)], fill=rgba(INK), width=round(1.1 * k))
        draw_text(d, (9 + 17 + 8) * k, text_top(font, h * k), text, font, rgba(PAPER))
        return self.done(img)

    def gauge(self, w, fraction, phase):
        """The launch gauge: a pill with teal stripes and a point."""
        k = self.s * 2
        h = 20
        img = self.canvas(w, h)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, w * k, h * k), h / 2 * k, fill=rgba('#cdd0b5'))
        fill_w = max(0.0, min(1.0, fraction)) * (w - 6) * k
        if fill_w > 2 * k:
            stripes = Image.new('RGBA', img.size, (0, 0, 0, 0))
            sd = ImageDraw.Draw(stripes)
            period = 24 * k
            for i in range(-4, int(w * k / period) + 6):
                x = i * period + phase * period
                sd.polygon([(x, h * k), (x + 12 * k, h * k), (x + 12 * k + h * k * .47, 0), (x + h * k * .47, 0)],
                           fill=rgba(BL))
                sd.polygon([(x + 12 * k, h * k), (x + 24 * k, h * k), (x + 24 * k + h * k * .47, 0),
                            (x + 12 * k + h * k * .47, 0)], fill=rgba(BL2))
            mask = Image.new('L', img.size, 0)
            ImageDraw.Draw(mask).polygon([(3 * k, 3 * k), (3 * k + fill_w - 9 * k, 3 * k), (3 * k + fill_w, h / 2 * k),
                                          (3 * k + fill_w - 9 * k, (h - 3) * k), (3 * k, (h - 3) * k)], fill=255)
            img.paste(stripes, (0, 0), mask)
        d.rounded_rectangle((0, 0, w * k, h * k), h / 2 * k, outline=rgba(INK), width=round(3 * k))
        return self.done(img)

    def window_buttons(self, hover):
        k = self.s * 2
        img = self.canvas(88, 32)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, 88 * k, 32 * k), 16 * k, fill=(27, 29, 30, 158))
        # Drawn with lines: Cabin has no multiplication sign.
        line = round(1.8 * k)
        for i in range(2):
            color = rgba(OR if hover == i else PAPER)
            cx, cy = (4 + 40 * i + 20) * k, 16 * k
            if i == 0:
                d.line([(cx - 6 * k, cy + 1 * k), (cx + 6 * k, cy + 1 * k)], fill=color, width=line)
            else:
                d.line([(cx - 5 * k, cy - 5 * k), (cx + 5 * k, cy + 5 * k)], fill=color, width=line)
                d.line([(cx - 5 * k, cy + 5 * k), (cx + 5 * k, cy - 5 * k)], fill=color, width=line)
        return self.done(img)

    def background(self, width, height):
        """The player's picture covering width x height (or a dusk gradient without it)."""
        w, h = self.px(width), self.px(height)
        try:
            with Image.open(BACKGROUND) as source:
                pic = source.convert('RGB')
            scale = max(w / pic.width, h / pic.height)
            return pic.resize((math.ceil(pic.width * scale), math.ceil(pic.height * scale)), Image.LANCZOS)
        except OSError:
            img = Image.new('RGB', (w, h), '#67a28f')
            d = ImageDraw.Draw(img)
            for y in range(h):
                f = y / h
                d.line([(0, y), (w, y)], fill=(int(103 + 70 * f), int(162 - 20 * f), int(143 - 50 * f)))
            return img

    def overlay(self):
        return Image.new('RGBA', (self.px(W), self.px(H)), (10, 16, 15, 153))


# ---------------------------------------------------------------------------------------------
# Animation: tweens advanced by one timer.

def ease_out_back(x, s=1.2):
    x -= 1
    return x * x * ((s + 1) * x + s) + 1


def ease_in(x):
    return x * x * x


def ease_out(x):
    return 1 - (1 - x) ** 3


class Animator:
    def __init__(self, root, enabled):
        self.root, self.enabled, self.items = root, enabled, []
        self.running = False

    def add(self, duration_ms, update, ease=ease_out, delay_ms=0, done=None):
        if not self.enabled:
            update(1.0)
            if done:
                done()
            return
        self.items.append([time.perf_counter() + delay_ms / 1000, duration_ms / 1000, update, ease, done])
        if not self.running:
            self.running = True
            self.root.after(16, self.tick)

    def tick(self):
        now = time.perf_counter()
        for item in self.items[:]:
            start, length, update, ease, done = item
            if now < start:
                continue
            x = min(1.0, (now - start) / length) if length else 1.0
            update(ease(x))
            if x >= 1.0:
                self.items.remove(item)
                if done:
                    done()
        if self.items:
            self.root.after(16, self.tick)
        else:
            self.running = False


def reduced_motion():
    """Windows "show animations" switched off (Settings > Accessibility > Visual effects)."""
    try:
        value = ctypes.c_bool(True)
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(value), 0)  # SPI_GETCLIENTAREAANIMATION
        return not value.value
    except (AttributeError, OSError):
        return False


# ---------------------------------------------------------------------------------------------
# Widgets on the paper.

class ImageButton:
    """A Label showing normal / hover / press pictures."""

    def __init__(self, app, parent, text, command, kind='sm', bg=PAPER):
        self.app, self.command, self.kind, self.text = app, command, kind, text
        tk = app.tk
        self.widget = tk.Label(parent, bd=0, bg=bg, cursor='hand2', highlightthickness=0)
        self.render()
        self.widget.bind('<Enter>', lambda e: self.show('hover'))
        self.widget.bind('<Leave>', lambda e: self.show('normal'))
        self.widget.bind('<ButtonPress-1>', lambda e: self.show('press'))
        self.widget.bind('<ButtonRelease-1>', self.release)

    def render(self):
        self.images = {look: ImageTk.PhotoImage(self.app.paint.button(self.text, self.kind, look))
                       for look in ('normal', 'hover', 'press')}
        self.show('normal')

    def set_text(self, text):
        self.text = text
        self.render()

    def show(self, look):
        self.widget.configure(image=self.images[look])

    def release(self, event):
        inside = 0 <= event.x < self.widget.winfo_width() and 0 <= event.y < self.widget.winfo_height()
        self.show('hover' if inside else 'normal')
        if inside and self.command:
            self.command()


class Toggle:
    def __init__(self, app, parent, value, on_change):
        self.app, self.value, self.on_change = app, bool(value), on_change
        self.images = [ImageTk.PhotoImage(app.paint.toggle(False)), ImageTk.PhotoImage(app.paint.toggle(True))]
        self.widget = app.tk.Label(parent, bd=0, bg=PAPER, cursor='hand2', image=self.images[self.value])
        self.widget.bind('<Button-1>', self.flip)

    def flip(self, _event=None):
        self.value = not self.value
        self.widget.configure(image=self.images[self.value])
        self.on_change(self.value)


class Segments:
    """A row of pill buttons, one chosen."""

    def __init__(self, app, parent, options, value, on_change):
        self.app, self.options, self.value, self.on_change = app, options, value, on_change
        self.widget = app.tk.Frame(parent, bg=PAPER)
        self.labels = []
        for key, text in options:
            images = (ImageTk.PhotoImage(app.paint.pill(t(text), False)), ImageTk.PhotoImage(app.paint.pill(t(text), True)))
            label = app.tk.Label(self.widget, bd=0, bg=PAPER, cursor='hand2')
            label.images = images
            label.bind('<Button-1>', lambda e, k=key: self.choose(k))
            label.pack(side='left', padx=(0, app.px(4)))
            self.labels.append((key, label))
        self.refresh()

    def refresh(self):
        for key, label in self.labels:
            label.configure(image=label.images[key == self.value])

    def choose(self, key):
        self.value = key
        self.refresh()
        self.on_change(key)


class Slider:
    """A pill track with a teal fill and an ink knob (Tk's Scale draws native blocks on Windows)."""

    def __init__(self, app, parent, low, high, step, value, on_change, width=220):
        self.app, self.low, self.high, self.step, self.on_change = app, low, high, step, on_change
        self.value = value
        self.w, self.h = app.px(width), app.px(26)
        self.widget = app.tk.Canvas(parent, width=self.w, height=self.h, bg=PAPER, highlightthickness=0, bd=0,
                                    cursor='hand2')
        for sequence in ('<Button-1>', '<B1-Motion>'):
            self.widget.bind(sequence, self.pick)
        self.draw()

    def draw(self):
        c, px = self.widget, self.app.px
        c.delete('all')
        r, y, pad = px(5), self.h / 2, px(12)
        frac = (self.value - self.low) / (self.high - self.low)
        x = pad + frac * (self.w - 2 * pad)
        c.create_rectangle(pad, y - r, self.w - pad, y + r, fill=PAPER2, outline=INK, width=px(2))
        c.create_rectangle(pad, y - r, x, y + r, fill=BL, outline=INK, width=px(2))
        c.create_oval(x - px(10), y - px(10), x + px(10), y + px(10), fill=INK, outline=INK)
        c.create_oval(x - px(4), y - px(4), x + px(4), y + px(4), fill=PAPER, outline='')

    def pick(self, event):
        pad = self.app.px(12)
        frac = min(1.0, max(0.0, (event.x - pad) / max(1, self.w - 2 * pad)))
        value = round((self.low + frac * (self.high - self.low)) / self.step) * self.step
        value = round(min(self.high, max(self.low, value)), 3)
        if value != self.value:
            self.value = value
            self.draw()
            self.on_change(value)


class InkScrollbar:
    """An ink thumb on a cream track (the mock-up's scrollbar)."""

    def __init__(self, app, parent, command):
        self.app, self.command = app, command
        self.first, self.last = 0.0, 1.0
        self.widget = app.tk.Canvas(parent, width=app.px(9), bg=PAPER, highlightthickness=0, bd=0)
        self.widget.bind('<Configure>', lambda e: self.draw())
        self.widget.bind('<Button-1>', self.drag)
        self.widget.bind('<B1-Motion>', self.drag)

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self.draw()

    def draw(self):
        c = self.widget
        c.delete('all')
        w, h = int(c['width']), c.winfo_height()
        if h < 4 or self.last - self.first >= 1.0:
            return
        r = w / 2
        c.create_rectangle(0, r, w, h - r, fill=PAPER2, outline=PAPER2)
        c.create_oval(0, 0, w, w, fill=PAPER2, outline=PAPER2)
        c.create_oval(0, h - w, w, h, fill=PAPER2, outline=PAPER2)
        y0, y1 = self.first * h, max(self.first * h + w, self.last * h)
        c.create_rectangle(0, y0 + r, w, y1 - r, fill=INK, outline=INK)
        c.create_oval(0, y0, w, y0 + w, fill=INK, outline=INK)
        c.create_oval(0, y1 - w, w, y1, fill=INK, outline=INK)

    def drag(self, event):
        h = max(1, self.widget.winfo_height())
        size = self.last - self.first
        self.command('moveto', min(1 - size, max(0.0, event.y / h - size / 2)))


class DashLine:
    def __init__(self, app, parent):
        self.widget = app.tk.Canvas(parent, height=1, bg=PAPER, highlightthickness=0, bd=0)
        self.widget.bind('<Configure>', lambda e: (self.widget.delete('all'), self.widget.create_line(
            0, 0, e.width, 0, fill=DASH, dash=(3, 3))))


# ---------------------------------------------------------------------------------------------
# The window.

NAV = [('game', 'Game'), ('video', 'Video'), ('controls', 'Controls'), ('advanced', 'Advanced'), ('log', 'Log & diagnostics')]
PANEL_X, PANEL_Y, PANEL_W, PANEL_H = 290, 100, 552, 508


class Inkfall:
    def __init__(self, root, tk, filedialog, logic):
        global LANG
        self.root, self.tk, self.filedialog, self.logic = root, tk, filedialog, logic
        self.app = {**logic.APP_DEFAULTS, 'skip_launcher': False, 'gyro_sens': 1.4,
                    **logic.load_json(logic.CONFIG_FILE, {})}
        self.ini, self.ini_lines = logic.load_ini()
        ui = self.app.get('ui_language') or logic.windows_language()
        LANG = 'it' if ui == 'it' else 'en'
        self.process = self.job = None
        self.output, self.log_lines = queue.Queue(), []
        self.page = None
        self.capture = None   # (button, chip) while waiting for a key
        self.lifted = []      # the interface is up (gravity shift): hover and levitation pause
        self.register_font()
        # Scale: the screen's DPI, kept inside 92 % of the work area.
        dpi = root.winfo_fpixels('1i') / 96
        fit = min(root.winfo_screenwidth() * .92 / W, root.winfo_screenheight() * .92 / H)
        self.s = max(.6, min(dpi, fit))
        self.paint = Painter(self.s)
        self.anim = Animator(root, not reduced_motion())
        self.build_window()
        self.build_scene()
        self.root.after(100, self.drain)
        self.root.after(30, self.levitate)

    # ---- basics ----------------------------------------------------------------------------
    def px(self, v):
        return max(1, round(v * self.s))

    def font(self, size, weight='normal', family='Cabin'):
        return (family, -self.px(size), weight)

    def register_font(self):
        try:
            ctypes.windll.gdi32.AddFontResourceExW(str(FONT_FILE), 0x10, 0)  # FR_PRIVATE
        except (AttributeError, OSError):
            pass

    def save(self):
        logic = self.logic
        logic.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        logic.CONFIG_FILE.write_text(json.dumps(self.app, indent=2, ensure_ascii=False), encoding='utf-8')
        logic.save_ini({key: self.ini.get(key, value) for key, value in logic.INI_DEFAULTS.items()}, self.ini_lines)
        self.ini, self.ini_lines = logic.load_ini()

    def user_dir(self):
        return Path(self.app.get('user_dir') or self.logic.DATA_DIR / 'user')

    # ---- window ----------------------------------------------------------------------------
    def build_window(self):
        root, tk = self.root, self.tk
        root.title('Inkfall · Gravity Rush')
        root.configure(bg='#2b3a36')
        width, height = self.px(W), self.px(H)
        x = (root.winfo_screenwidth() - width) // 2
        y = (root.winfo_screenheight() - height) // 2
        root.geometry(f'{width}x{height}+{x}+{y}')
        root.resizable(False, False)
        try:
            root.iconbitmap(default=str(HERE / 'gravityrush.ico'))
        except tk.TclError:
            pass
        root.overrideredirect(True)
        root.after(10, self.taskbar_entry)
        root.bind('<Map>', self.restore_frameless)
        self.cv = tk.Canvas(root, width=width, height=height, highlightthickness=0, bd=0, bg='#2b3a36')
        self.cv.pack()
        self.cv.bind('<Motion>', self.parallax)
        self.cv.bind('<Button-1>', self.click_background)
        root.bind('<Escape>', self.escape)
        root.bind_all('<MouseWheel>', self.wheel)
        root.bind('<KeyPress>', self.key_press)

    def taskbar_entry(self):
        """A frameless window still gets its taskbar button and Windows 11 rounded corners."""
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.root.winfo_id())
            style = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
            user32.SetWindowLongW(hwnd, -20, (style & ~0x80) | 0x40000)  # no TOOLWINDOW, APPWINDOW
            corner = ctypes.c_int(2)  # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))
            self.root.withdraw()
            self.root.after(10, self.root.deiconify)
        except (AttributeError, OSError):
            pass

    def minimize(self):
        self.root.overrideredirect(False)
        self.root.iconify()

    def restore_frameless(self, _event=None):
        if self.root.state() == 'normal' and not self.root.overrideredirect():
            self.root.overrideredirect(True)
            self.root.after(10, self.taskbar_entry)

    # ---- scene -----------------------------------------------------------------------------
    def build_scene(self):
        cv, paint = self.cv, self.paint
        self.photos = {}
        # Background, 18 px larger on every side for the parallax.
        self.bg_image = ImageTk.PhotoImage(paint.background(W + 36, H + 36))
        self.bg_excess = self.bg_image.width() / self.s - (W + 36)
        self.bg_pos = .5          # background-position: 50 % (home), 25 % (a page is open)
        self.par = [0.0, 0.0, 0.0, 0.0]   # current x, y and target x, y
        self.bg = cv.create_image(0, 0, anchor='nw', image=self.bg_image)
        self.place_background()
        # Title bar: name on the left, window buttons on a dark pill.
        self.photos['bar'] = ImageTk.PhotoImage(paint.label('INKFALL', 12, PAPER, spacing=.3))
        cv.create_polygon(self.diamond(26, 20, 5), fill=GD, outline=INK, width=self.px(2))
        cv.create_image(self.px(38), self.px(20), anchor='w', image=self.photos['bar'])
        self.win_images = [ImageTk.PhotoImage(paint.window_buttons(i)) for i in (None, 0, 1)]
        self.win = cv.create_image(self.px(W - 8), self.px(4), anchor='ne', image=self.win_images[0])
        cv.tag_bind(self.win, '<Motion>', self.window_hover)
        cv.tag_bind(self.win, '<Leave>', lambda e: cv.itemconfigure(self.win, image=self.win_images[0]))
        cv.tag_bind(self.win, '<Button-1>', self.window_click)
        self.drag_area = cv.create_rectangle(0, 0, self.px(W - 100), self.px(40), fill='', outline='')
        cv.tag_bind(self.drag_area, '<ButtonPress-1>', self.drag_start)
        cv.tag_bind(self.drag_area, '<B1-Motion>', self.drag_move)
        # Brand.
        self.brand_images = {1.0: ImageTk.PhotoImage(paint.brand(1.0)), .46: ImageTk.PhotoImage(paint.brand(.46))}
        self.brand_scale = 1.0
        self.brand = cv.create_image(self.px(56), self.px(62), anchor='nw', image=self.brand_images[1.0])
        self.brand_y = 62.0
        # Menu.
        self.nav_items = {}
        self.nav_hover = None
        self.render_nav()
        # Status pills and version.
        self.status_items = []
        self.refresh_status()
        self.photos['ver'] = ImageTk.PhotoImage(paint.label(t('VERSION {}').format(self.logic.VERSION), 12, PAPER,
                                                            spacing=.3, shadow=INK))
        self.ver = cv.create_image(self.px(W / 2), self.px(H - 38), anchor='center', image=self.photos['ver'])
        # Panel (hidden until a page opens), modal and toast.
        self.panel_items = []
        self.modal_items = []
        self.toast_items = []
        self.drop_in()

    def diamond(self, cx, cy, r):
        return [self.px(cx), self.px(cy - r), self.px(cx + r), self.px(cy), self.px(cx), self.px(cy + r),
                self.px(cx - r), self.px(cy)]

    def place_background(self):
        x = -18 + -self.bg_excess * self.bg_pos + self.par[0]
        y = -18 + self.par[1]
        self.cv.coords(self.bg, self.px(x) if x >= 0 else -self.px(-x), self.px(y) if y >= 0 else -self.px(-y))

    def parallax(self, event):
        if not self.anim.enabled:
            return
        self.par[2] = -(event.x / self.px(W) - .5) * 18
        self.par[3] = -(event.y / self.px(H) - .5) * 10

    def levitate(self):
        """Title levitation (6 px, 5.5 s) and the background easing toward the pointer."""
        if self.anim.enabled and not self.lifted:
            phase = (time.perf_counter() % 5.5) / 5.5
            lift = -6 * (0.5 - 0.5 * math.cos(phase * 2 * math.pi))
            self.cv.coords(self.brand, self.px(56), self.px(self.brand_y + lift))
            self.par[0] += (self.par[2] - self.par[0]) * .08
            self.par[1] += (self.par[3] - self.par[1]) * .08
            self.place_background()
        self.root.after(30, self.levitate)

    def window_hover(self, event):
        part = 0 if event.x < self.px(W - 8 - 44) else 1
        self.cv.itemconfigure(self.win, image=self.win_images[1 + part])

    def window_click(self, event):
        if event.x < self.px(W - 8 - 44):
            self.minimize()
        else:
            self.ask_quit()

    def drag_start(self, event):
        self.drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def drag_move(self, event):
        self.root.geometry(f'+{event.x_root - self.drag[0]}+{event.y_root - self.drag[1]}')

    # ---- menu ------------------------------------------------------------------------------
    def nav_entries(self):
        return [('go', t('Play'), 52)] + [(key, t(text), 40) for key, text in NAV] + [('quit', t('Quit'), 40)]

    def render_nav(self):
        """The capsules for the current state (wide at home, narrow with a page open)."""
        small = self.page is not None
        width = 206 if small else 300
        y = 190
        for index, (key, label, height) in enumerate(self.nav_entries()):
            go = key == 'go'
            looks = ('go', 'go_hover') if go else ('normal', 'hover', 'on')
            images = {look: ImageTk.PhotoImage(self.paint.nav_button(width, height, label, look, small, go)) for look in looks}
            item = self.nav_items.get(key)
            if item:
                item['images'] = images
                item['y'] = y
                self.cv.itemconfigure(item['id'], image=self.nav_image(key))
            else:
                item_id = self.cv.create_image(self.px(56), self.px(y), anchor='nw', image=images[looks[0]])
                item = self.nav_items[key] = {'id': item_id, 'images': images, 'y': y, 'x': 56.0, 'index': index}
                self.cv.tag_bind(item_id, '<Enter>', lambda e, k=key: self.nav_enter(k))
                self.cv.tag_bind(item_id, '<Leave>', lambda e, k=key: self.nav_leave(k))
                self.cv.tag_bind(item_id, '<Button-1>', lambda e, k=key: self.nav_click(k))
            y += height + 8

    def nav_image(self, key):
        item = self.nav_items[key]
        if key == 'go':
            return item['images']['go_hover' if self.nav_hover == key else 'go']
        if key == self.page:
            return item['images']['on']
        return item['images']['hover' if self.nav_hover == key else 'normal']

    def nav_move(self, key, x):
        item = self.nav_items[key]
        item['x'] = x
        self.cv.coords(item['id'], self.px(x), self.px(item['y']))

    def nav_enter(self, key):
        if self.lifted:
            return
        self.nav_hover = key
        self.cv.itemconfigure(self.nav_items[key]['id'], image=self.nav_image(key))
        start = self.nav_items[key]['x']
        self.anim.add(200, lambda v: self.nav_move(key, start + (66 - start) * v), ease_out_back)

    def nav_leave(self, key):
        if self.lifted:
            return
        if self.nav_hover == key:
            self.nav_hover = None
        self.cv.itemconfigure(self.nav_items[key]['id'], image=self.nav_image(key))
        start = self.nav_items[key]['x']
        self.anim.add(200, lambda v: self.nav_move(key, start + (56 - start) * v), ease_out)

    def nav_click(self, key):
        if self.modal_items:
            return 'break'
        if key == 'go':
            self.launch()
        elif key == 'quit':
            self.ask_quit()
        else:
            self.open_page(None if key == self.page else key)
        return 'break'

    def drop_in(self):
        """Menu entrance: every capsule falls in with a bounce, 70 ms apart."""
        for key, item in self.nav_items.items():
            target = item['y']

            def update(v, key=key, target=target):
                item = self.nav_items[key]
                self.cv.coords(item['id'], self.px(item['x']), self.px(target - 130 * (1 - v)))
            update(0.0)
            self.anim.add(750, update, ease_out_back, delay_ms=120 + item['index'] * 70)

    # ---- status ----------------------------------------------------------------------------
    def refresh_status(self):
        for item in self.status_items:
            self.cv.delete(item)
        self.status_items = []
        found = self.logic.game_info(self.app['game_dir'])
        left = [(t('Game found · all ready'), 'ok') if found else (t('Choose the game folder'), 'warn')]
        saves = self.user_dir() / 'savedata'
        newest = 0.0
        if saves.is_dir():
            for path in saves.rglob('*'):
                if path.is_file() and path.suffix not in ('.png',):
                    newest = max(newest, path.stat().st_mtime)
        left.append((t('Last save · {}').format(time.strftime('%d/%m %H:%M', time.localtime(newest))) if newest
                     else t('No saves yet'), 'cube'))
        mode = dict(WINDOW_MODES).get(self.ini.get('display_mode', 'borderless'), 'Borderless')
        fps = self.ini.get('fps_limit', '0')
        right = [(t(mode) + (' · ' + t('VSync') if self.ini.get('vsync', '1') == '1' else ''), 'cube'),
                 ((t('Limit {} FPS').format(fps) if fps not in ('', '0') else t('Unlimited FPS')), 'cube')]
        self.status_photos = []
        for column, rows in (('l', left), ('r', right)):
            y = H - 26 - 30 * len(rows) - 7 * (len(rows) - 1)
            for text, icon in rows:
                photo = ImageTk.PhotoImage(self.paint.status(text, icon))
                self.status_photos.append(photo)
                if column == 'l':
                    item = self.cv.create_image(self.px(56), self.px(y), anchor='nw', image=photo)
                else:
                    item = self.cv.create_image(self.px(W - 56), self.px(y), anchor='ne', image=photo)
                self.status_items.append(item)
                y += 37

    # ---- pages -----------------------------------------------------------------------------
    def click_background(self, event):
        hit = self.cv.find_overlapping(event.x, event.y, event.x, event.y)
        ours = {i['id'] for i in self.nav_items.values()} | set(self.panel_items) | set(self.modal_items) | {self.win, self.drag_area}
        if self.page and not (set(hit) & ours):
            self.open_page(None)

    def escape(self, _event=None):
        if self.capture:
            return
        if self.modal_items:
            if not self.process:
                self.close_modal()
        elif self.page:
            self.open_page(None)

    def open_page(self, key):
        """Opens (or closes, None) a page: narrower menu, smaller title, panel from the right."""
        was_open = self.page is not None
        self.page = key
        self.capture = None
        for item in self.panel_items:
            self.cv.delete(item)
        self.panel_items = []
        if hasattr(self, 'panel_frame'):
            self.panel_frame.destroy()
            del self.panel_frame
        if (key is not None) != was_open:
            self.render_nav()
            self.brand_scale = .46 if key else 1.0
            self.cv.itemconfigure(self.brand, image=self.brand_images[self.brand_scale])
            start, end = self.bg_pos, .25 if key else .5
            self.anim.add(900, lambda v: (setattr(self, 'bg_pos', start + (end - start) * v), self.place_background()), ease_out)
        for k, item in self.nav_items.items():
            self.cv.itemconfigure(item['id'], image=self.nav_image(k))
        if key:
            self.build_panel(key)

    def build_panel(self, key):
        tk, cv = self.tk, self.cv
        titles = dict(NAV)
        frame_photo = ImageTk.PhotoImage(self.paint.panel(PANEL_W, PANEL_H, t(titles[key])))
        self.photos['panel'] = frame_photo
        shell = cv.create_image(self.px(PANEL_X), self.px(PANEL_Y - 24), anchor='nw', image=frame_photo)
        inner_w, inner_h = PANEL_W - 6 - 56, PANEL_H - 6 - 34 - 20
        frame = self.panel_frame = tk.Frame(cv, bg=PAPER, width=self.px(inner_w), height=self.px(inner_h))
        frame.pack_propagate(False)
        window = cv.create_window(self.px(PANEL_X + 3 + 28), self.px(PANEL_Y + 3 + 34), anchor='nw', window=frame)
        self.panel_items = [shell, window]
        # Scrolling body and the footer.
        foot = tk.Frame(frame, bg=PAPER)
        foot.pack(side='bottom', fill='x', pady=(self.px(10), 0))
        holder = tk.Frame(frame, bg=PAPER)
        holder.pack(side='top', fill='both', expand=True)
        body_cv = tk.Canvas(holder, bg=PAPER, highlightthickness=0, bd=0)
        bar = InkScrollbar(self, holder, body_cv.yview)
        body = tk.Frame(body_cv, bg=PAPER)
        body_window = body_cv.create_window(0, 0, anchor='nw', window=body)
        body.bind('<Configure>', lambda e: body_cv.configure(scrollregion=body_cv.bbox('all')))
        body_cv.bind('<Configure>', lambda e: body_cv.itemconfigure(body_window, width=e.width))
        body_cv.configure(yscrollcommand=bar.set)
        body_cv.pack(side='left', fill='both', expand=True, padx=(0, self.px(10)))
        bar.widget.pack(side='right', fill='y')
        self.body_canvas = body_cv
        getattr(self, f'page_{key}')(body, foot)
        # Entrance: from the right, with a small overshoot.
        def update(v):
            dx = 70 * (1 - v)
            cv.coords(shell, self.px(PANEL_X + dx), self.px(PANEL_Y - 24))
            cv.coords(window, self.px(PANEL_X + 3 + 28 + dx), self.px(PANEL_Y + 3 + 34))
        update(0.0)
        self.anim.add(500, update, ease_out_back)

    def wheel(self, event):
        if self.page and hasattr(self, 'body_canvas'):
            try:
                self.body_canvas.yview_scroll(int(-event.delta / 120) * 3, 'units')
            except self.tk.TclError:
                pass

    # ---- page building blocks ----------------------------------------------------------------
    def sec(self, parent, title, first=False):
        holder = self.tk.Frame(parent, bg=PAPER)
        holder.pack(fill='x', pady=(self.px(4 if first else 20), self.px(4)))
        photo = ImageTk.PhotoImage(self.paint.section(t(title)))
        label = self.tk.Label(holder, image=photo, bg=PAPER, bd=0)
        label.image = photo
        label.pack(anchor='w', pady=(0, self.px(5)))
        self.tk.Frame(holder, bg=INK, height=self.px(3)).pack(fill='x')

    def row(self, parent, title, make, hint=None, wide=False):
        tk = self.tk
        line = tk.Frame(parent, bg=PAPER)
        line.pack(fill='x')
        inner = tk.Frame(line, bg=PAPER, height=self.px(46))
        inner.pack(fill='x')
        label = tk.Label(inner, text=t(title), bg=PAPER, fg=SD, font=self.font(15.5, 'normal', 'Cabin SemiBold'),
                         anchor='w', width=0)
        label.pack(side='left', fill='y', pady=self.px(8))
        control = tk.Frame(inner, bg=PAPER)
        control.pack(side='right', fill='x' if wide else None, expand=bool(wide), pady=self.px(6))
        make(control)
        if hint:
            tk.Label(line, text=t(hint), bg=PAPER, fg=MU, font=self.font(13), anchor='w', justify='left',
                     wraplength=self.px(PANEL_W - 110)).pack(fill='x', pady=(0, self.px(8)))
        DashLine(self, line).widget.pack(fill='x')

    def folder_row(self, parent, title, key, hint):
        tk = self.tk
        line = tk.Frame(parent, bg=PAPER)
        line.pack(fill='x', pady=(self.px(8), 0))
        tk.Label(line, text=t(title), bg=PAPER, fg=SD, font=self.font(15.5, 'normal', 'Cabin SemiBold'),
                 anchor='w').pack(fill='x', pady=(0, self.px(6)))
        fields = tk.Frame(line, bg=PAPER)
        fields.pack(fill='x')
        var = tk.StringVar(value=self.app.get(key, ''))
        entry = tk.Entry(fields, textvariable=var, font=self.font(14, 'normal', 'Cabin SemiBold'), bg='#ffffff', fg=TX,
                         relief='flat', highlightthickness=self.px(2.5), highlightbackground=INK, highlightcolor=BL2,
                         insertbackground=INK)
        entry.pack(side='left', fill='x', expand=True, ipady=self.px(7))

        def changed(*_):
            self.app[key] = var.get().strip()
            self.save()
            self.refresh_status()
        var.trace_add('write', changed)

        def browse():
            chosen = self.filedialog.askdirectory(initialdir=var.get() or str(self.logic.PORT_DIR))
            if chosen:
                var.set(str(Path(chosen)))
        ImageButton(self, fields, t('Browse…'), browse).widget.pack(side='left', padx=(self.px(8), 0))
        ImageButton(self, fields, t('Open'), lambda: self.open_path(var.get(), key)).widget.pack(side='left', padx=(self.px(8), 0))
        if hint:
            tk.Label(line, text=t(hint), bg=PAPER, fg=MU, font=self.font(13), anchor='w', justify='left',
                     wraplength=self.px(PANEL_W - 110)).pack(fill='x', pady=(self.px(6), self.px(8)))
        DashLine(self, line).widget.pack(fill='x')

    def toggle_row(self, parent, title, value, on_change, hint=None):
        self.row(parent, title, lambda c: Toggle(self, c, value, on_change).widget.pack(side='right'), hint)

    def choice(self, parent, options, value, on_change, width=22):
        """A select: the chosen text on a white field with a menu of the options."""
        tk = self.tk
        names = [t(text) for _key, text in options]
        var = tk.StringVar(value=next((t(text) for key, text in options if key == value), names[0]))
        menu = tk.OptionMenu(parent, var, *names, command=lambda name: on_change(options[names.index(name)][0]))
        menu.configure(font=self.font(14.5, 'normal', 'Cabin SemiBold'), bg='#ffffff', fg=TX, activebackground=PAPER2,
                       activeforeground=TX, relief='flat', highlightthickness=self.px(2.5), highlightbackground=INK,
                       bd=0, width=width, anchor='w', indicatoron=True, padx=self.px(8), pady=self.px(4))
        menu['menu'].configure(font=self.font(14, 'normal', 'Cabin'), bg='#ffffff', fg=TX, activebackground=BL,
                               activeforeground=PAPER, bd=0)
        return menu

    def buttons(self, parent, entries):
        holder = self.tk.Frame(parent, bg=PAPER)
        holder.pack(fill='x', pady=self.px(10))
        for text, command in entries:
            ImageButton(self, holder, t(text), command).widget.pack(side='left', padx=(0, self.px(8)))

    def footer(self, foot, entries):
        for text, command, primary in reversed(entries):
            ImageButton(self, foot, t(text), command, 'pri' if primary else 'gh').widget.pack(side='right', padx=(self.px(10), 0))

    def hint(self, parent, text):
        self.tk.Label(parent, text=t(text), bg=PAPER, fg=MU, font=self.font(13), anchor='w', justify='left',
                      wraplength=self.px(PANEL_W - 110)).pack(fill='x', pady=(self.px(4), self.px(8)))

    # ---- the pages ---------------------------------------------------------------------------
    def page_game(self, body, foot):
        logic = self.logic
        self.sec(body, 'FOLDERS', first=True)
        self.folder_row(body, 'Game folder', 'game_dir', 'Your game dump (eboot.bin, sce_module, sce_sys).')
        self.folder_row(body, 'Saves folder', 'user_dir', 'Empty: the launcher data folder (it also holds the shader cache).')
        self.sec(body, 'SHORTCUTS')
        self.toggle_row(body, 'Start without opening the launcher', self.app.get('skip_launcher', False),
                        lambda v: self.set_app('skip_launcher', v),
                        'The game starts at once with the saved settings. Hold Shift to open the launcher again.')
        self.buttons(body, [('Create desktop shortcut', self.shortcut)])
        self.sec(body, 'SAVES')
        names = logic.save_backup.list_backups(self.user_dir())
        self.backup_choice = names[0] if names else ''

        def make(control):
            if names:
                self.choice(control, [(n, n) for n in names], self.backup_choice,
                            lambda n: setattr(self, 'backup_choice', n), 16).pack(side='left')
            else:
                self.tk.Label(control, text='—', bg=PAPER, fg=MU, font=self.font(14)).pack(side='left')
            ImageButton(self, control, t('Restore'), self.ask_restore).widget.pack(side='left', padx=(self.px(8), 0))
            ImageButton(self, control, t('Refresh'), lambda: self.open_page('game')).widget.pack(side='left', padx=(self.px(8), 0))
        self.row(body, 'Save backups', make,
                 t('Made before every start, newest first: the last {} are kept. Restoring backs up the current saves first.')
                 .format(logic.save_backup.KEEP))
        self.sec(body, 'LANGUAGE')
        self.row(body, 'Game language', lambda c: self.choice(c, GAME_LANGUAGES, str(self.app.get('language', '1')),
                                                             lambda v: self.set_app('language', v), 14).pack(side='right'))

    def page_video(self, body, foot):
        self.sec(body, 'SCREEN', first=True)
        self.row(body, 'Window mode', lambda c: Segments(self, c, WINDOW_MODES, self.ini.get('display_mode', 'borderless'),
                                                        lambda v: self.set_ini('display_mode', v)).widget.pack(side='right'))
        self.toggle_row(body, 'Vertical sync', self.ini.get('vsync', '1') == '1', lambda v: self.set_ini('vsync', '1' if v else '0'))
        self.row(body, 'FPS limit', lambda c: Segments(self, c, FPS_CHOICES, self.ini.get('fps_limit', '0'),
                                                      lambda v: self.set_ini('fps_limit', v)).widget.pack(side='right'),
                 'The game is made for 60 FPS; other values can change physics and animations.')
        self.footer(foot, [('Reset', lambda: self.reset({'display_mode': 'borderless', 'vsync': '1', 'fps_limit': '0'}), False),
                           ('Apply', self.apply, True)])

    def page_controls(self, body, foot):
        tk, logic = self.tk, self.logic
        self.sec(body, 'GYROSCOPE', first=True)

        def make_slider(control):
            value = float(self.app.get('gyro_sens', 1.4))
            shown = tk.Label(control, text=f'{value:.1f}×', bg=PAPER, fg=MU, font=self.font(14, 'bold'), width=5, anchor='e')

            def changed(v):
                shown.configure(text=f'{v:.1f}×')
                self.set_app('gyro_sens', round(v, 1))
            Slider(self, control, 0.5, 3.0, 0.1, value, changed).widget.pack(side='left')
            shown.pack(side='left')
        self.row(body, 'Sensitivity', make_slider, 'Aiming by moving a DualSense or DualShock 4.')
        keys = self.app.get('controls', {}).get('key', {}) if isinstance(self.app.get('controls'), dict) else {}
        pads = logic.PAD_STYLES.get(self.app.get('pad_style', 'playstation'), logic.PAD_STYLES['playstation'])
        for group, members in (('BUTTONS', logic.CONTROLS[:12]), ('D-PAD', logic.CONTROLS[12:])):
            self.sec(body, group)
            if group == 'BUTTONS':
                self.hint(body, 'Click a key, then press the new one (Esc cancels).')
                head = tk.Frame(body, bg=PAPER)
                head.pack(fill='x', pady=(self.px(4), 0))
                for text, width in (('COMMAND', 168), ('CONTROLLER', 150), ('KEYBOARD', 120)):
                    tk.Label(head, text=t(text), bg=PAPER, fg=MU, font=self.font(12, 'bold'), anchor='w',
                             width=0).pack(side='left', ipadx=0, padx=(0, self.px(max(0, width - 70))))
            for button, default_key, pad in members:
                line = tk.Frame(body, bg=PAPER, height=self.px(36))
                line.pack(fill='x')
                line.pack_propagate(False)
                name = BUTTON_NAMES[button]
                tk.Label(line, text=name[1] if LANG == 'it' and len(name) > 1 else name[0], bg=PAPER, fg=SD,
                         font=self.font(13.5, 'normal', 'Cabin SemiBold'), width=0, anchor='w').place(x=0, rely=.5, anchor='w')
                pad_label = pads.get(pad, pad) if pad else 'Trigger'
                pad_label = t(PAD_NAMES.get(pad_label, pad_label)) if LANG == 'it' else pad_label
                tk.Label(line, text=pad_label, bg=PAPER, fg=SD,
                         font=self.font(13.5, 'normal', 'Cabin SemiBold')).place(x=self.px(168), rely=.5, anchor='w')
                chip = ImageButton(self, line, keys.get(button) or default_key, None, 'chip')
                chip.command = lambda b=button, c=chip: self.start_capture(b, c)
                chip.widget.place(x=self.px(318), rely=.5, anchor='w')
        self.footer(foot, [('Reset', self.reset_controls, False), ('Apply', self.apply, True)])

    def page_advanced(self, body, foot):
        self.sec(body, 'LAUNCHER', first=True)
        self.row(body, 'Launcher language', lambda c: self.choice(c, [('', 'System'), ('it', 'Italian'), ('en', 'English')],
                                                                 self.app.get('ui_language', ''),
                                                                 lambda v: self.set_app('ui_language', v), 14).pack(side='right'))
        self.sec(body, 'IN GAME')
        self.toggle_row(body, 'Performance overlay', self.ini.get('show_fps', '1') == '1',
                        lambda v: self.set_ini('show_fps', '1' if v else '0'), 'Shows the FPS while you play.')
        self.row(body, 'In-game menu', lambda c: ImageButton(self, c, 'Ins', None, 'chip').widget.pack(side='right'),
                 'Opens the settings while you play: Ins on the keyboard, or R3 + L2 on the controller.')
        self.sec(body, 'PERFORMANCE')
        cache = self.user_dir() / 'cache'
        size = sum(p.stat().st_size for p in cache.rglob('*') if p.is_file()) if cache.is_dir() else 0

        def make_cache(control):
            self.tk.Label(control, text=f'{size / 1048576:.0f} MB' if size else t('empty'), bg=PAPER, fg=MU,
                          font=self.font(14, 'bold')).pack(side='left', padx=(0, self.px(10)))
            ImageButton(self, control, t('Clear'), self.clear_cache).widget.pack(side='left')
        self.row(body, 'Shader cache', make_cache)
        self.sec(body, 'DEVELOPMENT')
        self.toggle_row(body, 'Validation layer', self.app.get('vk_validation', False),
                        lambda v: self.set_app('vk_validation', v), 'Vulkan checks for bug reports; slower.')
        self.sec(body, 'DATA')
        self.row(body, 'Launcher data folder', lambda c: ImageButton(self, c, t('Open'), lambda: self.open_path(
            str(self.logic.CONFIG_DIR))).widget.pack(side='right'))
        self.buttons(body, [('Export settings', self.export_settings), ('Import settings', self.import_settings)])
        self.footer(foot, [('Reset all', self.reset_all, False), ('Apply', self.apply, True)])

    def page_log(self, body, foot):
        tk = self.tk
        self.body_canvas.configure(yscrollincrement=1)
        tk.Label(body, text=t('Game messages'), bg=PAPER, fg=MU, font=self.font(14)).pack(anchor='w')
        text = self.console = tk.Text(body, height=16, bg=INK, fg='#aab3a4', insertbackground=PAPER, relief='flat',
                                      font=('Consolas', -self.px(12)), highlightthickness=self.px(3), highlightbackground=INK,
                                      wrap='none', padx=self.px(10), pady=self.px(8))
        text.tag_configure('ok', foreground='#6be06a')
        text.tag_configure('warn', foreground='#ffb454')
        text.pack(fill='both', expand=True, pady=(self.px(8), 0))
        if not self.log_lines:
            try:
                self.log_lines = (self.user_dir() / 'last_run.log').read_text(encoding='utf-8', errors='replace').splitlines(True)[-3000:]
            except OSError:
                self.log_lines = [t('No game started yet.')]
        for line in self.log_lines:
            self.console_line(line)
        text.configure(state='disabled')
        self.footer(foot, [('Copy log', self.copy_log, False), ('Open log folder', lambda: self.open_path(str(self.user_dir())), True)])

    def console_line(self, line):
        tag = 'warn' if ('Fault' in line or 'STOP' in line or 'error' in line.lower() or '<Warning>' in line) else \
              'ok' if ('trophy' in line or 'mounted' in line or 'Entering original' in line) else ''
        self.console.insert('end', line if line.endswith('\n') else line + '\n', tag)

    # ---- settings actions ------------------------------------------------------------------
    def set_app(self, key, value):
        self.app[key] = value
        self.save()

    def set_ini(self, key, value):
        self.ini[key] = value
        self.save()
        self.refresh_status()

    def apply(self):
        self.save()
        self.refresh_status()
        self.toast(t('Settings applied'))

    def reset(self, values):
        self.ini.update(values)
        self.save()
        self.refresh_status()
        self.open_page(self.page)
        self.toast(t('Defaults restored'))

    def reset_controls(self):
        self.app['controls'] = {}
        self.app['gyro_sens'] = 1.4
        self.save()
        self.open_page('controls')
        self.toast(t('Defaults restored'))

    def reset_all(self):
        self.ini.update({'show_fps': '1'})
        self.app['vk_validation'] = False
        self.app['ui_language'] = ''
        self.save()
        self.open_page('advanced')
        self.toast(t('Defaults restored'))

    def start_capture(self, button, chip):
        if self.capture:
            self.capture[1].set_text(self.capture[2])
        self.capture = (button, chip, chip.text)
        chip.set_text(t('Press a key…'))

    def key_press(self, event):
        if not self.capture:
            return
        button, chip, old = self.capture
        self.capture = None
        if event.keysym == 'Escape':
            chip.set_text(old)
            return 'break'
        name = TK_KEYS.get(event.keysym) or (event.keysym.upper() if len(event.keysym) == 1 else event.keysym)
        chip.set_text(name)
        controls = self.app.get('controls') if isinstance(self.app.get('controls'), dict) else {}
        keys = dict(controls.get('key', {}))
        default = next(row[1] for row in self.logic.CONTROLS if row[0] == button)
        if name.casefold() == default.casefold():
            keys.pop(button, None)
        else:
            keys[button] = name
        controls['key'] = keys
        self.app['controls'] = controls
        self.save()
        return 'break'

    def shortcut(self):
        logic = self.logic
        if logic.FROZEN:
            target, arguments, icon = sys.executable, '', f'{sys.executable},0'
        else:
            pythonw = Path(sys.executable).with_name('pythonw.exe')
            target = str(pythonw if pythonw.exists() else sys.executable)
            arguments, icon = str(HERE / 'gravityrush_launcher.py'), HERE / 'gravityrush.ico'
        script = ('$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath("Desktop")'
                  '+"\\Gravity Rush.lnk");'
                  f'$s.TargetPath="{target}";$s.WorkingDirectory="{logic.PORT_DIR}";$s.IconLocation="{icon}";'
                  + (f"$s.Arguments='\"{arguments}\"';" if arguments else '') + '$s.Save()')
        result = subprocess.run(['powershell', '-NoProfile', '-Command', script], capture_output=True,
                                creationflags=logic.NO_WINDOW)
        self.toast(t('Shortcut created on the desktop') if result.returncode == 0 else
                   t('Could not: {}').format(result.stderr.decode(errors='replace')[:80]))

    def ask_restore(self):
        if not getattr(self, 'backup_choice', ''):
            return
        if self.process:
            self.toast(t('Close the game first.'))
            return
        self.modal(t('Restore saves?'), t('The current saves are backed up first.'),
                   [('Cancel', self.close_modal, False), ('Restore', self.restore_backup, True)])

    def restore_backup(self):
        self.close_modal()
        try:
            self.logic.save_backup.restore(self.user_dir(), self.backup_choice)
            self.toast(t('Saves restored'))
        except (OSError, ValueError) as error:
            self.toast(t('Could not: {}').format(error))
        self.refresh_status()
        self.open_page('game')

    def clear_cache(self):
        if self.process:
            self.toast(t('Close the game first.'))
            return
        shutil.rmtree(self.user_dir() / 'cache', ignore_errors=True)
        self.toast(t('Shader cache cleared'))
        self.open_page('advanced')

    def export_settings(self):
        path = self.filedialog.asksaveasfilename(defaultextension='.json', initialfile='inkfall-settings.json',
                                                 filetypes=[('JSON', '*.json')])
        if path:
            Path(path).write_text(json.dumps({'app': self.app, 'ini': self.ini}, indent=2, ensure_ascii=False), encoding='utf-8')
            self.toast(t('Settings exported'))

    def import_settings(self):
        path = self.filedialog.askopenfilename(filetypes=[('JSON', '*.json')])
        if not path:
            return
        data = self.logic.load_json(path, {})
        self.app.update(data.get('app', {}))
        self.ini.update(data.get('ini', {}))
        self.save()
        self.refresh_status()
        self.open_page(self.page)
        self.toast(t('Settings imported'))

    def open_path(self, path, key=None):
        if key == 'user_dir' and not path:
            path = self.logic.DATA_DIR / 'user'
        path = Path(path or self.logic.DATA_DIR)
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))

    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(''.join(self.log_lines))
        self.toast(t('Log copied'))

    # ---- modal and toast -------------------------------------------------------------------
    def modal(self, title, text, buttons, gauge=False):
        """A dialog on a dimmed window: paper box, pops in with a small bounce."""
        self.close_modal()
        tk, cv = self.tk, self.cv
        self.photos['overlay'] = ImageTk.PhotoImage(self.paint.overlay())
        dim = cv.create_image(0, 0, anchor='nw', image=self.photos['overlay'])
        bw, bh = 400, 200 if gauge or buttons else 170
        self.photos['box'] = ImageTk.PhotoImage(self.paint.panel(bw, bh))
        bx, by = (W - bw) / 2, (H - bh) / 2
        box = cv.create_image(self.px(bx), self.px(by), anchor='nw', image=self.photos['box'])
        frame = tk.Frame(cv, bg=PAPER, width=self.px(bw - 58), height=self.px(bh - 50))
        frame.pack_propagate(False)
        win = cv.create_window(self.px(bx + 29), self.px(by + 26), anchor='nw', window=frame)
        photo = ImageTk.PhotoImage(self.paint.label(title, 24, INK, spacing=.1, upper=True))
        heading = tk.Label(frame, image=photo, bg=PAPER, bd=0)
        heading.image = photo
        heading.pack(anchor='w')
        self.modal_gauge = None
        if gauge:
            self.modal_gauge = tk.Label(frame, bg=PAPER, bd=0)
            self.modal_gauge.pack(fill='x', pady=(self.px(10), 0))
            self.gauge_fraction, self.gauge_phase = .08, 0.0
            self.tick_gauge()
        self.modal_text = tk.Label(frame, text=text, bg=PAPER, fg=SD, font=self.font(15), anchor='w', justify='left',
                                   wraplength=self.px(bw - 60))
        self.modal_text.pack(fill='x', pady=(self.px(10), self.px(10)))
        foot = tk.Frame(frame, bg=PAPER)
        foot.pack(side='bottom', fill='x')
        for label, command, primary in reversed(buttons):
            ImageButton(self, foot, t(label), command, 'pri' if primary else 'gh').widget.pack(side='right', padx=(self.px(10), 0))
        self.modal_frame = frame
        self.modal_items = [dim, box, win]

        def pop(v):
            dy = 30 * (1 - v)
            cv.coords(box, self.px(bx), self.px(by + dy))
            cv.coords(win, self.px(bx + 29), self.px(by + 26 + dy))
        pop(0.0)
        self.anim.add(400, pop, ease_out_back)

    def tick_gauge(self):
        if not self.modal_gauge or not self.modal_gauge.winfo_exists():
            return
        self.gauge_phase = (self.gauge_phase + 0.06) % 1.0
        photo = ImageTk.PhotoImage(self.paint.gauge(340, self.gauge_fraction, self.gauge_phase))
        self.modal_gauge.configure(image=photo)
        self.modal_gauge.image = photo
        self.root.after(33, self.tick_gauge)

    def close_modal(self):
        for item in self.modal_items:
            self.cv.delete(item)
        self.modal_items = []
        if hasattr(self, 'modal_frame'):
            self.modal_frame.destroy()
            del self.modal_frame
        self.modal_gauge = None

    def toast(self, text):
        for item in self.toast_items:
            self.cv.delete(item)
        k = self.s * 2
        font = pil_font(14 * k)
        w = text_width(text, font, 0) / k + 46
        img = self.paint.canvas(w, 44)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, w * k, 44 * k), 22 * k, fill=rgba(INK), outline=rgba(OR), width=round(3 * k))
        draw_text(d, 23 * k, text_top(font, 44 * k), text, font, rgba(PAPER))
        self.photos['toast'] = ImageTk.PhotoImage(self.paint.done(img))
        item = self.cv.create_image(self.px(W / 2), self.px(H - 78), anchor='s', image=self.photos['toast'])
        self.toast_items = [item]
        self.anim.add(350, lambda v: self.cv.coords(item, self.px(W / 2), self.px(H - 78 + 16 * (1 - v))), ease_out_back)
        self.root.after(1800, lambda: item in self.toast_items and (self.cv.delete(item), self.toast_items.remove(item)))

    # ---- quit --------------------------------------------------------------------------------
    def ask_quit(self):
        if self.modal_items:
            return
        self.modal(t('Quit?'), t('Close Inkfall?') + ('\n' + t('The game keeps running.') if self.process else ''),
                   [('Cancel', self.close_modal, False), ('Quit', self.quit, True)])

    def quit(self):
        try:
            self.save()
        except Exception:  # never keep the window open over a settings problem
            pass
        self.root.destroy()

    # ---- launch ----------------------------------------------------------------------------
    def gravity_items(self):
        """Everything that falls "up" when the game starts, in order."""
        items = [self.nav_items[k]['id'] for k, _l, _h in self.nav_entries()] + [self.brand]
        return items + self.panel_items + self.status_items + [self.ver]

    def launch(self):
        if self.process:
            return
        self.save()
        if not self.logic.game_info(self.app['game_dir']):
            self.toast(t('Choose the game folder first.'))
            self.open_page('game')
            return
        if self.capture:
            self.capture[1].set_text(self.capture[2])
            self.capture = None
        # Gravity shift: the interface tilts away upward, 45 ms apart, then the gauge.
        items = self.gravity_items()
        self.lifted = []
        for index, item in enumerate(items):
            x, y = self.cv.coords(item)[:2] if self.cv.coords(item) else (0, 0)
            self.lifted.append((item, x, y))

            def update(v, item=item, x=x, y=y):
                self.cv.coords(item, x, y - self.px(H * 1.1) * v)
            self.anim.add(900, update, ease_in, delay_ms=index * 45)
        self.root.after(1000 if self.anim.enabled else 0, self.start_game)

    def start_game(self):
        logic = self.logic
        env = logic.game_environment(self.app)
        self.log_lines = []
        try:
            self.process = subprocess.Popen(logic.run_command(), cwd=logic.PORT_DIR, env=env, stdin=subprocess.DEVNULL,
                                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=logic.NO_WINDOW)
        except OSError as error:
            self.drop_back()
            self.toast(t('Could not: {}').format(error))
            return
        self.job = logic.GameJob(self.process)
        threading.Thread(target=self.read_output, args=(self.process,), daemon=True).start()
        self.modal(t('Starting…'), t('Preparing the game'), [], gauge=True)

    def read_output(self, process):
        log = None
        try:
            self.user_dir().mkdir(parents=True, exist_ok=True)
            log = open(self.user_dir() / 'last_run.log', 'w', encoding='utf-8', buffering=1)
        except OSError:
            pass
        for raw in iter(process.stdout.readline, b''):
            text = raw.decode('utf-8', errors='replace')
            if log:
                log.write(text)
            self.output.put(text)
        code = process.wait()
        if log:
            log.write(f'\nThe game exited (code {code}).\n')
            log.close()
        self.output.put((code,))

    def drain(self):
        try:
            for _i in range(500):
                item = self.output.get_nowait()
                if isinstance(item, tuple):
                    self.game_exited(item[0])
                    continue
                self.log_lines.append(item)
                if len(self.log_lines) > 6000:
                    del self.log_lines[:1000]
                if self.page == 'log' and hasattr(self, 'console') and self.console.winfo_exists():
                    self.console.configure(state='normal')
                    self.console_line(item)
                    self.console.see('end')
                    self.console.configure(state='disabled')
                if self.modal_gauge is not None:
                    if 'Mapped' in item or 'Linked modules' in item:
                        self.gauge_fraction = max(self.gauge_fraction, .4)
                        self.modal_text.configure(text=t('The game is starting'))
                    elif 'Window:' in item or 'Vulkan' in item:
                        self.gauge_fraction = max(self.gauge_fraction, .7)
                    elif 'Entering original x86-64 code' in item:
                        self.gauge_fraction = 1.0
                        self.root.after(600, self.in_game)
        except queue.Empty:
            pass
        self.root.after(100, self.drain)

    def in_game(self):
        if not self.process:
            return
        self.modal(t('In game'), t('The game is running in its own window.'),
                   [('Stop the game', self.stop_game, False), ('Close the launcher', self.quit, True)])

    def stop_game(self):
        if self.job:
            self.job.terminate()

    def game_exited(self, code):
        self.process = None
        if self.job:
            self.job.close()
            self.job = None
        self.close_modal()
        self.refresh_status()
        self.drop_back()
        self.toast(t('The game exited.'))

    def drop_back(self):
        """The interface falls back in after the game."""
        for index, (item, x, y) in enumerate(getattr(self, 'lifted', [])):
            if not self.cv.type(item):
                continue
            start = self.cv.coords(item)[1] if self.cv.coords(item) else y

            def update(v, item=item, x=x, y=y, start=start):
                self.cv.coords(item, x, start + (y - start) * v)
            self.anim.add(750, update, ease_out_back, delay_ms=index * 40)
        self.lifted = []


def run(logic, tk, filedialog):
    """Opens the launcher window (Tk is created here)."""
    root = tk.Tk()
    Inkfall(root, tk, filedialog, logic)
    root.mainloop()
