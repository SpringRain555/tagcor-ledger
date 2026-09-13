@echo off
rem One-click launcher. All logic lives in tools\Launch.ps1 (UTF-8 with BOM).
rem This wrapper is ASCII-only on purpose: cmd.exe codepage handling is unreliable.
rem Named start_<slug>.cmd per D:\Projects CONVENTIONS section 16.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Launch.ps1" %*
