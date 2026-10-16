#!/usr/bin/env python3
"""Integra la libreria dei font di shadPS4 (gia' copiata in gpu/shadps4/core/libraries/font) nel progetto.

Cosa fa (tutto con controlli: se non trova un punto lo dice e non rovina nulla):
  1. crea gpu/shim/core/file_sys/fs.h: "punti di montaggio" finti (i font di sistema PlayStation non ci sono);
  2. fa vedere alla libreria i file del kernel che dichiarano sceKernelUsleep e sceKernelGetCompiledSdkVersion;
  3. aggiunge a gpu/CMakeLists.txt la compilazione dei font e il collegamento a FreeType;
  4. registra i font in gpu/shim/gow3gpu.cpp, come gia' fatto per l'AvPlayer;
  5. toglie dal runtime la versione "spia" (src/runtime_extra.c), che altrimenti coprirebbe quella vera.
E' sicuro lanciarlo piu' volte.

Uso:  python scripts/gr_install_fontlib.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GPU = ROOT / 'gpu'
problems = []


def rd(p):
    return p.read_bytes().decode('utf-8')


def wr(p, s):
    p.write_bytes(s.encode('utf-8'))


def nl_of(s):
    return '\r\n' if '\r\n' in s else '\n'


def replace_once(s, old, new, tag):
    if new in s:
        print(f"  gia' fatto: {tag}")
        return s
    if old not in s:
        print(f'  NON TROVO il punto per: {tag}')
        problems.append(tag)
        return s
    print(f'  fatto: {tag}')
    return s.replace(old, new, 1)


def add_line_after(s, anchor, line, tag):
    if line.strip() in s:
        print(f"  gia' fatto: {tag}")
        return s
    i = s.find(anchor)
    if i < 0:
        print(f'  NON TROVO il punto per: {tag}')
        problems.append(tag)
        return s
    j = s.find('\n', i)
    j = len(s) - 1 if j < 0 else j
    print(f'  fatto: {tag}')
    return s[:j + 1] + line + nl_of(s) + s[j + 1:]


FS_H = '''// gow3: stand-in for shadPS4's core/file_sys/fs.h. The font library only uses it to find fonts on
// the PlayStation's system partition, which a PC port does not have: every lookup says "not found".
#pragma once
#include <filesystem>
#include <optional>
#include <string_view>
#include <vector>
#include "common/singleton.h"
#include "common/types.h"

namespace Core::FileSys {
class FileHandle {
public:
    std::optional<std::filesystem::path> GetHostPath() const { return std::nullopt; }
};
class MntPoints {
public:
    std::filesystem::path GetHostPath(std::string_view) const { return {}; }
    std::optional<std::vector<u8>> ReadFile(std::string_view) const { return std::nullopt; }
    std::optional<FileHandle> Open(std::string_view, bool) const { return std::nullopt; }
};
} // namespace Core::FileSys
'''


def step_fs():
    print('1. file system finto')
    p = GPU / 'shim' / 'core' / 'file_sys' / 'fs.h'
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and rd(p) == FS_H:
        print("  gia' fatto: fs.h")
    else:
        wr(p, FS_H)
        print('  fatto: scritto gpu/shim/core/file_sys/fs.h')


def step_kernel():
    print('2. dichiarazioni del kernel')
    kdir = GPU / 'shadps4' / 'core' / 'libraries' / 'kernel'
    found = {}
    for h in sorted(kdir.glob('*.h')):
        text = rd(h)
        for name in ('sceKernelUsleep', 'sceKernelGetCompiledSdkVersion'):
            if name in text and name not in found and h.name != 'kernel.h':
                found[name] = h.name
    shim = GPU / 'shim' / 'core' / 'libraries' / 'kernel' / 'kernel.h'
    if not shim.exists():
        print('  NON TROVO', shim)
        problems.append('kernel.h')
        return
    s = rd(shim)
    nl = nl_of(s)
    for name in ('sceKernelUsleep', 'sceKernelGetCompiledSdkVersion'):
        h = found.get(name)
        if not h:
            print(f"  ATTENZIONE: {name} non e' dichiarata in nessun file del kernel: va aggiunta a mano")
            problems.append(name)
    for h in sorted(set(found.values())):
        inc = f'#include "core/libraries/kernel/{h}"'
        if inc in s:
            print(f"  gia' fatto: {inc}")
        else:
            s = s.rstrip('\r\n') + nl + inc + nl
            print(f'  fatto: aggiunto {inc}')
    wr(shim, s)


def detect_ns(cpp, default):
    p = GPU / 'shadps4' / 'core' / 'libraries' / 'font' / cpp
    if p.exists():
        m = re.search(r'namespace\s+(Libraries::\w+)\s*\{', rd(p))
        if m:
            return m.group(1)
    return default


def step_cmake():
    print('3. gpu/CMakeLists.txt')
    p = GPU / 'CMakeLists.txt'
    s = rd(p)
    s = add_line_after(s, 'file(GLOB AVPLAYER', 'file(GLOB FONTLIB CONFIGURE_DEPENDS shadps4/core/libraries/font/*.cpp)', 'elenco dei file dei font')
    s = add_line_after(s, 'pkg_check_modules(FFMPEG', 'pkg_check_modules(FREETYPE REQUIRED IMPORTED_TARGET freetype2)', 'ricerca di FreeType')
    s = replace_once(s, 'equeue.cpp ${AVPLAYER}', 'equeue.cpp ${AVPLAYER} ${FONTLIB}', 'file dei font nella libreria')
    s = replace_once(s, 'PkgConfig::FFMPEG miniz::miniz', 'PkgConfig::FFMPEG PkgConfig::FREETYPE miniz::miniz', 'collegamento a FreeType')
    wr(p, s)


def step_register():
    print('4. registrazione in gow3gpu.cpp')
    p = GPU / 'shim' / 'gow3gpu.cpp'
    s = rd(p)
    ns_font = detect_ns('font.cpp', 'Libraries::Font')
    ns_ft = detect_ns('fontft.cpp', 'Libraries::FontFt')
    print(f'  nomi trovati: {ns_font}, {ns_ft}')
    s = add_line_after(s, 'namespace Libraries::AvPlayer { void RegisterLib',
                       f'namespace {ns_font} {{ void RegisterLib(Core::Loader::SymbolsResolver* sym); }}', 'dichiarazione Font')
    s = add_line_after(s, f'namespace {ns_font} {{ void RegisterLib',
                       f'namespace {ns_ft} {{ void RegisterLib(Core::Loader::SymbolsResolver* sym); }}', 'dichiarazione FontFt')
    s = add_line_after(s, '    Libraries::AvPlayer::RegisterLib(&resolver);', f'    {ns_font}::RegisterLib(&resolver);', 'registrazione Font')
    s = add_line_after(s, f'    {ns_font}::RegisterLib(&resolver);', f'    {ns_ft}::RegisterLib(&resolver);', 'registrazione FontFt')
    wr(p, s)


def step_spy():
    print('5. rimozione della versione "spia"')
    p = ROOT / 'src' / 'runtime_extra.c'
    s = rd(p)
    before = s
    s = re.sub(r'#include "gr_font\.inc"\r?\n', '', s)
    s, n = re.subn(r'\{\s*"[A-Za-z0-9_]+"\s*,\s*gr_font_[A-Za-z0-9_]+\s*\},?[ ]?', '', s)
    if s != before:
        wr(p, s)
        print(f'  fatto: tolte {n} voci "spia" e la riga #include')
    else:
        print("  gia' fatto: nessuna voce \"spia\" nel runtime")


def main():
    if not (GPU / 'shadps4' / 'core' / 'libraries' / 'font' / 'font.cpp').exists():
        print('Prima copia i file dei font in gpu/shadps4/core/libraries/font (passo 25, punto 1).')
        return 1
    for step in (step_fs, step_kernel, step_cmake, step_register, step_spy):
        step()
    print()
    if problems:
        print('ATTENZIONE, da sistemare:', '; '.join(problems))
        return 2
    print('Tutto fatto. Ora ricompila.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
