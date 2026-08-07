"""
Debug del Pipeline OCR Completo
================================
Prueba el pipeline OCR completo con datos simulados.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import time


def test_full_pipeline():
    """Prueba el pipeline OCR completo."""
    print("=" * 60)
    print("DEBUG: Pipeline OCR Completo")
    print("=" * 60)
    
    try:
        # 1. Importar módulos
        print("\n[1] Importando módulos...")
        from core.image_preprocessor import ImagePreprocessor, enhance_invoice_for_ocr
        from ocr.advanced_field_extractor import extract_fields_advanced
        from ocr.layout_detector import extract_fields_by_layout
        from ocr.ocr_corrector import correct_ocr_fields
        from ocr.pos_fields_detector import detect_pos_fields, is_pos_invoice
        from ocr.items_extractor import extract_invoice_items
        from ocr.correction_learner import apply_learned_corrections
        from ocr.document_type_detector import detect_document_type
        from ocr.rif_validator import validate_rif
        print("[OK] Todos los módulos importados")
        
        # 2. Crear datos de prueba
        print("\n[2] Creando datos de prueba...")
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
        print("[OK] Datos de prueba creados")
        
        # 3. Preprocesamiento
        print("\n[3] Preprocesamiento de imagen...")
        start = time.time()
        enhanced = enhance_invoice_for_ocr(test_image)
        elapsed = (time.time() - start) * 1000
        print(f"[OK] Preprocesamiento completado en {elapsed:.2f}ms")
        print(f"     Shape original: {test_image.shape}")
        print(f"     Shape mejorado: {enhanced.shape}")
        
        # 4. Extracción avanzada
        print("\n[4] Extracción avanzada de campos...")
        start = time.time()
        advanced_fields = extract_fields_advanced(test_text, test_words)
        elapsed = (time.time() - start) * 1000
        print(f"[OK] Extracción avanzada completada en {elapsed:.2f}ms")
        print(f"     Campos extraídos: {list(advanced_fields.keys())}")
        
        # 5. Detección de layout
        print("\n[5] Detección de layout...")
        start = time.time()
        layout_fields = extract_fields_by_layout(test_words)
        elapsed = (time.time() - start) * 1000
        print(f"[OK] Layout detection completado en {elapsed:.2f}ms")
        print(f"     Campos por layout: {list(layout_fields.keys())}")
        
        # 6. Detección POS
        print("\n[6] Detección de campos POS...")
        start = time.time()
        is_pos = is_pos_invoice(test_text)
        if is_pos:
            pos_fields = detect_pos_fields(test_text)
            print(f"[OK] Factura POS detectada")
            print(f"     Campos POS: {list(pos_fields.keys())}")
        else:
            print("[OK] No es factura POS")
        elapsed = (time.time() - start) * 1000
        print(f"     Tiempo: {elapsed:.2f}ms")
        
        # 7. Extracción de items
        print("\n[7] Extracción de items...")
        start = time.time()
        items = extract_invoice_items(test_text, test_words)
        elapsed = (time.time() - start) * 1000
        print(f"[OK] Extracción de items completada en {elapsed:.2f}ms")
        print(f"     Items extraídos: {len(items)}")
        
        # 8. Corrección OCR
        print("\n[8] Corrección de errores OCR...")
        start = time.time()
        corrected, corrections = correct_ocr_fields(advanced_fields, use_context=True)
        elapsed = (time.time() - start) * 1000
        print(f"[OK] Corrección OCR completada en {elapsed:.2f}ms")
        print(f"     Correcciones aplicadas: {len(corrections)}")
        
        # 9. Correcciones aprendidas
        print("\n[9] Aplicando correcciones aprendidas...")
        start = time.time()
        learned_corrected, learned_corrections = apply_learned_corrections(corrected)
        elapsed = (time.time() - start) * 1000
        print(f"[OK] Correcciones aprendidas aplicadas en {elapsed:.2f}ms")
        print(f"     Correcciones aprendidas: {len(learned_corrections)}")
        
        # 10. Detección de tipo de documento
        print("\n[10] Detección de tipo de documento...")
        start = time.time()
        doc_detection = detect_document_type(test_text)
        elapsed = (time.time() - start) * 1000
        print(f"[OK] Detección de documento completada en {elapsed:.2f}ms")
        print(f"     Tipo: {doc_detection.document_type.value}")
        print(f"     Subtipo: {doc_detection.subtype}")
        print(f"     Confianza: {doc_detection.confidence}")
        
        # 11. Validación de RIF
        print("\n[11] Validación de RIF...")
        start = time.time()
        rif_validation = validate_rif("J-12345678-9")
        elapsed = (time.time() - start) * 1000
        print(f"[OK] Validación de RIF completada en {elapsed:.2f}ms")
        print(f"     Formato válido: {rif_validation.is_valid_format}")
        print(f"     Checksum válido: {rif_validation.is_valid_checksum}")
        print(f"     RIF normalizado: {rif_validation.normalized_rif}")
        
        # 12. Resumen final
        print("\n" + "=" * 60)
        print("RESUMEN DEL PIPELINE")
        print("=" * 60)
        print(f"Campos finales extraídos: {list(learned_corrected.keys())}")
        print(f"Items extraídos: {len(items)}")
        print(f"Tipo de documento: {doc_detection.document_type.value}")
        print(f"RIF validado: {rif_validation.is_valid_format}")
        
        print("\n[SUCCESS] Pipeline OCR completo funcionando correctamente")
        return True
        
    except Exception as e:
        print(f"\n[FAIL] Error en pipeline: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_full_pipeline()
    exit(0 if success else 1)
