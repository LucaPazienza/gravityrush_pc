#!/usr/bin/env bash
# Builds the two executables in the port folder itself: "Gravity Rush Launcher.exe" (the launcher,
# one file) and "Gravity Rush.exe" (packaging/windows/play.c: plays with the saved settings). They play from
# this tree (out/gravityrush-runtime.exe, your saves in user/, gravityrush.ini) and reads its font and
# background from launcher/. For the shareable package use packaging/windows/package.sh.
# Run from MSYS2 CLANG64 in the port folder: bash scripts/gr_build_launcher.sh
set -euo pipefail
cd "$(dirname "$0")/.."
# A Windows Python (the MSYS2 ones build a venv PyInstaller cannot freeze for Windows).
python=${WINPYTHON:-}
if [[ -z $python ]]; then
    for candidate in $(which -a py.exe python.exe 2>/dev/null); do
        case $candidate in /clang64/*|/usr/*|/mingw*|/ucrt64/*) continue ;; esac
        python=$candidate; break
    done
fi
if [[ -z $python ]]; then  # MSYS2 login shells drop Windows' PATH: the usual install folders
    for candidate in /c/Windows/py.exe "$(cygpath -u "${LOCALAPPDATA:-C:/Users/$(id -un)/AppData/Local}")"/Python/*/python.exe \
                     "$(cygpath -u "${LOCALAPPDATA:-C:/Users/$(id -un)/AppData/Local}")"/Programs/Python/*/python.exe; do
        [[ -x $candidate ]] && { python=$candidate; break; }
    done
fi
[[ -n $python ]] || { echo 'Need a Windows Python 3 (python.org) or WINPYTHON=path\to\python.exe' >&2; exit 1; }
if [[ -d out/pyenv && ! -x out/pyenv/Scripts/python.exe ]]; then rm -rf out/pyenv; fi  # an MSYS2-made venv
export USERPROFILE=${USERPROFILE:-$(cygpath -w "/c/Users/$(id -un)")}
if [[ ! -x out/pyenv/Scripts/python.exe ]]; then
    "$python" -m venv out/pyenv
fi
out/pyenv/Scripts/python.exe -m pip install -q --disable-pip-version-check pyinstaller cryptography pillow
# The scripts run inside GravityRush.exe (--run, --script): the modules they import come along.
hidden=()
for module in argparse base64 collections hashlib json re shutil struct tempfile xml.etree.ElementTree \
              urllib.request ctypes.wintypes zlib hmac pkg_extract pkg_keys game_profiles ue4_override \
              graphics_options prepare link_libc link_modules mods patches save_backup \
              cryptography.hazmat.primitives.ciphers PIL.Image PIL.ImageTk PIL.ImageDraw PIL.ImageFont \
              PIL.ImageFilter theme launcher_ui; do
    hidden+=(--hidden-import "$module")
done
out/pyenv/Scripts/python.exe -m PyInstaller --noconfirm --clean --log-level WARN --windowed --onefile \
    --name "Gravity Rush Launcher" --icon "$(cygpath -w "$PWD/launcher/gravityrush.ico")" --collect-submodules cryptography \
    --distpath "$(cygpath -w "$PWD")" --workpath out/pyi-work --specpath out/pyi-work \
    --paths "$(cygpath -w "$PWD/scripts")" --paths "$(cygpath -w "$PWD/launcher")" "${hidden[@]}" \
    "$(cygpath -w "$PWD/launcher/gravityrush_launcher.py")"
# Gravity Rush.exe: a small native program that runs the launcher with --play.
(cd packaging/windows && windres play.rc -O coff -o ../../out/play.res)
clang -O2 -municode -mwindows packaging/windows/play.c out/play.res -o "Gravity Rush.exe"
rm -f GravityRush.exe  # the old single executable
echo "Built $PWD/Gravity Rush Launcher.exe and $PWD/Gravity Rush.exe"
