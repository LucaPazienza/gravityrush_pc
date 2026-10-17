#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Windows counterpart of run.sh: prepares the game image and starts gravityrush-runtime.exe.

Same environment variables as run.sh (GOW3_GAME_DIR, GOW3_DATA_DIR, GOW3_PATCHES, GOW3_MODS_*,
GOW3_USER_DIR, ...). Extra arguments go to gravityrush-runtime.
The in-game "Apply and restart" runs this script again through GOW3_RESTART_COMMAND;
`--after PID` waits for the previous game process to end first (its GPU device and memory).
"""
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys

PORT = Path(__file__).resolve().parent


def fail(message):
    print(message, file=sys.stderr)
    sys.exit(1)


def wait_for(pid):
    kernel32 = ctypes.windll.kernel32
    SYNCHRONIZE = 0x00100000
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if handle:
        kernel32.WaitForSingleObject(handle, 30000)
        kernel32.CloseHandle(handle)


def no_console():
    """Started without a console (the launcher): console programs must not open their own."""
    return 0 if ctypes.windll.kernel32.GetConsoleWindow() else subprocess.CREATE_NO_WINDOW


def run_script(name, *args, capture=False):
    # Inside the packaged launcher executable (PyInstaller) the executable runs scripts itself.
    script = ['--script'] if getattr(sys, 'frozen', False) else []
    command = [sys.executable, *script, str(PORT / 'scripts' / name), *map(str, args)]
    if capture:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True,
                                creationflags=no_console())
        if result.returncode:
            sys.exit(result.returncode)
        return result.stdout
    # stdin given: the output handles are passed explicitly (a windowed launcher child would
    # get none otherwise).
    result = subprocess.run(command, stdin=subprocess.DEVNULL, creationflags=no_console())
    if result.returncode:
        sys.exit(result.returncode)
    return None


def find_executable(name):
    """bin/ (packaged), else out/ (built with build.sh)."""
    for candidate in (PORT / 'bin' / name, PORT / 'out' / name):
        if candidate.is_file():
            return candidate
    return None


def main():
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == '--after':
        wait_for(int(args[1]))
        args = args[2:]
    # As run.sh: relative paths (GOW3_GAME_DIR, GOW3_DATA_DIR, fsr4_shaders/) are from the port.
    os.chdir(PORT)
    env = os.environ
    data = Path(env.get('GOW3_DATA_DIR', PORT))
    out = data / 'out'
    out.mkdir(parents=True, exist_ok=True)
    if not (data / 'gravityrush.ini').exists() and (data / 'gow3.ini').exists():
        (data / 'gow3.ini').rename(data / 'gravityrush.ini')  # settings of builds before 1.1
    env.setdefault('GOW3_CONFIG', str(data / 'gravityrush.ini'))
    # Values this script derived on the previous start ("Apply and restart" inherits them) are
    # derived again from the new options.
    for key in env.pop('GOW3_DERIVED', '').split(','):
        env.pop(key, None)
    derived = []
    sys.path.insert(0, str(PORT / 'scripts'))
    import graphics_options
    graphics, reverted = graphics_options.prepare(env['GOW3_CONFIG'], out / 'graphics_state.json')
    if reverted:
        print('Graphics: the last restart never reached the game; previous options restored', flush=True)
    env.update(graphics_options.environment(graphics))
    if not env.get('GOW3_FSR411_DIR') and not (PORT / 'fsr4_411').is_dir() and (data / 'fsr4_411').is_dir():
        env['GOW3_FSR411_DIR'] = str(data / 'fsr4_411')

    probe = Path(env['GOW3_PROBE']) if env.get('GOW3_PROBE') else find_executable('gravityrush-runtime.exe')
    if not probe or not probe.is_file():
        fail('gravityrush-runtime.exe not found: build it with build.sh (MSYS2 CLANG64) or use a packaged build.')
    # Development builds run from the MSYS2 tree: its CLANG64 DLLs (SDL3, FFmpeg, ...).
    if not (probe.parent / 'SDL3.dll').is_file():
        clang64 = Path(env.get('MSYS2_ROOT', r'C:\msys64')) / 'clang64' / 'bin'
        if clang64.is_dir():
            env['PATH'] = f'{clang64}{os.pathsep}{env.get("PATH", "")}'

    game = Path(env.get('GOW3_GAME_DIR', PORT.parent / 'CUSA11227'))
    if game.suffix.lower() == '.pkg' and game.is_file():
        # A PKG is unpacked once beside it (<folder>/<TITLE_ID>); later starts reuse the folder.
        import pkg_extract
        target = Path(env.get('GOW3_PKG_TARGET') or pkg_extract.default_target(game))
        if not pkg_extract.is_extracted(game, target):
            print(f'Unpacking {game.name} into {target} (first start only)…', flush=True)
            last = [-1]

            def report(done, total, rate):
                percent = done * 100 // max(total, 1)
                if percent != last[0]:
                    last[0] = percent
                    print(f'PKG: {percent}% ({done >> 20} of {total >> 20} MB, {rate:.0f} MB/s)', flush=True)
            try:
                pkg_extract.extract(game, target, report)
            except (OSError, ValueError) as error:
                fail(f'Could not unpack {game}: {error}')
        game = target
    if not (game / 'eboot.bin').is_file():
        fail(f'No eboot.bin in {game} (set GOW3_GAME_DIR to the game folder or its .pkg).')
    import game_profiles
    profile = game_profiles.profile(game)
    if profile['name']:
        print(f'Game profile: {profile["name"]} ({", ".join(profile["modules"])})', flush=True)
    engine_fps = int(graphics['engine_fps'])
    if profile.get('ue4_render_scale') and engine_fps > 60:
        # Unreal Engine 4 flips at every vblank (rhi.SyncInterval 1). A 480 Hz vblank with a frame
        # limit shows each frame when it is ready: a 120 Hz vblank turned 9 ms frames into 17 ms.
        env.setdefault('GOW3_VBLANK_HZ', '0')
        env.setdefault('GOW3_FPS_CAP', str(engine_fps))
    if profile.get('ue4_render_scale'):
        import ue4_override
        # Native output: the runtime sets the game's r.SetRes live once it runs (runtime_extra.c).
        if output := ue4_override.NATIVE_OUTPUT.get(graphics['render_resolution']):
            env.setdefault('GOW3_UE4_SETRES', output)
    for key, value in profile['env'].items():
        env.setdefault(key, value)
    profile_ue4 = bool(profile.get('ue4_render_scale'))
    if profile_ue4:
        import ue4_override
        try:
            ini = graphics_options.read_ini(env['GOW3_CONFIG'])
            print('Render resolution:', ue4_override.apply(game, graphics['render_resolution'],
                                                           ini.get('ue4_quality', 'console'), engine_fps,
                                                           ini.get('cheat_menu') == '1',
                                                           ini.get('cheat_infinite_ammo') == '1',
                                                           ini.get('ue4_upscale', 'off')), flush=True)
        except (OSError, ValueError) as error:
            print(f'Render resolution: unchanged ({error})', flush=True)
    original_game = game.resolve()
    game = Path(run_script('mods.py', game, '--out', out,
                           '--mods-dir', env.get('GOW3_MODS_DIR', data / 'mods'),
                           '--config', env.get('GOW3_MODS_CONFIG', data / 'mods.json'),
                           '--enabled', env.get('GOW3_MODS_ENABLED', '1'), capture=True).strip())
    mod_view = game if game.resolve() != original_game else None
    try:
        run_script('prepare.py', game, '--out', out)
        run_script('link_libc.py', game, '--out', out)
        run_script('link_modules.py', game, '--out', out, '--modules', *profile['modules'])
        run_script('content_profile.py', game, '--out', out, '--sku', env.get('GOW3_CONTENT_SKU', 'full'))

        from patches import (eboot_matches, game_app_version, game_profile, game_title_id,
                             patch_requirements, selected_patches)
        profile = game_profile(game_title_id(game))
        patched = bool(profile) and ((game_app_version(game) == profile[2] and eboot_matches(game, profile))
                                     or bool(env.get('GOW3_FORCE_PATCHES')))
        # The window shows the port's icon, else the game's (BMP: the format SDL loads without
        # extra libraries). launcher/gravityrush.bmp is ready-made, so no Pillow is needed for it.
        if (PORT / 'launcher' / 'gravityrush.bmp').is_file():
            env.setdefault('GOW3_WINDOW_ICON', str(PORT / 'launcher' / 'gravityrush.bmp'))
        try:
            from PIL import Image
            source = PORT / 'launcher' / 'gravityrush.png'
            if not source.is_file():
                source = game / 'sce_sys' / 'icon0.png'
            with Image.open(source) as icon:
                icon.convert('RGBA').resize((64, 64), Image.LANCZOS).save(out / 'window_icon.bmp')
            env.setdefault('GOW3_WINDOW_ICON', str(out / 'window_icon.bmp'))
        except (ImportError, OSError):
            pass
        # The temporal upscalers and motion vectors are not calibrated for this game yet; linear
        # image readbacks fix its corrupted textures.
        env.setdefault('GOW3_UPSCALER', 'none')
        env.setdefault('GOW3_READBACK_LINEAR', '1')
        if patched:
            # The patch notes give the direct memory and VBlank rate the selected patches need.
            names = selected_patches(profile[1], profile[2], env.get('GOW3_PATCHES', ''), env.get('GOW3_PATCHES_ONLY') == '1')
            # gravityrush.ini decides the resolution and frame rate patches (in-game menu, launcher).
            if not profile_ue4:  # God of War III's resolution / frame rate patch names
                names = graphics_options.patch_names(names, graphics)
            env['GOW3_PATCHES'] = ';'.join(names)
            env['GOW3_PATCHES_ONLY'] = '1'
            dmem, vblank = patch_requirements(profile[1], names, profile[2])
            for key, value in (('GOW3_DMEM_MB', dmem), ('GOW3_VBLANK_HZ', vblank)):
                if value and key not in env:
                    env[key] = str(value)
                    derived.append(key)
        run_script('patches.py', '--out', out, '--extra', env.get('GOW3_PATCHES', ''), '--game-dir', game,
                   '--patches-dir', env.get('GOW3_PATCHES_DIR', data / 'patches'),
                   '--patches-config', env.get('GOW3_PATCHES_CONFIG', data / 'patches.json'))
        if 'GOW3_VBLANK_HZ' not in env:
            env['GOW3_VBLANK_HZ'] = '60'
            derived.append('GOW3_VBLANK_HZ')
        env['GOW3_DERIVED'] = ','.join(derived)

        # The in-game restart starts this script again once this process is gone.
        # GPU caches (shaders, pipelines) beside the saves; read before main(), so set here.
        user_dir = Path(env.get('GOW3_USER_DIR', data / 'user')).resolve()
        user_dir.mkdir(parents=True, exist_ok=True)
        env.setdefault('GOW3_GPU_USER_DIR', str(user_dir))
        from save_backup import backup
        try:
            if made := backup(user_dir):
                print(f'Saves backed up to {made}', flush=True)
        except OSError as error:
            print(f'Save backup failed, starting anyway: {error}', flush=True)
        this = ['--run'] if getattr(sys, 'frozen', False) else [str(Path(__file__).resolve())]
        restart = [sys.executable, *this, '--after', str(os.getpid()), *args]
        env['GOW3_RESTART_COMMAND'] = subprocess.list2cmdline(restart)
        command = [str(probe), str(out / 'boot-linked.bin'), '--content-profile', str(out / 'content.bin'),
                   '--patches', str(out / 'patches.bin'), '--app0', str(game),
                   '--user', str(user_dir),
                   '--timeout', env.get('GOW3_TIMEOUT', '0'), *args]
        # No stdin: an inherited pipe (shells such as Git Bash) cost the game its console output.
        return subprocess.run(command, stdin=subprocess.DEVNULL, creationflags=no_console()).returncode
    finally:
        if mod_view:
            shutil.rmtree(mod_view, ignore_errors=True)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
