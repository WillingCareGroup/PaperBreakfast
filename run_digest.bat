@echo off
set PYTHONIOENCODING=utf-8
cd /d %~dp0
.venv\Scripts\python.exe main.py run-once >> logs\scheduler.log 2>&1
