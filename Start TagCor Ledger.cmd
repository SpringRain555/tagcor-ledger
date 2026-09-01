@echo off
rem One-click launcher. All logic lives in Launch.ps1 (UTF-8 with BOM).
rem This wrapper is ASCII-only on purpose: cmd.exe codepage handling is unreliable.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Launch.ps1" %*
