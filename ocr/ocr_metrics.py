"""
Sistema de Métricas y Logging de Calidad OCR
=============================================
Registra métricas de calidad del procesamiento OCR.

Funcionalidades:
  - Registro de métricas por procesamiento
  - Tracking de errores y warnings
  - Análisis de calidad de extracción
  - Exportación de métricas
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum


class MetricLevel(Enum):
    """Niveles de métrica."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class ProcessingMetric:
    """Métrica de procesamiento OCR."""
    timestamp: str
    processing_time_ms: float
    ocr_confidence: float
    fields_extracted: int
    fields_valid: int
    fields_corrected: int
    items_extracted: int
    document_type: str
    document_subtype: str
    image_preprocessing_applied: bool
    corrections_applied: List[str]
    errors: List[str]
    warnings: List[str]
    validation_status: str


class OCRMetrics:
    """
    Sistema de métricas para calidad OCR.
    
    Registra métricas de cada procesamiento para análisis de calidad.
    """
    
    def __init__(self, log_dir: str = None):
        """
        Args:
            log_dir: Directorio para almacenar logs
        """
        if log_dir is None:
            log_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                'data',
                'ocr_metrics'
            )
        
        self.log_dir = log_dir
        self._metrics: List[ProcessingMetric] = []
        
        # Crear directorio de logs
        os.makedirs(self.log_dir, exist_ok=True)
    
    def log_processing(self, ocr_result: Dict[str, Any], processing_time_ms: float):
        """
        Registra métricas de un procesamiento OCR.
        
        Args:
            ocr_result: Resultado del procesamiento OCR
            processing_time_ms: Tiempo de procesamiento en milisegundos
        """
        metric = ProcessingMetric(
            timestamp=datetime.now().isoformat(),
            processing_time_ms=processing_time_ms,
            ocr_confidence=ocr_result.get('ocr_confidence', 0.0),
            fields_extracted=len([k for k, v in ocr_result.items() if v and k not in ['raw_text', 'items']]),
            fields_valid=self._count_valid_fields(ocr_result),
            fields_corrected=len(ocr_result.get('corrections_applied', [])),
            items_extracted=len(ocr_result.get('items', [])),
            document_type=ocr_result.get('document_type', 'unknown'),
            document_subtype=ocr_result.get('document_subtype', ''),
            image_preprocessing_applied=ocr_result.get('preprocessing_applied', False),
            corrections_applied=[c.get('type', 'unknown') for c in ocr_result.get('corrections_applied', [])],
            errors=ocr_result.get('validation_errors', []),
            warnings=ocr_result.get('warnings', []),
            validation_status=ocr_result.get('validation_status', 'unknown')
        )
        
        self._metrics.append(metric)
        self._save_metric(metric)
    
    def _count_valid_fields(self, ocr_result: Dict[str, Any]) -> int:
        """Cuenta campos válidos en el resultado."""
        valid_fields = 0
        field_names = ['numero_factura', 'rif_emisor', 'fecha', 'total', 'base_imponible', 'iva']
        
        for field in field_names:
            value = ocr_result.get(field)
            if value and value not in ['', 'N/A', 'null']:
                valid_fields += 1
        
        return valid_fields
    
    def _save_metric(self, metric: ProcessingMetric):
        """Guarda una métrica en archivo."""
        date_str = datetime.now().strftime('%Y-%m-%d')
        log_file = os.path.join(self.log_dir, f'metrics_{date_str}.jsonl')
        
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(asdict(metric)) + '\n')
        except Exception as e:
            print(f"[WARN] Error guardando métrica: {e}")
    
    def get_metrics(self, limit: int = 100) -> List[ProcessingMetric]:
        """
        Retorna métricas registradas.
        
        Args:
            limit: Número máximo de métricas a retornar
            
        Returns:
            Lista de métricas
        """
        return self._metrics[-limit:]
    
    def get_summary(self) -> Dict[str, Any]:
        """Retorna un resumen de métricas."""
        if not self._metrics:
            return {}
        
        total = len(self._metrics)
        
        # Promedios
        avg_confidence = sum(m.ocr_confidence for m in self._metrics) / total
        avg_processing_time = sum(m.processing_time_ms for m in self._metrics) / total
        avg_fields_extracted = sum(m.fields_extracted for m in self._metrics) / total
        avg_fields_valid = sum(m.fields_valid for m in self._metrics) / total
        
        # Conteos
        total_errors = sum(len(m.errors) for m in self._metrics)
        total_warnings = sum(len(m.warnings) for m in self._metrics)
        total_corrections = sum(m.fields_corrected for m in self._metrics)
        
        # Distribución de tipos de documento
        doc_types = {}
        for m in self._metrics:
            doc_types[m.document_type] = doc_types.get(m.document_type, 0) + 1
        
        return {
            'total_processings': total,
            'avg_confidence': avg_confidence,
            'avg_processing_time_ms': avg_processing_time,
            'avg_fields_extracted': avg_fields_extracted,
            'avg_fields_valid': avg_fields_valid,
            'total_errors': total_errors,
            'total_warnings': total_warnings,
            'total_corrections': total_corrections,
            'document_type_distribution': doc_types,
        }
    
    def export_metrics(self, export_path: str):
        """
        Exporta todas las métricas a un archivo.
        
        Args:
            export_path: Ruta del archivo de exportación
        """
        try:
            data = [asdict(m) for m in self._metrics]
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[WARN] Error exportando métricas: {e}")
    
    def clear_metrics(self):
        """Limpia todas las métricas."""
        self._metrics.clear()


class QualityAnalyzer:
    """
    Analizador de calidad de OCR.
    
    Analiza métricas para identificar problemas de calidad.
    """
    
    def __init__(self, metrics: OCRMetrics):
        """
        Args:
            metrics: Instancia de OCRMetrics
        """
        self.metrics = metrics
    
    def analyze_quality(self) -> Dict[str, Any]:
        """Analiza la calidad del procesamiento OCR."""
        summary = self.metrics.get_summary()
        
        if not summary:
            return {'status': 'no_data'}
        
        analysis = {
            'status': 'ok',
            'issues': [],
            'recommendations': []
        }
        
        # Analizar confianza promedio
        if summary['avg_confidence'] < 0.7:
            analysis['status'] = 'warning'
            analysis['issues'].append('Confianza OCR baja')
            analysis['recommendations'].append('Mejorar preprocesamiento de imágenes')
        
        # Analizar tiempo de procesamiento
        if summary['avg_processing_time_ms'] > 5000:
            analysis['issues'].append('Tiempo de procesamiento alto')
            analysis['recommendations'].append('Optimizar pipeline OCR')
        
        # Analizar tasa de errores
        error_rate = summary['total_errors'] / max(summary['total_processings'], 1)
        if error_rate > 0.3:
            analysis['status'] = 'error'
            analysis['issues'].append('Tasa de errores alta')
            analysis['recommendations'].append('Revisar validaciones')
        
        # Analizar campos válidos
        valid_rate = summary['avg_fields_valid'] / max(summary['avg_fields_extracted'], 1)
        if valid_rate < 0.8:
            analysis['issues'].append('Tasa de campos válidos baja')
            analysis['recommendations'].append('Mejorar extracción de campos')
        
        return analysis
    
    def get_trends(self, window: int = 10) -> Dict[str, Any]:
        """
        Analiza tendencias de calidad.
        
        Args:
            window: Ventana de tiempo en procesamientos
            
        Returns:
            Tendencias de métricas clave
        """
        recent_metrics = self.metrics.get_metrics(limit=window)
        
        if len(recent_metrics) < 2:
            return {'status': 'insufficient_data'}
        
        # Calcular tendencias
        confidences = [m.ocr_confidence for m in recent_metrics]
        processing_times = [m.processing_time_ms for m in recent_metrics]
        
        conf_trend = 'stable'
        if confidences[-1] > confidences[0] + 0.1:
            conf_trend = 'improving'
        elif confidences[-1] < confidences[0] - 0.1:
            conf_trend = 'degrading'
        
        time_trend = 'stable'
        if processing_times[-1] > processing_times[0] + 1000:
            time_trend = 'slowing'
        elif processing_times[-1] < processing_times[0] - 1000:
            time_trend = 'speeding'
        
        return {
            'confidence_trend': conf_trend,
            'processing_time_trend': time_trend,
            'avg_confidence': sum(confidences) / len(confidences),
            'avg_processing_time': sum(processing_times) / len(processing_times),
        }


# Instancia global de métricas
_global_metrics: Optional[OCRMetrics] = None


def get_ocr_metrics(log_dir: str = None) -> OCRMetrics:
    """Retorna la instancia global de OCRMetrics."""
    global _global_metrics
    if _global_metrics is None:
        _global_metrics = OCRMetrics(log_dir=log_dir)
    return _global_metrics


def log_ocr_processing(ocr_result: Dict[str, Any], processing_time_ms: float):
    """
    Función de conveniencia para registrar un procesamiento OCR.
    
    Args:
        ocr_result: Resultado del procesamiento OCR
        processing_time_ms: Tiempo de procesamiento en milisegundos
    """
    metrics = get_ocr_metrics()
    metrics.log_processing(ocr_result, processing_time_ms)
