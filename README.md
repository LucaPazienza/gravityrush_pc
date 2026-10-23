# Gravity Rush Remastered — Native PC Port

<p align="center">
  <img src="launcher/gravityrush.png" alt="Gravity Rush PC port icon" width="160">
</p>

<p align="center">
  <em>The PS4 game running natively on Windows: no emulator.</em>
</p>

## About

This project brings **Gravity Rush Remastered** (PS4, CUSA01113, tested with the European release
EP9000-CUSA01113_00) to PC as a native port.

There is no emulator: the game's original x86-64 executable runs directly on the PC's processor,
a runtime written for this port replaces the PS4 system libraries, and the graphics run on the
[shadPS4](https://github.com/shadps4-emu/shadPS4) video core, which translates the PS4 GPU commands
and shaders to Vulkan.

## Current Status

**Status: version 0.1.7 — the opening, the first episode and the city work,
with sound and saves. Not every part of the game has been tested yet.**

**[Download the latest release](https://github.com/LucaPazienza/gravityrush_pc/releases/latest)** —
see [Playing](#playing) below.

Tested on Windows 11 with an NVIDIA RTX 5070 Ti, an Xbox One controller and a DualSense.

What works today:

- **Boot and story:** title flow, the opening apple scene, the opening movie, episode 1 and the
  city of Hekseville; dialogue, menus and trophies.
- **Audio:** movies (AvPlayer) and the game's own sound engine on top of a real NGS2 sampler:
  PCM effects, ATRAC9 streamed music and ambience (wind, city), voice volume, pitch and panning,
  pause and resume, a mastering limiter, and a 7.1-to-stereo downmix for stereo devices.
- **Saves:** the save dialog, autosave, loading and manual saves; backups before every start.
- **Graphics:** Vulkan through the shadPS4 video core, readable text (font library with FreeType),
  borderless window by default (windowed and fullscreen, with a refresh rate choice).
  **Render resolution up to 4K** through patches of the game's own sizes and screen-space shader
  constants, **high-quality shadows** (4096 shadow map) and anisotropic filtering.
  **Anti-aliasing and upscaling:** the game's FXAA, TAA, **FSR 3.1** and **DLSS** (NVIDIA RTX), with
  Native/DLAA, Quality, Balanced and Performance modes that render below the screen and enlarge the
  image to it, the HUD kept as the game draws it. FSR 1.0 is available as a simple upscaler.
- **Input:** controllers through SDL3 (Xbox, DualSense and others), keyboard and mouse.
  The touchpad works with real touch ids; the mouse acts as a finger (hold and drag for swipes).
  The **DualSense gyro** steers the gravity camera like on the PS4 (adjustable sensitivity).
  On handhelds whose controller has no gyro (ROG Xbox Ally), **Vita mode** uses the console's own
  gyroscope instead (Windows sensors; a switch on the Controls page).
- **Launcher:** a dark window with a sidebar menu and pages in a card (game, video, controls,
  advanced, log), in English, Italian, French, German and Spanish. `Gravity Rush.exe` starts the game directly with the saved settings.
  The launcher finds new releases on GitHub by itself and installs them when the player agrees
  (saves, settings and mods are kept).
- **In-game menu** (Insert, or R3+L2): image options, performance and an FPS overlay.

Not done yet / known gaps:

- No systematic testing of later episodes, stability over long sessions, or other hardware.

### Roadmap

- [x] Native runtime: boot, title flow, graphics, text
- [x] Get past the opening scene
- [x] Audio: movies, effects, streamed music and ambience
- [x] Saves: load, autosave, manual save
- [x] Controller, touchpad and DualSense gyro
- [x] Launcher
- [x] Render resolution up to 4K, high-quality shadows
- [x] First preview release
- [x] First official release (0.1.2), with automatic updates
- [ ] Play through the whole story and fix what breaks
- [ ] Trophies
- [ ] Performance and stability work

## Requirements

- Windows 10 (1903 or newer) or Windows 11, 64-bit.
- A graphics card with Vulkan 1.3 and a current driver.
- Your own legally acquired copy of Gravity Rush Remastered (PS4), as an unpacked game folder
  (eboot.bin, sce_module, sce_sys) that you prepare with your own tools. Tested with the European
  release CUSA01113, version 01.00; the resolution and shadow patches only apply to that version.

## Playing

1. Download the Windows zip from [Releases](https://github.com/LucaPazienza/gravityrush_pc/releases)
   and extract it anywhere (not inside the zip).
2. Open **Gravity Rush Launcher.exe** (Windows may warn that the program is not signed: More info,
   Run anyway), choose your game folder on the Game page and press **Play**.
3. Later, **Gravity Rush.exe** starts the game straight away with the saved settings.
4. New versions: the launcher offers them when it opens (Advanced > Updates).

The Video page sets the render resolution (up to 4K), shadow quality and the display options.
To report a problem, press **F12** where you see it (the frames are saved in `user\screenshots`)
and open an [issue](https://github.com/LucaPazienza/gravityrush_pc/issues) with them,
`user\last_run.log` and where you were in the game.

## Building and Running

1. Install [MSYS2](https://www.msys2.org) and, in the **MSYS2 CLANG64** shell, the packages listed
   in [packaging/windows/README.md](packaging/windows/README.md). Install
   [Python 3](https://www.python.org) with `pip install pillow cryptography`.
2. Build (newer CLANG64 toolchains need the standard headers forced for some third-party code):

   ```bash
   git clone --recursive https://github.com/LucaPazienza/gravityrush_pc
   cd gravityrush_pc
   CXXFLAGS="-include cstdlib -include cstdio -include cwchar -include cmath -include new" bash build.sh
   ```

3. Run the game (or start the launcher with `Gravity Rush Launcher.cmd`, or build
   `Gravity Rush Launcher.exe` and `Gravity Rush.exe` with `bash scripts/gr_build_launcher.sh`):

   ```powershell
   $env:GOW3_GAME_DIR = 'D:\path\CUSA01113'   # the game folder
   python run.py
   ```

The loader stops at the first PS4 system function the runtime does not implement and names it.

| Part | Where | What it does |
|---|---|---|
| Loader | `src/probe.c` | Loads the image and starts the game's original code |
| Runtime | `src/runtime_*.c`, `src/gr_*.inc` | PS4 system functions |
| GPU and libraries | `gpu/shadps4/` | shadPS4 video core (Vulkan), font library and AvPlayer |
| Preparation | `scripts/` | Reads `eboot.bin`, links the game's `libc` and `libSceFios2` |
| Launcher | `launcher/gravityrush_launcher.py`, `launcher/launcher_ui.py` | Settings, controls and the play button |
| Packaging | `packaging/windows/package.sh` | Builds the release zip (with the third-party licenses) |

Please do not add proprietary game files, disc images, executables, firmware, or other copyrighted
game data to this repository.

## Contributing

Contributions, technical research, bug reports, and documentation improvements are welcome.

Before opening an issue or pull request:

1. Check existing issues to avoid duplicates.
2. Include clear reproduction steps for bugs.
3. Separate confirmed findings from guesses or unverified observations.
4. Do not upload copyrighted game files or other proprietary assets.

## Credits and Acknowledgements

- **God of War Native Port** — technical starting point: [Waffle565/God-Of-War-Native-Port](https://github.com/Waffle565/God-Of-War-Native-Port)
  and [FelipePrado0/gow3_pc](https://github.com/FelipePrado0/gow3_pc), with their credits:
  Supermedo and deadinside28 (bloodborne_pc), cuesta4 (shadPS4 GPU fixes).
- **MediEvil PC port** — the fork this project grew from: [bc160201983/medievil_2019_pc_port](https://github.com/bc160201983/medievil_2019_pc_port).
- **shadPS4 team** — the video core, font and AvPlayer libraries, PKG format code and the NID
  name list.
- Launcher font: Cabin (SIL Open Font License).
- Also used: LibAtrac9, FFmpeg, FreeType, SDL3, Dear ImGui, sirit, magic_enum, miniz, xbyak,
  Vulkan Memory Allocator, FSR-Vulkan, MSYS2, LLVM, Pillow and cryptography.
- **Gravity Rush** — developed by Japan Studio and published by Sony Interactive Entertainment.

The inclusion of a project in this section does not imply endorsement or affiliation.

## License

GNU GPL v2 or later ([LICENSE](LICENSE)). Third-party components keep their own licenses.

## Disclaimer

This is an unofficial, community-driven project and is not affiliated with, endorsed by, or
sponsored by Sony Interactive Entertainment or Japan Studio. Gravity Rush and all related names,
characters, artwork, and other intellectual property belong to their respective owners.

This repository is intended for research, development, and game-preservation purposes. It does not
provide copyrighted game files. Users must obtain and use their own legally acquired copy of the game.
