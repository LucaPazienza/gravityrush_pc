#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Names the stacks of a GOW3_SAMPLE_FILE profile (gpu/shim/gow3_sampler.cpp).

    python scripts/symbolize_samples.py <profile.txt> [--exe out/gravityrush-runtime.exe] [--top 40]

Prints the functions where the thread spends its time (self), the functions on the stack
(total, callers included) and the most frequent stacks. Needs llvm-symbolizer (MSYS2 CLANG64).
"""
import argparse
import collections
import shutil
import struct
import subprocess
from pathlib import Path


def image_base(exe):
    data = exe.read_bytes()[:4096]
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    return struct.unpack_from('<Q', data, pe + 24 + 24)[0]  # optional header (PE32+) ImageBase


def symbolize(exe, offsets):
    tool = shutil.which('llvm-symbolizer') or r'C:\msys64\clang64\bin\llvm-symbolizer.exe'
    base = image_base(exe)
    query = '\n'.join(f'0x{base + o:x}' for o in offsets) + '\n'
    out = subprocess.run([tool, f'--obj={exe}', '--functions=linkage', '--demangle', '--no-inlines'],
                         input=query, capture_output=True, text=True, check=True).stdout
    names = {}
    blocks = [b for b in out.strip('\n').split('\n\n')]
    for offset, block in zip(offsets, blocks):
        lines = block.split('\n')
        where = lines[1].rsplit('/', 1)[-1].rsplit('\\', 1)[-1] if len(lines) > 1 else '?'
        names[offset] = f'{lines[0]} ({where})'
    return names


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('profile', type=Path)
    parser.add_argument('--exe', type=Path, default=Path(__file__).resolve().parent.parent / 'out' / 'gravityrush-runtime.exe')
    parser.add_argument('--top', type=int, default=40)
    args = parser.parse_args()
    stacks = []
    for line in args.profile.read_text().splitlines():
        if line.startswith('#') or not line.strip():
            continue
        count, *frames = line.split()
        stacks.append((int(count), frames))
    offsets = sorted({int(f[1:], 16) for _, frames in stacks for f in frames if f.startswith('+')})
    names = symbolize(args.exe, offsets)
    name = lambda f: names.get(int(f[1:], 16), f) if f.startswith('+') else f'[{f}]'
    total = sum(c for c, _ in stacks)
    self_time, inclusive = collections.Counter(), collections.Counter()
    for count, frames in stacks:
        self_time[name(frames[0])] += count
        for n in {name(f) for f in frames}:
            inclusive[n] += count
    print(f'{total} samples\n\nSelf (where the thread is):')
    for n, c in self_time.most_common(args.top):
        print(f'{100 * c / total:6.2f}%  {n}')
    print('\nTotal (on the stack):')
    for n, c in inclusive.most_common(args.top):
        print(f'{100 * c / total:6.2f}%  {n}')
    print('\nStacks:')
    for count, frames in sorted(stacks, key=lambda s: -s[0])[:args.top // 2]:
        print(f'{100 * count / total:6.2f}%  ' + ' <- '.join(name(f).split(' (')[0] for f in frames))


if __name__ == '__main__':
    main()
