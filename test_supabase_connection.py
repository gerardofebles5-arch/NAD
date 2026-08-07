#!/usr/bin/env python3
"""
Test de conexión a Supabase - NAD Scanner
Verifica que las credenciales funcionen y las tablas estén creadas.
"""

import os
import sys

# Leer directamente el archivo .env para evitar conflictos con variables de entorno del sistema
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, '.env')

print(f"Leyendo .env desde: {env_path}")
print(f"Archivo existe: {os.path.exists(env_path)}")

SUPABASE_URL = None
SUPABASE_ANON_KEY = None

if os.path.exists(env_path):
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line.startswith('SUPABASE_URL='):
                SUPABASE_URL = line.split('=', 1)[1].strip()
            elif line.startswith('SUPABASE_ANON_KEY='):
                SUPABASE_ANON_KEY = line.split('=', 1)[1].strip()
else:
    print("❌ Error: Archivo .env no encontrado")
    sys.exit(1)

print("=== Test de Conexión Supabase ===")
print(f"URL: {SUPABASE_URL}")
print(f"Key: {SUPABASE_ANON_KEY[:20]}..." if SUPABASE_ANON_KEY else "Key: No configurada")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    print("❌ Error: Credenciales de Supabase no configuradas en .env")
    exit(1)

try:
    from supabase import create_client
    
    # Crear cliente
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    print("✅ Cliente Supabase creado exitosamente")
    
    # Verificar tablas
    tablas_esperadas = ['clientes', 'facturas', 'correcciones_ocr', 'alertas_tasa_cambio', 'estados_financieros']
    
    for tabla in tablas_esperadas:
        try:
            # Intentar consultar la tabla (limit 0 para no traer datos)
            result = client.table(tabla).select('*').limit(0).execute()
            print(f"✅ Tabla '{tabla}' existe y es accesible")
        except Exception as e:
            print(f"❌ Error accediendo a tabla '{tabla}': {e}")
    
    print("\n✅ Conexión a Supabase verificada exitosamente")
    
except ImportError:
    print("❌ Error: supabase package no instalado")
    print("   Ejecutar: pip install supabase")
except Exception as e:
    print(f"❌ Error conectando a Supabase: {e}")
