@echo off
chcp 65001 >nul
title Remote PC — Agent

cd /d "%~dp0"

echo ============================================
echo   Remote PC Control — Agent
echo ============================================
echo.

REM Cek apakah file .env ada
if not exist ".env" (
    echo [ERROR] File .env tidak ditemukan.
    echo         Salin .env.example menjadi .env dan isi nilainya.
    echo.
    pause
    exit /b 1
)

REM Cek apakah Python tersedia
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python tidak ditemukan. Pastikan Python sudah terinstall
    echo         dan sudah ditambahkan ke PATH.
    echo.
    pause
    exit /b 1
)

echo Memulai agent...
echo Tekan Ctrl+C untuk menghentikan.
echo.

python agent.py

echo.
echo Agent berhenti.
pause
