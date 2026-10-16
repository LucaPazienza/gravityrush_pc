#!/usr/bin/env python3
"""Aggiunge alla cartella gpu/shim le intestazioni finte che la libreria dei font di shadPS4 richiede:

  - core/tls.h                       (la libreria lo include ma non lo usa)
  - imgui/notifications_layer.h      (una notifica a schermo: qui non fa nulla)
  - imgui/renderer/font_data.h       (font di riserva: dichiarati come in shadPS4, ma con dati vuoti)
  - gow3_font_stubs.cpp              (le definizioni vuote dei font di riserva, per il linker)
E' sicuro lanciarlo piu' volte.

Uso:  python scripts/gr_install_fontstubs.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHIM = ROOT / 'gpu' / 'shim'
REF_HEADER = ROOT.parent / 'ref_gr2fork' / 'src' / 'imgui' / 'renderer' / 'font_data.h'
FALLBACK_FONTS = ['notosans_regular', 'notosansarabic_regular', 'notosansthai_regular',
                  'notosanssymbols2_regular', 'notosanscjk_regular', 'proggyvector_regular']

TLS_H = '''// gow3: shadPS4's core/tls.h (thread-local storage helpers for guest code) is only #included by the
// font library, never used. The port's runtime handles guest TLS itself.
#pragma once
'''

NOTIF_H = '''// gow3: stand-in for shadPS4's on-screen notifications. The font library queues a single warning when
// it cannot find the PS4 system fonts; the port shows nothing.
#pragma once
#include <string>

namespace shadNotifications {
enum class position { TopLeft, TopRight, BottomLeft, BottomRight };
enum class stockIcons { shadPS4, Settings, Profiles, Input };
template <class... Rest>
inline void QueueNotification(std::string, float, position, Rest&&...) {}
} // namespace shadNotifications
'''


def write_if_changed(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and p.read_bytes().decode('utf-8') == text:
        print(f"  gia' fatto: {p.relative_to(ROOT)}")
    else:
        p.write_bytes(text.encode('utf-8'))
        print(f'  scritto: {p.relative_to(ROOT)}')


def main():
    if REF_HEADER.exists():
        header = REF_HEADER.read_bytes().decode('utf-8').replace('\r\n', '\n')
        print(f'Uso come modello {REF_HEADER}')
    else:
        header = '#pragma once\n\n' + ''.join(
            f'extern const unsigned int imgui_font_{n}_compressed_size;\n'
            f'extern const unsigned char imgui_font_{n}_compressed_data[];\n\n' for n in FALLBACK_FONTS)
        print('Modello di shadPS4 non trovato: uso l\'elenco standard dei sei font di riserva')
    sizes = re.findall(r'extern\s+const\s+unsigned\s+int\s+(\w+)\s*;', header)
    datas = re.findall(r'extern\s+const\s+unsigned\s+char\s+(\w+)\s*\[\s*\]\s*;', header)
    if not sizes or not datas:
        print('Non riesco a leggere le dichiarazioni dei font di riserva.')
        return 1
    write_if_changed(SHIM / 'core' / 'tls.h', TLS_H)
    write_if_changed(SHIM / 'imgui' / 'notifications_layer.h', NOTIF_H)
    write_if_changed(SHIM / 'imgui' / 'renderer' / 'font_data.h', header)
    body = ['// gow3: empty stand-ins for the fallback fonts that shadPS4 bundles (Noto Sans and others).',
            '// The game brings its own fonts through sceFontOpenFontMemory, so these are never read.',
            '#include "imgui/renderer/font_data.h"', '']
    body += [f'const unsigned int {n} = 0;' for n in sizes]
    body += [f'const unsigned char {n}[1] = {{0}};' for n in datas]
    write_if_changed(SHIM / 'gow3_font_stubs.cpp', '\n'.join(body) + '\n')
    print(f'Fatto: {len(sizes)} font di riserva definiti.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
