#!/usr/bin/env python3
"""Unattended run of the Gravity Rush opening: starts run.py with scripted input, taps the
touchpad through the apple scene once its first cutscene ended, lets the game run on and stops it.

Usage (MSYS2 CLANG64, from the port folder):
  GOW3_GAME_DIR=... python scripts/gr_autotest.py logs/gr_autoN.txt [seconds after the taps, default 60]
  --plain: no apple scene expected (a save is loaded, ...): run that many seconds in all, then stop.
Extra environment (GOW3_AUDIO_TRACE=1, ...) goes through to the game.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

PORT = Path(__file__).resolve().parent.parent


def main():
    plain = '--plain' in sys.argv   # just run for the given seconds (no apple scene expected)
    argv = [a for a in sys.argv if a != '--plain']
    log = Path(argv[1])
    after = float(argv[2]) if len(argv) > 2 else 60.0
    log.parent.mkdir(parents=True, exist_ok=True)
    pad = PORT / 'logs' / 'autotest_pad.txt'
    pad.write_text('')
    env = dict(os.environ, GOW3_PAD_FILE=str(pad))
    with open(log, 'wb') as out:
        game = subprocess.Popen([sys.executable, str(PORT / 'run.py')], cwd=PORT, env=env, stdout=out,
                                stderr=subprocess.STDOUT)
    started = time.time()
    stopped = False
    try:
        if plain:
            deadline = started + after
        else:
            # Wait for the end of the first cutscene (the apple then takes taps), at most 4 minutes.
            while game.poll() is None and b'DEMO END' not in log.read_bytes():
                if time.time() - started > 240:
                    print('autotest: no "DEMO END" within 4 minutes')
                    break
                time.sleep(0.5)
            time.sleep(3)
            # Separate taps: press and release, the file size tells the edits apart.
            for _ in range(30):
                if game.poll() is not None or b'touchCounter = 2' in log.read_bytes():
                    break
                pad.write_text('touchpad_left')
                time.sleep(0.25)
                pad.write_text('')
                time.sleep(0.6)
            deadline = time.time() + after
        while game.poll() is None and time.time() < deadline:
            time.sleep(1)
    finally:
        if game.poll() is None:
            stopped = True
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(game.pid)], capture_output=True)
            game.wait(30)
        pad.write_text('')
    code = game.poll()
    print(f'autotest: done after {time.time() - started:.0f} s, game exit code '
          f'{"stopped by the test" if code in (None, 1) and stopped else hex(code & 0xffffffff) if code is not None else "?"}, log {log}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
