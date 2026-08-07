"""
Debug de Performance de Módulos OCR
===================================
Verifica el rendimiento de los módulos OCR.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import time


def test_performance():
    """Prueba el rendimiento de los módulos."""
    print("=" * 60)
    print("DEBUG: Performance de Módulos OCR")
    print("=" * 60)
    
    # Datos de prueba
    test_image = np.random.randint(0, 255, (1000, 800, 3), dtype=np.uint8)
    test_words = [
        ("FACTURA", (50, 50, 150, 80), 0.95),
        ("F001-000001", (160, 50, 260, 80), 0.90),
        ("RIF", (50, 90, 100, 120), 0.95),
        ("J-12345678-9", (110, 90, 210, 120), 0.92),
        ("TOTAL", (50, 850, 100, 880), 0.95),
        ("1.218,00", (110, 850, 200, 880), 0.90),
    ]
    test_text = """
    FACTURA N° F001-000001
    RIF: J-12345678-9
    RAZÓN SOCIAL: EMPRESA DEMO C.A.
    FECHA: 15/08/2026
    BASE IMPONIBLE: 1.050,00
    IVA: 168,00
    TOTAL: 1.218,00
    """
    
    performance_results = {}
    
    # 1. Test ImagePreprocessor
    print("\n[1] Performance: ImagePreprocessor...")
    try:
        from core.image_preprocessor import ImagePreprocessor
        
        preprocessor = ImagePreprocessor()
        start = time.time()
        for _ in range(10):
            processed = preprocessor.process(test_image)
        elapsed = (time.time() - start) * 1000
        avg_time = elapsed / 10
        performance_results['ImagePreprocessor'] = avg_time
        print(f"[OK] Tiempo promedio: {avg_time:.2f}ms (10 iteraciones)")
        
    except Exception as e:
        print(f"[FAIL] Error: {e}")
    
    # 2. Test AdvancedFieldExtractor
    print("\n[2] Performance: AdvancedFieldExtractor...")
    try:
        from ocr.advanced_field_extractor import extract_fields_advanced
        
        start = time.time()
        for _ in range(100):
            fields = extract_fields_advanced(test_text, test_words)
        elapsed = (time.time() - start) * 1000
        avg_time = elapsed / 100
        performance_results['AdvancedFieldExtractor'] = avg_time
        print(f"[OK] Tiempo promedio: {avg_time:.2f}ms (100 iteraciones)")
        
    except Exception as e:
        print(f"[FAIL] Error: {e}")
    
    # 3. Test LayoutDetector
    print("\n[3] Performance: LayoutDetector...")
    try:
        from ocr.layout_detector import extract_fields_by_layout
        
        start = time.time()
        for _ in range(100):
            fields = extract_fields_by_layout(test_words)
        elapsed = (time.time() - start) * 1000
        avg_time = elapsed / 100
        performance_results['LayoutDetector'] = avg_time
        print(f"[OK] Tiempo promedio: {avg_time:.2f}ms (100 iteraciones)")
        
    except Exception as e:
        print(f"[FAIL] Error: {e}")
    
    # 4. Test OCRCorrector
    print("\n[4] Performance: OCRCorrector...")
    try:
        from ocr.ocr_corrector import correct_ocr_fields
        
        test_fields = {'numero_factura': 'F001-000001', 'total': '1.218,00'}
        start = time.time()
        for _ in range(100):
            corrected, corrections = correct_ocr_fields(test_fields)
        elapsed = (time.time() - start) * 1000
        avg_time = elapsed / 100
        performance_results['OCRCorrector'] = avg_time
        print(f"[OK] Tiempo promedio: {avg_time:.2f}ms (100 iteraciones)")
        
    except Exception as e:
        print(f"[FAIL] Error: {e}")
    
    # 5. Test ItemsExtractor
    print("\n[5] Performance: ItemsExtractor...")
    try:
        from ocr.items_extractor import extract_invoice_items
        
        start = time.time()
        for _ in range(100):
            items = extract_invoice_items(test_text, test_words)
        elapsed = (time.time() - start) * 1000
        avg_time = elapsed / 100
        performance_results['ItemsExtractor'] = avg_time
        print(f"[OK] Tiempo promedio: {avg_time:.2f}ms (100 iteraciones)")
        
    except Exception as e:
        print(f"[FAIL] Error: {e}")
    
    # 6. Test RIFValidator
    print("\n[6] Performance: RIFValidator...")
    try:
        from ocr.rif_validator import validate_rif
        
        start = time.time()
        for _ in range(1000):
            validation = validate_rif("J-12345678-9")
        elapsed = (time.time() - start) * 1000
        avg_time = elapsed / 1000
        performance_results['RIFValidator'] = avg_time
        print(f"[OK] Tiempo promedio: {avg_time:.2f}ms (1000 iteraciones)")
        
    except Exception as e:
        print(f"[FAIL] Error: {e}")
    
    # 7. Test DocumentTypeDetector
    print("\n[7] Performance: DocumentTypeDetector...")
    try:
        from ocr.document_type_detector import detect_document_type
        
        start = time.time()
        for _ in range(100):
            detection = detect_document_type(test_text)
        elapsed = (time.time() - start) * 1000
        avg_time = elapsed / 100
        performance_results['DocumentTypeDetector'] = avg_time
        print(f"[OK] Tiempo promedio: {avg_time:.2f}ms (100 iteraciones)")
        
    except Exception as e:
        print(f"[FAIL] Error: {e}")
    
    # 8. Test OCRCache
    print("\n[8] Performance: OCRCache...")
    try:
        from ocr.ocr_cache import OCRCache
        import tempfile
        
        temp_dir = tempfile.mkdtemp()
        cache = OCRCache(cache_dir=temp_dir)
        
        test_image_bytes = b"test_image_data"
        test_result = {"data": "test"}
        
        # Test set
        start = time.time()
        for _ in range(100):
            cache.set(test_image_bytes, test_result)
        elapsed = (time.time() - start) * 1000
        avg_time = elapsed / 100
        performance_results['OCRCache_set'] = avg_time
        print(f"[OK] Set tiempo promedio: {avg_time:.2f}ms (100 iteraciones)")
        
        # Test get
        start = time.time()
        for _ in range(100):
            result = cache.get(test_image_bytes)
        elapsed = (time.time() - start) * 1000
        avg_time = elapsed / 100
        performance_results['OCRCache_get'] = avg_time
        print(f"[OK] Get tiempo promedio: {avg_time:.2f}ms (100 iteraciones)")
        
        # Limpieza
        cache.clear()
        import shutil
        shutil.rmtree(temp_dir)
        
    except Exception as e:
        print(f"[FAIL] Error: {e}")
    
    # Resumen
    print("\n" + "=" * 60)
    print("RESUMEN DE PERFORMANCE")
    print("=" * 60)
    
    for module, time_ms in performance_results.items():
        status = "[OK]" if time_ms < 100 else "[SLOW]"
        print(f"{status} {module}: {time_ms:.2f}ms")
    
    total_time = sum(performance_results.values())
    print(f"\nTiempo total promedio: {total_time:.2f}ms")
    
    print("\n[SUCCESS] Performance de módulos revisada")
    return True


if __name__ == "__main__":
    success = test_performance()
    exit(0 if success else 1)
