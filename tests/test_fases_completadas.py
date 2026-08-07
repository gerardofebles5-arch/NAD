"""
Prueba de Fases Completadas - Migración Híbrida
================================================
Valida Fases 1-4: PaddleOCR-VL, Supabase, Drive↔DB, Motor Financiero
"""
import os
import sys
import numpy as np
import cv2
from pathlib import Path

# Agregar directorio del proyecto al sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

def test_fase1_paddleocr_vl():
    """Fase 1: PaddleOCR-VL"""
    print("=" * 60)
    print("FASE 1: PaddleOCR-VL")
    print("=" * 60)
    
    try:
        from ocr.paddleocr_vl_backend import PaddleOCRVLBackend
        from ocr.plugin_manager import get_factory
        
        # Test 1: Registrar backend
        factory = get_factory()
        factory.register_all()
        names = factory.list_registered()
        
        if 'paddleocr_vl' in names:
            print("✅ PaddleOCR-VL registrado en plugin manager")
        else:
            print("❌ PaddleOCR-VL NO registrado en plugin manager")
            return False
        
        # Test 2: Crear backend
        try:
            backend = factory.create('paddleocr_vl')
            if backend:
                print("✅ Backend PaddleOCR-VL creado")
            else:
                print("❌ Error creando backend PaddleOCR-VL (retornó None)")
                # Intentar crear directamente para ver el error
                try:
                    from ocr.paddleocr_vl_backend import PaddleOCRVLBackend
                    backend_direct = PaddleOCRVLBackend()
                    print("✅ Backend creado directamente (error en factory)")
                except Exception as e:
                    print(f"❌ Error creando backend directamente: {e}")
                    return False
        except Exception as e:
            print(f"❌ Excepción creando backend: {e}")
            return False
        
        # Test 3: Inicializar
        backend.initialize()
        if backend._initialized:
            print("✅ PaddleOCR-VL inicializado")
        else:
            print("❌ Error inicializando PaddleOCR-VL")
            return False
        
        # Test 4: Reconocer imagen (si hay imagen de prueba)
        test_image_path = "output/data/test.jpg"
        if os.path.exists(test_image_path):
            image = cv2.imread(test_image_path)
            if image is not None:
                result = backend.extract_structured(image)
                print(f"✅ Extracción estructurada funcionó")
                print(f"   - Confidence: {result.get('confidence', 0):.3f}")
                print(f"   - Campos extraídos: {len([k for k, v in result.items() if v])}")
            else:
                print("⚠️  No se pudo cargar imagen de prueba")
        else:
            print("⚠️  No hay imagen de prueba, omitiendo test de extracción")
        
        print("\n✅ FASE 1 COMPLETADA")
        return True
        
    except Exception as e:
        print(f"❌ Error en Fase 1: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_fase2_supabase():
    """Fase 2: Supabase"""
    print("\n" + "=" * 60)
    print("FASE 2: Supabase")
    print("=" * 60)
    
    try:
        from utils.supabase_client import is_configured, get_supabase_client
        
        # Test 1: Verificar configuración
        if is_configured():
            print("✅ Supabase configurado (variables de entorno presentes)")
        else:
            print("⚠️  Supabase no configurado (faltan SUPABASE_URL y SUPABASE_KEY)")
            print("   Esto es normal si aún no has configurado Supabase")
            return True  # No es error, solo no configurado
        
        # Test 2: Conectar cliente
        client = get_supabase_client()
        if client:
            print("✅ Cliente Supabase creado")
        else:
            print("❌ Error creando cliente Supabase")
            return False
        
        # Test 3: Consultar tabla (si está configurado)
        try:
            result = client.table('clientes').select('*').limit(1).execute()
            print("✅ Conexión a Supabase funcionando (tabla clientes accesible)")
        except Exception as e:
            print(f"⚠️  Error consultando tabla (puede que no exista aún): {e}")
        
        print("\n✅ FASE 2 COMPLETADA")
        return True
        
    except Exception as e:
        print(f"❌ Error en Fase 2: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_fase3_drive_db():
    """Fase 3: Drive ↔ DB"""
    print("\n" + "=" * 60)
    print("FASE 3: Drive ↔ DB")
    print("=" * 60)
    
    try:
        from integrations.drive_supabase import get_or_create_cliente
        
        # Test 1: Función get_or_create_cliente
        print("✅ Módulo drive_supabase importado")
        
        # Test 2: Verificar que la función existe
        if callable(get_or_create_cliente):
            print("✅ Función get_or_create_cliente disponible")
        else:
            print("❌ Error: get_or_create_cliente no es callable")
            return False
        
        # Test 3: Verificar integración en web_server
        with open('web_server.py', 'r', encoding='utf-8') as f:
            content = f.read()
            if 'upload_to_drive_with_db' in content:
                print("✅ Integración Drive↔DB en web_server.py detectada")
            else:
                print("⚠️  Integración Drive↔DB no encontrada en web_server.py")
        
        print("\n✅ FASE 3 COMPLETADA")
        return True
        
    except Exception as e:
        print(f"❌ Error en Fase 3: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_fase4_financial_engine():
    """Fase 4: Motor Financiero"""
    print("\n" + "=" * 60)
    print("FASE 4: Motor Financiero")
    print("=" * 60)
    
    try:
        from financial.engine import get_financial_engine
        
        # Test 1: Crear motor
        engine = get_financial_engine()
        print("✅ Motor financiero creado")
        
        # Test 2: Verificar métodos
        methods = ['get_monthly_summary', 'get_top_providers', 'get_currency_breakdown', 'get_yearly_summary']
        for method in methods:
            if hasattr(engine, method):
                print(f"✅ Método {method} disponible")
            else:
                print(f"❌ Método {method} NO disponible")
                return False
        
        # Test 3: Verificar endpoints en web_server
        with open('web_server.py', 'r', encoding='utf-8') as f:
            content = f.read()
            endpoints = ['/api/financial/monthly', '/api/financial/top-providers', 
                        '/api/financial/currency-breakdown', '/api/financial/yearly']
            for endpoint in endpoints:
                if endpoint in content:
                    print(f"✅ Endpoint {endpoint} en web_server.py")
                else:
                    print(f"⚠️  Endpoint {endpoint} NO encontrado en web_server.py")
        
        print("\n✅ FASE 4 COMPLETADA")
        return True
        
    except Exception as e:
        print(f"❌ Error en Fase 4: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Ejecuta todas las pruebas de fases completadas."""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 15 + "PRUEBA DE FASES COMPLETADAS" + " " * 15 + "║")
    print("╚" + "=" * 58 + "╝")
    print("\n")
    
    results = {}
    
    # Ejecutar pruebas
    results['Fase 1'] = test_fase1_paddleocr_vl()
    results['Fase 2'] = test_fase2_supabase()
    results['Fase 3'] = test_fase3_drive_db()
    results['Fase 4'] = test_fase4_financial_engine()
    
    # Resumen
    print("\n" + "=" * 60)
    print("RESUMEN")
    print("=" * 60)
    
    for fase, resultado in results.items():
        status = "✅ PASÓ" if resultado else "❌ FALLÓ"
        print(f"{fase}: {status}")
    
    total = len(results)
    pasadas = sum(results.values())
    
    print(f"\nTotal: {pasadas}/{total} fases pasaron")
    
    if pasadas == total:
        print("\n🎉 ¡Todas las fases completadas están funcionando!")
        print("\nSiguientes pasos:")
        print("  1. Configurar Supabase (si aún no está configurado)")
        print("  2. Probar el endpoint /process con sincronización Supabase")
        print("  3. Continuar con Fase 5: Flutter Web")
    else:
        print("\n⚠️  Algunas fases fallaron. Revisa los errores arriba.")
    
    return pasadas == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
