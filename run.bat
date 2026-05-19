@echo off
cd /d D:\Silverhand
call venv\Scripts\activate.bat
venv\Scripts\python.exe main.py
if %errorlevel% neq 0 pause