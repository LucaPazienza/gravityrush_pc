#!/bin/bash
# Disassembles part of the game image (Intel syntax; addresses = image offsets, as in F12 dumps
# "eboot+0x..." and scripts/gr_callsites.py). Needs out/re/image.bin: python scripts/gr_callsites.py <NID> --dump
# Usage (MSYS2 CLANG64, port folder): bash scripts/gr_disasm.sh <start hex> <stop hex>
cd "$(dirname "$0")/.." || exit 1
if [ ! -f out/re/image.bin ]; then echo "run: python scripts/gr_callsites.py <NID> --dump" >&2; exit 1; fi
if [ ! -f out/re/image.o ] || [ out/re/image.bin -nt out/re/image.o ]; then
    llvm-objcopy -I binary -O elf64-x86-64 --rename-section .data=.text,alloc,load,code out/re/image.bin out/re/image.o
fi
llvm-objdump -d --no-show-raw-insn -M intel --start-address="$1" --stop-address="$2" out/re/image.o | tail -n +7
