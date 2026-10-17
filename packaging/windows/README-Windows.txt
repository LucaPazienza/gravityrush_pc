Gravity Rush Remastered (PS4) for PC (gravityrush_pc)
=====================================================

Work in progress: the game boots but does not get past the opening scene yet, and has no audio.

No game files are included. You need your own copy of Gravity Rush Remastered (PS4): CUSA01113,
either as an unpacked folder (eboot.bin, sce_module, sce_sys) or as a fake package (.pkg).

You need
- Windows 10 (1903 or newer) or Windows 11, 64-bit.
- A graphics card with Vulkan 1.3 and a current driver.

Start
1. Extract this folder anywhere, for example C:\Games\gravityrush-windows (not inside the zip).
2. Open "Gravity Rush Launcher.exe". If Windows shows "Windows protected your PC", click More info, then
   Run anyway (the program is not signed).
3. Game page:
   - Install from PKG: "Choose .pkg..." unpacks the game once next to the .pkg (progress bar;
     an interrupted unpack continues where it stopped), or
   - Game folder: Browse... to the folder with eboot.bin.
4. Press PLAY.

While playing
- Insert on the keyboard, or R3 + L2 on the controller, opens the port's menu (image,
  performance, overlay).
- Controller (DualSense, Xbox and others) and keyboard work; remap them on the Controls page.
- Touchpad: Tab (left side), Backspace (right side), the controller's View button, or hold the
  left mouse button over the window and drag.

Next time
- "Gravity Rush.exe" starts the game straight away with the saved settings (shortcut, Steam).
- Saves, shader cache and the log: user\ next to the executables (keep it when updating).
- Settings: gravityrush.ini next to the executables; launcher options in %APPDATA%\gravityrush-launcher.

If something goes wrong
- Black screen at start: Advanced > Clear shader cache, then start again.
- The game does not open: check the Log page, or send user\last_run.log with your report.

Online features (PSN) are not available: the game runs as a console that is not signed in.

This project is not affiliated with Sony Interactive Entertainment.
Gravity Rush is a trademark of Sony Interactive Entertainment.
Based on medievil_2019_pc_port and gow3_pc (GPL-2.0-or-later).
