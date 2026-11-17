@echo off
cd /d "%~dp0"
python start_agent_lab.py
if errorlevel 1 pause
