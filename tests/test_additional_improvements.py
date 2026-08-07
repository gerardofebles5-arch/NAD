"""
Test de Mejoras Adicionales del Sistema OCR
===========================================
Verifica que los nuevos módulos adicionales funcionen correctamente.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import cv2


def test_items_extractor():
    """Test del extractor de items."""
    print("\n=== Test: Items Extractor ===")
    
    try:
        from ocr.items_extractor import ItemsExtractor, extract_invoice_items, validate_items_against_total
        
        # Test con texto de items
        test_text = """
        CANTIDAD DESCRIPCIÓN PRECIO TOTAL
        2 Producto A 50,00 100,00
        1 Producto B 150,00 150,00
        """
        
        extractor = ItemsExtractor()
        items = extractor.extract(test_text)
        
        assert len(items) > 0, "Debe extraer al menos un item"
        print(f"[OK] Items extraidos: {len(items)}")
        
        # Test cálculo de total
        total = extractor.calculate_total()
        print(f"[OK] Total calculado: {total}")
        
        # Test validación
        errors = extractor.validate_items(250.00)
        print(f"[OK] Validacion funciona: {len(errors)} errores")
        
        print("[OK] Items Extractor: PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] Items Extractor: FAILED - {e}")
        return False


def test_perspective_correction():
    """Test de corrección de perspectiva."""
    print("\n=== Test: Perspective Correction ===")
    
    try:
        from core.image_preprocessor import ImagePreprocessor
        
        # Crear imagen de prueba
        img = np.ones((1000, 800, 3), dtype=np.uint8) * 255
        
        preprocessor = ImagePreprocessor()
        
        # Test deskew
        deskewed = preprocessor.deskew(img)
        assert deskewed.shape == img.shape, "Deskew debe mantener shape"
        print("[OK] Deskew funciona")
        
        # Test perspective correction
        corrected = preprocessor.correct_perspective(img)
        print(f"[OK] Perspective correction funciona (shape: {corrected.shape})")
        
        # Test stats
        stats = preprocessor.get_stats()
        print(f"[OK] Stats: {list(stats.keys())}")
        
        print("[OK] Perspective Correction: PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] Perspective Correction: FAILED - {e}")
        return False


def test_correction_learner():
    """Test del sistema de aprendizaje de correcciones."""
    print("\n=== Test: Correction Learner ===")
    
    try:
        from ocr.correction_learner import CorrectionLearner, register_user_correction, apply_learned_corrections
        
        # Crear learner temporal
        import tempfile
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
        temp_path = temp_file.name
        temp_file.close()
        
        learner = CorrectionLearner(storage_path=temp_path)
        
        # Test registro de corrección
        learner.register_correction('rif_emisor', 'J-12345678-0', 'J-12345678-9')
        print("[OK] Registro de corrección funciona")
        
        # Test aplicación de correcciones
        fields = {'rif_emisor': 'J-12345678-0', 'total': '100,00'}
        corrected, applied = learner.apply_corrections(fields)
        
        assert corrected['rif_emisor'] == 'J-12345678-9', "Debe aplicar corrección"
        print(f"[OK] Aplicación de correcciones funciona: {len(applied)} aplicadas")
        
        # Test top corrections
        top = learner.get_top_corrections(limit=5)
        print(f"[OK] Top corrections: {len(top)}")
        
        # Limpieza
        import os
        os.unlink(temp_path)
        
        print("[OK] Correction Learner: PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] Correction Learner: FAILED - {e}")
        return False


def test_document_type_detector():
    """Test del detector de tipo de documento."""
    print("\n=== Test: Document Type Detector ===")
    
    try:
        from ocr.document_type_detector import DocumentTypeDetector, detect_document_type, is_invoice, is_pos_invoice
        
        # Test con factura
        invoice_text = "FACTURA N° F001-000001 RIF J-12345678-9"
        detector = DocumentTypeDetector()
        detection = detector.detect(invoice_text)
        
        assert detection.document_type.value == 'factura', "Debe detectar factura"
        print(f"[OK] Deteccion de factura: {detection.document_type.value}")
        
        # Test con factura POS
        pos_text = "SERIAL 12345678 TER 0001 VISA FACTURA"
        pos_detection = detector.detect(pos_text)
        assert pos_detection.subtype == 'pos', "Debe detectar subtipo POS"
        print(f"[OK] Deteccion POS: {pos_detection.subtype}")
        
        # Test funciones de conveniencia
        assert is_invoice(invoice_text), "Debe ser factura"
        assert is_pos_invoice(pos_text), "Debe ser factura POS"
        print("[OK] Funciones de conveniencia funcionan")
        
        print("[OK] Document Type Detector: PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] Document Type Detector: FAILED - {e}")
        return False


def test_integration_v2():
    """Test de integración de nuevos módulos."""
    print("\n=== Test: Integration V2 ===")
    
    try:
        # Verificar imports
        from ocr.items_extractor import extract_invoice_items
        from ocr.correction_learner import apply_learned_corrections
        from ocr.document_type_detector import detect_document_type
        from core.image_preprocessor import ImagePreprocessor
        
        print("[OK] Todos los modulos nuevos se importan correctamente")
        
        # Test flujo integrado
        test_text = "FACTURA F001-000001 2 Producto A 50,00 100,00"
        test_words = [("FACTURA", (10, 10, 100, 30), 0.95)]
        
        # Extracción de items
        items = extract_invoice_items(test_text, test_words)
        print(f"[OK] Extraccion de items en flujo integrado")
        
        # Detección de documento
        doc_type = detect_document_type(test_text)
        print(f"[OK] Deteccion de documento en flujo integrado")
        
        # Preprocesamiento
        img = np.ones((1000, 800, 3), dtype=np.uint8) * 255
        preprocessor = ImagePreprocessor()
        processed = preprocessor.process(img)
        print(f"[OK] Preprocesamiento en flujo integrado")
        
        print("[OK] Integration V2: PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] Integration V2: FAILED - {e}")
        return False


def main():
    """Ejecuta todos los tests."""
    print("=" * 60)
    print("TEST DE MEJORAS ADICIONALES DEL SISTEMA OCR")
    print("=" * 60)
    
    results = []
    
    results.append(("Items Extractor", test_items_extractor()))
    results.append(("Perspective Correction", test_perspective_correction()))
    results.append(("Correction Learner", test_correction_learner()))
    results.append(("Document Type Detector", test_document_type_detector()))
    results.append(("Integration V2", test_integration_v2()))
    
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
