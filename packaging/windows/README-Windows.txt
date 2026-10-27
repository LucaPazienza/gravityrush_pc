Gravity Rush Remastered (PS4) for PC - version 0.1.9
====================================================

A native PC port: the game's own code runs on your processor, with no emulator. The whole story
has been played from start to finish with this port. Only Nvidia graphics cards have been tested
so far.

No game files are included. You need your own copy of Gravity Rush Remastered (PS4), as an
unpacked game folder (eboot.bin, sce_module, sce_sys), prepared with your own tools.

This port is developed for the European release only: CUSA01113, version 01.00. Every fix and
enhancement is made and checked on that version. Other releases, such as the American one
(CUSA01130), may start and play, but none of the port's work on the game applies to them: the
render resolution stays at 1080p (no higher resolutions, no upscaling modes that render below the
screen), shadows stay at the game's quality, the gravity-shift camera may swing above 60 FPS (a
60 FPS limit avoids it), and the mouse turns the camera through the right stick instead of
directly.

You need
- Windows 10 (1903 or newer) or Windows 11, 64-bit.
- A graphics card with Vulkan 1.3 and a current driver.

Start
1. Extract this folder anywhere, for example C:\Games\gravityrush-windows (not inside the zip).
2. Open "Gravity Rush Launcher.exe". If Windows shows "Windows protected your PC", click More info,
   then Run anyway (the program is not signed).
3. Game page: Browse... to your game folder (the one with eboot.bin).
4. Press Play.

Graphics (Video page)
- Anti-aliasing: FXAA (the game's own, as on the PS4), TAA, FSR 3.1, DLSS (NVIDIA RTX) or off.
- With FSR 3.1 or DLSS, Mode: Native/DLAA, Quality, Balanced or Performance. Lower modes draw the
  game below your screen's size and enlarge it to the screen: more FPS, still sharp.
- With FXAA or TAA, Render resolution: from 540p to 4K. Above your screen's size it works as
  anti-aliasing; below it, "Simple upscaler" (FSR 1.0) enlarges it.
- Shadow quality: Standard (the game's 2048) or High (4096).
- Anisotropic filtering, window mode, refresh rate (fullscreen), vertical sync and FPS limit.

While playing
- Insert on the keyboard, or R3 + L2 on the controller, opens the port's menu (image, performance,
  FPS overlay).
- Controllers (DualSense, DualShock 4, Xbox and others), keyboard and mouse work. On the Controls
  page choose what you play with and remap every button (two keys or mouse buttons per button;
  L2 + R2, the gravity slide, on one key). The DualSense / DualShock 4 gyro aims the camera like
  on the PS4.
- Mouse look: the mouse turns the camera directly, by its DPI. The pointer stays in the game
  window while you play; the Insert menu or Alt+Tab frees it.
- Touchpad: Tab (left side), Backspace (right side) or the controller's View button. With mouse
  look switched off, holding the left mouse button over the window and dragging is a finger.
- Mods: on the Game page, switch mods on and choose their folder.

Next time
- "Gravity Rush.exe" starts the game straight away with the saved settings (shortcut, Steam).
- Updates: when a new version is out, the launcher offers it as it opens and installs it if you
  agree (it closes, replaces the program files and opens again; user\, gravityrush.ini and mods
  stay as they are). Advanced page: "Check for updates at start" turns this off.
- Saves, shader cache and logs: user\ next to the executables (keep it when updating).
- Settings: gravityrush.ini next to the executables; launcher options in %APPDATA%\gravityrush-launcher.

Reporting a problem
- Press F12 when you see it: the next frames are saved in user\screenshots, and the log notes where
  the game was. Send them with user\last_run.log and a few words on where you were in the game.
  (Advanced page: "F12 closes the game" also closes it right after, if you prefer.)
- Reports: https://github.com/LucaPazienza/gravityrush_pc/issues

Known issues
- Graphics glitches: press F12 when you see one and send the files.
- Online features (PSN) are not available: the game runs as a console that is not signed in.

If something goes wrong
- Black screen at start: Advanced > Clear shader cache, then start again.
- The game does not open: check the Log page, or send user\last_run.log with your report.

This project is not affiliated with Sony Interactive Entertainment. Gravity Rush is a trademark of
Sony Interactive Entertainment. Licensed under the GNU GPL v2 or later (LICENSE); third-party
licenses are in THIRD-PARTY-LICENSES. Based on medievil_2019_pc_port, the God of War III native port
(Waffle565/God-Of-War-Native-Port, FelipePrado0/gow3_pc) and the shadPS4 video core.
