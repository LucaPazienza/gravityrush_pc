# Gravity Rush — Native PC Port

<p align="center">
  <img src="https://picfiles.alphacoders.com/229/229663.png" alt="Kat and Dusty overlooking the floating city in Gravity Rush" width="800">
</p>

<p align="center">
  <em>A community project exploring a native PC port of Gravity Rush.</em>
</p>

## About

This project aims to bring **Gravity Rush Remastered** (PS4, CUSA01113) to PC as a native port,
using the God of War native-port project as its technical starting point. The goal is to
investigate what is needed to adapt the game's code and platform-specific systems for a native PC
environment while preserving its distinctive gravity-based gameplay and comic-inspired art direction.

There is no emulator: the game's original x86-64 executable runs directly on the PC's processor,
a runtime written for this port replaces the PS4 system libraries, and the graphics run on the
[shadPS4](https://github.com/shadps4-emu/shadPS4) video core, which translates the PS4 GPU commands
and shaders to Vulkan.

This is an early-stage community project. Features, compatibility, performance, and build
instructions will be documented as development progresses.

## Screenshots

<p align="center">
  <img src="https://picfiles.alphacoders.com/229/229602.jpg" alt="Kat and Dusty in a market in Gravity Rush" width="48%">
  <img src="https://images.pushsquare.com/screenshots/33344/900x.jpg" alt="Kat using her gravity powers in Gravity Rush" width="48%">
</p>

<p align="center">
  <img src="https://www.gamerclick.it/images/Anime_big/GravityRushRemastered/GravityRushRemastered5.jpg" alt="Kat overlooking the city in Gravity Rush Remastered" width="48%">
  <img src="https://images.pushsquare.com/screenshots/71727/large.jpg" alt="An industrial district in Gravity Rush Remastered" width="48%">
</p>

Images are hosted by their respective third-party websites and are included here as visual
references. All game assets and trademarks belong to their respective owners.

## Project Goals

- Explore a native PC implementation based on the existing God of War porting foundation.
- Investigate and implement the platform-specific systems required by Gravity Rush.
- Preserve the original gameplay, especially gravity shifting, traversal, and combat.
- Document technical findings, compatibility, and progress as the project develops.

These are project goals, not a statement that the features are already implemented.

## Current Status

**Status: Early Development — the game boots, but is not playable yet.**

What works today (tested on Windows 11 with an RTX 5070 Ti):

- The game boots, completes its initialization and runs the title flow (EULA, save data check).
- It draws in Vulkan and shows readable text (shadPS4 font library with FreeType).
- Controller (DualSense, Xbox and others, through SDL3) and keyboard. The touchpad is simulated:
  Tab (left side), Backspace (right side), the controller's View/Back button, or the left mouse
  button held over the window (drag for a swipe).
- Saving and loading; save backups before every start.
- In-game menu (Insert, or R3+L2): image, performance and the FPS overlay.

Known problems:

- The opening scene stops after the apple is tapped: the next cutscene never starts.
- No audio yet: the NGS2 sound library is a silent stand-in.
- Movies (AvPlayer) are untested.

### Roadmap

- [x] Initial research and project setup
- [x] Analyze the existing porting framework
- [x] Investigate Gravity Rush's engine and platform-specific systems
- [x] Establish a working native runtime (boot, title flow, graphics, text)
- [ ] Get past the opening scene
- [ ] Implement and test core game functionality
- [ ] Improve graphics, audio, input, and performance
- [ ] Document compatibility

Please do not assume the game is currently playable. This section will be updated as milestones are tested.

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

3. Run the game (or start the launcher with `Gravity Rush Launcher.cmd`):

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
| Launcher | `launcher/gravityrush_launcher.py` | Settings, PKG install, mods, controls and the play button |

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
- Also used: LibAtrac9, FFmpeg, FreeType, SDL3, Dear ImGui, sirit, magic_enum, miniz, xbyak,
  Vulkan Memory Allocator, FSR-Vulkan, MSYS2, LLVM, Pillow and cryptography.
- **Gravity Rush** — developed by Japan Studio and published by Sony Interactive Entertainment.
- Screenshot sources: Alpha Coders, Push Square, and GamerClick.

The inclusion of a project in this section does not imply endorsement or affiliation.

## License

GNU GPL v2 or later ([LICENSE](LICENSE)). Third-party components keep their own licenses.

## Disclaimer

This is an unofficial, community-driven project and is not affiliated with, endorsed by, or
sponsored by Sony Interactive Entertainment or Japan Studio. Gravity Rush and all related names,
characters, artwork, and other intellectual property belong to their respective owners.

This repository is intended for research, development, and game-preservation purposes. It does not
provide copyrighted game files. Users must obtain and use their own legally acquired copy of the game.
