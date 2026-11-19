@echo off
rem Run dev.ps1 from cmd.exe, e.g.  scripts\dev.cmd   or   scripts\dev.cmd -Worker   or   scripts\dev.cmd -Stop
rem -ExecutionPolicy Bypass applies to this one run only; it changes no system setting.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev.ps1" %*
