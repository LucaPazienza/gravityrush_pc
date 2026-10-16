@echo off
rem Opens the Gravity Rush launcher (needs Python 3 with Pillow: pip install pillow).
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw -3 launcher\gravityrush_launcher.py) || (start "" pythonw launcher\gravityrush_launcher.py)
