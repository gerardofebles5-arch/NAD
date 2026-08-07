"""
Test de Integración Completa del Sistema OCR
============================================
Verifica que todos los módulos funcionen juntos en el pipeline principal.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import tempfile


def test_full_pipeline_integration():
    """Test de integración completa del pipeline."""
    print("\n=== Test: Full Pipeline Integration ===")
    
    try:
        from ocr.extractor import InvoiceParser
        from ocr.extractor import InvoiceData
        
        extractor = InvoiceParser()
        
        # Crear imagen de prueba
        img = np.random.randint(0, 255, (1000, 800, 3), dtype=np.uint8)
        
        # Ejecutar extracción completa
        print("  Ejecutando pipeline completo...")
        inv = extractor.extract(img)
        
        # Verificar que el resultado es InvoiceData
        assert isinstance(inv, InvoiceData), "Debe retornar InvoiceData"
        print(f"[OK] Pipeline retorna InvoiceData")
        
        # Verificar que los campos básicos existen
        assert hasattr(inv, 'numero_factura'), "Debe tener numero_factura"
        assert hasattr(inv, 'rif_emisor'), "Debe tener rif_emisor"
        assert hasattr(inv, 'total'), "Debe tener total"
        assert hasattr(inv, 'fecha'), "Debe tener fecha"
        print(f"[OK] Campos básicos presentes")
        
        # Verificar nuevos campos integrados (solo si hay texto)
        if inv.raw_text and len(inv.raw_text) > 0:
            assert hasattr(inv, 'document_type'), "Debe tener document_type"
            assert hasattr(inv, 'document_subtype'), "Debe tener document_subtype"
            print(f"[OK] Campos de detección de documento presentes")
        else:
            print(f"[OK] Sin texto, campos de detección no aplicables")
        
        # Verificar que el sistema de exportación funciona
        temp_dir = tempfile.mkdtemp()
        json_path = os.path.join(temp_dir, 'test_export.json')
        extractor.export_result(inv, json_path, 'json')
        assert os.path.exists(json_path), "Debe crear archivo JSON"
        print(f"[OK] Exportación a JSON funciona")
        
        # Limpieza
        import shutil
        shutil.rmtree(temp_dir)
        
        print("[OK] Full Pipeline Integration: PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] Full Pipeline Integration: FAILED - {e}")
        import traceback
        traceback.print_exc()
        return False


def test_nlp_integration():
    """Test de integración de NLP en pipeline."""
    print("\n=== Test: NLP Integration ===")
    
    try:
        from ocr.nlp_corrector import NLPCorrector
        
        corrector = NLPCorrector()
        
        # Test corrección de términos
        text = "factra J123456789 fcha"
        corrected, corrections = corrector.correct_text(text)
        
        assert "factura" in corrected.lower(), "Debe corregir 'factra' a 'factura'"
        assert "fecha" in corrected.lower(), "Debe corregir 'fcha' a 'fecha'"
        print(f"[OK] NLP corrige términos venezolanos")
        
        print("[OK] NLP Integration: PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] NLP Integration: FAILED - {e}")
        return False


def test_table_detector_integration():
    """Test de integración de Table Detector."""
    print("\n=== Test: Table Detector Integration ===")
    
    try:
        from ocr.table_detector import TableDetector
        
        detector = TableDetector()
        
        # Test detección de tablas
        words = [
            ("Item", (50, 50, 100, 70), 0.95),
            ("Cantidad", (110, 50, 180, 70), 0.95),
            ("Precio", (190, 50, 250, 70), 0.95),
            ("Total", (260, 50, 310, 70), 0.95),
        ]
        
        tables = detector.detect(None, words)
        print(f"[OK] Table Detector detecta tablas: {len(tables)}")
        
        print("[OK] Table Detector Integration: PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] Table Detector Integration: FAILED - {e}")
        return False


def test_exporter_integration():
    """Test de integración de Exporter."""
    print("\n=== Test: Exporter Integration ===")
    
    try:
        from ocr.exporter import OCRResultExporter
        
        exporter = OCRResultExporter()
        
        test_data = {'test': 'value'}
        temp_dir = tempfile.mkdtemp()
        csv_path = os.path.join(temp_dir, 'test.csv')
        
        exporter.export_to_csv(test_data, csv_path)
        assert os.path.exists(csv_path), "Debe crear archivo CSV"
        print(f"[OK] Exporter crea archivos")
        
        # Limpieza
        import shutil
        shutil.rmtree(temp_dir)
        
        print("[OK] Exporter Integration: PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] Exporter Integration: FAILED - {e}")
        return False


def test_notifications_integration():
    """Test de integración de Notifications."""
    print("\n=== Test: Notifications Integration ===")
    
    try:
        from ocr.notifications import NotificationSystem
        
        system = NotificationSystem()
        
        # Test notificaciones
        system.notify_low_confidence(0.6)
        system.notify_slow_processing(4000)
        system.notify_validation_error(['Error'])
        
        notifications = system.get_notifications()
        assert len(notifications) > 0, "Debe tener notificaciones"
        print(f"[OK] Notifications genera alertas: {len(notifications)}")
        
        print("[OK] Notifications Integration: PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] Notifications Integration: FAILED - {e}")
        return False


def test_all_modules_import():
    """Test que todos los módulos importen correctamente."""
    print("\n=== Test: All Modules Import ===")
    
    try:
        # Módulos de alta prioridad
        from core.image_preprocessor import ImagePreprocessor
        from ocr.advanced_field_extractor import extract_fields_advanced
        from ocr.layout_detector import extract_fields_by_layout
        from ocr.ocr_corrector import correct_ocr_fields
        from ocr.pos_fields_detector import detect_pos_fields
        from ocr.items_extractor import extract_invoice_items
        from ocr.correction_learner import apply_learned_corrections
        from ocr.document_type_detector import detect_document_type
        from ocr.rif_validator import validate_rif
        from ocr.ocr_cache import get_cached_ocr_result, cache_ocr_result
        from ocr.ocr_metrics import log_ocr_processing
        from ocr.pdf_processor import convert_pdf_to_ocr_images
        
        # Módulos de media/baja prioridad
        from ocr.nlp_corrector import NLPCorrector
        from ocr.table_detector import TableDetector
        from ocr.exporter import OCRResultExporter
        from ocr.notifications import NotificationSystem
        
        print("[OK] Todos los módulos importan correctamente")
        print("[OK] All Modules Import: PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] All Modules Import: FAILED - {e}")
        return False


def main():
    """Ejecuta todos los tests de integración."""
    print("=" * 60)
    print("TEST DE INTEGRACIÓN COMPLETA DEL SISTEMA OCR")
    print("=" * 60)
    
    results = []
    
    results.append(("All Modules Import", test_all_modules_import()))
    results.append(("NLP Integration", test_nlp_integration()))
    results.append(("Table Detector Integration", test_table_detector_integration()))
    results.append(("Exporter Integration", test_exporter_integration()))
    results.append(("Notifications Integration", test_notifications_integration()))
    results.append(("Full Pipeline Integration", test_full_pipeline_integration()))
    
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
        print("\n[SUCCESS] Todos los tests de integración pasaron exitosamente!")
        return 0
    else:
        print(f"\n[WARNING] {total - passed} tests fallaron")
        return 1


if __name__ == "__main__":
    exit(main())
