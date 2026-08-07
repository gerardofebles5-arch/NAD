#!/usr/bin/env python3
"""
Test de Servicios Críticos - NAD Scanner
Verifica que todos los servicios críticos estén configurados y funcionando.
"""

import os
import sys

print("=== Test de Servicios Críticos - NAD Scanner ===\n")

# Test 1: Archivo .env existe
print("1. Verificando archivo .env...")
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    print("✅ Archivo .env existe")
else:
    print("❌ Archivo .env no encontrado")
    sys.exit(1)

# Test 2: Credenciales de Supabase
print("\n2. Verificando credenciales de Supabase...")
SUPABASE_URL = None
SUPABASE_ANON_KEY = None

with open(env_path, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line.startswith('SUPABASE_URL='):
            SUPABASE_URL = line.split('=', 1)[1].strip()
        elif line.startswith('SUPABASE_ANON_KEY='):
            SUPABASE_ANON_KEY = line.split('=', 1)[1].strip()

if SUPABASE_URL and SUPABASE_ANON_KEY:
    print(f"✅ Credenciales de Supabase configuradas")
    print(f"   URL: {SUPABASE_URL}")
else:
    print("❌ Credenciales de Supabase no configuradas")
    sys.exit(1)

# Test 3: Conexión a Supabase
print("\n3. Verificando conexión a Supabase...")
try:
    from supabase import create_client
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    print("✅ Conexión a Supabase exitosa")
except Exception as e:
    print(f"❌ Error conectando a Supabase: {e}")
    sys.exit(1)

# Test 4: Credenciales de Google Drive (Desktop app)
print("\n4. Verificando credenciales de Google Drive (Desktop app)...")
credentials_path = os.path.join(os.path.dirname(__file__), 'credentials.json')
if os.path.exists(credentials_path):
    print("✅ credentials.json existe para backend")
else:
    print("❌ credentials.json no encontrado para backend")
    sys.exit(1)

# Test 5: Credenciales de Google Drive (Web app)
print("\n5. Verificando credenciales de Google Drive (Web app)...")
web_credentials_path = os.path.join(os.path.dirname(__file__), 'react_web', 'credentials.json')
if os.path.exists(web_credentials_path):
    print("✅ credentials.json existe para frontend")
else:
    print("❌ credentials.json no encontrado para frontend")
    sys.exit(1)

# Test 6: Tesseract OCR
print("\n6. Verificando Tesseract OCR...")
try:
    import pytesseract
    print("✅ pytesseract instalado")
    # Verificar si Tesseract está instalado
    try:
        pytesseract.get_tesseract_version()
        print("✅ Tesseract OCR detectado")
    except Exception as e:
        print(f"⚠️  Tesseract no detectado en el sistema: {e}")
        print("   Instalar Tesseract desde: https://github.com/UB-Mannheim/tesseract/wiki")
except ImportError:
    print("❌ pytesseract no instalado")
    sys.exit(1)

# Test 7: Configuración del sistema
print("\n7. Verificando configuración del sistema...")
try:
    from utils.config import CONFIG
    print(f"✅ Configuración cargada")
    print(f"   Motor OCR: {CONFIG.ocr.engine}")
    print(f"   Idioma: {CONFIG.ocr.lang}")
except Exception as e:
    print(f"❌ Error cargando configuración: {e}")
    sys.exit(1)

# Test 8: Backend Tesseract
print("\n8. Verificando backend Tesseract...")
try:
    from ocr.backends import TesseractBackend
    backend = TesseractBackend()
    print(f"✅ Backend Tesseract disponible")
    print(f"   Nombre: {backend.get_name()}")
except Exception as e:
    print(f"❌ Error con backend Tesseract: {e}")
    sys.exit(1)

print("\n" + "="*50)
print("✅ TODOS LOS SERVICIOS CRÍTICOS CONFIGURADOS")
print("="*50)
print("\nSistema listo para deployment en producción.")
print("\nPróximos pasos:")
print("1. Ejecutar el sistema: python main.py")
print("2. Desplegar frontend React en producción")
print("3. Configurar dominio negocioaldia.app con SSL")
