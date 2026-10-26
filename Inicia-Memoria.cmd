@echo off
title Memoria - Cataleg local
cd /d "%~dp0"
python "%~dp0app.py"
if errorlevel 1 pause
