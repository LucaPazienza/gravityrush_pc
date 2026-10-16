"""Unreal Engine 4 render resolution override for Unreal Engine 4 games (up to 4K).

UE4 games read their config only from their paks. A small pak whose name ends in _P mounts with
priority over them, so a changed copy of Engine/Config/PS4/PS4Engine.ini (taken from the game's
own pak) wins. r.ScreenPercentage scales the 3D scene: 200% of the 1080p frame renders it at
3840x2160 (4K) and scales it down to the game's 1920x1080 output (supersampling: much sharper
edges and detail). The HUD stays at 1080p. The game itself keeps its 60 FPS cap.
The pak is written into the game's Paks folder at every start and removed for native.

Usage: python scripts/ue4_override.py <game dir> [--resolution native|480p|720p|1440p|1800p|4K]
"""
import argparse
import hashlib
import os
import struct
import zlib
from pathlib import Path

PAK_MAGIC = 0x5A6F12E1
PAK_NAME = 'pakchunk99-ps4_P.pak'
CONFIG = 'Engine/Config/PS4/PS4Engine.ini'
# Render resolution (gravityrush.ini render_resolution) -> scene scale of the 1080p frame, in percent.
SCREEN_PERCENTAGE = {'native': None, '480p': '44.444', '720p': '66.667', '1440p': '133.333',
                     '1800p': '166.667', '4K': '200'}
# Native output: the game's own output size (PS4Engine.ini r.setres, 1920x1080 as shipped), shown
# pixel for pixel on a 1440p or 4K display. 4K needs the "Native 4K framebuffer pool" patch.
# Upscaling at native output (gravityrush.ini ue4_upscale): UE4's temporal upsampling renders the 3D
# scene at a lower scale and its temporal AA rebuilds the full output from the game's own motion
# vectors (as FSR 2 / DLSS do, without the AI). Not with the supersampling scales above.
TEMPORAL_UPSCALE = {'quality': '66.667', 'balanced': '58', 'performance': '50'}
NATIVE_OUTPUT = {'720p_native': '1280x720', '1440p_native': '2560x1440', '1800p_native': '3200x1800',
                 '4K_native': '3840x2160'}


def paks_dir(game):
    return Path(game) / 'overbite' / 'content' / 'paks'


def read_index(path):
    """{name: (offset, size, compression, zlib blocks)} of a version 7 pak (unencrypted index)."""
    with open(path, 'rb') as f:
        f.seek(os.path.getsize(path) - 44)
        magic, version, index_offset, index_size = struct.unpack('<IIQQ', f.read(24))
        if magic != PAK_MAGIC or version != 7:
            raise ValueError(f'{path.name}: unsupported pak (magic {magic:#x}, version {version})')
        f.seek(index_offset)
        index = f.read(index_size)
    pos = 0

    def fstring():
        nonlocal pos
        n, = struct.unpack_from('<i', index, pos)
        pos += 4
        if n < 0:
            text = index[pos:pos - 2 * n].decode('utf-16le')[:-1]
            pos += -2 * n
        else:
            text = index[pos:pos + n].decode('latin1')[:-1]
            pos += n
        return text
    fstring()  # mount point
    count, = struct.unpack_from('<i', index, pos)
    pos += 4
    entries = {}
    for _ in range(count):
        name = fstring()
        offset, size, _uncompressed, compression = struct.unpack_from('<qqqi', index, pos)
        pos += 48
        blocks = []
        if compression:
            count_blocks, = struct.unpack_from('<i', index, pos)
            pos += 4
            for _ in range(count_blocks):
                blocks.append(struct.unpack_from('<qq', index, pos))  # [start, end) from the entry
                pos += 16
        pos += 5
        entries[name] = (offset, size, compression, blocks)
    return entries


def read_file(game, name):
    """A file of the game's own paks (stored or zlib-compressed)."""
    for pak in sorted(paks_dir(game).glob('pakchunk*-ps4.pak')):
        entries = read_index(pak)
        if name in entries:
            offset, size, compression, blocks = entries[name]
            with open(pak, 'rb') as f:
                if not compression:
                    f.seek(offset + 53)  # the entry header in front of the data
                    return f.read(size)
                data = bytearray()
                for start, end in blocks:
                    f.seek(offset + start)
                    data += zlib.decompress(f.read(end - start))
                return bytes(data)
    raise FileNotFoundError(name)


def fstring(text):
    data = text.encode('latin1') + b'\0'
    return struct.pack('<i', len(data)) + data


def entry(offset, data):
    """FPakEntry, version 7, uncompressed and unencrypted (as UnrealPak writes it)."""
    return struct.pack('<qqqi', offset, len(data), len(data), 0) + hashlib.sha1(data).digest() + b'\0' + \
        struct.pack('<I', 0)


def write_pak(path, files, mount='../../../'):
    body, records = b'', []
    for name, data in files.items():
        records.append((name, len(body)))
        body += entry(0, data) + data  # the copy in front of the data has offset 0
    index = fstring(mount) + struct.pack('<i', len(files))
    for (name, offset), data in zip(records, files.values()):
        index += fstring(name) + entry(offset, data)
    footer = bytes(16) + b'\0' + struct.pack('<IIQQ', PAK_MAGIC, 7, len(body), len(index)) + \
        hashlib.sha1(index).digest()
    tmp = path.with_suffix('.tmp')
    tmp.write_bytes(body + index + footer)
    tmp.replace(path)


def set_section(text, section, values):
    """Sets keys in the first [section] of an ini text, replacing existing lines there."""
    head, sep, rest = text.partition(f'[{section}]\n')
    if not sep:
        head, sep, rest = text.rstrip('\n') + '\n\n', f'[{section}]\n', ''
    lines = rest.split('\n')
    section_end = next((i for i, l in enumerate(lines) if l.startswith('[')), len(lines))
    body = [l for l in lines[:section_end] if l.strip() and l.split('=', 1)[0].strip() not in values]
    body += [f'{k}={v}' for k, v in values.items()] + ['']
    return head + sep + '\n'.join(body + lines[section_end:])


def set_values(ini, values, engine=None):
    """Sets keys in [SystemSettings] (console variables) and [/Script/Engine.Engine]."""
    text = ini.decode('utf-8-sig').replace('\r\n', '\n')
    if values:
        text = set_section(text, 'SystemSettings', values)
    if engine:
        text = set_section(text, '/Script/Engine.Engine', engine)
    return text.replace('\n', '\r\n').encode('utf-8')


def frame_rate_range(fps):
    """UGameEngine::GetMaxTickRate on consoles: with VSync on, the game ticks at most at the upper
    bound of SmoothedFrameRateRange (BaseEngine.ini: below 62, so 60 FPS), even with
    bSmoothFrameRate off. The PS4 build keeps that default; a higher bound lifts the 60 FPS cap."""
    return {'SmoothedFrameRateRange': '(LowerBound=(Type="ERangeBoundTypes::Inclusive",Value=22),'
                                      f'UpperBound=(Type="ERangeBoundTypes::Exclusive",Value={fps + 2}))'}


# Graphics quality (gravityrush.ini ue4_quality): console keeps the PS4 settings; medium and low trade
# effects for speed on integrated and older graphics cards.
QUALITY = {
    'console': {},
    # Diagnostics (not in the launcher): console quality with one effect off.
    'diag_ao': {'r.AmbientOcclusionLevels': '0'},
    'diag_ssr': {'r.SSR.Quality': '0'},
    'diag_shadow': {'r.ShadowQuality': '2', 'r.Shadow.MaxCSMResolution': '1536'},
    'diag_mb': {'r.MotionBlurQuality': '0'},
    'diag_fxaa': {'r.PostProcessAAQuality': '2'},  # FXAA instead of temporal AA
    'diag_localres': {'r.Shadow.MaxResolution': '512'},  # point/spot light shadow maps
    'diag_nocube': {'r.AllowPointLightCubemapShadows': '0'},
    'diag_fixedres': {'r.Shadow.MinResolution': '1024', 'r.Shadow.MaxResolution': '1024'},
    # Fewer shadow draws (the GPU thread tops out near 2000 draws a frame at 60 FPS).
    'diag_draws': {'r.Shadow.MinResolution': '512', 'r.Shadow.MaxResolution': '512',
                   'r.Shadow.RadiusThreshold': '0.1', 'r.Shadow.CacheWholeSceneShadows': '1',
                   'r.Shadow.CSM.MaxCascades': '2', 'r.Shadow.DistanceScale': '0.8'},
    'diag_nopoint': {'r.Shadow.MinResolution': '512', 'r.Shadow.MaxResolution': '512',
                     'r.Shadow.CacheWholeSceneShadows': '1', 'r.AllowPointLightCubemapShadows': '0'},
    'diag_fixed512': {'r.Shadow.MinResolution': '512', 'r.Shadow.MaxResolution': '512',
                      'r.Shadow.RadiusThreshold': '0.05', 'r.Shadow.CacheWholeSceneShadows': '1'},
    'diag_lod': {'r.ViewDistanceScale': '0.7', 'foliage.DensityScale': '0.6', 'grass.DensityScale': '0.6',
                 'r.Shadow.CSM.MaxCascades': '2'},
    'diag_post': {'r.VolumetricFog': '0', 'r.DepthOfFieldQuality': '0', 'r.LensFlareQuality': '0',
                  'r.SceneColorFringeQuality': '0', 'r.BloomQuality': '2', 'r.RefractionQuality': '0'},
    # Above the PS4: GPU cost, little memory (the game keeps its PS4 memory budget, so texture
    # streaming pools stay as shipped).
    'high': {
        'r.ShadowQuality': '4', 'r.Shadow.MaxCSMResolution': '2048', 'r.Shadow.MaxResolution': '2048',
        'r.Shadow.DistanceScale': '1.5', 'r.AmbientOcclusionLevels': '3', 'r.SSR.Quality': '3',
        'r.MaxAnisotropy': '16', 'r.ViewDistanceScale': '1.5', 'r.StaticMeshLODDistanceScale': '0.75',
        'foliage.LODDistanceScale': '1.5',
    },
    'ultra': {
        'r.ShadowQuality': '5', 'r.Shadow.MaxCSMResolution': '4096', 'r.Shadow.MaxResolution': '2048',
        'r.Shadow.DistanceScale': '2', 'r.Shadow.CSM.MaxCascades': '4', 'r.AmbientOcclusionLevels': '3',
        'r.SSR.Quality': '4', 'r.MaxAnisotropy': '16', 'r.ViewDistanceScale': '2',
        'r.StaticMeshLODDistanceScale': '0.5', 'foliage.LODDistanceScale': '2',
        'r.DetailMode': '2', 'r.MaterialQualityLevel': '1',
    },
    'medium': {
        'r.ShadowQuality': '2', 'r.Shadow.MaxCSMResolution': '1536', 'r.Shadow.MaxResolution': '1024',
        'r.AmbientOcclusionLevels': '1', 'r.SSR.Quality': '1', 'r.MotionBlurQuality': '2',
        'r.DepthOfFieldQuality': '1', 'r.ViewDistanceScale': '0.85',
    },
    'low': {
        'r.ShadowQuality': '1', 'r.Shadow.MaxCSMResolution': '1024', 'r.Shadow.MaxResolution': '512',
        'r.Shadow.CSM.MaxCascades': '2', 'r.VolumetricFog': '0', 'r.AmbientOcclusionLevels': '0',
        'r.SSR.Quality': '0', 'r.MotionBlurQuality': '0', 'r.DepthOfFieldQuality': '0',
        'r.LensFlareQuality': '0', 'r.SceneColorFringeQuality': '0', 'r.BloomQuality': '2',
        'r.RefractionQuality': '0', 'r.ViewDistanceScale': '0.7', 'foliage.DensityScale': '0.6',
        'grass.DensityScale': '0.6',
    },
}


# Point and spot light shadows at one fixed size per preset, with small lights unshadowed. UE4
# sizes them by their size on screen, so walking re-creates them constantly; those re-created
# maps flickered on the port (shadows blinking while moving, outdoor levels).
# The second number is r.Shadow.RadiusThreshold: lights smaller than that on screen cast no shadow.
# Every shadowed point light redraws its surroundings six times, and the port's GPU thread keeps
# 60 FPS up to about 2000 draws a frame; busy outdoor scenes reached 4000 (30 FPS) before.
LOCAL_SHADOWS = {'ultra': (1024, 0.06), 'high': (1024, 0.08), 'console': (512, 0.1),
                 'medium': (512, 0.12), 'low': (256, 0.15)}
# Sun/moon shadow cascades and distance per preset (each cascade redraws the scene once).
SUN_SHADOWS = {'ultra': ('3', '1.5'), 'high': ('3', '1.2'), 'console': ('2', '0.8'),
               'medium': ('2', '0.75'), 'low': ('2', '0.6')}


# The developers' debug menu (R3 in the game: level select, complete level, gear and items for
# the level, runes, gold, life bottles, invulnerability). OverbiteGameSingleton reads the switch.
GAME_CONFIG = 'OVERBITE/Config/PS4/PS4Game.ini'


def debug_menu_config(game, enabled):
    text = read_file(game, GAME_CONFIG).decode('utf-8-sig').replace('\r\n', '\n')
    text = '\n'.join(l for l in text.split('\n') if not l.strip().startswith('AllowDebugMenu')).replace(' \n', '\n')
    text = set_section(text, '/Script/OVERBITE.OverbiteGameSingleton',
                       {'AllowDebugMenu': 'true' if enabled else 'false'})
    return text.replace('\n', '\r\n').encode('utf-8')


# The debug menu's widget Blueprint: when it is created it calls SetFrameRateLimit(60) and
# ApplySettings ("Set FPS Max to 30" off), which capped the game at 60 FPS again; 0 is no limit.
# Its "Cinematic Mode (1440p)" button (r.SetRes) becomes 4K and a profiling toggle 1440p. Same-length edits only (the Blueprint
# bytecode and the package's export sizes stay valid); each must match exactly once.
DEBUG_HUD = 'OVERBITE/Content/Blueprints/Debug/DebugHUD.uexp'
DEBUG_HUD_EDITS = [
    # SetFrameRateLimit(60.0): EX_FloatConst 60.0 after the call to that import.
    (bytes.fromhex('1c1dffffff1e00007042'), bytes.fromhex('1c1dffffff1e00000000'), 1),
    # 4K needs the "Native 4K framebuffer pool" patch (a patch file in patches/): the PS4 pool of
    # 128 MB ran out of memory.
    (b'r.SetRes 2560x1440\0', b'r.SetRes 3840x2160\0', 1),
    (b'Cinematic Mode (1440p)\0', b'Cinematic Mode (2160p)\0', 2),
    # The "Show Stat SceneRendering" toggle (a profiling overlay) switches to 1440p instead.
    (b'\x1fstat SceneRendering\0', b'\x1fr.SetRes 2560x1440 \0', 1),
    (b'Show Stat SceneRendering\0', b'Render 2560x1440 (1440p)\0', 2),
]


# The debug menu's first resolution button follows the native output setting: the base PS4
# renderer makes its buffers at the display size at start, so only a live r.SetRes switches.
# Command and label keep their lengths (the game's own 18 and 22 characters).
NATIVE_BUTTON = {'720p_native': (b'r.SetRes 1280x720 ', b'Cinematic Mode (720p) '),
                 '1440p_native': (b'r.SetRes 2560x1440', b'Cinematic Mode (1440p)'),
                 '1800p_native': (b'r.SetRes 3200x1800', b'Cinematic Mode (1800p)'),
                 '4K_native': (b'r.SetRes 3840x2160', b'Cinematic Mode (2160p)')}


def debug_hud(game, resolution='native'):
    data = read_file(game, DEBUG_HUD)
    for old, new, count in DEBUG_HUD_EDITS:
        if data.count(old) != count:
            raise ValueError(f'{DEBUG_HUD}: unexpected contents (game version?)')
        data = data.replace(old, new)
    if resolution in NATIVE_BUTTON:
        command, label = NATIVE_BUTTON[resolution]
        data = data.replace(b'r.SetRes 3840x2160\0', command + b'\0', 1)
        data = data.replace(b'Cinematic Mode (2160p)\0', label + b'\0')
    return data


# Unlimited ammo: every weapon uses up ammo (and wear) through the Blueprint function
# RemoveInventoryItemHealth(Item, Health), which adds Subtract_IntInt(0, Health) to the item. Health
# becomes the function's own result variable, still 0 then (UE4 zeroes a script function's locals):
# nothing is taken and the item's real count is still returned (no "out of ammo"). The operand must
# keep its size on disk and in memory (an object reference is 8 bytes loaded): EX_IntConst instead
# broke the loaded bytecode and crashed at start. Weapons stop wearing out, the Store may not
# charge for what uses the same function.
INFINITE_AMMO = 'OVERBITE/Content/Blueprints/GameInstance/OverbiteGameInstanceFunctions.uexp'
INFINITE_AMMO_EDITS = [
    (bytes.fromhex('6816ffffff1d00000000007d030000161b53'),
     bytes.fromhex('6816ffffff1d00000000007c030000161b53'), 1),
]


def edited_asset(game, name, edits):
    data = read_file(game, name)
    for old, new, count in edits:
        if data.count(old) != count:
            raise ValueError(f'{name}: unexpected contents (game version?)')
        data = data.replace(old, new)
    return data


def apply(game, resolution='native', quality='console', fps=60, debug_menu=False, infinite_ammo=False,
          upscale='off'):
    """Writes or removes the override pak. Returns a short description of the active state."""
    pak = paks_dir(game) / PAK_NAME
    values = dict(QUALITY.get(quality, {}))
    if quality in LOCAL_SHADOWS:
        size, threshold = LOCAL_SHADOWS[quality]
        values.update({'r.Shadow.MinResolution': str(size), 'r.Shadow.MaxResolution': str(size),
                       'r.Shadow.RadiusThreshold': str(threshold), 'r.Shadow.CacheWholeSceneShadows': '1'})
        cascades, distance = SUN_SHADOWS[quality]
        values.update({'r.Shadow.CSM.MaxCascades': cascades, 'r.Shadow.DistanceScale': distance})
    percentage = SCREEN_PERCENTAGE.get(resolution)
    if percentage:
        values['r.ScreenPercentage'] = percentage
    output = NATIVE_OUTPUT.get(resolution)
    if output:
        values['r.setres'] = output
    scale = TEMPORAL_UPSCALE.get(upscale) if not percentage else None
    if scale:
        values.update({'r.ScreenPercentage': scale, 'r.TemporalAA.Upsampling': '1'})
    engine = frame_rate_range(fps) if fps > 60 else {}
    if not values and not engine and not debug_menu and not infinite_ammo:
        pak.unlink(missing_ok=True)
        return 'native 1080p, console quality, 60 FPS'
    files = {CONFIG: set_values(read_file(game, CONFIG), values, engine)}
    # Native output: the base PS4 renderer makes its buffers at the display size at start and only
    # a live r.SetRes changes them; the runtime sets it (GOW3_UE4_SETRES), and the debug menu's
    # first resolution button follows the setting.
    if debug_menu:
        files[GAME_CONFIG] = debug_menu_config(game, True)
        files[DEBUG_HUD] = debug_hud(game, resolution)
    if infinite_ammo:
        files[INFINITE_AMMO] = edited_asset(game, INFINITE_AMMO, INFINITE_AMMO_EDITS)
    write_pak(pak, files)
    return (f'{resolution if percentage or output else "native 1080p"}'
            f'{f" (r.ScreenPercentage={percentage})" if percentage else ""}'
            f'{f" (r.setres={output})" if output else ""}'
            f'{f", temporal upscaling {upscale} ({scale}%)" if scale else ""}, {quality} quality, '
            f'{f"up to {fps}" if fps > 60 else 60} FPS{", debug menu (R3)" if debug_menu else ""}'
            f'{", unlimited ammo" if infinite_ammo else ""}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('game', type=Path)
    parser.add_argument('--resolution', choices=[*SCREEN_PERCENTAGE, *NATIVE_OUTPUT], default='native')
    parser.add_argument('--quality', choices=list(QUALITY), default='console')
    parser.add_argument('--fps', type=int, default=60, help='engine frame rate (60 = original)')
    parser.add_argument('--debug-menu', action='store_true', help='allow the developer debug menu (R3)')
    args = parser.parse_args()
    print('Render resolution:', apply(args.game, args.resolution, args.quality, args.fps, args.debug_menu))
