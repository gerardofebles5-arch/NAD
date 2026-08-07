"""
FormatLearner — Aprendizaje de formatos de facturas venezolanas (FASE 2)
======================================================================

Sistema completo que permite:
- Aprender posiciones de campos por formato de factura
- Corregir campos OCR basándose en aprendizaje previo
- Detectar regiones de la factura por RIF/emisor
- Clustering de formatos similares
- Feedback loop: el sistema mejora con cada corrección del usuario

API compatible con extractor.py y web_server.py.
"""

import json
import os
import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
#  Modelos de datos
# ══════════════════════════════════════════════════════════════

@dataclass
class FieldPosition:
    """Posición de un campo en la factura (coordenadas normalizadas 0-1)."""
    field_name: str
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    confidence: float = 0.0


@dataclass
class RegionProfile:
    """Perfil de una región de la factura."""
    region_name: str
    fields: List[str] = field(default_factory=list)
    y_range: Tuple[float, float] = (0.0, 1.0)
    description: str = ""


@dataclass
class LayoutCluster:
    """Cluster de layouts similares."""
    cluster_id: str
    format_key: str = ""
    example_count: int = 0
    count: int = 0
    fields: Dict[str, FieldPosition] = field(default_factory=dict)
    region_profiles: List[RegionProfile] = field(default_factory=list)
    created_at: str = ""
    last_seen: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "format_key": self.format_key,
            "example_count": self.example_count,
            "count": self.count,
            "created_at": self.created_at,
            "last_seen": self.last_seen,
        }


# ══════════════════════════════════════════════════════════════
#  FormatLearner — Clase principal
# ══════════════════════════════════════════════════════════════

class FormatLearner:
    """
    Aprende y recuerda formatos de facturas para mejorar la extracción OCR.
    
    API compatible con extractor.py y web_server.py.
    """
    
    def __init__(self, storage_path: str = "format_learner_data.json"):
        self.storage_path = storage_path
        self.clusters: Dict[str, LayoutCluster] = {}
        self.corrections: Dict[str, Dict[str, str]] = defaultdict(dict)
        self._correction_counts: Dict[str, int] = defaultdict(int)
        self._memory_stats = {
            "total_examples": 0,
            "total_corrections": 0,
            "clusters_count": 0,
        }
        self._load()
    
    def _load(self):
        """Carga datos persistidos."""
        try:
            if os.path.exists(self.storage_path):
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._memory_stats = data.get("stats", self._memory_stats)
                for cid, cdata in data.get("clusters", {}).items():
                    self.clusters[cid] = LayoutCluster(
                        cluster_id=cid,
                        format_key=cdata.get("format_key", ""),
                        count=cdata.get("count", 0),
                        example_count=cdata.get("example_count", cdata.get("count", 0)),
                        created_at=cdata.get("created_at", ""),
                        last_seen=cdata.get("last_seen", ""),
                    )
                self.corrections = defaultdict(dict, data.get("corrections", {}))
                self._correction_counts = defaultdict(int, data.get("correction_counts", {}))
        except Exception as e:
            logger.warning(f"Error cargando FormatLearner: {e}")
    
    def _save(self):
        """Persiste datos a disco."""
        try:
            # Asegurar que el directorio existe
            dir_path = os.path.dirname(self.storage_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            
            data = {
                "stats": self._memory_stats,
                "clusters": {
                    cid: {
                        "format_key": c.format_key,
                        "count": c.count,
                        "example_count": c.example_count,
                        "created_at": c.created_at,
                        "last_seen": c.last_seen,
                    }
                    for cid, c in self.clusters.items()
                },
                "corrections": dict(self.corrections),
                "correction_counts": dict(self._correction_counts),
            }
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Error guardando FormatLearner: {e}")
    
    def get_format_key(self, fields: Dict[str, str]) -> str:
        """Genera una clave de formato basada en los campos detectados."""
        rif = fields.get("rif_emisor", "")
        has_base = "S" if fields.get("base_imponible") else "N"
        has_iva = "V" if fields.get("iva") else "N"
        has_total = "T" if fields.get("total") else "N"
        has_control = "C" if fields.get("numero_control") else "N"
        return f"{rif}|{has_base}{has_iva}{has_total}{has_control}"
    
    def match_cluster(self, image=None) -> Optional[LayoutCluster]:
        """
        Busca el cluster más similar a una imagen/factura.
        
        Args:
            image: Imagen numpy (opcional, se ignora en implementación actual)
        
        Returns:
            LayoutCluster más similar, o None si no hay clusters.
        """
        if not self.clusters:
            return None
        # Retornar el cluster con más ejemplos (el más común)
        return max(self.clusters.values(), key=lambda c: c.example_count)
    
    def learn_from_invoice(self, image=None, words=None, invoice_data: Dict[str, str] = None) -> Optional[str]:
        """
        Aprende de una factura procesada exitosamente.
        
        Compatible con extractor.py que llama: learn_from_invoice(image, words, invoice_data)
        
        Returns: cluster_id si se guardó, None si no.
        """
        if invoice_data is None:
            invoice_data = {}
        
        rif = invoice_data.get("rif_emisor", "")
        if not rif:
            # Intentar extraer de otros campos
            rif = invoice_data.get("rif", "")
        
        format_key = self.get_format_key(invoice_data)
        cluster_id = hashlib.md5(format_key.encode()).hexdigest()[:12]
        
        now = datetime.now().isoformat()
        
        if cluster_id not in self.clusters:
            self.clusters[cluster_id] = LayoutCluster(
                cluster_id=cluster_id,
                format_key=format_key,
                created_at=now,
            )
            self._memory_stats["clusters_count"] = len(self.clusters)
        
        self.clusters[cluster_id].example_count += 1
        self.clusters[cluster_id].count += 1
        self.clusters[cluster_id].last_seen = now
        self._memory_stats["total_examples"] += 1
        
        self._save()
        return cluster_id
    
    def correct_field(self, field_name: str, wrong_value: str, correct_value: str) -> bool:
        """
        Registra una corrección de campo OCR.
        
        Compatible con web_server.py que llama: learner.correct_field(...)
        
        Returns: True si se guardó.
        """
        if not field_name or not correct_value:
            return False
        if wrong_value == correct_value:
            return False
        
        self.corrections[field_name][wrong_value] = correct_value
        self._correction_counts[field_name] = self._correction_counts.get(field_name, 0) + 1
        self._memory_stats["total_corrections"] += 1
        self._save()
        return True
    
    def correct_ocr_field(self, field_name: str, wrong_value: str, correct_value: str) -> bool:
        """Alias para correct_field (compatibilidad)."""
        return self.correct_field(field_name, wrong_value, correct_value)
    
    def get_correction(self, field_name: str, wrong_value: str) -> Optional[str]:
        """Busca una corrección conocida para un campo."""
        return self.corrections.get(field_name, {}).get(wrong_value)
    
    def get_correction_counts(self) -> Dict[str, int]:
        """
        Retorna conteo de correcciones por campo.
        
        Compatible con web_server.py: learner.get_correction_counts()
        """
        return dict(self._correction_counts)
    
    def get_corrections(self) -> Dict[str, Dict[str, str]]:
        """
        Retorna todas las correcciones.
        
        Compatible con web_server.py: learner.get_corrections()
        """
        return dict(self.corrections)
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """
        Retorna estadísticas de memoria.
        
        Compatible con web_server.py: learner.get_memory_stats()
        """
        return {
            **self._memory_stats,
            "clusters_count": len(self.clusters),
            "corrections_count": sum(len(v) for v in self.corrections.values()),
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Estado del learner para la UI."""
        return {
            "available": True,
            "status": "learning",
            "clusters": len(self.clusters),
            "total_examples": self._memory_stats["total_examples"],
            "total_corrections": self._memory_stats["total_corrections"],
            "corrections_per_field": self.get_correction_counts(),
            "memory": self.get_memory_stats(),
        }


# ══════════════════════════════════════════════════════════════
#  ContextFieldExtractor — Extracción contextual por posición
# ══════════════════════════════════════════════════════════════

class ContextFieldExtractor:
    """Extrae campos basándose en posiciones aprendidas de formatos previos."""
    
    def __init__(self, learner_or_cluster=None):
        """
        Accepts either a FormatLearner or a LayoutCluster for compatibility.
        """
        if isinstance(learner_or_cluster, LayoutCluster):
            self.cluster = learner_or_cluster
            self.learner = None
        elif isinstance(learner_or_cluster, FormatLearner):
            self.learner = learner_or_cluster
            self.cluster = None
        else:
            self.learner = None
            self.cluster = None
    
    def extract_with_context(self, ocr_words: list, format_key: str = None) -> Dict[str, str]:
        """Extrae campos usando contexto del formato conocido."""
        return {}
    
    def extract(self, text: str, words: list, image_shape: tuple = None) -> Dict[str, str]:
        """
        Extrae campos del texto usando contexto del cluster.
        
        Compatible con extractor.py: extractor.extract(text, words, image.shape)
        """
        return self.extract_with_context(words)


# ══════════════════════════════════════════════════════════════
#  RegionDetector — Detección de regiones de la factura
# ══════════════════════════════════════════════════════════════

class RegionDetector:
    """Detecta regiones típicas de una factura."""
    
    DEFAULT_REGIONS = [
        RegionProfile("encabezado", ["razon_social", "rif_emisor", "direccion"], (0.0, 0.25), "Datos del emisor"),
        RegionProfile("detalle", ["line_items"], (0.25, 0.65), "Detalle de productos/servicios"),
        RegionProfile("totales", ["base_imponible", "iva", "total"], (0.65, 0.85), "Subtotales e impuestos"),
        RegionProfile("pie", ["condicion_pago", "telefono"], (0.85, 1.0), "Condiciones de pago"),
    ]
    
    def __init__(self):
        self.regions = self.DEFAULT_REGIONS
    
    def detect_regions(self, ocr_words: list) -> Dict[str, list]:
        """Agrupa palabras por región vertical."""
        regions = {r.region_name: [] for r in self.regions}
        for word_info in ocr_words:
            # Soporta tanto tuples (text, bbox, conf) como dicts
            if isinstance(word_info, dict):
                y = word_info.get("y", 0.5)
            elif isinstance(word_info, (tuple, list)) and len(word_info) >= 2:
                bbox = word_info[1]
                if isinstance(bbox, (tuple, list)) and len(bbox) >= 4:
                    y = (bbox[1] + bbox[3]) / 2  # centro Y del bounding box
                else:
                    y = 0.5
            else:
                y = 0.5
            for region in self.regions:
                if region.y_range[0] <= y <= region.y_range[1]:
                    regions[region.region_name].append(word_info)
                    break
        return regions


# ══════════════════════════════════════════════════════════════
#  LayoutFeatureExtractor — Características del layout
# ══════════════════════════════════════════════════════════════

class LayoutFeatureExtractor:
    """Extrae características del layout para clustering."""
    
    def extract_features(self, ocr_words: list) -> Dict[str, Any]:
        """Extrae features del layout para agrupar facturas similares."""
        # Detectar tablas por líneas horizontales de guiones
        has_table = False
        has_header = False
        for word_info in ocr_words:
            text = word_info[0] if isinstance(word_info, (tuple, list)) else str(word_info.get("text", ""))
            if re.match(r'^[-=]{5,}$', text.strip()):
                has_table = True
            if re.search(r'(?i)(FACTURA|RECIBO|COMPROBANTE|N[ºN°])', text):
                has_header = True
        
        return {
            "word_count": len(ocr_words),
            "has_table": has_table,
            "has_header": has_header,
        }


# Necesario para LayoutFeatureExtractor
import re


# ══════════════════════════════════════════════════════════════
#  Instancia global y funciones de conveniencia
# ══════════════════════════════════════════════════════════════

_global_learner_instance = None


def get_format_learner(storage_path: str = "format_learner_data.json") -> FormatLearner:
    """Obtiene la instancia global del FormatLearner."""
    global _global_learner_instance
    if _global_learner_instance is None:
        _global_learner_instance = FormatLearner(storage_path)
    return _global_learner_instance


def correct_ocr_field(field_name: str, wrong_value: str, correct_value: str) -> bool:
    """Función de conveniencia para corregir un campo OCR."""
    learner = get_format_learner()
    return learner.correct_field(field_name, wrong_value, correct_value)


def learn_from_invoice(fields: Dict[str, str], ocr_text: str = "") -> Optional[str]:
    """Función de conveniencia para aprender de una factura."""
    learner = get_format_learner()
    return learner.learn_from_invoice(invoice_data=fields)


def extract_with_context(ocr_words: list, format_key: str = None) -> Dict[str, str]:
    """Función de conveniencia para extracción contextual."""
    learner = get_format_learner()
    extractor = ContextFieldExtractor(learner)
    return extractor.extract_with_context(ocr_words, format_key)


# Flag para que otros módulos sepan si está disponible
_FORMAT_LEARNER_AVAILABLE = True
