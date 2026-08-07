"""
Test de Mejoras V3 del Sistema OCR
==================================
Verifica que los módulos v3 funcionen correctamente.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import time


def test_rif_validator():
    """Test del validador de RIF."""
    print("\n=== Test: RIF Validator ===")
    
    try:
        from ocr.rif_validator import RIFValidator, validate_rif, normalize_rif, get_rif_type
        
        # Test validación de formato de RIF
        validator = RIFValidator()
        valid_rif = "J-12345678-9"
        validation = validator.validate(valid_rif)
        
        assert validation.is_valid_format, "Debe tener formato válido"
        print(f"[OK] Validacion de formato RIF: {validation.normalized_rif}")
        
        # Test normalización
        normalized = normalize_rif("J123456789")
        assert normalized == "J-12345678-9", "Debe normalizar correctamente"
        print(f"[OK] Normalizacion funciona: {normalized}")
        
        # Test tipo de RIF
        rif_type = get_rif_type("V-12345678-9")
        print(f"[OK] Tipo de RIF: {rif_type}")
        
        # Test RIF con formato inválido
        invalid_rif = "INVALID-RIF"
        invalid_validation = validator.validate(invalid_rif)
        assert not invalid_validation.is_valid_format, "Debe tener formato inválido"
        print(f"[OK] Deteccion de formato invalido funciona")
        
        print("[OK] RIF Validator: PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] RIF Validator: FAILED - {e}")
        return False


def test_ocr_cache():
    """Test del sistema de cache OCR."""
    print("\n=== Test: OCR Cache ===")
    
    try:
        from ocr.ocr_cache import OCRCache, cache_ocr_result, get_cached_ocr_result
        
        # Crear cache temporal
        import tempfile
        temp_dir = tempfile.mkdtemp()
        cache = OCRCache(cache_dir=temp_dir, ttl_hours=1)
        
        # Test cache miss
        test_image = b"test_image_data"
        result = cache.get(test_image)
        assert result is None, "Debe ser cache miss inicialmente"
        print("[OK] Cache miss funciona")
        
        # Test cache set
        test_result = {"fields": {"rif": "J-12345678-9"}, "confidence": 0.9}
        cache.set(test_image, test_result)
        print("[OK] Cache set funciona")
        
        # Test cache hit
        cached_result = cache.get(test_image)
        assert cached_result is not None, "Debe ser cache hit"
        assert cached_result["fields"]["rif"] == "J-12345678-9", "Debe retornar resultado correcto"
        print("[OK] Cache hit funciona")
        
        # Test estadísticas
        stats = cache.get_stats()
        assert stats['hits'] == 1, "Debe tener 1 hit"
        assert stats['misses'] == 1, "Debe tener 1 miss"
        print(f"[OK] Estadisticas: {stats}")
        
        # Limpieza
        cache.clear()
        import shutil
        shutil.rmtree(temp_dir)
        
        print("[OK] OCR Cache: PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] OCR Cache: FAILED - {e}")
        return False


def test_ocr_metrics():
    """Test del sistema de métricas OCR."""
    print("\n=== Test: OCR Metrics ===")
    
    try:
        from ocr.ocr_metrics import OCRMetrics, log_ocr_processing, QualityAnalyzer
        
        # Crear métricas temporales
        import tempfile
        temp_dir = tempfile.mkdtemp()
        metrics = OCRMetrics(log_dir=temp_dir)
        
        # Test logging de procesamiento
        test_result = {
            'ocr_confidence': 0.85,
            'numero_factura': 'F001-000001',
            'rif_emisor': 'J-12345678-9',
            'fecha': '15/08/2026',
            'total': '1000,00',
            'document_type': 'factura',
            'document_subtype': '',
            'preprocessing_applied': True,
            'corrections_applied': [],
            'validation_errors': [],
            'warnings': [],
            'validation_status': 'ok'
        }
        
        metrics.log_processing(test_result, processing_time_ms=1500)
        print("[OK] Logging de procesamiento funciona")
        
        # Test resumen
        summary = metrics.get_summary()
        assert summary['total_processings'] == 1, "Debe tener 1 procesamiento"
        assert summary['avg_confidence'] == 0.85, "Debe tener confianza promedio correcta"
        print(f"[OK] Resumen: {summary}")
        
        # Test análisis de calidad
        analyzer = QualityAnalyzer(metrics)
        quality = analyzer.analyze_quality()
        print(f"[OK] Analisis de calidad: {quality}")
        
        # Test tendencias
        # Agregar más métricas para tendencias
        for i in range(5):
            test_result['ocr_confidence'] = 0.8 + (i * 0.02)
            metrics.log_processing(test_result, processing_time_ms=1400 + (i * 100))
        
        trends = analyzer.get_trends(window=6)
        print(f"[OK] Tendencias: {trends}")
        
        # Limpieza
        metrics.clear_metrics()
        import shutil
        shutil.rmtree(temp_dir)
        
        print("[OK] OCR Metrics: PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] OCR Metrics: FAILED - {e}")
        return False


def test_integration_v3():
    """Test de integración de módulos v3."""
    print("\n=== Test: Integration V3 ===")
    
    try:
        # Verificar imports
        from ocr.rif_validator import validate_rif
        from ocr.ocr_cache import OCRCache
        from ocr.ocr_metrics import OCRMetrics
        
        print("[OK] Todos los modulos v3 se importan correctamente")
        
        # Test flujo integrado
        # Validar RIF
        rif_validation = validate_rif("J-12345678-9")
        print(f"[OK] Validacion de RIF en flujo integrado")
        
        # Cache
        import tempfile
        temp_dir = tempfile.mkdtemp()
        cache = OCRCache(cache_dir=temp_dir)
        cache.set(b"test", {"data": "test"})
        cached = cache.get(b"test")
        print(f"[OK] Cache en flujo integrado")
        
        # Métricas
        metrics = OCRMetrics(log_dir=temp_dir)
        metrics.log_processing({"ocr_confidence": 0.9}, 1000)
        print(f"[OK] Metricas en flujo integrado")
        
        # Limpieza
        cache.clear()
        metrics.clear_metrics()
        import shutil
        shutil.rmtree(temp_dir)
        
        print("[OK] Integration V3: PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] Integration V3: FAILED - {e}")
        return False


def main():
    """Ejecuta todos los tests."""
    print("=" * 60)
    print("TEST DE MEJORAS V3 DEL SISTEMA OCR")
    print("=" * 60)
    
    results = []
    
    results.append(("RIF Validator", test_rif_validator()))
    results.append(("OCR Cache", test_ocr_cache()))
    results.append(("OCR Metrics", test_ocr_metrics()))
    results.append(("Integration V3", test_integration_v3()))
    
    print("\n" + "=" * 60)
    print("RESUMEN DE TESTS")
    print("=" * 60)
    
    for test_name, passed in results:
        status = "[OK] PASSED" if passed else "[FAIL] FAILED"
        print(f"{test_name}: {status}")
    
    total = len(results)
    passed = sum(1 for _, p in results if p)
    
    print(f"\nTotal: {passed}/{total} tests pasaron")
    
    if passed == total:
        print("\n[SUCCESS] Todos los tests pasaron exitosamente!")
        return 0
    else:
        print(f"\n[WARNING] {total - passed} tests fallaron")
        return 1


if __name__ == "__main__":
    exit(main())
