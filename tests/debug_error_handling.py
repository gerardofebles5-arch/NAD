"""
Debug del Manejo de Errores en Módulos OCR
===========================================
Verifica que los módulos manejen correctamente los errores.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np


def test_error_handling():
    """Prueba el manejo de errores en los módulos."""
    print("=" * 60)
    print("DEBUG: Manejo de Errores en Módulos OCR")
    print("=" * 60)
    
    errors_found = []
    
    # 1. Test ImagePreprocessor con imagen inválida
    print("\n[1] Test ImagePreprocessor con imagen inválida...")
    try:
        from core.image_preprocessor import ImagePreprocessor
        preprocessor = ImagePreprocessor()
        
        # Test con None
        try:
            preprocessor.process(None)
            print("[WARN] No maneja imagen None")
            errors_found.append("ImagePreprocessor no maneja imagen None")
        except Exception as e:
            print(f"[OK] Maneja imagen None: {type(e).__name__}")
        
        # Test con array vacío
        try:
            preprocessor.process(np.array([]))
            print("[WARN] No maneja array vacío")
            errors_found.append("ImagePreprocessor no maneja array vacío")
        except Exception as e:
            print(f"[OK] Maneja array vacío: {type(e).__name__}")
            
    except Exception as e:
        print(f"[FAIL] Error en test ImagePreprocessor: {e}")
        errors_found.append(f"ImagePreprocessor: {e}")
    
    # 2. Test AdvancedFieldExtractor con texto vacío
    print("\n[2] Test AdvancedFieldExtractor con texto vacío...")
    try:
        from ocr.advanced_field_extractor import extract_fields_advanced
        
        fields = extract_fields_advanced("", [])
        if fields:
            print(f"[OK] Maneja texto vacío: {len(fields)} campos")
        else:
            print("[OK] Maneja texto vacío: sin campos")
            
    except Exception as e:
        print(f"[FAIL] Error en test AdvancedFieldExtractor: {e}")
        errors_found.append(f"AdvancedFieldExtractor: {e}")
    
    # 3. Test LayoutDetector con palabras vacías
    print("\n[3] Test LayoutDetector con palabras vacías...")
    try:
        from ocr.layout_detector import extract_fields_by_layout
        
        fields = extract_fields_by_layout([])
        if fields:
            print(f"[OK] Maneja palabras vacías: {len(fields)} campos")
        else:
            print("[OK] Maneja palabras vacías: sin campos")
            
    except Exception as e:
        print(f"[FAIL] Error en test LayoutDetector: {e}")
        errors_found.append(f"LayoutDetector: {e}")
    
    # 4. Test OCRCorrector con campos vacíos
    print("\n[4] Test OCRCorrector con campos vacíos...")
    try:
        from ocr.ocr_corrector import correct_ocr_fields
        
        corrected, corrections = correct_ocr_fields({})
        if corrected:
            print(f"[OK] Maneja campos vacíos: {len(corrected)} campos")
        else:
            print("[OK] Maneja campos vacíos: sin campos")
            
    except Exception as e:
        print(f"[FAIL] Error en test OCRCorrector: {e}")
        errors_found.append(f"OCRCorrector: {e}")
    
    # 5. Test ItemsExtractor con texto inválido
    print("\n[5] Test ItemsExtractor con texto inválido...")
    try:
        from ocr.items_extractor import extract_invoice_items
        
        items = extract_invoice_items("texto sin formato", [])
        if items:
            print(f"[OK] Maneja texto inválido: {len(items)} items")
        else:
            print("[OK] Maneja texto inválido: sin items")
            
    except Exception as e:
        print(f"[FAIL] Error en test ItemsExtractor: {e}")
        errors_found.append(f"ItemsExtractor: {e}")
    
    # 6. Test RIFValidator con RIF inválido
    print("\n[6] Test RIFValidator con RIF inválido...")
    try:
        from ocr.rif_validator import validate_rif
        
        validation = validate_rif("INVALID")
        if not validation.is_valid_format:
            print("[OK] Maneja RIF inválido correctamente")
        else:
            print("[WARN] No detecta RIF inválido")
            errors_found.append("RIFValidator no detecta RIF inválido")
            
    except Exception as e:
        print(f"[FAIL] Error en test RIFValidator: {e}")
        errors_found.append(f"RIFValidator: {e}")
    
    # 7. Test DocumentTypeDetector con texto vacío
    print("\n[7] Test DocumentTypeDetector con texto vacío...")
    try:
        from ocr.document_type_detector import detect_document_type
        
        detection = detect_document_type("")
        if detection.document_type.value == 'desconocido':
            print("[OK] Maneja texto vacío: documento desconocido")
        else:
            print(f"[WARN] Tipo detectado: {detection.document_type.value}")
            
    except Exception as e:
        print(f"[FAIL] Error en test DocumentTypeDetector: {e}")
        errors_found.append(f"DocumentTypeDetector: {e}")
    
    # 8. Test OCRCache con datos inválidos
    print("\n[8] Test OCRCache con datos inválidos...")
    try:
        from ocr.ocr_cache import OCRCache
        import tempfile
        
        temp_dir = tempfile.mkdtemp()
        cache = OCRCache(cache_dir=temp_dir)
        
        # Test con None
        result = cache.get(None)
        if result is None:
            print("[OK] Maneja imagen None")
        else:
            print("[WARN] No maneja imagen None")
            errors_found.append("OCRCache no maneja imagen None")
        
        # Limpieza
        cache.clear()
        import shutil
        shutil.rmtree(temp_dir)
            
    except Exception as e:
        print(f"[FAIL] Error en test OCRCache: {e}")
        errors_found.append(f"OCRCache: {e}")
    
    # 9. Test OCRMetrics con datos inválidos
    print("\n[9] Test OCRMetrics con datos inválidos...")
    try:
        from ocr.ocr_metrics import OCRMetrics
        import tempfile
        
        temp_dir = tempfile.mkdtemp()
        metrics = OCRMetrics(log_dir=temp_dir)
        
        # Test con resultado vacío
        metrics.log_processing({}, 0)
        print("[OK] Maneja resultado vacío")
        
        # Limpieza
        metrics.clear_metrics()
        import shutil
        shutil.rmtree(temp_dir)
            
    except Exception as e:
        print(f"[FAIL] Error en test OCRMetrics: {e}")
        errors_found.append(f"OCRMetrics: {e}")
    
    # Resumen
    print("\n" + "=" * 60)
    print("RESUMEN DE MANEJO DE ERRORES")
    print("=" * 60)
    
    if errors_found:
        print(f"\n[WARNING] Se encontraron {len(errors_found)} errores:")
        for error in errors_found:
            print(f"  - {error}")
        return False
    else:
        print("\n[SUCCESS] Todos los módulos manejan errores correctamente")
        return True


if __name__ == "__main__":
    success = test_error_handling()
    exit(0 if success else 1)
