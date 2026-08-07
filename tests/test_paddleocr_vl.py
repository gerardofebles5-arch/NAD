"""
Pruebas A/B: PaddleOCR-VL vs OCR Clásico
=========================================
Compara precisión de ambos motores en lote real de facturas.
"""
import os
import json
import time
from pathlib import Path
from typing import Dict, List, Tuple
from dataclasses import dataclass, asdict
import numpy as np
import cv2

from ocr.paddleocr_vl_backend import PaddleOCRVLBackend
from ocr.extractor import InvoiceParser, InvoiceData


@dataclass
class ABTestResult:
    """Resultado de prueba A/B para una factura."""
    filename: str
    vl_data: Dict
    classic_data: InvoiceData
    comparison: Dict
    vl_time: float
    classic_time: float


class ABTester:
    """Ejecuta pruebas A/B entre PaddleOCR-VL y OCR clásico."""
    
    def __init__(self):
        self.vl_backend = PaddleOCRVLBackend()
        self.vl_backend.initialize()
        self.parser = InvoiceParser()
        self.results: List[ABTestResult] = []
    
    def compare_fields(self, vl_data: Dict, classic_data: InvoiceData) -> Dict:
        """Compara campos críticos entre ambos motores."""
        critical_fields = ['numero_factura', 'rif_emisor', 'fecha', 'total', 'base_imponible', 'iva']
        
        comparison = {}
        for field in critical_fields:
            vl_value = vl_data.get(field, '')
            classic_value = getattr(classic_data, field, '')
            
            comparison[field] = {
                'vl_value': vl_value,
                'classic_value': classic_value,
                'match': vl_value == classic_value if vl_value and classic_value else False,
                'both_empty': not vl_value and not classic_value
            }
        
        return comparison
    
    def test_invoice(self, image_path: str) -> ABTestResult:
        """Prueba una factura con ambos motores."""
        filename = Path(image_path).name
        image = cv2.imread(image_path)
        
        if image is None:
            print(f"❌ No se pudo cargar: {filename}")
            return None
        
        # PaddleOCR-VL
        start_vl = time.time()
        vl_data = self.vl_backend.extract_structured(image)
        vl_time = time.time() - start_vl
        
        # OCR clásico
        start_classic = time.time()
        classic_data = self.parser.extract(image)
        classic_time = time.time() - start_classic
        
        # Comparación
        comparison = self.compare_fields(vl_data, classic_data)
        
        result = ABTestResult(
            filename=filename,
            vl_data=vl_data,
            classic_data=classic_data,
            comparison=comparison,
            vl_time=vl_time,
            classic_time=classic_time
        )
        
        return result
    
    def run_batch(self, invoice_dir: str) -> List[ABTestResult]:
        """Ejecuta pruebas A/B en lote de facturas."""
        invoice_path = Path(invoice_dir)
        
        if not invoice_path.exists():
            print(f"❌ Directorio no existe: {invoice_dir}")
            return []
        
        # Buscar imágenes
        image_files = []
        for ext in ['*.jpg', '*.jpeg', '*.png', '*.JPG', '*.JPEG', '*.PNG']:
            image_files.extend(invoice_path.glob(ext))
        
        if not image_files:
            print(f"❌ No se encontraron imágenes en: {invoice_dir}")
            return []
        
        print(f"📁 Encontradas {len(image_files)} imágenes")
        print(f"🔄 Ejecutando pruebas A/B...\n")
        
        self.results = []
        for i, image_file in enumerate(image_files, 1):
            print(f"[{i}/{len(image_files)}] Probando: {image_file.name}")
            
            try:
                result = self.test_invoice(str(image_file))
                if result:
                    self.results.append(result)
                    
                    # Mostrar resultado rápido
                    matches = sum(1 for c in result.comparison.values() if c['match'])
                    total = len(result.comparison)
                    print(f"  ✅ Coincidencias: {matches}/{total}")
                    print(f"  ⏱️  VLM: {result.vl_time:.2f}s | Clásico: {result.classic_time:.2f}s")
            except Exception as e:
                print(f"  ❌ Error: {e}")
            
            print()
        
        return self.results
    
    def generate_report(self) -> str:
        """Genera reporte de resultados."""
        if not self.results:
            return "(sin resultados)"
        
        # Estadísticas generales
        total = len(self.results)
        
        # Comparación por campo
        field_stats = {}
        for result in self.results:
            for field, comp in result.comparison.items():
                if field not in field_stats:
                    field_stats[field] = {'matches': 0, 'total': 0}
                field_stats[field]['total'] += 1
                if comp['match']:
                    field_stats[field]['matches'] += 1
        
        # Tiempos promedio
        avg_vl_time = sum(r.vl_time for r in self.results) / total
        avg_classic_time = sum(r.classic_time for r in self.results) / total
        
        # Generar reporte
        lines = []
        lines.append("=" * 80)
        lines.append("REPORTE PRUEBAS A/B - PaddleOCR-VL vs OCR Clásico")
        lines.append("=" * 80)
        lines.append(f"\nTotal facturas probadas: {total}")
        lines.append(f"\nTiempos promedio:")
        lines.append(f"  PaddleOCR-VL: {avg_vl_time:.2f}s")
        lines.append(f"  OCR Clásico: {avg_classic_time:.2f}s")
        lines.append(f"\nPrecisión por campo:")
        
        for field, stats in field_stats.items():
            accuracy = stats['matches'] / stats['total'] * 100 if stats['total'] > 0 else 0
            lines.append(f"  {field:20s}: {stats['matches']:3d}/{stats['total']:3d} ({accuracy:.1f}%)")
        
        lines.append(f"\nDetalle por factura:")
        lines.append("-" * 80)
        
        for result in self.results:
            matches = sum(1 for c in result.comparison.values() if c['match'])
            total_fields = len(result.comparison)
            accuracy = matches / total_fields * 100 if total_fields > 0 else 0
            
            lines.append(f"\n📄 {result.filename}")
            lines.append(f"  Coincidencias: {matches}/{total_fields} ({accuracy:.1f}%)")
            lines.append(f"  Tiempos: VLM={result.vl_time:.2f}s | Clásico={result.classic_time:.2f}s")
            
            # Mostrar discrepancias
            discrepancies = [f for f, c in result.comparison.items() if not c['match'] and not c['both_empty']]
            if discrepancies:
                lines.append(f"  Discrepancias: {', '.join(discrepancies)}")
        
        lines.append("\n" + "=" * 80)
        
        return "\n".join(lines)
    
    def save_report(self, output_path: str = "ab_test_report.json"):
        """Guarda reporte en JSON."""
        data = {
            'total': len(self.results),
            'results': [asdict(r) for r in self.results],
            'summary': self._generate_summary()
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"📊 Reporte guardado en: {output_path}")
    
    def _generate_summary(self) -> Dict:
        """Genera resumen estadístico."""
        if not self.results:
            return {}
        
        total = len(self.results)
        
        # Comparación por campo
        field_stats = {}
        for result in self.results:
            for field, comp in result.comparison.items():
                if field not in field_stats:
                    field_stats[field] = {'matches': 0, 'total': 0}
                field_stats[field]['total'] += 1
                if comp['match']:
                    field_stats[field]['matches'] += 1
        
        # Tiempos
        avg_vl_time = sum(r.vl_time for r in self.results) / total
        avg_classic_time = sum(r.classic_time for r in self.results) / total
        
        return {
            'total_invoices': total,
            'avg_vl_time': avg_vl_time,
            'avg_classic_time': avg_classic_time,
            'field_accuracy': {
                field: stats['matches'] / stats['total'] * 100 if stats['total'] > 0 else 0
                for field, stats in field_stats.items()
            }
        }


def main():
    """Función principal para ejecutar pruebas A/B."""
    import sys
    
    if len(sys.argv) < 2:
        print("Uso: python tests/test_paddleocr_vl.py <directorio_facturas>")
        print("\nEjemplo:")
        print("  python tests/test_paddleocr_vl.py output/data/")
        return
    
    invoice_dir = sys.argv[1]
    
    tester = ABTester()
    results = tester.run_batch(invoice_dir)
    
    if results:
        report = tester.generate_report()
        print(report)
        
        # Guardar reporte
        tester.save_report()
    else:
        print("❌ No se generaron resultados")


if __name__ == "__main__":
    main()
