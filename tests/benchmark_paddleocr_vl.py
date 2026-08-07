"""
Benchmark PaddleOCR-VL en MiniSiragon
=====================================
Mide RAM, CPU, tiempo de inferencia para validar rendimiento en hardware objetivo.
"""
import time
import psutil
import numpy as np
import cv2
from pathlib import Path
from typing import Dict, List
from dataclasses import dataclass, asdict

from ocr.paddleocr_vl_backend import PaddleOCRVLBackend


@dataclass
class BenchmarkResult:
    """Resultado de benchmark de una imagen."""
    filename: str
    image_size: tuple
    inference_time: float
    ram_before_mb: float
    ram_after_mb: float
    ram_peak_mb: float
    ram_delta_mb: float
    cpu_before: float
    cpu_after: float
    cpu_delta: float
    word_count: int
    confidence: float


class PaddleOCRVLBenchmark:
    """Benchmark de rendimiento para PaddleOCR-VL."""
    
    def __init__(self):
        self.backend = PaddleOCRVLBackend()
        self.backend.initialize()
        self.results: List[BenchmarkResult] = []
    
    def get_system_metrics(self) -> Dict:
        """Obtiene métricas actuales del sistema."""
        return {
            'ram_mb': psutil.virtual_memory().used / 1024 / 1024,
            'cpu_percent': psutil.cpu_percent(interval=0.1)
        }
    
    def benchmark_image(self, image_path: str) -> BenchmarkResult:
        """Ejecuta benchmark en una imagen."""
        filename = Path(image_path).name
        image = cv2.imread(image_path)
        
        if image is None:
            print(f"❌ No se pudo cargar: {filename}")
            return None
        
        image_size = image.shape[:2]
        
        # Métricas iniciales
        metrics_before = self.get_system_metrics()
        
        # Inferencia
        start = time.time()
        result = self.backend.extract_structured(image)
        inference_time = time.time() - start
        
        # Métricas finales
        metrics_after = self.get_system_metrics()
        
        # Calcular delta
        ram_delta = metrics_after['ram_mb'] - metrics_before['ram_mb']
        cpu_delta = metrics_after['cpu_percent'] - metrics_before['cpu_percent']
        
        # Extraer datos del resultado
        word_count = len(result.get('raw_text', '').split()) if result.get('raw_text') else 0
        confidence = result.get('confidence', 0.0)
        
        benchmark_result = BenchmarkResult(
            filename=filename,
            image_size=image_size,
            inference_time=inference_time,
            ram_before_mb=metrics_before['ram_mb'],
            ram_after_mb=metrics_after['ram_mb'],
            ram_peak_mb=metrics_after['ram_mb'],  # Simplificado (no tracking real-time)
            ram_delta_mb=ram_delta,
            cpu_before=metrics_before['cpu_percent'],
            cpu_after=metrics_after['cpu_percent'],
            cpu_delta=cpu_delta,
            word_count=word_count,
            confidence=confidence
        )
        
        return benchmark_result
    
    def run_batch(self, image_dir: str) -> List[BenchmarkResult]:
        """Ejecuta benchmark en lote de imágenes."""
        image_path = Path(image_dir)
        
        if not image_path.exists():
            print(f"❌ Directorio no existe: {image_dir}")
            return []
        
        # Buscar imágenes
        image_files = []
        for ext in ['*.jpg', '*.jpeg', '*.png', '*.JPG', '*.JPEG', '*.PNG']:
            image_files.extend(image_path.glob(ext))
        
        if not image_files:
            print(f"❌ No se encontraron imágenes en: {image_dir}")
            return []
        
        print(f"📁 Encontradas {len(image_files)} imágenes")
        print(f"🔄 Ejecutando benchmark...\n")
        
        self.results = []
        for i, image_file in enumerate(image_files, 1):
            print(f"[{i}/{len(image_files)}] Benchmark: {image_file.name}")
            
            try:
                result = self.benchmark_image(str(image_file))
                if result:
                    self.results.append(result)
                    
                    # Mostrar resultado rápido
                    print(f"  ⏱️  Tiempo: {result.inference_time:.2f}s")
                    print(f"  💾 RAM delta: {result.ram_delta_mb:+.2f} MB")
                    print(f"  📊 Confianza: {result.confidence:.3f}")
            except Exception as e:
                print(f"  ❌ Error: {e}")
            
            print()
        
        return self.results
    
    def generate_report(self) -> str:
        """Genera reporte de benchmark."""
        if not self.results:
            return "(sin resultados)"
        
        total = len(self.results)
        
        # Estadísticas
        avg_inference_time = sum(r.inference_time for r in self.results) / total
        avg_ram_delta = sum(r.ram_delta_mb for r in self.results) / total
        avg_cpu_delta = sum(r.cpu_delta for r in self.results) / total
        avg_confidence = sum(r.confidence for r in self.results) / total
        
        max_ram_delta = max(r.ram_delta_mb for r in self.results)
        max_inference_time = max(r.inference_time for r in self.results)
        
        # Generar reporte
        lines = []
        lines.append("=" * 80)
        lines.append("BENCHMARK PADDLEOCR-VL - MINISIRAGON N-95")
        lines.append("=" * 80)
        lines.append(f"\nTotal imágenes procesadas: {total}")
        lines.append(f"\nMétricas promedio:")
        lines.append(f"  Tiempo inferencia: {avg_inference_time:.2f}s")
        lines.append(f"  RAM delta: {avg_ram_delta:+.2f} MB")
        lines.append(f"  CPU delta: {avg_cpu_delta:+.2f}%")
        lines.append(f"  Confianza: {avg_confidence:.3f}")
        lines.append(f"\nMétricas máximas:")
        lines.append(f"  Tiempo inferencia: {max_inference_time:.2f}s")
        lines.append(f"  RAM delta: {max_ram_delta:+.2f} MB")
        lines.append(f"\nDetalle por imagen:")
        lines.append("-" * 80)
        
        for result in self.results:
            lines.append(f"\n📄 {result.filename}")
            lines.append(f"  Tamaño: {result.image_size[1]}x{result.image_size[0]}")
            lines.append(f"  Tiempo: {result.inference_time:.2f}s")
            lines.append(f"  RAM: {result.ram_before_mb:.2f} → {result.ram_after_mb:.2f} MB (delta: {result.ram_delta_mb:+.2f})")
            lines.append(f"  CPU: {result.cpu_before:.1f}% → {result.cpu_after:.1f}% (delta: {result.cpu_delta:+.1f})")
            lines.append(f"  Palabras: {result.word_count}")
            lines.append(f"  Confianza: {result.confidence:.3f}")
        
        lines.append("\n" + "=" * 80)
        lines.append("CRITERIOS DE ACEPTACIÓN:")
        lines.append(f"  ✅ RAM pico < 4GB: {'SÍ' if max_ram_delta < 4000 else 'NO'}")
        lines.append(f"  ✅ Tiempo inferencia < 5s: {'SÍ' if max_inference_time < 5 else 'NO'}")
        lines.append(f"  ✅ Confianza promedio > 0.7: {'SÍ' if avg_confidence > 0.7 else 'NO'}")
        lines.append("=" * 80)
        
        return "\n".join(lines)
    
    def save_report(self, output_path: str = "benchmark_paddleocr_vl.json"):
        """Guarda reporte en JSON."""
        data = {
            'total': len(self.results),
            'results': [asdict(r) for r in self.results],
            'summary': self._generate_summary()
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            import json
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"📊 Reporte guardado en: {output_path}")
    
    def _generate_summary(self) -> Dict:
        """Genera resumen estadístico."""
        if not self.results:
            return {}
        
        total = len(self.results)
        
        return {
            'total_images': total,
            'avg_inference_time': sum(r.inference_time for r in self.results) / total,
            'avg_ram_delta_mb': sum(r.ram_delta_mb for r in self.results) / total,
            'avg_cpu_delta': sum(r.cpu_delta for r in self.results) / total,
            'avg_confidence': sum(r.confidence for r in self.results) / total,
            'max_inference_time': max(r.inference_time for r in self.results),
            'max_ram_delta_mb': max(r.ram_delta_mb for r in self.results),
            'criteria_met': {
                'ram_under_4gb': max(r.ram_delta_mb for r in self.results) < 4000,
                'time_under_5s': max(r.inference_time for r in self.results) < 5,
                'confidence_over_0_7': (sum(r.confidence for r in self.results) / total) > 0.7
            }
        }


def main():
    """Función principal para ejecutar benchmark."""
    import sys
    
    if len(sys.argv) < 2:
        print("Uso: python tests/benchmark_paddleocr_vl.py <directorio_imagenes>")
        print("\nEjemplo:")
        print("  python tests/benchmark_paddleocr_vl.py output/data/")
        return
    
    image_dir = sys.argv[1]
    
    benchmark = PaddleOCRVLBenchmark()
    results = benchmark.run_batch(image_dir)
    
    if results:
        report = benchmark.generate_report()
        print(report)
        
        # Guardar reporte
        benchmark.save_report()
    else:
        print("❌ No se generaron resultados")


if __name__ == "__main__":
    main()
