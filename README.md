# Gravity Rush Remastered (PS4) for PC

A work-in-progress native PC port of **Gravity Rush Remastered** (PlayStation 4, CUSA01113) for
Windows 10 and 11.

The CPU side is native: the game's original x86-64 executable runs directly on the PC's processor
and a runtime written for this port replaces the PS4 system libraries, so there is no emulator.
The graphics run on the [shadPS4](https://github.com/shadps4-emu/shadPS4) video core, which
translates the PS4 GPU commands and shaders to Vulkan.

> **No game files are included.** You need your own copy of Gravity Rush Remastered (CUSA01113),
> as an unpacked folder or a fake package (.pkg). This project is not affiliated with Sony
> Interactive Entertainment. Gravity Rush is a trademark of Sony Interactive Entertainment.

## Status

- Boots, completes initialization, draws the title flow and shows readable text (shadPS4 font
  library with FreeType).
- Controller (DualSense, Xbox and others, through SDL3) and keyboard. The touchpad is simulated:
  Tab (left side) and Backspace (right side), the controller's View/Back button, or the left mouse
  button held over the window (drag for a swipe).
- Saving and loading; save backups before every start.
- **In-game menu** (Insert, or R3+L2): image, performance and the FPS overlay.
- Online features (PSN) answer as a console that is not signed in.

### Known problems

- The opening scene does not advance past the first touch interaction.
- No audio yet: NGS2 is a silent renderer for now.
- Movies (AvPlayer) are untested.

## Building from source

1. Install [MSYS2](https://www.msys2.org) and, in the **MSYS2 CLANG64** shell, the packages listed
   in [packaging/windows/README.md](packaging/windows/README.md). Install
   [Python 3](https://www.python.org) with `pip install pillow cryptography`.
2. Build (newer CLANG64 toolchains need the standard headers forced for some third-party code):

   ```bash
   git clone --recursive https://github.com/LucaPazienza/gravityrush_pc
   cd gravityrush_pc
   CXXFLAGS="-include cstdlib -include cstdio -include cwchar -include cmath -include new" bash build.sh
   ```

3. Start the launcher with `Gravity Rush Launcher.cmd` (or `python launcher/gravityrush_launcher.py`),
   or the game directly:

   ```powershell
   $env:GOW3_GAME_DIR = 'D:\path\CUSA01113'   # or the .pkg
   python run.py
   ```

4. Package: `bash packaging/windows/package.sh` builds `dist/gravityrush-windows.zip`.

## How it works

| Part | Where | What it does |
|---|---|---|
| PKG install | `scripts/pkg_extract.py` | Unpacks fake PKGs (PFS, PFSC), as shadPS4 does |
| Game profiles | `scripts/game_profiles.py` | Modules to link and GPU defaults per title |
| Preparation | `scripts/` | Reads `eboot.bin`, links the game's `libc` and `libSceFios2` |
| Loader | `src/probe.c` | Loads the image and starts the game's original code |
| Runtime | `src/runtime_*.c` | PS4 system functions; `runtime_extra.c` and `src/gr_*.inc` hold the ones added for Gravity Rush |
| GPU and libraries | `gpu/shadps4/` | shadPS4 video core (Vulkan), font library and AvPlayer |
| Launcher | `launcher/gravityrush_launcher.py` | Settings, PKG install, mods, controls and the play button |

The loader stops at the first system function the runtime does not implement and names it;
`scripts/gen_import_names.py` adds a game's imports to the name table.

## Credits

- **bc160201983**: [medievil_2019_pc_port](https://github.com/bc160201983/medievil_2019_pc_port),
  the MediEvil port this project was forked from.
- **FelipePrado0**: [gow3_pc](https://github.com/FelipePrado0/gow3_pc) and
  **Waffle565**: [God-Of-War-Native-Port](https://github.com/Waffle565/God-Of-War-Native-Port),
  the God of War III native port both are built on, and its credits: **Supermedo** and
  **deadinside28** (bloodborne_pc), **cuesta4** (shadPS4 GPU fixes).
- **shadPS4 team**: the video core, font and AvPlayer libraries, the PKG format code used by
  `scripts/pkg_extract.py` and the NID name list (`tools/aerolib.inl`).
- Also used: LibAtrac9, FFmpeg, FreeType, SDL3, Dear ImGui, sirit, magic_enum, miniz, xbyak,
  Vulkan Memory Allocator, FSR-Vulkan, MSYS2, LLVM, Pillow and cryptography.

## License

GNU GPL v2 or later ([LICENSE](LICENSE)). Third-party components keep their own licenses.
