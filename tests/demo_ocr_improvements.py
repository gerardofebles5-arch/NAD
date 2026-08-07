"""
Demo de Mejoras del Sistema OCR
================================
Demostración del pipeline OCR mejorado con los nuevos módulos.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import cv2


def create_test_invoice_image():
    """Crea una imagen de prueba simulando una factura."""
    # Crear imagen en blanco
    img = np.ones((1200, 800, 3), dtype=np.uint8) * 255
    
    # Añadir algo de ruido para simular imagen real
    noise = np.random.normal(0, 25, img.shape).astype(np.uint8)
    img = cv2.add(img, noise)
    
    # Añadir texto simulado (en una imagen real esto sería texto de factura)
    # Para demo, usaremos una imagen simple con patrones
    cv2.rectangle(img, (50, 50), (750, 150), (0, 0, 0), 2)
    
    return img


def demo_preprocessing():
    """Demo del preprocesamiento de imágenes."""
    print("\n" + "="*60)
    print("DEMO: Preprocesamiento de Imágenes")
    print("="*60)
    
    try:
        from core.image_preprocessor import ImagePreprocessor, PreprocessingLevel, InvoiceImageEnhancer
        
        # Crear imagen de prueba
        img = create_test_invoice_image()
        print(f"Imagen original: {img.shape}")
        
        # Test diferentes niveles
        for level in [PreprocessingLevel.BASIC, PreprocessingLevel.MEDIUM, PreprocessingLevel.AGGRESSIVE]:
            preprocessor = ImagePreprocessor(level=level)
            processed = preprocessor.process(img)
            stats = preprocessor.get_stats()
            print(f"\nNivel {level.value}:")
            print(f"  - Shape: {processed.shape}")
            print(f"  - Stats: {stats}")
        
        # Test enhancer especializado
        print("\nInvoiceImageEnhancer:")
        enhancer = InvoiceImageEnhancer()
        enhanced = enhancer.enhance_for_ocr(img)
        print(f"  - Shape: {enhanced.shape}")
        print(f"  - Mejora aplicada para OCR de facturas")
        
        print("\n✅ Preprocesamiento demo completado")
        
    except Exception as e:
        print(f"❌ Error en demo de preprocesamiento: {e}")


def demo_advanced_extraction():
    """Demo de extracción avanzada de campos."""
    print("\n" + "="*60)
    print("DEMO: Extracción Avanzada de Campos")
    print("="*60)
    
    try:
        from ocr.advanced_field_extractor import AdvancedFieldExtractor, extract_fields_advanced, validate_extracted_fields
        
        # Texto de ejemplo simulando OCR
        test_text = """
        FACTURA N° F001-000001
        RIF: J-12345678-9
        RAZÓN SOCIAL: EMPRESA DEMO C.A.
        FECHA: 15/08/2026
        DIRECCIÓN: AV. PRINCIPAL #123
        TELÉFONO: 0212-1234567
        BASE IMPONIBLE: 1.050,00
        IVA: 168,00
        TOTAL: 1.218,00
        CONDICIÓN DE PAGO: CONTADO
        """
        
        print("Texto de prueba:")
        print(test_text)
        
        # Extracción avanzada
        extractor = AdvancedFieldExtractor()
        fields = extractor.extract_all(test_text)
        
        print("\nCampos extraídos:")
        for key, value in fields.items():
            print(f"  - {key}: {value}")
        
        # Validación
        errors = validate_extracted_fields(fields)
        print(f"\nValidación: {len(errors)} errores")
        for field, field_errors in errors.items():
            print(f"  - {field}: {field_errors}")
        
        # Mostrar matches con metadatos
        matches = extractor.get_field_matches()
        print(f"\nTotal matches: {sum(len(m) for m in matches.values())}")
        
        print("\n✅ Extracción avanzada demo completado")
        
    except Exception as e:
        print(f"❌ Error en demo de extracción avanzada: {e}")


def demo_layout_detection():
    """Demo de detección de layout."""
    print("\n" + "="*60)
    print("DEMO: Detección de Layout")
    print("="*60)
    
    try:
        from ocr.layout_detector import LayoutDetector, detect_invoice_layout
        
        # Simular palabras OCR con coordenadas
        test_words = [
            # Header (top 25%)
            ("FACTURA", (50, 50, 150, 80), 0.95),
            ("F001-000001", (160, 50, 260, 80), 0.90),
            ("RIF", (50, 90, 100, 120), 0.95),
            ("J-12345678-9", (110, 90, 210, 120), 0.92),
            # Items (middle 45%)
            ("ITEM", (50, 350, 100, 380), 0.88),
            ("PRODUCTO", (110, 350, 200, 380), 0.85),
            # Totals (bottom 30%)
            ("TOTAL", (50, 850, 100, 880), 0.95),
            ("1.218,00", (110, 850, 200, 880), 0.90),
            # Footer
            ("CONTADO", (50, 1000, 120, 1030), 0.88),
        ]
        
        print(f"Palabras de prueba: {len(test_words)}")
        
        detector = LayoutDetector()
        regions = detector.detect(None, test_words)
        
        print("\nRegiones detectadas:")
        for region_name, region in regions.items():
            print(f"  - {region_name}:")
            print(f"    Tipo: {region.region_type.value}")
            print(f"    BBox: {region.bbox}")
            print(f"    Confianza: {region.confidence}")
            print(f"    Contenido: {region.content[:50]}...")
        
        layout_type = detector.get_layout_type()
        print(f"\nTipo de layout: {layout_type}")
        
        print("\n✅ Detección de layout demo completado")
        
    except Exception as e:
        print(f"❌ Error en demo de detección de layout: {e}")


def demo_ocr_correction():
    """Demo de corrección de errores OCR."""
    print("\n" + "="*60)
    print("DEMO: Corrección de Errores OCR")
    print("="*60)
    
    try:
        from ocr.ocr_corrector import OCRCorrector, ContextualCorrector, correct_ocr_fields
        
        # Campos con errores típicos de OCR
        test_fields = {
            'numero_factura': 'F0O1-OOOOO1',  # O en lugar de 0
            'rif_emisor': 'J-12345678-9',
            'fecha': '15/O8/2O26',  # O en lugar de 0
            'base_imponible': '1,05O,OO',  # O en lugar de 0
            'iva': '168,OO',
            'total': '1,218,OO',
        }
        
        print("Campos con errores OCR:")
        for key, value in test_fields.items():
            print(f"  - {key}: {value}")
        
        # Corrección básica
        print("\n--- Corrección Básica ---")
        corrector = OCRCorrector()
        corrected, corrections = corrector.correct_all_fields(test_fields)
        
        print("Campos corregidos:")
        for key, value in corrected.items():
            print(f"  - {key}: {value}")
        
        print(f"\nCorrecciones aplicadas: {len(corrections)}")
        for corr in corrections:
            print(f"  - {corr.field}: '{corr.original}' → '{corr.corrected}' ({corr.correction_type})")
        
        # Corrección contextual
        print("\n--- Corrección Contextual ---")
        contextual_corrector = ContextualCorrector()
        corrected_ctx, corrections_ctx = contextual_corrector.correct_with_context(test_fields)
        
        print("Campos corregidos (contextual):")
        for key, value in corrected_ctx.items():
            print(f"  - {key}: {value}")
        
        print(f"\nCorrecciones contextuales: {len(corrections_ctx)}")
        
        print("\n✅ Corrección de errores OCR demo completado")
        
    except Exception as e:
        print(f"❌ Error en demo de corrección OCR: {e}")


def demo_pos_detection():
    """Demo de detección de campos POS."""
    print("\n" + "="*60)
    print("DEMO: Detección de Campos POS")
    print("="*60)
    
    try:
        from ocr.pos_fields_detector import POSFieldsDetector, detect_pos_fields, is_pos_invoice
        
        # Texto POS de ejemplo
        test_text = """
        SERIAL: 12345678
        TER: 0001
        AFIL: 123456
        ADQUIRIENTE: 123456789012
        VISA ****1234
        AUTORIZACIÓN: 123456
        FECHA/HORA: 15-08-2026 14:30
        """
        
        print("Texto POS de prueba:")
        print(test_text)
        
        detector = POSFieldsDetector()
        
        # Detectar si es factura POS
        is_pos = detector.is_pos_invoice(test_text)
        print(f"\n¿Es factura POS? {is_pos}")
        
        # Extraer campos POS
        pos_fields = detector.detect(test_text)
        
        print("\nCampos POS detectados:")
        for key, value in pos_fields.items():
            print(f"  - {key}: {value}")
        
        # Detección de info de tarjeta
        card_info = detector.detect_card_info(test_text)
        print("\nInformación de tarjeta:")
        for key, value in card_info.items():
            print(f"  - {key}: {value}")
        
        print("\n✅ Detección de campos POS demo completado")
        
    except Exception as e:
        print(f"❌ Error en demo de detección POS: {e}")


def demo_full_pipeline():
    """Demo del pipeline completo integrado."""
    print("\n" + "="*60)
    print("DEMO: Pipeline Completo Integrado")
    print("="*60)
    
    try:
        from core.image_preprocessor import enhance_invoice_for_ocr
        from ocr.advanced_field_extractor import extract_fields_advanced
        from ocr.layout_detector import extract_fields_by_layout
        from ocr.ocr_corrector import correct_ocr_fields
        from ocr.pos_fields_detector import detect_pos_fields, is_pos_invoice
        
        # Simular datos de entrada
        img = create_test_invoice_image()
        test_words = [
            ("FACTURA", (50, 50, 150, 80), 0.95),
            ("F001-000001", (160, 50, 260, 80), 0.90),
            ("RIF", (50, 90, 100, 120), 0.95),
            ("J-12345678-9", (110, 90, 210, 120), 0.92),
            ("TOTAL", (50, 850, 100, 880), 0.95),
            ("1,218,00", (110, 850, 200, 880), 0.90),
        ]
        test_text = "FACTURA F001-000001 RIF J-12345678-9 TOTAL 1,218,00"
        
        print("Pipeline OCR Mejorado:")
        print("1. Preprocesamiento de imagen")
        enhanced_img = enhance_invoice_for_ocr(img)
        print(f"   ✓ Imagen mejorada: {enhanced_img.shape}")
        
        print("\n2. Extracción avanzada de campos")
        fields = extract_fields_advanced(test_text, test_words)
        print(f"   ✓ Campos extraídos: {list(fields.keys())}")
        
        print("\n3. Detección de layout")
        layout_fields = extract_fields_by_layout(test_words)
        print(f"   ✓ Campos por layout: {list(layout_fields.keys())}")
        
        print("\n4. Detección POS")
        if is_pos_invoice(test_text):
            pos_fields = detect_pos_fields(test_text)
            print(f"   ✓ Campos POS: {list(pos_fields.keys())}")
        else:
            print("   - No es factura POS")
        
        print("\n5. Corrección de errores OCR")
        corrected, corrections = correct_ocr_fields(fields)
        print(f"   ✓ {len(corrections)} correcciones aplicadas")
        
        print("\nResultado final:")
        for key, value in corrected.items():
            print(f"  - {key}: {value}")
        
        print("\n✅ Pipeline completo demo completado")
        
    except Exception as e:
        print(f"❌ Error en demo de pipeline completo: {e}")


def main():
    """Ejecuta todas las demos."""
    print("="*60)
    print("DEMO DE MEJORAS DEL SISTEMA OCR")
    print("="*60)
    
    demos = [
        demo_preprocessing,
        demo_advanced_extraction,
        demo_layout_detection,
        demo_ocr_correction,
        demo_pos_detection,
        demo_full_pipeline,
    ]
    
    for demo in demos:
        try:
            demo()
        except Exception as e:
            print(f"Error en {demo.__name__}: {e}")
    
    print("\n" + "="*60)
    print("DEMO COMPLETADA")
    print("="*60)


if __name__ == "__main__":
    main()
