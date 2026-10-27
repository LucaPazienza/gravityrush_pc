#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Gravity Rush Remastered (PS4, CUSA01113) launcher for Windows (Tkinter).

Every setting of the port in one window: the game (a folder or the .pkg, unpacked once), saves,
gravityrush.ini (display, frame rate, shaders, GPU data), start-up options passed to run.py as
environment variables, mods, third-party patches and controls.
Launcher options live in %APPDATA%/gravityrush-launcher/settings.json.

Frozen with PyInstaller, "Gravity Rush Launcher.exe" also runs the game without the window (`--play`,
which "Gravity Rush.exe" uses), run.py (`--run`) and the preparation scripts (`--script`), so a
packaged port needs no Python.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import webbrowser
import zipfile

FROZEN = getattr(sys, 'frozen', False)
LAUNCHER_EXE = 'Gravity Rush Launcher.exe'  # this program, frozen
GAME_EXE = 'Gravity Rush.exe'               # packaging/windows/play.c: plays with the saved settings
PORT_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PORT_DIR / 'scripts'))
import save_backup  # noqa: E402,F401  (scripts/; launcher_ui uses it)
DATA_DIR = Path(os.environ.get('GOW3_DATA_DIR', PORT_DIR))
CONFIG_DIR = Path(os.environ.get('APPDATA') or os.environ.get('USERPROFILE') or PORT_DIR) / 'gravityrush-launcher'
CONFIG_FILE = CONFIG_DIR / 'settings.json'
MOD_PRESETS = DATA_DIR / 'mods_presets.json'
APP_NAME = 'Gravity Rush'
MAX_LOG_LINES = 6000
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
# This build. A release package's launcher looks for a newer release on GitHub when it opens
# (Advanced > Updates) and installs it when the player agrees. Pre-releases count too (the first
# releases were previews). Tests: GR_UPDATE_API serves another release list, GR_UPDATE_TEST_FROM
# makes this build compare as an older version.
VERSION = '0.1.9'
RELEASES_API = os.environ.get('GR_UPDATE_API') or \
    'https://api.github.com/repos/LucaPazienza/gravityrush_pc/releases?per_page=20'
RELEASES_PAGE = 'https://github.com/LucaPazienza/gravityrush_pc/releases'
INSTALLED_VERSION = os.environ.get('GR_UPDATE_TEST_FROM') or VERSION
# The Windows package of a release (packaging/windows/package.sh).
RELEASE_ASSET = re.compile(r'GravityRush-PC-[0-9.]+-Windows\.zip', re.IGNORECASE)
UPDATE_DIR = Path(tempfile.gettempdir()) / 'gravityrush-update'
# Updates install only over a release package (runtime in bin/); a development copy updates with git.
IS_RELEASE = FROZEN and (PORT_DIR / 'bin' / 'gravityrush-runtime.exe').is_file() and not (PORT_DIR / 'build.sh').exists()
# Never copied over an installation by an update (the package does not hold them either): what
# players create next to the launcher, at the top of the folder.
USER_FILES = ('user', 'out', 'mods', 'gravityrush.ini', 'mods.json', 'mods_presets.json', 'patches.json', 'last_run.log')


# ---------------------------------------------------------------------------------------------
# Command line roles of the frozen executable.

def attach_stdio():
    """A windowed executable starts without sys.stdout; inherited pipes or a console still exist."""
    import msvcrt
    for name, std in (('stdout', -11), ('stderr', -12)):
        if getattr(sys, name) is not None:
            continue
        stream = None
        handle = ctypes.windll.kernel32.GetStdHandle(std)
        if handle and handle != ctypes.c_void_p(-1).value:
            try:
                stream = open(msvcrt.open_osfhandle(handle, os.O_WRONLY), 'w', encoding='utf-8',
                              errors='replace', buffering=1)
            except OSError:
                stream = None
        setattr(sys, name, stream or open(os.devnull, 'w'))


def run_role(argv):
    """--run [args]: run.py; --script <file> [args]: a preparation script. Returns an exit code."""
    attach_stdio()
    for stream in (sys.stdout, sys.stderr):  # keep messages in order with the game's output
        try:
            stream.reconfigure(line_buffering=True)
        except (AttributeError, ValueError):
            pass
    if argv[0] == '--script':
        path, sys.argv = argv[1], argv[1:]
    else:
        path = str(PORT_DIR / 'run.py')
        sys.argv = [path, *argv[1:]]
    try:
        runpy.run_path(path, run_name='__main__')
    except SystemExit as stop:
        return stop.code if isinstance(stop.code, int) else (0 if stop.code is None else 1)
    return 0


def run_command():
    """The command that starts run.py: this executable when frozen, else Python."""
    return [sys.executable, '--run'] if FROZEN else [sys.executable, str(PORT_DIR / 'run.py')]


# ---------------------------------------------------------------------------------------------
# Languages: every text is written in English with the Russian next to it; the other
# languages are in lang.py, keyed by the English text.

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lang  # noqa: E402

LANG = 'en'


WARN = '  ⚠'  # marks a risky choice; the text before it is translated as usual


def _(en, ru=None):
    if en.endswith(WARN):
        return _(en[:-len(WARN)], ru and ru.removesuffix(WARN)) + WARN
    if LANG == 'ru':
        return ru or en
    return lang.table(LANG).get(en) or en


def windows_language():
    try:
        primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3ff
    except (AttributeError, OSError):
        return 'en'
    return lang.WINDOWS_LANGUAGES.get(primary, 'en')


# ---------------------------------------------------------------------------------------------
# Settings. gravityrush.ini keys (the game reads them, the in-game menu edits them) and the
# launcher's own settings.json (passed to run.py as environment variables).

INI_FLAGS = {'sharpen', 'object_motion', 'show_fps', 'vsync', 'async_shaders', 'deferred_readback',
             'stale_readback', 'fsr1', 'rcas'}
# The graphics keys are also in the in-game menu (Insert / R3+L2); run.py reads the startup ones.
INI_DEFAULTS = {'upscaler': 'off', 'preset': '1', 'sharpen': '0', 'sharpness': '0.50',
                'object_motion': '1', 'show_fps': '1', 'output_res': '1920x1080',
                'live_resolution': 'auto', 'display_mode': 'borderless', 'vsync': '1', 'fps_limit': '0',
                'async_shaders': '1', 'deferred_readback': '1', 'stale_readback': '0',
                'render_resolution': 'native', 'engine_fps': '60', 'fsr1': '0', 'rcas': '1',
                'rcas_strength': '75', 'frames_queued': '1',
                # The Video page's other settings: only the keys listed here are written to the file.
                'refresh_rate': '0', 'shadow_quality': 'standard', 'anisotropy': '16', 'fxaa': '1'}
DISPLAY_MODES = [('windowed', ('Windowed',)), ('borderless', ('Borderless',)), ('fullscreen', ('Fullscreen',))]
FPS_LIMITS = [('30', ('30',)), ('60', ('60',)), ('120', ('120',)), ('240', ('240',)), ('0', ('Unlimited',))]
APP_DEFAULTS = {'ui_language': '', 'game_dir': os.environ.get('GOW3_GAME_DIR', ''), 'user_dir': '',
                'mods_dir': '', 'mods_enabled': True, 'patches_dir': '', 'language': '1',
                'player_name': '', 'hdr': False, 'draw_pipe': '', 'readbacks': '',
                'prep_workers': '', 'copy_threads': '', 'record_thread': True, 'gpu': '',
                'background_warmup': True, 'parallel_warmup': True, 'pipeline_binary_cache': True, 'perf_diag': False, 'frame_capture_key': False, 'frame_stats': False, 'gpu_profile': False,
                'vk_validation': False, 'close_on_play': False, 'f12_quits': False,
                'check_updates': False, 'game_patches': {}, 'controls': {}, 'button_names': 'auto',
                'last_pkg': '', 'update_check': True,
                # Mouse look: the camera follows the mouse; its buttons press PS4 buttons.
                'input_device': 'auto', 'mouse_look': True, 'mouse_sens': 1.0, 'mouse_invert': False,
                # The save backups made before every start.
                'save_backup': True, 'save_backup_keep': 10}

# PS4 button, default key, default gamepad button (SDL names; src/runtime_pad.c). L2/R2 come
# from the analog triggers and are not remapped on the gamepad.
CONTROLS = [('cross', 'Space', 'a'), ('circle', 'Left Shift', 'b'), ('square', 'E', 'x'),
            ('triangle', 'Q', 'y'), ('l1', '1', 'leftshoulder'), ('r1', '3', 'rightshoulder'),
            ('l2', 'R', None), ('r2', 'F', None), ('l3', 'Z', 'leftstick'),
            ('r3', 'C', 'rightstick'), ('options', 'Return', 'start'), ('touchpad', 'Tab', 'back'),
            ('up', 'I', 'dpup'), ('down', 'K', 'dpdown'), ('left', 'J', 'dpleft'), ('right', 'L', 'dpright'),
            # Gravity slide: L2 and R2 together on one key ('' on the gamepad: its triggers do it).
            ('slide', 'Left Ctrl', '')]
# The second keyboard/mouse binding of a button (src/runtime_pad.c key map): with mouse look the
# mouse buttons kick, shift gravity and make a stasis field.
ALT_KEYS = {'square': 'Mouse Left', 'r1': 'Mouse Right', 'circle': 'Mouse Middle'}
MOUSE_KEYS = ('Mouse Left', 'Mouse Right', 'Mouse Middle', 'Mouse X1', 'Mouse X2')
PS_BUTTON_NAMES = {'cross': 'Cross', 'circle': 'Circle', 'square': 'Square', 'triangle': 'Triangle',
                   'l1': 'L1', 'r1': 'R1', 'l2': 'L2', 'r2': 'R2', 'l3': 'L3', 'r3': 'R3',
                   'options': 'Options', 'touchpad': 'Touchpad', 'up': 'D-pad up', 'down': 'D-pad down',
                   'left': 'D-pad left', 'right': 'D-pad right', 'slide': 'L2 + R2'}
# Gamepad buttons by SDL name, labelled as on a PlayStation or an Xbox controller.
PAD_STYLES = {
    'playstation': {'a': 'Cross', 'b': 'Circle', 'x': 'Square', 'y': 'Triangle', 'leftshoulder': 'L1',
                    'rightshoulder': 'R1', 'leftstick': 'L3', 'rightstick': 'R3', 'start': 'Options',
                    'back': 'Share / Create', 'touchpad': 'Touchpad click', 'guide': 'PS button',
                    'dpup': 'D-pad up', 'dpdown': 'D-pad down', 'dpleft': 'D-pad left',
                    'dpright': 'D-pad right', 'misc1': 'Mute button'},
    'xbox': {'a': 'A', 'b': 'B', 'x': 'X', 'y': 'Y', 'leftshoulder': 'LB', 'rightshoulder': 'RB',
             'leftstick': 'LS (left stick click)', 'rightstick': 'RS (right stick click)', 'start': 'Menu',
             'back': 'View', 'touchpad': 'Touchpad click', 'guide': 'Xbox button', 'dpup': 'D-pad up',
             'dpdown': 'D-pad down', 'dpleft': 'D-pad left', 'dpright': 'D-pad right', 'misc1': 'Share'},
}


def control_changes(values, kind):
    """The buttons whose chosen key or SDL gamepad name differs from the default."""
    column = 1 if kind == 'key' else 2
    return {row[0]: values[row[0]].strip() for row in CONTROLS
            if row[column] and values.get(row[0], '').strip()
            and values[row[0]].strip().casefold() != row[column].casefold()}


# Input device (controls page): 'auto' plays with whatever is connected, 'controller' only with the
# controller, 'keyboard' only with the keyboard and mouse (GOW3_INPUT, src/runtime_pad.c).
INPUT_DEVICES = ('auto', 'controller', 'keyboard')
# SDL_GamepadType values (SDL3) of PlayStation pads; Xbox and the others use the Xbox names.
SDL_PLAYSTATION_TYPES = {4, 5, 6}  # PS3, PS4, PS5


def gamepads():
    """[(name, style)] of the connected controllers, found with the game's own SDL3 (the same
    names and types the game sees). Empty when SDL3 is missing or nothing is connected."""
    import ctypes
    candidates = [PORT_DIR / 'bin' / 'SDL3.dll', Path(r'C:\msys64\clang64\bin\SDL3.dll')]
    sdl = None
    for path in candidates:
        if path.is_file():
            try:
                sdl = ctypes.CDLL(str(path))  # full path: PyInstaller's folder holds no SDL3
                break
            except OSError:
                continue
    if sdl is None:
        return []
    found = []
    try:
        sdl.SDL_Init.argtypes, sdl.SDL_Init.restype = [ctypes.c_uint32], ctypes.c_bool
        sdl.SDL_GetGamepads.argtypes = [ctypes.POINTER(ctypes.c_int)]
        sdl.SDL_GetGamepads.restype = ctypes.POINTER(ctypes.c_uint32)
        sdl.SDL_GetGamepadNameForID.argtypes, sdl.SDL_GetGamepadNameForID.restype = [ctypes.c_uint32], ctypes.c_char_p
        sdl.SDL_GetGamepadTypeForID.argtypes, sdl.SDL_GetGamepadTypeForID.restype = [ctypes.c_uint32], ctypes.c_int
        sdl.SDL_free.argtypes = [ctypes.c_void_p]
        if not sdl.SDL_Init(0x00002000):  # SDL_INIT_GAMEPAD
            return []
        count = ctypes.c_int(0)
        ids = sdl.SDL_GetGamepads(ctypes.byref(count))
        for i in range(count.value if ids else 0):
            name = (sdl.SDL_GetGamepadNameForID(ids[i]) or b'Controller').decode('utf-8', 'replace')
            style = 'playstation' if sdl.SDL_GetGamepadTypeForID(ids[i]) in SDL_PLAYSTATION_TYPES else 'xbox'
            found.append((name, style))
        if ids:
            sdl.SDL_free(ids)
        sdl.SDL_Quit()
    except (AttributeError, OSError, ValueError):
        return found
    return found


def key_bindings(controls, button):
    """(main, alternative) keyboard/mouse binding of a button: the chosen ones, else the defaults;
    '' is no binding."""
    controls = controls if isinstance(controls, dict) else {}
    default = next(row[1] for row in CONTROLS if row[0] == button)
    picked = []
    for kind, fallback in (('key', default), ('alt', ALT_KEYS.get(button, ''))):
        chosen = controls.get(kind, {}) if isinstance(controls.get(kind), dict) else {}
        value = chosen.get(button, fallback)
        picked.append(value.strip() if isinstance(value, str) and not set(value) & set(',=|') else fallback)
    return tuple(picked)


def control_map(controls, kind):
    """GOW3_KEY_MAP/GOW3_PAD_MAP value for the changed buttons: 'cross=Q,square=E|Mouse Left'
    (keyboard: main and alternative binding; 'circle=' leaves a button without any)."""
    controls = controls if isinstance(controls, dict) else {}
    if kind == 'key':
        changed = set()
        for part in ('key', 'alt'):
            if isinstance(controls.get(part), dict):
                changed |= {b for b, v in controls[part].items() if isinstance(v, str)}
        return ','.join(f"{button}={'|'.join(k for k in key_bindings(controls, button) if k)}"
                        for button, _key, _pad in CONTROLS if button in changed)
    chosen = controls.get(kind, {}) if isinstance(controls.get(kind), dict) else {}
    return ','.join(f'{button}={chosen[button].strip()}' for button, _key, _pad in CONTROLS
                    if isinstance(chosen.get(button), str) and chosen[button].strip()
                    and not set(chosen[button]) & set(',=|'))

UPSCALERS = [('dlss', ('DLSS (NVIDIA GeForce RTX)',)),
             ('fsr4', ('FSR 4 (best quality)', 'FSR 4 (лучшее качество)')),
             ('fsr411', ('FSR 4.1.1 (needs fsr4_411 assets)', 'FSR 4.1.1 (нужны ассеты fsr4_411)')),
             ('fsr3', ('FSR 3.1 (every GPU)', 'FSR 3.1 (любая видеокарта)')),
             ('taa', ('TAA (native resolution anti-aliasing)', 'TAA (нативное сглаживание)')),
             ('off', ('Off', 'Выключен'))]
PRESETS = [('0', ('Native AA (×1.0)',)), ('1', ('Quality (×1.5)',)), ('2', ('Balanced (×1.7)',)),
           ('3', ('Performance (×2)',)), ('4', ('Ultra Performance (×3)',))]
OUTPUTS = [('1280x720', ('1280 × 720 (Steam Deck)',)), ('1920x1080', ('1920 × 1080',)),
           ('2560x1440', ('2560 × 1440',)), ('3840x2160', ('3840 × 2160 (4K)',))]
LIVE = [('auto', ('Auto (by graphics card)', 'Авто (по видеокарте)')), ('0', ('Off (faster)', 'Выключена (быстрее)')),
        ('1', ('On (change without restarting)', 'Включена (без перезапуска)'))]
LANGUAGES = [('1', ('English', 'Английский')), ('8', ('Russian', 'Русский')), ('0', ('Japanese', 'Японский')),
             ('2', ('French', 'Французский')), ('3', ('Spanish', 'Испанский')), ('4', ('German', 'Немецкий')),
             ('5', ('Italian', 'Итальянский'))]
DRAW_PIPE = [('', ('Auto (8+ threads)', 'Авто (8+ потоков)')), ('1', ('On', 'Включён')),
             ('0', ('Off (more stable)', 'Выключен (стабильнее)'))]
READBACKS = [('', ('Relaxed (default)', 'Relaxed (по умолчанию)')), ('0', ('Off', 'Выключены')),
             ('2', ('Precise',))]
FRAMES_QUEUED = [('1', ('1 (lowest latency)',)), ('2', ('2',)), ('0', ('Unlimited',))]
UI_LANGUAGES = lang.LANGUAGE_NAMES

FSR4_COMMIT = 'ae8d628fae208813172446d1e49ed94150b04658'
FSR4_BASE = f'https://raw.githubusercontent.com/FireBurn/Q2RTX/{FSR4_COMMIT}/baseq2/fsr4_shaders'


def fsr4_files():
    """The FSR 4 v07 asset set of tools/fetch_fsr4_assets.sh (1080 and 2160 tiers)."""
    files = ['LICENSE-FSR4-v07.txt', 'rcas.spv', 'spd_auto_exposure.spv']
    for model in ('native', 'quality', 'balanced', 'performance', 'ultraperf', 'drs'):
        files += [f'fsr4_model_v07_i8_{model}_initializers.bin', f'fsr4_model_v07_i8_{model}_pre_weights.bin',
                  f'fsr4_model_v07_i8_{model}_shader_manifest.json']
        for tier in ('1080', '2160'):
            files += [f'fsr4_model_v07_i8_{model}_{tier}_pre.spv', f'fsr4_model_v07_i8_{model}_{tier}_post.spv']
            files += [f'fsr4_model_v07_i8_{model}_{tier}_pass{n}.spv' for n in range(1, 13)]
    return files


def fsr4_missing():
    folder = PORT_DIR / 'fsr4_shaders'
    return [name for name in fsr4_files() if not (folder / name).is_file() or not (folder / name).stat().st_size]


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def ini_path():
    old = DATA_DIR / 'gow3.ini'  # settings of builds before 1.1
    if not (DATA_DIR / 'gravityrush.ini').exists() and old.exists():
        old.rename(DATA_DIR / 'gravityrush.ini')
    return Path(os.environ.get('GOW3_CONFIG', DATA_DIR / 'gravityrush.ini'))


def load_ini():
    values, lines = dict(INI_DEFAULTS), []
    try:
        lines = ini_path().read_text(encoding='utf-8').splitlines()
    except OSError:
        pass
    for line in lines:
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip()
    # The temporal sharpening is no longer offered (it strengthened a fine grid in the image).
    values['sharpen'] = '0'
    return values, lines


def save_ini(values, lines):
    """Rewrites the edited keys in place, appends missing ones, keeps comments and other keys."""
    written, out = set(), []
    for line in lines:
        if '=' in line and not line.lstrip().startswith('#'):
            key = line.split('=', 1)[0].strip()
            if key in values:
                out.append(f'{key}={values[key]}')
                written.add(key)
                continue
        out.append(line)
    if not lines:
        out.append('# Gravity Rush settings (in-game menu: Insert / R3+L2)')
    out += [f'{key}={value}' for key, value in values.items() if key not in written]
    ini_path().write_text('\n'.join(out) + '\n', encoding='utf-8')


def game_info(folder):
    """(title, app version) of a game folder, or None without eboot.bin."""
    folder = Path(folder or '.')
    if not (folder / 'eboot.bin').is_file():
        return None
    try:
        from prepare import sfo
        values = sfo((folder / 'sce_sys/param.sfo').read_bytes())
        return values.get('TITLE', APP_NAME).replace('™', '').replace('®', '').strip(), values.get('APP_VER', '?')
    except (OSError, ValueError, ImportError):
        return APP_NAME, '?'


def game_profile_of(folder):
    """(title id, (ids, built-in XML, app version)) of a game with a patch profile, else (id, None)."""
    from patches import game_profile, game_title_id
    title_id = game_title_id(folder) if folder else None
    return title_id, game_profile(title_id)


_GPUS = None


def vulkan_gpus():
    """The graphics cards as Vulkan lists them (the game's GOW3_GPU_ID counts in this order):
    [(name, kind)], kind 'discrete', 'integrated' or 'other'. Empty without a Vulkan driver."""
    global _GPUS
    if _GPUS is not None:
        return _GPUS
    _GPUS = []
    # The packaged launcher (PyInstaller) resolves a bare DLL name in its own folder: the system's
    # Vulkan loader is loaded by its full path first.
    names = ([os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'vulkan-1.dll'), 'vulkan-1']
             if os.name == 'nt' else ['libvulkan.so.1'])
    vk = None
    for name in names:
        try:
            vk = ctypes.WinDLL(name) if os.name == 'nt' else ctypes.CDLL(name)
            break
        except OSError as error:
            gpu_probe_note(f'no Vulkan loader at {name}: {error!r}')
    if vk is None:
        return _GPUS

    class InstanceCreateInfo(ctypes.Structure):
        _fields_ = [('sType', ctypes.c_int), ('pNext', ctypes.c_void_p), ('flags', ctypes.c_uint),
                    ('pApplicationInfo', ctypes.c_void_p), ('enabledLayerCount', ctypes.c_uint),
                    ('ppEnabledLayerNames', ctypes.c_void_p), ('enabledExtensionCount', ctypes.c_uint),
                    ('ppEnabledExtensionNames', ctypes.c_void_p)]
    instance = ctypes.c_void_p()
    info = InstanceCreateInfo(1, None, 0, None, 0, None, 0, None)  # VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO
    try:
        result = vk.vkCreateInstance(ctypes.byref(info), None, ctypes.byref(instance))
        if result != 0:
            gpu_probe_note(f'vkCreateInstance returned {result}')
            return _GPUS
        count = ctypes.c_uint(0)
        vk.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), None)
        devices = (ctypes.c_void_p * count.value)()
        vk.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), devices)
        for device in devices[:count.value]:
            props = ctypes.create_string_buffer(2048)  # VkPhysicalDeviceProperties (824 bytes)
            vk.vkGetPhysicalDeviceProperties(ctypes.c_void_p(device), props)
            kind = int.from_bytes(props.raw[16:20], 'little')  # deviceType
            name = props.raw[20:276].split(b'\0', 1)[0].decode('utf-8', 'replace')
            _GPUS.append((name, {1: 'integrated', 2: 'discrete'}.get(kind, 'other')))
        vk.vkDestroyInstance(instance, None)
    except (OSError, AttributeError, ValueError) as error:
        _GPUS = []
        gpu_probe_note(f'error {error!r}')
    gpu_probe_note(f'{len(_GPUS)} cards: {_GPUS}')
    return _GPUS


def gpu_probe_note(text):
    # GR_GPU_PROBE=1: what the card list found, in the launcher data folder (diagnostics).
    if os.environ.get('GR_GPU_PROBE'):
        try:
            with open(CONFIG_DIR / 'gpu_probe.txt', 'a', encoding='utf-8') as f:
                f.write(text + '\n')
        except OSError:
            pass


def game_environment(s):
    env = dict(os.environ)
    env['GOW3_GAME_DIR'] = s['game_dir']
    # The launcher's patch selection is the whole list (run.py, patches.py).
    title_id, profile = game_profile_of(s['game_dir'])
    chosen = s.get('game_patches', {}).get(title_id) if title_id else None
    if profile and chosen is not None:
        env['GOW3_PATCHES'] = ';'.join(chosen)
        env['GOW3_PATCHES_ONLY'] = '1'
    if s['user_dir']:
        env['GOW3_USER_DIR'] = s['user_dir']
    env['GOW3_MODS_DIR'] = s['mods_dir'] or str(DATA_DIR / 'mods')
    env['GOW3_MODS_CONFIG'] = str(DATA_DIR / 'mods.json')
    env['GOW3_MODS_ENABLED'] = '1' if s['mods_enabled'] else '0'
    env['GOW3_PATCHES_DIR'] = s['patches_dir'] or str(DATA_DIR / 'patches')
    env['GOW3_PATCHES_CONFIG'] = str(DATA_DIR / 'patches.json')
    env['GOW3_LANGUAGE'] = s['language']
    env['GOW3_SAVE_BACKUP'] = '1' if s.get('save_backup', True) else '0'
    env['GOW3_SAVE_BACKUP_KEEP'] = str(s.get('save_backup_keep', 10))
    if str(s['player_name']).strip():
        env['GOW3_USER_NAME'] = str(s['player_name']).strip()
    if s['hdr']:
        env['GOW3_HDR'] = '1'
    for key, name in (('draw_pipe', 'GOW3_DRAW_PIPE'), ('readbacks', 'GOW3_READBACKS'),
                      ('prep_workers', 'GOW3_PREP_WORKERS'), ('copy_threads', 'GOW3_COPY_THREADS')):
        if str(s.get(key, '')):
            env[name] = str(s[key])
    if not s.get('record_thread', True):
        env['GOW3_VK_RECORD_THREAD'] = '0'
    # The card is saved by name: its index changes when cards are added or removed, and a missing
    # one falls back to the game's own choice (an index past the list would stop the game).
    if s.get('gpu'):
        names = [name for name, _ in vulkan_gpus()]
        if s['gpu'] in names:
            env['GOW3_GPU_ID'] = str(names.index(s['gpu']))
    env['GOW3_BACKGROUND_WARMUP'] = '1' if s.get('background_warmup', True) else '0'
    env['GOW3_PARALLEL_WARMUP'] = '1' if s.get('parallel_warmup', True) else '0'
    env['GOW3_PIPELINE_BINARIES'] = '1' if s.get('pipeline_binary_cache', True) else '0'
    env.setdefault('GOW3_PERF_DIAG', '1' if s.get('perf_diag', False) else '0')
    for key, name in (('frame_stats', 'GOW3_FRAME_STATS'), ('gpu_profile', 'GOW3_GPU_PROFILE'),
                      ('vk_validation', 'GOW3_VK_VALIDATION'), ('frame_capture_key', 'GOW3_FRAME_CAPTURE_KEY')):
        if s[key]:
            env[name] = '1'
    for kind, name in (('key', 'GOW3_KEY_MAP'), ('pad', 'GOW3_PAD_MAP')):
        if value := control_map(s.get('controls', {}), kind):
            env[name] = value
    if s.get('gyro_sens'):
        env['GOW3_GYRO_SENS'] = str(s['gyro_sens'])
    if s.get('input_device') in ('controller', 'keyboard'):
        env['GOW3_INPUT'] = 'pad' if s['input_device'] == 'controller' else 'keyboard'
    env['GOW3_MOUSE_LOOK'] = '1' if s.get('mouse_look', True) and s.get('input_device') != 'controller' else '0'
    env['GOW3_MOUSE_INVERT_Y'] = '1' if s.get('mouse_invert') else '0'
    env.setdefault('GOW3_FPS_LOG', '1')  # FPS and worst frame every 5 s in the log (diagnostics)
    env.setdefault('GOW3_FRAME_STATS', '1')  # draws, compiles and stalls every 5 s (diagnostics)
    # F12 in the game (or creating the trigger file) saves the next frames here, for bug reports
    # (PNG files once the game has closed). Each session gets its own folder (frame numbers restart
    # at every start); one press saves 2 consecutive frames, so a flicker shows up between them.
    shots = Path(s['user_dir'] or DATA_DIR / 'user') / 'screenshots'
    session = shots / time.strftime('%Y%m%d-%H%M%S')
    try:
        session.mkdir(parents=True, exist_ok=True)
        env.setdefault('GOW3_DUMP_DIR', str(session))
        env.setdefault('GOW3_FRAME_DUMP_TRIGGER', str(shots / 'trigger'))
        env.setdefault('GOW3_FRAME_DUMP_COUNT', '2')
        # Option: F12 also closes the game once the frames are saved (the report ends at the problem).
        env.setdefault('GOW3_F12_QUIT', '1' if s.get('f12_quits') else '0')
        # Diagnostics: GPU optimizations switched off while playing, by writing a number here.
        env.setdefault('GOW3_TOGGLE_FILE', str(shots / 'toggles.txt'))
        # Frame analyzer: creating this file records how the next frame is drawn (render passes).
        env.setdefault('GOW3_CAPTURE_TRIGGER', str(shots / 'capture'))
        env.setdefault('GOW3_CAPTURE_DIR', str(session))
    except OSError:
        pass
    env['PYTHONUNBUFFERED'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


class GameJob:
    """A Windows job holding run.py and everything it starts: gravityrush-runtime.exe and the launches made
    by the in-game restart (no longer descendants of the first process)."""

    def __init__(self, process):
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        self.handle = kernel32.CreateJobObjectW(None, None)
        if self.handle:
            kernel32.AssignProcessToJobObject(ctypes.c_void_p(self.handle), ctypes.c_void_p(int(process._handle)))

    def terminate(self):
        if self.handle:
            ctypes.windll.kernel32.TerminateJobObject(ctypes.c_void_p(self.handle), 1)

    def close(self):
        if self.handle:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(self.handle))
            self.handle = None


def convert_frame_dumps(user_dir):
    """F12's raw frames (<name>_<n>_<width>x<height>.raw, 32-bit pixels) into PNG files a bug report
    can carry; the raw files are removed once converted."""
    try:
        from PIL import Image
    except ImportError:
        return
    for raw in Path(user_dir, 'screenshots').glob('*/*.raw'):
        try:
            width, height = (int(v) for v in raw.stem.rsplit('_', 1)[1].split('x'))
            data = raw.read_bytes()
            if len(data) < width * height * 4:
                continue
            Image.frombytes('RGBA', (width, height), data[:width * height * 4]).convert('RGB').save(
                raw.with_suffix('.png'), optimize=True)
            raw.unlink()
        except (OSError, ValueError, IndexError):
            pass


def play_without_window(settings):
    """--play: the game with the saved settings (shortcuts, Steam). Output goes to the console
    when there is one and to <saves folder>/last_run.log."""
    attach_stdio()
    log_dir = Path(settings.get('user_dir') or DATA_DIR / 'user')
    log_dir.mkdir(parents=True, exist_ok=True)
    with open(log_dir / 'last_run.log', 'w', encoding='utf-8', buffering=1) as log:
        process = subprocess.Popen(run_command(), cwd=PORT_DIR, env=game_environment(settings),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        for raw in iter(process.stdout.readline, b''):
            text = raw.decode('utf-8', errors='replace')
            log.write(text)
            try:
                sys.stdout.write(text)
            except (OSError, ValueError):
                pass
        code = process.wait()
    convert_frame_dumps(log_dir)
    return code


def version_tuple(text):
    return tuple(int(number) for number in re.findall(r'\d+', text or ''))


def http_request(url):
    return urllib.request.Request(url, headers={'Accept': 'application/vnd.github+json',
                                                'User-Agent': f'gravityrush-launcher/{VERSION}'})


def latest_release():
    """The newest published release with a Windows package (pre-releases count): a dict with
    version, url (the package), name, size, sha256 (or sha256_url) and page."""
    with urllib.request.urlopen(http_request(RELEASES_API), timeout=15) as response:
        releases = json.load(response)
    if isinstance(releases, dict):  # one release (the /latest endpoint)
        releases = [releases]
    best = None
    for release in releases:
        version = '.'.join(re.findall(r'\d+', release.get('tag_name') or ''))
        if release.get('draft') or not version:
            continue
        assets = release.get('assets') or []
        package = next((a for a in assets if RELEASE_ASSET.fullmatch(a.get('name') or '')), None)
        if not package or (best and version_tuple(version) <= version_tuple(best['version'])):
            continue
        # GitHub lists a SHA-256 for each asset; package.sh also publishes NAME.sha256.
        digest = (package.get('digest') or '').lower()
        checksum = next((a for a in assets if a.get('name') == package['name'] + '.sha256'), {})
        best = {'version': version, 'url': package.get('browser_download_url'), 'name': package['name'],
                'size': int(package.get('size') or 0), 'page': release.get('html_url') or RELEASES_PAGE,
                'sha256': digest[7:] if digest.startswith('sha256:') else None,
                'sha256_url': checksum.get('browser_download_url')}
    if not best:
        raise ValueError('no release with a Windows package')
    return best


def download_update(release, progress):
    """Downloads the release's package into UPDATE_DIR, checks its SHA-256 and unpacks it; returns
    the folder holding the new launcher. progress(done bytes, total bytes) runs on this thread."""
    shutil.rmtree(UPDATE_DIR, ignore_errors=True)
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    archive = UPDATE_DIR / 'update.zip'
    digest = hashlib.sha256()
    with urllib.request.urlopen(http_request(release['url']), timeout=60) as response, open(archive, 'wb') as out:
        total, done = int(response.headers.get('Content-Length') or release.get('size') or 0), 0
        while chunk := response.read(1 << 20):
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            progress(done, total)
    expected = release.get('sha256')
    if not expected and release.get('sha256_url'):
        with urllib.request.urlopen(http_request(release['sha256_url']), timeout=30) as response:
            expected = (response.read(4096).decode('ascii', 'replace').split() or [''])[0].lower()
    if not expected:
        raise OSError('the release lists no checksum for its package')
    if digest.hexdigest() != expected:
        raise OSError('the download is damaged (checksum mismatch); try again')
    with zipfile.ZipFile(archive) as package:  # extractall drops absolute paths and ".." parts
        package.extractall(UPDATE_DIR / 'new')
    archive.unlink()
    new = next((p.parent for p in (UPDATE_DIR / 'new').rglob(LAUNCHER_EXE)), None)
    if not new or not (new / 'bin' / 'gravityrush-runtime.exe').is_file():
        raise OSError(f'{LAUNCHER_EXE} is missing from the download')
    return new


def folder_writable(folder):
    """Whether an update can replace files in this folder (not under Program Files, not read-only)."""
    probe = Path(folder) / f'.update-check-{os.getpid()}'
    try:
        probe.write_bytes(b'')
        probe.unlink()
        return True
    except OSError:
        return False


def start_update(new):
    """Starts the downloaded launcher: it copies itself over this installation once this launcher
    has closed (--install-update, kept the same in every version), then opens it again."""
    command = [str(new / LAUNCHER_EXE), '--install-update', str(PORT_DIR), str(os.getpid())]
    flags = NO_WINDOW | 0x01000000  # CREATE_BREAKAWAY_FROM_JOB: it outlives this launcher
    try:
        subprocess.Popen(command, cwd=str(new), stdin=subprocess.DEVNULL, creationflags=flags)
    except OSError:  # a job that forbids breaking away
        subprocess.Popen(command, cwd=str(new), stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)


def install_update(target, wait_pid):
    """--install-update TARGET PID, run by the downloaded version from its temporary folder:
    waits for the old launcher to close, copies this version over TARGET (never the saves,
    settings or mods) and starts it."""
    target = Path(target)
    kernel = ctypes.windll.kernel32
    handle = kernel.OpenProcess(0x00100000, False, int(wait_pid))  # SYNCHRONIZE
    if handle:
        kernel.WaitForSingleObject(handle, 60000)
        kernel.CloseHandle(handle)

    def ignore(folder, names):  # players' files at the top of the installation
        return [name for name in names if Path(folder) == PORT_DIR and name in USER_FILES]
    for attempt in range(30):
        try:
            shutil.copytree(PORT_DIR, target, dirs_exist_ok=True, ignore=ignore)
            break
        except OSError:  # a file still in use: the old launcher (or the game) is closing
            time.sleep(1)
    else:
        ctypes.windll.user32.MessageBoxW(None, _(
            'Could not install the update. Download it from the releases page.',
            'Не удалось установить обновление. Скачайте его со страницы релизов.'), APP_NAME, 0x10)
        webbrowser.open(RELEASES_PAGE)
        return 1
    subprocess.Popen([str(target / LAUNCHER_EXE), '--updated'], cwd=str(target))
    return 0


def main():
    global LANG
    args = sys.argv[1:]
    if args and args[0] in ('--run', '--script'):
        sys.exit(run_role(args))
    settings = {**APP_DEFAULTS, **load_json(CONFIG_FILE, {})}
    LANG = settings.get('ui_language') or windows_language()
    if args[:1] == ['--install-update'] and len(args) == 3:
        sys.exit(install_update(args[1], args[2]))
    if FROZEN and UPDATE_DIR not in PORT_DIR.parents:
        shutil.rmtree(UPDATE_DIR, ignore_errors=True)  # what a finished update left behind
    # --play (Gravity Rush.exe): the game at once. Without a usable game folder there is nothing to
    # play yet: open the launcher instead.
    if '--play' in args and (Path(settings['game_dir'] or '.') / 'eboot.bin').is_file():
        sys.exit(play_without_window(settings))
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharp text on scaled displays
    except (AttributeError, OSError):
        pass
    import tkinter as tk
    from tkinter import filedialog
    import launcher_ui
    launcher_ui.run(sys.modules[__name__], tk, filedialog)


if __name__ == '__main__' and os.environ.get('GR_GPU_PROBE'):
    vulkan_gpus()
if __name__ == '__main__':
    main()
