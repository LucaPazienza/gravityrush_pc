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

**Status: playable in development builds — the opening, the first episode and the city work,
with sound and saves. Not every part of the game has been tested yet.**

Tested on Windows 11 with an NVIDIA RTX 5070 Ti, an Xbox One controller and a DualSense.

What works today:

- **Boot and story:** title flow, the opening apple scene, the opening movie, episode 1 and the
  city of Hekseville; dialogue, menus and trophies.
- **Audio:** movies (AvPlayer) and the game's own sound engine on top of a real NGS2 sampler:
  PCM effects, ATRAC9 streamed music and ambience (wind, city), voice volume, pitch and panning,
  pause and resume, a mastering limiter, and a 7.1-to-stereo downmix for stereo devices.
- **Saves:** the save dialog, autosave, loading and manual saves; backups before every start.
- **Graphics:** Vulkan through the shadPS4 video core, readable text (font library with FreeType),
  borderless window by default (windowed and fullscreen in the settings).
- **Input:** controllers through SDL3 (Xbox, DualSense and others), keyboard and mouse.
  The touchpad works with real touch ids; the mouse acts as a finger (hold and drag for swipes).
  The **DualSense gyro** steers the gravity camera like on the PS4 (adjustable sensitivity).
- **Launcher:** a comic-book styled window with the game, video, controls, advanced and
  log pages, in English, Italian, French, German and Spanish. `Gravity Rush.exe` starts the game directly with the saved settings.
- **In-game menu** (Insert, or R3+L2): image options, performance and an FPS overlay.

Not done yet / known gaps:

- Audio effects that the game routes through NGS2 submixers (reverb sends, filters, envelopes)
  are not modelled: the dry sound plays.
- No systematic testing of later episodes, stability over long sessions, or performance.

### Roadmap

- [x] Native runtime: boot, title flow, graphics, text
- [x] Get past the opening scene
- [x] Audio: movies, effects, streamed music and ambience
- [x] Saves: load, autosave, manual save
- [x] Controller, touchpad and DualSense gyro
- [x] Launcher
- [ ] Play through the whole story and fix what breaks
- [ ] NGS2 effects (reverb, filters)
- [ ] Performance and stability work
- [ ] Release packages

## Requirements

- Windows 10 (1903 or newer) or Windows 11, 64-bit.
- A graphics card with Vulkan 1.3 and a current driver.
- Your own legally acquired copy of Gravity Rush Remastered (CUSA01113), as an unpacked folder
  (eboot.bin, sce_module, sce_sys) or a fake package (.pkg).

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
   $env:GOW3_GAME_DIR = 'D:\path\CUSA01113'   # or the .pkg
   python run.py
   ```

The loader stops at the first PS4 system function the runtime does not implement and names it.

| Part | Where | What it does |
|---|---|---|
| Loader | `src/probe.c` | Loads the image and starts the game's original code |
| Runtime | `src/runtime_*.c`, `src/gr_*.inc` | PS4 system functions |
| GPU and libraries | `gpu/shadps4/` | shadPS4 video core (Vulkan), font library and AvPlayer |
| Preparation | `scripts/` | Reads `eboot.bin`, links the game's `libc` and `libSceFios2` |
| Launcher | `launcher/gravityrush_launcher.py`, `launcher/launcher_ui.py` | Settings, PKG install, mods, controls and the play button |

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
