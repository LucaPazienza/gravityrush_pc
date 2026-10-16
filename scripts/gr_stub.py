#!/usr/bin/env python3
"""Aggiunge funzioni PS4 alla tabella exports[] di src/runtime_extra.c come "ok_noop"
(rispondono 'fatto' senza fare nulla). Va bene per le funzioni di contorno.

Uso:  python scripts/gr_stub.py nomeFunzione1 nomeFunzione2 ...
I nomi sono quelli che compaiono dopo "API:" quando il gioco si ferma.
"""
import re
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent / 'src' / 'runtime_extra.c'
MARK = '/* gr-stubs */'
ANCHOR = '{"_ZNK3sce4Json6StringeqEPKc",json_equals},'


def main():
    names = sys.argv[1:]
    if not names:
        print(__doc__)
        return 1
    bad = [n for n in names if not re.fullmatch(r'[A-Za-z0-9_]+', n)]
    if bad:
        print('Nomi non validi (solo lettere, numeri e _):', ', '.join(bad))
        return 1
    text = TARGET.read_bytes().decode('utf-8')   # niente conversione dei fine riga
    nl = '\r\n' if '\r\n' in text else '\n'
    present = set(re.findall(r'\{\s*"([^"]+)"\s*,', text))
    new = [n for n in dict.fromkeys(names) if n not in present]
    for n in names:
        if n in present:
            print(f'  gia\' presente: {n}')
    if not new:
        print('Niente da aggiungere.')
        return 0
    if MARK not in text:
        if ANCHOR not in text:
            print('Non trovo il punto dove inserire le voci: avvisami e lo sistemiamo a mano.')
            return 2
        text = text.replace(ANCHOR, ANCHOR + nl + '    ' + MARK, 1)
    entries = ' '.join(f'{{"{n}",ok_noop}},' for n in new)
    text = text.replace(MARK, MARK + nl + '    ' + entries, 1)
    TARGET.write_bytes(text.encode('utf-8'))
    print(f'Aggiunte {len(new)} funzioni: ' + ', '.join(new))
    return 0


if __name__ == '__main__':
    sys.exit(main())
