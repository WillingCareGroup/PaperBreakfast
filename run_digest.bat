@echo off
set PYTHONIOENCODING=utf-8
cd /d C:\Users\g_rid\Documents\Github\PaperBreakfast
.venv\Scripts\python.exe main.py fetch >> logs\scheduler.log 2>&1
.venv\Scripts\python.exe main.py digest >> logs\scheduler.log 2>&1
