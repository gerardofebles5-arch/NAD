"""
Test de Mejoras del Sistema OCR
================================
Verifica que los nuevos módulos de mejora OCR funcionen correctamente.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import cv2


def test_image_preprocessor():
    """Test del módulo de preprocesamiento de imágenes."""
    print("\n=== Test: Image Preprocessor ===")
    
    try:
        from core.image_preprocessor import ImagePreprocessor, PreprocessingLevel, InvoiceImageEnhancer
        
        # Crear imagen de prueba
        test_image = np.random.randint(0, 255, (1000, 1000, 3), dtype=np.uint8)
        
        # Test básico
        preprocessor = ImagePreprocessor(level=PreprocessingLevel.MEDIUM)
        processed = preprocessor.process(test_image)
        
        assert processed.shape == test_image.shape, "Shape debe ser igual"
        print("✓ Preprocesamiento básico funciona")
        
        # Test enhancer
        enhancer = InvoiceImageEnhancer()
        enhanced = enhancer.enhance_for_ocr(test_image)
        
        assert enhanced.shape[0] >= test_image.shape[0], "Enhancer debe mantener o aumentar tamaño"
        print("✓ InvoiceImageEnhancer funciona")
        
        # Test stats
        stats = preprocessor.get_stats()
        assert 'denoise_applied' in stats, "Stats deben incluir denoise_applied"
        print("✓ Stats de preprocesamiento funcionan")
        
        print("✅ Image Preprocessor: PASSED")
        return True
    except Exception as e:
        print(f"❌ Image Preprocessor: FAILED - {e}")
        return False


def test_advanced_field_extractor():
    """Test del extractor avanzado de campos."""
    print("\n=== Test: Advanced Field Extractor ===")
    
    try:
        from ocr.advanced_field_extractor import AdvancedFieldExtractor, extract_fields_advanced, validate_extracted_fields
        
        # Test con texto de ejemplo
        test_text = """
        FACTURA N° F001-000001
        RIF: J-12345678-9
        FECHA: 15/08/2026
        TOTAL: 1.250,00
        IVA: 200,00
        BASE IMPONIBLE: 1.050,00
        """
        
        extractor = AdvancedFieldExtractor()
        fields = extractor.extract_all(test_text)
        
        assert 'numero_factura' in fields or 'total' in fields, "Debe extraer al menos algunos campos"
        print(f"✓ Campos extraídos: {list(fields.keys())}")
        
        # Test validación
        errors = validate_extracted_fields(fields)
        print(f"✓ Validación de campos funciona: {len(errors)} errores")
        
        print("✅ Advanced Field Extractor: PASSED")
        return True
    except Exception as e:
        print(f"❌ Advanced Field Extractor: FAILED - {e}")
        return False


def test_layout_detector():
    """Test del detector de layout."""
    print("\n=== Test: Layout Detector ===")
    
    try:
        from ocr.layout_detector import LayoutDetector, detect_invoice_layout
        
        # Test con palabras de ejemplo
        test_words = [
            ("FACTURA", (10, 10, 100, 30), 0.95),
            ("F001-000001", (110, 10, 200, 30), 0.90),
            ("TOTAL", (10, 700, 100, 720), 0.95),
            ("1.250,00", (110, 700, 200, 720), 0.90),
        ]
        
        detector = LayoutDetector()
        regions = detector.detect(None, test_words)
        
        assert len(regions) > 0, "Debe detectar al menos una región"
        print(f"✅ Regiones detectadas: {list(regions.keys())}")
        
        # Test tipo de layout
        layout_type = detector.get_layout_type()
        print(f"✓ Tipo de layout: {layout_type}")
        
        print("✅ Layout Detector: PASSED")
        return True
    except Exception as e:
        print(f"❌ Layout Detector: FAILED - {e}")
        return False


def test_ocr_corrector():
    """Test del corrector de errores OCR."""
    print("\n=== Test: OCR Corrector ===")
    
    try:
        from ocr.ocr_corrector import OCRCorrector, ContextualCorrector, correct_ocr_fields
        
        # Test con campos con errores típicos
        test_fields = {
            'numero_factura': 'F0O1-OOOOO1',  # O en lugar de 0
            'rif_emisor': 'J-12345678-9',
            'total': '1,25O,OO',  # O en lugar de 0
        }
        
        corrector = OCRCorrector()
        corrected, corrections = corrector.correct_all_fields(test_fields)
        
        assert len(corrected) == len(test_fields), "Debe corregir todos los campos"
        print(f"✓ Campos corregidos: {len(corrections)} correcciones")
        
        # Test con contexto
        contextual_corrector = ContextualCorrector()
        corrected_ctx, corrections_ctx = contextual_corrector.correct_with_context(test_fields)
        
        print(f"✓ Corrección contextual funciona")
        
        print("✅ OCR Corrector: PASSED")
        return True
    except Exception as e:
        print(f"❌ OCR Corrector: FAILED - {e}")
        return False


def test_pos_fields_detector():
    """Test del detector de campos POS."""
    print("\n=== Test: POS Fields Detector ===")
    
    try:
        from ocr.pos_fields_detector import POSFieldsDetector, detect_pos_fields, is_pos_invoice
        
        # Test con texto POS de ejemplo
        test_text = """
        SERIAL: 12345678
        TER: 0001
        AFIL: 123456
        VISA ****1234
        AUTORIZACIÓN: 123456
        """
        
        detector = POSFieldsDetector()
        fields = detector.detect(test_text)
        
        assert len(fields) > 0, "Debe detectar campos POS"
        print(f"✓ Campos POS detectados: {list(fields.keys())}")
        
        # Test detección de factura POS
        is_pos = detector.is_pos_invoice(test_text)
        assert is_pos, "Debe identificar como factura POS"
        print("✓ Detección de factura POS funciona")
        
        print("✅ POS Fields Detector: PASSED")
        return True
    except Exception as e:
        print(f"❌ POS Fields Detector: FAILED - {e}")
        return False


def test_integration():
    """Test de integración de todos los módulos."""
    print("\n=== Test: Integration ===")
    
    try:
        # Verificar que todos los módulos se pueden importar
        from core.image_preprocessor import enhance_invoice_for_ocr
        from ocr.advanced_field_extractor import extract_fields_advanced
        from ocr.layout_detector import extract_fields_by_layout
        from ocr.ocr_corrector import correct_ocr_fields
        from ocr.pos_fields_detector import detect_pos_fields
        
        print("✓ Todos los módulos se importan correctamente")
        
        # Test flujo completo con datos simulados
        test_image = np.random.randint(0, 255, (1000, 1000, 3), dtype=np.uint8)
        test_words = [
            ("FACTURA", (10, 10, 100, 30), 0.95),
            ("F001-000001", (110, 10, 200, 30), 0.90),
        ]
        test_text = "FACTURA F001-000001 RIF J-12345678-9"
        
        # Preprocesamiento
        enhanced = enhance_invoice_for_ocr(test_image)
        print("✓ Preprocesamiento en flujo integrado")
        
        # Extracción avanzada
        fields = extract_fields_advanced(test_text, test_words)
        print("✓ Extracción avanzada en flujo integrado")
        
        # Layout
        layout_fields = extract_fields_by_layout(test_words)
        print("✓ Layout en flujo integrado")
        
        # Corrección
        corrected, corrections = correct_ocr_fields(fields)
        print("✓ Corrección en flujo integrado")
        
        print("✅ Integration: PASSED")
        return True
    except Exception as e:
        print(f"❌ Integration: FAILED - {e}")
        return False


def main():
    """Ejecuta todos los tests."""
    print("=" * 60)
    print("TEST DE MEJORAS DEL SISTEMA OCR")
    print("=" * 60)
    
    results = []
    
    results.append(("Image Preprocessor", test_image_preprocessor()))
    results.append(("Advanced Field Extractor", test_advanced_field_extractor()))
    results.append(("Layout Detector", test_layout_detector()))
    results.append(("OCR Corrector", test_ocr_corrector()))
    results.append(("POS Fields Detector", test_pos_fields_detector()))
    results.append(("Integration", test_integration()))
    
    print("\n" + "=" * 60)
    print("RESUMEN DE TESTS")
    print("=" * 60)
    
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name}: {status}")
    
    total = len(results)
    passed = sum(1 for _, p in results if p)
    
    print(f"\nTotal: {passed}/{total} tests pasaron")
    
    if passed == total:
        print("\n🎉 Todos los tests pasaron exitosamente!")
        return 0
    else:
        print(f"\n⚠️ {total - passed} tests fallaron")
        return 1


if __name__ == "__main__":
    exit(main())
