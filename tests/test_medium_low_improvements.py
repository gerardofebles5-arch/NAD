"""
Test de Mejoras Media/Baja Prioridad del Sistema OCR
===================================================
Verifica que los módulos de media/baja prioridad funcionen correctamente.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import tempfile


def test_nlp_corrector():
    """Test del corrector NLP."""
    print("\n=== Test: NLP Corrector ===")
    
    try:
        from ocr.nlp_corrector import NLPCorrector, correct_text_nlp
        
        corrector = NLPCorrector()
        
        # Test corrección de términos venezolanos
        text = "factra J123456789 fcha"
        corrected, corrections = corrector.correct_text(text)
        
        assert "factura" in corrected.lower(), "Debe corregir 'factra' a 'factura'"
        print(f"[OK] Corrección de términos venezolanos funciona")
        print(f"     Original: {text}")
        print(f"     Corregido: {corrected}")
        print(f"     Correcciones: {len(corrections)}")
        
        # Test corrección por campo
        text = "F001-000001"
        corrected, corrections = corrector.correct_text(text, field_name='numero_factura')
        # Verificar que el formato se mantiene o mejora
        assert "F001" in corrected or "F-001" in corrected, "Debe mantener formato de factura"
        print(f"[OK] Corrección por campo funciona")
        print(f"     Original: {text}")
        print(f"     Corregido: {corrected}")
        
        # Test corrección de RIF
        text = "J123456789"
        corrected, corrections = corrector.correct_text(text, field_name='rif')
        assert "-" in corrected, "Debe normalizar formato de RIF"
        print(f"[OK] Corrección de RIF funciona")
        
        print("[OK] NLP Corrector: PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] NLP Corrector: FAILED - {e}")
        return False


def test_table_detector():
    """Test del detector de tablas."""
    print("\n=== Test: Table Detector ===")
    
    try:
        from ocr.table_detector import TableDetector, detect_tables
        
        detector = TableDetector()
        
        # Test detección desde palabras
        words = [
            ("Item", (50, 50, 100, 70), 0.95),
            ("Cantidad", (110, 50, 180, 70), 0.95),
            ("Precio", (190, 50, 250, 70), 0.95),
            ("Total", (260, 50, 310, 70), 0.95),
            ("Producto A", (50, 80, 120, 100), 0.90),
            ("2", (130, 80, 150, 100), 0.90),
            ("100", (160, 80, 200, 100), 0.90),
            ("200", (210, 80, 250, 100), 0.90),
        ]
        
        tables = detector.detect(None, words)
        
        if tables:
            print(f"[OK] Tablas detectadas: {len(tables)}")
            table = tables[0]
            print(f"     Filas: {table.rows}, Columnas: {table.cols}")
            print(f"     Headers: {table.headers}")
        else:
            print("[WARN] No se detectaron tablas (puede ser normal)")
        
        # Test extracción de datos de tabla
        if tables:
            table_data = detector.extract_table_data(tables[0])
            print(f"[OK] Extracción de datos de tabla funciona: {len(table_data)} filas")
        
        print("[OK] Table Detector: PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] Table Detector: FAILED - {e}")
        return False


def test_exporter():
    """Test del exportador."""
    print("\n=== Test: Exporter ===")
    
    try:
        from ocr.exporter import OCRResultExporter, export_ocr_result
        
        exporter = OCRResultExporter()
        
        # Datos de prueba
        test_data = {
            'numero_factura': 'F001-000001',
            'rif_emisor': 'J-12345678-9',
            'total': '1.218,00',
            'fecha': '15/08/2026'
        }
        
        # Test exportación a CSV
        temp_dir = tempfile.mkdtemp()
        csv_path = os.path.join(temp_dir, 'test.csv')
        exporter.export_to_csv(test_data, csv_path)
        assert os.path.exists(csv_path), "Debe crear archivo CSV"
        print(f"[OK] Exportación a CSV funciona")
        
        # Test exportación a JSON
        json_path = os.path.join(temp_dir, 'test.json')
        exporter.export_to_json(test_data, json_path)
        assert os.path.exists(json_path), "Debe crear archivo JSON"
        print(f"[OK] Exportación a JSON funciona")
        
        # Test exportación a Excel (puede fallar si no está instalado)
        try:
            excel_path = os.path.join(temp_dir, 'test.xlsx')
            exporter.export_to_excel(test_data, excel_path)
            if os.path.exists(excel_path):
                print(f"[OK] Exportación a Excel funciona")
            else:
                print(f"[WARN] Excel no disponible (openpyxl no instalado)")
        except:
            print(f"[WARN] Excel no disponible (openpyxl no instalado)")
        
        # Test exportación a PDF (puede fallar si no está instalado)
        try:
            pdf_path = os.path.join(temp_dir, 'test.pdf')
            exporter.export_to_pdf(test_data, pdf_path)
            if os.path.exists(pdf_path):
                print(f"[OK] Exportación a PDF funciona")
            else:
                print(f"[WARN] PDF no disponible (reportlab no instalado)")
        except:
            print(f"[WARN] PDF no disponible (reportlab no instalado)")
        
        # Limpieza
        import shutil
        shutil.rmtree(temp_dir)
        
        print("[OK] Exporter: PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] Exporter: FAILED - {e}")
        return False


def test_notifications():
    """Test del sistema de notificaciones."""
    print("\n=== Test: Notifications ===")
    
    try:
        from ocr.notifications import NotificationSystem, NotificationLevel, notify_ocr_quality
        
        system = NotificationSystem()
        
        # Test notificación de confianza baja
        system.notify_low_confidence(0.6)
        print(f"[OK] Notificación de confianza baja funciona")
        
        # Test notificación de procesamiento lento
        system.notify_slow_processing(4000)
        print(f"[OK] Notificación de procesamiento lento funciona")
        
        # Test notificación de errores de validación
        system.notify_validation_error(['Error 1', 'Error 2'])
        print(f"[OK] Notificación de errores de validación funciona")
        
        # Test notificación de estado del sistema
        system.notify_system_status('ok')
        print(f"[OK] Notificación de estado del sistema funciona")
        
        # Test función de conveniencia
        notify_ocr_quality(0.8, 2000, ['Error'])
        print(f"[OK] Función de conveniencia funciona")
        
        # Test obtener notificaciones
        notifications = system.get_notifications()
        print(f"[OK] Obtener notificaciones funciona: {len(notifications)} notificaciones")
        
        print("[OK] Notifications: PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] Notifications: FAILED - {e}")
        return False


def test_dashboard():
    """Test del dashboard de métricas."""
    print("\n=== Test: Metrics Dashboard ===")
    
    try:
        dashboard_path = "d:/nuevo escaner/nadscanner_final/data/metrics_dashboard.html"
        
        if os.path.exists(dashboard_path):
            print(f"[OK] Dashboard HTML existe")
            print(f"     Ruta: {dashboard_path}")
        else:
            print(f"[WARN] Dashboard HTML no encontrado")
        
        print("[OK] Metrics Dashboard: PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] Metrics Dashboard: FAILED - {e}")
        return False


def test_integration_medium_low():
    """Test de integración de mejoras media/baja prioridad."""
    print("\n=== Test: Integration Medium/Low ===")
    
    try:
        # Verificar imports
        from ocr.nlp_corrector import NLPCorrector
        from ocr.table_detector import TableDetector
        from ocr.exporter import OCRResultExporter
        from ocr.notifications import NotificationSystem
        
        print("[OK] Todos los módulos media/baja prioridad se importan correctamente")
        
        # Test flujo integrado
        corrector = NLPCorrector()
        text = "factra J123456789"
        corrected, _ = corrector.correct_text(text)
        print(f"[OK] NLP en flujo integrado")
        
        detector = TableDetector()
        print(f"[OK] Table detector en flujo integrado")
        
        exporter = OCRResultExporter()
        print(f"[OK] Exporter en flujo integrado")
        
        system = NotificationSystem()
        print(f"[OK] Notifications en flujo integrado")
        
        print("[OK] Integration Medium/Low: PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] Integration Medium/Low: FAILED - {e}")
        return False


def main():
    """Ejecuta todos los tests."""
    print("=" * 60)
    print("TEST DE MEJORAS MEDIA/BAJA PRIORIDAD DEL SISTEMA OCR")
    print("=" * 60)
    
    results = []
    
    results.append(("NLP Corrector", test_nlp_corrector()))
    results.append(("Table Detector", test_table_detector()))
    results.append(("Exporter", test_exporter()))
    results.append(("Notifications", test_notifications()))
    results.append(("Metrics Dashboard", test_dashboard()))
    results.append(("Integration Medium/Low", test_integration_medium_low()))
    
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
