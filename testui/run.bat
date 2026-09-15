@echo off
REM Test harness for the Smart Filter API - not part of the service itself.
REM
REM It borrows a venv that already has tools_factory, emt_client, fastapi and
REM uvicorn installed. Override either path if your checkouts live elsewhere:
REM   set PYTHON=...\.venv\Scripts\python.exe
REM   set TOOLS_DIR=...\EMT_TOOLS_ECOSYSTEM
cd /d "%~dp0"
if "%PYTHON%"=="" set PYTHON=%~dp0..\..\emt-chatbot\.venv\Scripts\python.exe
"%PYTHON%" -m uvicorn app:app --reload --port 8600
