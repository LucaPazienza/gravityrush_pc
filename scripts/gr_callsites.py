#!/usr/bin/env python3
"""Finds where the game's code calls an imported function, to read the code around it.

Reads out/boot.bin (written by prepare.py): finds the import's slot, then the PLT-style
`jmp [rip+X]` stubs and direct `call [rip+X]` instructions that use the slot, then the
`call rel32` instructions that reach those stubs. Prints image offsets; with --dump the image is
also written to out/re/image.bin for scripts/gr_disasm.sh.

Usage: python scripts/gr_callsites.py <NID or substring of NID#lib> [--dump]
"""
import re
import struct
import sys
from pathlib import Path

PORT = Path(__file__).resolve().parent.parent


def load(path):
    data = path.read_bytes()
    magic, size, _entry, nloads, nrelocs, nnames, _ = struct.unpack_from('<8sQQQQQQ', data, 0)
    assert magic == b'G3PROBE2', magic
    pos = struct.calcsize('<8sQQQQQQ')
    loads = [struct.unpack_from('<QQQ', data, pos + 24 * i) for i in range(nloads)]
    pos += 24 * nloads
    names = [data[pos + 128 * i:pos + 128 * (i + 1)].split(b'\0')[0].decode() for i in range(nnames)]
    pos += 128 * nnames
    relocs = [struct.unpack_from('<QQqq', data, pos + 32 * i) for i in range(nrelocs)]
    pos += 32 * nrelocs
    return data[pos:pos + size], loads, names, relocs


def main():
    key = sys.argv[1]
    image, loads, names, relocs = load(PORT / 'out' / 'boot.bin')
    if '--dump' in sys.argv:
        (PORT / 'out' / 're').mkdir(parents=True, exist_ok=True)
        (PORT / 'out' / 're' / 'image.bin').write_bytes(image)
    wanted = {i for i, n in enumerate(names) if key in n}
    if not wanted:
        sys.exit(f'no import matches {key}')
    for index in sorted(wanted):
        slots = [r[0] for r in relocs if r[1] in (1, 2) and r[2] == index]
        print(f'{names[index]}: slots {[hex(s) for s in slots]}')
        targets = set()
        for slot in slots:
            # ff 25 disp32 (jmp [rip+disp]) and ff 15 disp32 (call [rip+disp]) reaching the slot.
            for m in re.finditer(rb'\xff[\x15\x25]', image):
                at = m.start()
                disp = struct.unpack_from('<i', image, at + 2)[0]
                if at + 6 + disp == slot:
                    kind = 'jmp' if image[at + 1] == 0x25 else 'call'
                    print(f'  {kind} [slot] at 0x{at:x}')
                    if kind == 'jmp':
                        targets.add(at)
        for stub in sorted(targets):
            calls = []
            for m in re.finditer(rb'\xe8', image):
                at = m.start()
                if at + 5 > len(image):
                    continue
                if at + 5 + struct.unpack_from('<i', image, at + 1)[0] == stub:
                    calls.append(at)
            print(f'  stub 0x{stub:x}: {len(calls)} calls: ' + ' '.join(f'0x{c:x}' for c in calls[:40]))


if __name__ == '__main__':
    main()
