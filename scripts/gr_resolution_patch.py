#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Writes patches/CUSA01113.xml: render resolution and shadow patches for Gravity Rush Remastered 01.00.

The game sizes its graphics device, the three display buffers and the base render targets with
1920x1080 constants (and two half-size targets with 960x540 / 960x544); every other target is
derived from those. Each patch rewrites these immediates. The original bytes are checked against
out/re/image.bin (python scripts/gr_callsites.py <NID> --dump) before the file is written.

Usage: python scripts/gr_resolution_patch.py
"""
import struct
from pathlib import Path

PORT = Path(__file__).resolve().parent.parent
EBOOT_BASE = 0x400000
APP_VER = '01.00'

# Image offsets of 32-bit immediates: (offset, what), what = W/H full size, w/h half size,
# hh the 544-line half target (540 rounded up).
SITES = [
    (0x4aa, 'W'), (0x4ae, 'H'),                      # start-up: device config
    (0x14902, 'W'), (0x14906, 'H'),                  # device config defaults
    (0x14959, 'W'), (0x1495f, 'H'),                  # device constructor
    (0x14b92, 'W'), (0x14b96, 'H'),                  # device init: forced output size
    (0x14d49, 'W'), (0x14d54, 'W'), (0x14d5a, 'H'),  # display buffer 1 (pitch, width, height)
    (0x14dde, 'W'), (0x14de9, 'W'), (0x14def, 'H'),  # display buffer 2
    (0x14e7e, 'W'), (0x14e89, 'W'), (0x14e8f, 'H'),  # display buffer 3
    (0x28417, 'W'), (0x2841d, 'H'), (0x28423, 'W'),  # scene colour target
    (0x2849a, 'W'), (0x284a0, 'H'),                  # scene depth
    (0x28779, 'w'), (0x2877f, 'h'), (0x28785, 'w'),  # half-size target
    (0x6761c, 'W'), (0x67622, 'H'), (0x67628, 'W'),  # full-size target
    (0x24f653, 'W'), (0x24f659, 'H'), (0x24f65f, 'W'),  # renderer full-size target
    (0x1b621b, 'w'), (0x1b6221, 'hh'), (0x1b6227, 'w'),  # half-size target (544 lines)
]
ORIGINAL = {'W': 1920, 'H': 1080, 'w': 960, 'h': 540, 'hh': 544}
# Name suffix (graphics_options.RESOLUTIONS) -> output size.
# The other sizes serve the launcher's upscaling modes (FSR 3.1 / DLSS quality, balanced, performance
# for 1080p, 1440p and 2160p screens): exact 16:9, widths a multiple of 64 like the verified ones.
RESOLUTIONS = {'720p': (1280, 720), '1440p': (2560, 1440), '1800p': (3200, 1800), '4K': (3840, 2160),
               '540p': (960, 540), '648p': (1152, 648), '864p': (1536, 864), '972p': (1728, 972),
               '1296p': (2304, 1296)}


# Pixel shaders that turn a pixel's screen position into texture coordinates with literal
# constants for a 1920x1080 screen (v_mul_f32 / v_madmk_f32 / v_add_f32 with 1/1920, and the
# next instruction with 1/1080, 8 bytes on): the comic panels' mask and other screen-space
# passes. Image offsets of the 1/1920 literals; each resolution patch writes 1/width, 1/height.
SCREEN_UV_SITES = [0x161a274, 0x1625ee0, 0x16939ac, 0x16ab1b4, 0x16ac25c, 0x16ac4ec, 0x16acee8, 0x16ad2a8,
                   0x16ae1a8, 0x16ae758, 0x16afc54, 0x16b0404, 0x16b16ac, 0x16b1bac, 0x16b25b8, 0x16b2ae4]


def screen_uv_writes(width, height):
    return [w for o in SCREEN_UV_SITES for w in ((o, struct.pack('<f', 1 / width)),
                                                  (o + 8, struct.pack('<f', 1 / height)))]


def check_screen_uv(image):
    for o in SCREEN_UV_SITES:
        if image[o:o + 4] != struct.pack('<f', 1 / 1920) or image[o + 8:o + 12] != struct.pack('<f', 1 / 1080):
            raise SystemExit(f'{o:#x}: not the expected shader constants (another eboot build?)')


# 2D clip rectangle: the 2D layer (a 960x544 canvas) clips text and lists to a rectangle that
# 0xebbc60 turns into screen pixels with this vector, (1920/960, 1080/544) twice, for a pixel
# shader that compares it with the pixel position (the mission descriptions in the pause menu
# vanished above 1080p). Read only there; each resolution patch writes (width/960, height/544).
CLIP_SCALE = 0x103fab0


def clip_scale(width, height):
    return struct.pack('<4f', width / 960, height / 544, width / 960, height / 544)


def check_clip_scale(image):
    if image[CLIP_SCALE:CLIP_SCALE + 16] != clip_scale(1920, 1080):
        raise SystemExit(f'{CLIP_SCALE:#x}: not the expected 2D clip scale (another eboot build?)')


def align(value, step):
    return (value + step - 1) // step * step


def values(width, height):
    return {'W': width, 'H': height, 'w': width // 2, 'h': height // 2, 'hh': align(height // 2, 32)}


# Shadow map: one 2048x2048 depth texture with four cascades. Only its size is patched: the game
# keeps setting 2048-based cascade viewports (0x274e4d -> 0x137b0) and the renderer scales them for
# the passes into the larger map (vk_rasterizer.cpp). Scaling them in the game instead (a routine
# in padding at 0x6dd51) left the doubled viewport in the game's state for later 2D draws: the
# comic panels came out at half position and size. The constant at 0x104d310 must stay 1/2048:
# the shaders also turn 2048-based positions into texture coordinates with it.
SHADOW_SIZE_SITES = [0x28679, 0x2867f]
SHADOW_TEXEL = 0x104d310
SHADOW_SIZES = {'4096': 4096}


def shadow_writes(size):
    """[(image offset, bytes)] of the shadow map patch."""
    return [(o, struct.pack('<I', size)) for o in SHADOW_SIZE_SITES]


def check_shadow(image):
    expected = [(o, struct.pack('<I', 2048)) for o in SHADOW_SIZE_SITES] + [
        (SHADOW_TEXEL, struct.pack('<2f', 1 / 2048, 1 / 2048))]
    for offset, data in expected:
        if image[offset:offset + len(data)] != data:
            raise SystemExit(f'{offset:#x}: not the expected bytes (another eboot build?)')


# Gravity-shift camera (the camera class at 0x926b0): while Kat floats it keeps correcting its roll.
# Every ~1.2 s it computes a correction angle once (0x9413e: angle/2 = X * -0.07 * 0.5, made into a
# quaternion) and then applies a share of it at every frame for 1.2 s (0x94308: q = dq * q). The
# angle is per frame, so the total correction grows with the frame rate: about 1.6 times the error
# at 60 FPS (settles), 3.2 times at 120 FPS (the view swings left and right more each time). The
# patch scales the angle with the game's frame time (0x15e8434, a 32-frame average):
# X * dt * -2.1, which is the original value at 60 FPS.
CAMERA_SITE = 0x9413e
CAMERA_ORIGINAL = bytes.fromhex('c5fa5905f27af900c5fa5905ce7af900')  # vmulss [-0.07]; vmulss [0.5]
CAMERA_DT = 0x15e8434
CAMERA_CONSTANT = 0x6dd54  # unreachable nop padding after a ret (0x6dd51-0x6dd5f)


def camera_writes():
    """[(image offset, bytes)] of the gravity-shift camera fix."""
    def vmulss_xmm0(site, target):
        return bytes.fromhex('c5fa5905') + struct.pack('<i', target - (site + 8))
    return [(CAMERA_SITE, vmulss_xmm0(CAMERA_SITE, CAMERA_DT) + vmulss_xmm0(CAMERA_SITE + 8, CAMERA_CONSTANT)),
            (CAMERA_CONSTANT, struct.pack('<f', -0.07 * 0.5 * 60))]


def check_camera(image):
    if image[CAMERA_SITE:CAMERA_SITE + 16] != CAMERA_ORIGINAL or image[CAMERA_CONSTANT - 3:CAMERA_CONSTANT + 12] != bytes([0x90]) * 15:
        raise SystemExit(f'{CAMERA_SITE:#x}: not the expected bytes (another eboot build?)')


def main():
    image = (PORT / 'out/re/image.bin').read_bytes()
    for offset, what in SITES:
        found = struct.unpack_from('<I', image, offset)[0]
        if found != ORIGINAL[what]:
            raise SystemExit(f'{offset:#x}: expected {ORIGINAL[what]}, found {found} (another eboot build?)')
    check_screen_uv(image)
    check_clip_scale(image)
    lines = ['<?xml version="1.0" encoding="utf-8"?>',
             '<!-- Gravity Rush Remastered (CUSA01113 01.00) render resolution patches; generated by',
             '     scripts/gr_resolution_patch.py. -->',
             '<Patch>',
             '    <TitleID>',
             '        <ID>CUSA01113</ID>',
             '        <ID>CUSA01130</ID>',
             '    </TitleID>']
    for name, (width, height) in RESOLUTIONS.items():
        v = values(width, height)
        lines.append(f'    <Metadata Title="Gravity Rush Remastered" Name="Resolution Patch - {name}" '
                     f'Note="Renders at {width}x{height}." Author="LucaPazienza" PatchVer="1.0" '
                     f'AppVer="{APP_VER}" AppElf="eboot.bin">')
        lines.append('        <PatchList>')
        for offset, what in SITES:
            lines.append(f'            <Line Type="bytes32" Address="{EBOOT_BASE + offset:#010x}" '
                         f'Value="{v[what]:#x}"/>')
        for offset, data in screen_uv_writes(width, height) + [(CLIP_SCALE, clip_scale(width, height))]:
            lines.append(f'            <Line Type="bytes" Address="{EBOOT_BASE + offset:#010x}" Value="{data.hex()}"/>')
        lines += ['        </PatchList>', '    </Metadata>']
    check_shadow(image)
    for name, size in SHADOW_SIZES.items():
        lines.append(f'    <Metadata Title="Gravity Rush Remastered" Name="Shadow Quality - {name}" '
                     f'Note="Shadow map {size}x{size} (the game uses 2048x2048)." Author="LucaPazienza" '
                     f'PatchVer="1.0" AppVer="{APP_VER}" AppElf="eboot.bin">')
        lines.append('        <PatchList>')
        for offset, data in shadow_writes(size):
            lines.append(f'            <Line Type="bytes" Address="{EBOOT_BASE + offset:#010x}" Value="{data.hex()}"/>')
        lines += ['        </PatchList>', '    </Metadata>']
    check_camera(image)
    lines.append('    <Metadata Title="Gravity Rush Remastered" Name="Bug Fix - Gravity Shift Camera" '
                 'Note="The roll correction of the gravity-shift camera follows the frame time: above '
                 '60 FPS the view no longer swings left and right." Author="LucaPazienza" '
                 f'PatchVer="1.0" AppVer="{APP_VER}" AppElf="eboot.bin" isEnabled="true">')
    lines.append('        <PatchList>')
    for offset, data in camera_writes():
        lines.append(f'            <Line Type="bytes" Address="{EBOOT_BASE + offset:#010x}" Value="{data.hex()}"/>')
    lines += ['        </PatchList>', '    </Metadata>']
    lines.append('</Patch>')
    out = PORT / 'patches/CUSA01113.xml'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    print(f'Wrote {out} ({len(RESOLUTIONS)} resolution patches, {len(SITES) + 2 * len(SCREEN_UV_SITES) + 1} writes each)')


if __name__ == '__main__':
    main()
