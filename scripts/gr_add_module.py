#!/usr/bin/env python3
"""Aggancia un blocco di codice C (src/<modulo>.inc) al runtime e registra le sue funzioni.

Uso:  python scripts/gr_add_module.py <modulo> <nomePS4>=<funzioneC> [<nomePS4>=<funzioneC> ...]
Esempio:  python scripts/gr_add_module.py gr_ngs2 sceNgs2RackCreate=gr_ngs2_rack_create

  - <modulo> e' il nome del file in src/ senza ".inc" (lo crei prima con cat);
  - inserisce '#include "<modulo>.inc"' in src/runtime_extra.c, prima della tabella exports[];
  - registra le coppie nome=funzione dopo il segnaposto /* gr-stubs */;
  - se esisteva uno stub 'ok_noop' con lo stesso nome lo sostituisce.
E' sicuro lanciarlo piu' volte: non duplica nulla.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / 'src' / 'runtime_extra.c'
MARK = '/* gr-stubs */'
ANCHOR = '{"_ZNK3sce4Json6StringeqEPKc",json_equals},'


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    module, pairs = sys.argv[1], sys.argv[2:]
    if not re.fullmatch(r'[A-Za-z0-9_]+', module):
        print('Nome del modulo non valido.')
        return 1
    if not (ROOT / 'src' / (module + '.inc')).exists():
        print(f'Non trovo src/{module}.inc: crealo prima con il comando cat.')
        return 1
    entries = []
    for p in pairs:
        m = re.fullmatch(r'([A-Za-z0-9_]+)=([A-Za-z_][A-Za-z0-9_]*)', p)
        if not m:
            print(f'Coppia non valida: {p}  (serve nome=funzione)')
            return 1
        entries.append((m.group(1), m.group(2)))
    text = TARGET.read_bytes().decode('utf-8')          # niente conversione dei fine riga
    nl = '\r\n' if '\r\n' in text else '\n'
    inc = f'#include "{module}.inc"'
    if inc not in text:
        m = re.search(r'^[ \t]*static\s+const\s+RuntimeExport\s+exports\s*\[\s*\]\s*=\s*\{', text, re.M)
        if not m:
            print('Non trovo la tabella exports[] in runtime_extra.c: avvisami.')
            return 2
        text = text[:m.start()] + inc + nl + text[m.start():]
    if MARK not in text:
        if ANCHOR not in text:
            print('Non trovo il punto dove registrare le funzioni: avvisami.')
            return 2
        text = text.replace(ANCHOR, ANCHOR + nl + '    ' + MARK, 1)
    for name, _ in entries:
        text = re.sub(r'\{\s*"%s"\s*,\s*ok_noop\s*\},?[ ]?' % re.escape(name), '', text)
    present = set(re.findall(r'\{\s*"([^"]+)"\s*,', text))
    new = [(n, f) for n, f in entries if n not in present]
    for n, _ in entries:
        if n in present:
            print(f"  gia' presente: {n}")
    if new:
        line = ' '.join('{"%s",%s},' % (n, f) for n, f in new)
        text = text.replace(MARK, MARK + nl + '    ' + line, 1)
    TARGET.write_bytes(text.encode('utf-8'))
    print(f'Modulo {module}: registrate {len(new)} funzioni' + (': ' + ', '.join(n for n, _ in new) if new else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
