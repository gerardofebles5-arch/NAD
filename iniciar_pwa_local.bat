@echo off
title NAD Scanner - PWA Local
color 0B
cls

echo ============================================
echo     NAD Scanner - PWA Local
echo     Pruebas en red local
echo ============================================
echo.

:: Ir al directorio del script
cd /d "%~dp0"

:: Verificar Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   ERROR: Python no está instalado o no está en el PATH.
    pause
    exit /b 1
)

:: Activar entorno virtual si existe
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
    echo   [OK] Entorno virtual activado
) else (
    echo   [WARN] No hay entorno virtual, usando Python global
)

:: Verificar dependencias
echo   Verificando dependencias...
python -c "import flask" >nul 2>&1
if %errorlevel% neq 0 (
    echo   Instalando flask...
    pip install flask -q
)
python -c "import cryptography" >nul 2>&1
if %errorlevel% neq 0 (
    echo   Instalando cryptography...
    pip install cryptography -q
)

echo.
echo ============================================
echo  Iniciando servidor HTTPS en puerto 5000
echo ============================================
echo.
echo  PASOS EN EL TELÉFONO:
echo  ─────────────────────────────────────────
echo  1. Asegurese de que PC y teléfono están
echo     en la misma red WiFi
echo.
echo  2. Abra el navegador del teléfono y escriba:
echo     https://[SU-IP]:5000/pwa
echo.
echo  3. Si aparece advertencia de seguridad:
echo     Chrome:  "Avanzado" → "Proceder"
echo     Firefox: "Avanzado" → "Aceptar riesgo"
echo     Samsung: "Configuración" → "Continuar"
echo.
echo  4. La PWA cargará y podrá probar la cámara
echo ============================================
echo.

python web_server.py

pause
