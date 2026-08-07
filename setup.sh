#!/bin/bash
# ============================================================
# Script de Instalación del Sistema OCR NAD Scanner
# ============================================================
# Uso: bash setup.sh [dev|prod]
# Por defecto: dev

set -e

MODE=${1:-dev}
echo "Modo de instalación: $MODE"

# Verificar Python
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 no está instalado"
    exit 1
fi

echo "✓ Python 3 encontrado"

# Crear entorno virtual
if [ ! -d "venv" ]; then
    echo "Creando entorno virtual..."
    python3 -m venv venv
fi

echo "✓ Entorno virtual creado"

# Activar entorno virtual
source venv/bin/activate

# Actualizar pip
echo "Actualizando pip..."
pip install --upgrade pip

# Instalar dependencias
echo "Instalando dependencias..."
pip install -r requirements.txt

# Instalar Tesseract (Linux)
if [ "$MODE" = "prod" ]; then
    echo "Instalando Tesseract..."
    sudo apt-get update
    sudo apt-get install -y tesseract-ocr tesseract-ocr-spa poppler-utils
fi

# Crear directorios necesarios
echo "Creando directorios..."
mkdir -p output/queue
mkdir -p output/render
mkdir -p output/data
mkdir -p data
mkdir -p config
mkdir -p logs

# Copiar archivo .env de ejemplo si no existe
if [ ! -f ".env" ]; then
    echo "Creando archivo .env desde ejemplo..."
    cp .env.example .env
    echo "⚠️  Configura .env con tus credenciales reales"
fi

# Ejecutar tests
echo "Ejecutando tests..."
python tests/test_full_integration.py

echo ""
echo "✅ Instalación completada exitosamente"
echo ""
echo "Próximos pasos:"
echo "1. Configura el archivo .env con tus credenciales"
echo "2. Activa el entorno virtual: source venv/bin/activate"
echo "3. Ejecuta el sistema: python main.py"
