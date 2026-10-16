#!/usr/bin/env python3
"""Aggiunge due funzioni che la libreria dei font di shadPS4 chiede e il progetto non ha:

  - EmulatorSettings.GetFontsDir()   in gpu/shim/core/emulator_settings.h  (cartella dei font di sistema: vuota)
  - Memory::IsValidMapping()         in gpu/shim/core/memory.h             (un puntatore del gioco e' plausibile?)
E' sicuro lanciarlo piu' volte.

Uso:  python scripts/gr_fix_fontdeps.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / 'gpu' / 'shim' / 'core'
problems = []

FONTS_DIR = '''    // gow3: the font library looks for PS4 system fonts in this folder. A PC port has none (the game
    // brings its own fonts), so it is empty: "no system fonts".
    std::filesystem::path GetFontsDir() { return {}; }
'''

VALID_MAPPING = '''    // gow3: the font library asks whether a pointer from the game is usable. Guest pointers (stack, image
    // and heap alike) are below 1 TiB, so that is the test; a bad pointer inside that range faults exactly
    // as it would in every other HLE function.
    bool IsValidMapping(VAddr virtual_addr, u64 size = 0) const {
        constexpr u64 kGuestLimit = 1ull << 40;
        return virtual_addr >= 0x10000 && virtual_addr < kGuestLimit && size < kGuestLimit - virtual_addr;
    }
'''


def rd(p):
    return p.read_bytes().decode('utf-8')


def wr(p, s):
    p.write_bytes(s.encode('utf-8'))


def insert_before_line(s, anchor, block, marker, tag):
    nl = '\r\n' if '\r\n' in s else '\n'
    if marker in s:
        print(f"  gia' fatto: {tag}")
        return s
    i = s.find(anchor)
    if i < 0:
        print(f'  NON TROVO il punto per: {tag}')
        problems.append(tag)
        return s
    start = s.rfind('\n', 0, i) + 1
    print(f'  fatto: {tag}')
    return s[:start] + block.replace('\n', nl) + s[start:]


def main():
    p = CORE / 'emulator_settings.h'
    print('1. impostazioni')
    s = rd(p)
    s = insert_before_line(s, 's32 GetGpuId()', FONTS_DIR, 'GetFontsDir()', 'GetFontsDir')
    if '#include <filesystem>' not in s:
        nl = '\r\n' if '\r\n' in s else '\n'
        if '#include <cstdlib>' in s:
            s = s.replace('#include <cstdlib>', '#include <cstdlib>' + nl + '#include <filesystem>', 1)
            print('  fatto: #include <filesystem>')
        else:
            problems.append('include filesystem')
            print('  NON TROVO dove aggiungere #include <filesystem>')
    wr(p, s)
    p = CORE / 'memory.h'
    print('2. memoria')
    s = rd(p)
    s = insert_before_line(s, 'u64 ClampRangeSize(VAddr virtual_addr, u64 size);', VALID_MAPPING, 'IsValidMapping(', 'IsValidMapping')
    wr(p, s)
    print()
    if problems:
        print('ATTENZIONE, da sistemare:', '; '.join(problems))
        return 2
    print('Tutto fatto. Ora ricompila i file dei font.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
