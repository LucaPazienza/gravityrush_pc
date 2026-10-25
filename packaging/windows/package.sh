#!/usr/bin/env bash
# Builds dist/gravityrush-windows/ (and dist/GravityRush-PC-<version>-Windows.zip with its .sha256, the
# release assets the launcher's updater looks for; the version is VERSION in
# launcher/gravityrush_launcher.py): "Gravity Rush Launcher.exe" (frozen
# with PyInstaller so players need no Python), "Gravity Rush.exe" (plays with the saved settings), gravityrush-runtime.exe with the MSYS2 CLANG64 DLLs it needs,
# the preparation scripts and run.py. Run from an MSYS2 CLANG64 shell after `bash build.sh`.
# Freezing uses a Windows Python 3.10+ (python.org; WINPYTHON overrides) and a private venv in
# out/pyenv with PyInstaller. TAA and FSR 3.1 are built in; DLSS ships when
# packaging/windows/build_dlss.sh has put gow3_dlss.dll and NVIDIA's nvngx_dlss.dll in out/ (with
# NVIDIA's license), so players need nothing else. The FSR 4 assets are not packaged.
set -euo pipefail
cd -- "$(dirname -- "$0")/../.."
source ./msys2-env.sh
[[ -f out/gravityrush-runtime.exe && -f out/gravityrush-gpu-check.exe && -f out/gravityrush-play.exe ]] || { echo 'Build first: bash build.sh' >&2; exit 1; }

# A Windows Python (not MSYS2's) for PyInstaller: the MSYS2 ones build a venv PyInstaller cannot
# freeze for Windows.
python=${WINPYTHON:-}
if [[ -z $python ]]; then
    for candidate in $(which -a py.exe python.exe 2>/dev/null); do
        case $candidate in /clang64/*|/usr/*|/mingw*|/ucrt64/*) continue ;; esac
        python=$candidate; break
    done
fi
if [[ -z $python ]]; then  # MSYS2 login shells drop Windows' PATH: the usual install folders
    local_app=$(cygpath -u "${LOCALAPPDATA:-C:/Users/$(id -un)/AppData/Local}")
    for candidate in /c/Windows/py.exe "$local_app"/Python/*/python.exe "$local_app"/Programs/Python/*/python.exe \
                     /c/Python3*/python.exe; do
        [[ -x $candidate ]] && { python=$candidate; break; }
    done
fi
[[ -n $python ]] || { echo 'Need a Windows Python 3 (python.org) or WINPYTHON=path\to\python.exe' >&2; exit 1; }
# Windows Python needs USERPROFILE (some MSYS2 shells start without it).
export USERPROFILE=${USERPROFILE:-$(cygpath -w "/c/Users/$(id -un)")}
if [[ -d out/pyenv && ! -x out/pyenv/Scripts/python.exe ]]; then rm -rf out/pyenv; fi  # an MSYS2-made venv
if [[ ! -x out/pyenv/Scripts/python.exe ]]; then
    "$python" -m venv out/pyenv
fi
# cryptography: the classic launcher's imports; Pillow: the launcher's drawing and icons; fontTools: the
# keyboard and mouse prompt font (scripts/gr_prompt_font.py).
out/pyenv/Scripts/python.exe -m pip install -q --disable-pip-version-check pyinstaller cryptography pillow fonttools
# The scripts run inside "Gravity Rush Launcher.exe" (--script): the standard modules they import come along.
hidden=()
for module in argparse base64 collections hashlib json re shutil struct tempfile xml.etree.ElementTree \
              urllib.request ctypes.wintypes zlib hmac game_profiles \
              graphics_options prepare link_libc link_modules mods patches save_backup content_profile gr_prompt_font lzma \
              cryptography.hazmat.primitives.ciphers PIL.Image PIL.ImageTk PIL.ImageDraw PIL.ImageFont \
              PIL.ImageFilter launcher_ui; do
    hidden+=(--hidden-import "$module")
done
out/pyenv/Scripts/python.exe -m PyInstaller --noconfirm --clean --log-level WARN --windowed \
    --name "Gravity Rush Launcher" --icon "$(cygpath -w "$PWD/launcher/gravityrush.ico")" --collect-submodules cryptography --collect-submodules fontTools --distpath out/pyi-dist \
    --workpath out/pyi-work --specpath out/pyi-work --paths "$(cygpath -w "$PWD/scripts")" --paths "$(cygpath -w "$PWD/launcher")" "${hidden[@]}" \
    "$(cygpath -w "$PWD/launcher/gravityrush_launcher.py")"

# The package is assembled in a fresh staging folder and zipped from there; dist/gow3-windows
# (a playable copy that may hold saves and settings) is only refreshed afterwards.
dest=out/stage/gravityrush-windows
rm -rf -- out/stage
mkdir -p "$dest/bin" "$dest/launcher"
cp -r "out/pyi-dist/Gravity Rush Launcher/." "$dest/"
llvm-strip -o "$dest/Gravity Rush.exe" out/gravityrush-play.exe
cp launcher/gravityrush.ico launcher/gravityrush.png launcher/gravityrush.bmp "$dest/launcher/"
# The launcher's font (OFL) and its background picture (when there is one); a player's own picture
# can go in launcher/assets.
[[ -f launcher/background.jpg ]] && cp launcher/background.jpg "$dest/launcher/"
mkdir -p "$dest/launcher/fonts" "$dest/launcher/assets"
cp launcher/fonts/Cabin.ttf launcher/fonts/OFL-Cabin.txt "$dest/launcher/fonts/"
# The executables without debug information (out/ keeps the symbols for crash reports).
for exe in gravityrush-runtime.exe gravityrush-gpu-check.exe; do
    llvm-strip --strip-debug -o "$dest/bin/$exe" "out/$exe"
done
# Every DLL the executables load from the CLANG64 tree (SDL3, FFmpeg, Vulkan loader, ...).
ldd "$dest/bin/gravityrush-runtime.exe" "$dest/bin/gravityrush-gpu-check.exe" |
    awk '/\/clang64\/bin\// {print $3}' | sort -u | while read -r dll; do
        cp -u "$dll" "$dest/bin/"
    done
cp -r scripts patches "$dest/"
# No package unpacker in releases: the player prepares the game folder with their own tools.
rm -f "$dest/scripts/pkg_extract.py" "$dest/scripts/pkg_keys.py"
cp run.py LICENSE README.md packaging/windows/README-Windows.txt "$dest/"
# DLSS: the MIT bridge (gpu/dlss_bridge) and NVIDIA's runtime, next to gravityrush-runtime.exe.
dlss=0
if [[ -f out/gow3_dlss.dll && -f out/nvngx_dlss.dll && -f out/NVIDIA-DLSS-LICENSE.txt ]]; then
    cp out/gow3_dlss.dll out/nvngx_dlss.dll "$dest/bin/"
    dlss=1
else
    echo 'DLSS not packaged (run packaging/windows/build_dlss.sh first)' >&2
fi
# The licenses of what ships with the port: every MSYS2 package a DLL comes from (its license files
# and a summary with version and license), and the Python parts frozen into the launcher.
licenses="$dest/THIRD-PARTY-LICENSES"
mkdir -p "$licenses"
{
    echo "Third-party components shipped with the Gravity Rush PC port."
    echo "DLLs in bin/ come from MSYS2 CLANG64 packages (sources: https://github.com/msys2/MINGW-packages"
    echo "and https://packages.msys2.org). Each package's license files are in the folder of its name."
    echo
    for dll in "$dest"/bin/*.dll; do
        pacman -Qqo "/clang64/bin/$(basename "$dll")" 2>/dev/null || true
    done | sort -u | while read -r pkg; do
        version=$(pacman -Q "$pkg" | cut -d' ' -f2)
        license=$(LC_ALL=C pacman -Qi "$pkg" | sed -n 's/^Licenses *: *//p')
        echo "$pkg $version: $license"
        { pacman -Qlq "$pkg" | grep '/share/licenses/.\+[^/]$' || true; } | while read -r file; do
            mkdir -p "$licenses/$pkg"
            cp "$file" "$licenses/$pkg/"
        done
    done
    echo
    echo "The launcher is frozen with PyInstaller (GPL with a bootloader exception) and contains Python"
    echo "(PSF License), Tcl/Tk (BSD-style), Pillow (MIT-CMU) and cryptography (Apache-2.0 / BSD)."
    echo "The launcher font Cabin is under the SIL Open Font License (launcher/fonts/OFL-Cabin.txt)."
    if [[ $dlss == 1 ]]; then
        echo
        echo "bin/nvngx_dlss.dll is NVIDIA DLSS, redistributed under the NVIDIA RTX SDKs license"
        echo "(NVIDIA-DLSS-LICENSE.txt); bin/gow3_dlss.dll is the port's bridge to it (MIT, gpu/dlss_bridge)."
    fi
} > "$licenses/README.txt"
[[ $dlss == 1 ]] && cp out/NVIDIA-DLSS-LICENSE.txt "$licenses/"
find "$dest" -name __pycache__ -prune -exec rm -r {} +
# No game files and nothing a player made (saves, shader caches built from the game's shaders,
# settings, logs) may ship: stop when one is found.
forbidden=$(find "$dest" \( -iname eboot.bin -o -iname sce_module -o -iname sce_sys -o -iname savedata \
    -o -iname user -o -iname cache -o -iname '*.log' -o -iname gravityrush.ini -o -iname settings.json \
    -o -iname mods.json -o -iname patches.json -o -iname fsr4_shaders \
    -o -iname '*.spv' -o -iname '*.pkg' -o -iname '*.sprx' -o -iname '*.prx' \) -print)
if [[ -n $forbidden ]]; then
    echo "Package holds files that must not ship:" >&2
    echo "$forbidden" >&2
    exit 1
fi
version=$(sed -n "s/^VERSION = '\([0-9.]*\)'.*/\1/p" launcher/gravityrush_launcher.py)
[[ -n $version ]] || { echo 'No VERSION in launcher/gravityrush_launcher.py' >&2; exit 1; }
zip_name="GravityRush-PC-$version-Windows.zip"
mkdir -p dist
rm -f dist/gravityrush-windows.zip "dist/$zip_name" "dist/$zip_name.sha256"
(cd out/stage && powershell -NoProfile -Command \
    "Compress-Archive -Path gravityrush-windows -DestinationPath ../../dist/$zip_name")
# The updater checks the download against this (and against GitHub's own digest of the asset).
(cd dist && sha256sum "$zip_name" | sed 's/ \*/  /' > "$zip_name.sha256")

# Refresh dist/gow3-windows, keeping what players create there (saves, settings, mods), and
# only while nothing runs from it: deleting a running launcher's files breaks it.
play=dist/gravityrush-windows
running=$(powershell -NoProfile -Command \
    "@(Get-Process | Where-Object { \$_.Path -like '$(cygpath -w "$PWD/$play")\\*' }).Count" | tr -d '\r')
if [[ ${running:-0} != 0 ]]; then
    echo "dist/gravityrush-windows is in use ($running processes): not refreshed; the zip is ready." >&2
else
    mkdir -p "$play"
    find "$play" -mindepth 1 -maxdepth 1 ! -name user ! -name mods ! -name gravityrush.ini \
        ! -name mods.json ! -name patches.json -exec rm -rf {} +
    cp -r "$dest/." "$play/"
fi
du -sh "$dest" "dist/$zip_name"
