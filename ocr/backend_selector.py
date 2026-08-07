"""
[NAD] Backend Selector + Continuous Benchmark Learning
========================================================
Seleccion automatica del mejor backend OCR con aprendizaje continuo
por tipo de documento.

Caracteristicas:
  1. Preview rapido (~50ms) con cada backend disponible
  2. Clasificacion del tipo de documento (factura, ID, recibo, libro)
  3. Historial de selecciones por tipo de documento
  4. Aprendizaje: despues de N documentos del mismo tipo, salta el preview
     y usa directamente el backend que mejor rendimiento historico tiene

Uso:
    from ocr.backend_selector import ContinuousLearner, BackendSelector

    # Con aprendizaje continuo (recomendado)
    learner = ContinuousLearner()
    best = learner.select(image)  # Primera vez: preview completo
    best = learner.select(image)  # Siguientes: usa historial
    print(learner.get_history_table())

    # Sin aprendizaje (selector original)
    selector = BackendSelector()
    best = selector.select(image)
    print(selector.get_results_table())
"""

import time
import math
import json
import os
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

import numpy as np

from ocr.backend_base import OCRBackend, WordResult
from ocr.plugin_manager import get_factory


# ============================================================
#  Tipos de documento
# ============================================================

class DocumentType(Enum):
    """Tipos de documento detectables."""
    INVOICE = "factura"
    ID = "identificacion"
    RECEIPT = "recibo"
    BOOK = "libro"
    LETTER = "carta"
    FORM = "formulario"
    UNKNOWN = "desconocido"

    @classmethod
    def from_label(cls, label: str) -> "DocumentType":
        label = label.lower().strip()
        mapping = {
            "factura": cls.INVOICE, "invoice": cls.INVOICE,
            "identificacion": cls.ID, "id": cls.ID, "cedula": cls.ID,
            "recibo": cls.RECEIPT, "receipt": cls.RECEIPT, "pago": cls.RECEIPT,
            "libro": cls.BOOK, "book": cls.BOOK, "contable": cls.BOOK,
            "carta": cls.LETTER, "letter": cls.LETTER,
            "formulario": cls.FORM, "form": cls.FORM,
        }
        return mapping.get(label, cls.UNKNOWN)


class DocumentTypeDetector:
    """
    Detecta el tipo de documento basado en metricas del preview OCR.

    Usa heuristicas sobre las palabras detectadas:
      - digit_ratio: ratio de digitos (facturas tienen muchos: montos, RIF, fechas)
      - long_word_ratio: palabras largas (libros tienen texto continuo)
      - word_count: cantidad de palabras
      - coverage: area cubierta
    """

    THRESHOLDS = {
        DocumentType.INVOICE: {"min_digit_ratio": 0.15, "min_word_count": 15, "min_coverage": 0.10},
        DocumentType.ID: {"max_digit_ratio": 0.12, "max_word_count": 30, "max_coverage": 0.15, "min_long_word_ratio": 0.30},
        DocumentType.RECEIPT: {"max_word_count": 25, "max_coverage": 0.12, "min_digit_ratio": 0.10},
        DocumentType.BOOK: {"min_word_count": 40, "min_long_word_ratio": 0.40, "min_coverage": 0.20, "max_digit_ratio": 0.05},
        DocumentType.LETTER: {"min_word_count": 30, "min_long_word_ratio": 0.35, "max_digit_ratio": 0.03},
        DocumentType.FORM: {"max_long_word_ratio": 0.20, "min_word_count": 10, "min_digit_ratio": 0.05},
    }

    @classmethod
    def detect(cls, result: "BackendPreviewResult") -> DocumentType:
        if result.word_count == 0:
            return DocumentType.UNKNOWN
        scores = {}
        for doc_type, thresholds in cls.THRESHOLDS.items():
            score = 0.0
            n = 0
            for metric, threshold in thresholds.items():
                n += 1
                key = metric.replace("min_", "").replace("max_", "")
                val = getattr(result, key, 0)
                if metric.startswith("min_"):
                    if val >= threshold: score += 1.0
                    elif val >= threshold * 0.7: score += 0.5
                else:
                    if val <= threshold: score += 1.0
                    elif val <= threshold * 1.5: score += 0.5
            if n > 0:
                scores[doc_type] = score / n
        if not scores:
            return DocumentType.UNKNOWN
        best = max(scores, key=scores.get)
        return best if scores[best] >= 0.4 else DocumentType.UNKNOWN

    @classmethod
    def detect_from_metrics(cls, digit_ratio: float, long_word_ratio: float,
                            word_count: int, coverage: float) -> DocumentType:
        mock = BackendPreviewResult(name="_mock_", available=True,
            word_count=word_count, coverage=coverage,
            digit_ratio=digit_ratio, long_word_ratio=long_word_ratio)
        return cls.detect(mock)


# ============================================================
#  BackendPreviewResult — Metricas de preview
# ============================================================

@dataclass
class BackendPreviewResult:
    """Resultado del preview rapido para un backend."""
    name: str = ""
    available: bool = False
    time_ms: float = 0.0
    word_count: int = 0
    avg_confidence: float = 0.0
    text_density: float = 0.0
    coverage: float = 0.0
    digit_ratio: float = 0.0
    long_word_ratio: float = 0.0
    score: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "name": self.name, "available": self.available,
            "time_ms": round(self.time_ms, 1), "word_count": self.word_count,
            "avg_confidence": round(self.avg_confidence, 3),
            "text_density": round(self.text_density, 6),
            "coverage": round(self.coverage, 4),
            "digit_ratio": round(self.digit_ratio, 3),
            "long_word_ratio": round(self.long_word_ratio, 3),
            "score": round(self.score, 3),
        }


# ============================================================
#  BackendSelector (original)
# ============================================================

class BackendSelector:
    """
    Selector automatico del mejor backend OCR.

    Ejecuta un preview rapido (~50ms por backend) sobre un crop
    reducido de la imagen, evaluando metricas clave para facturas
    (confianza, densidad, cobertura, ratio de digitos).
    """

    DEFAULT_WEIGHTS = {
        "avg_confidence": 0.40, "word_count": 0.15,
        "coverage": 0.15, "digit_ratio": 0.20, "text_density": 0.10,
    }

    def __init__(self, weights=None, preview_scale=0.25, max_preview_time_ms=100.0, min_preview_words=3):
        self._weights = weights or dict(self.DEFAULT_WEIGHTS)
        self._preview_scale = preview_scale
        self._max_preview_time = max_preview_time_ms / 1000.0
        self._min_words = min_preview_words
        self.results: List[BackendPreviewResult] = []
        self.best: Optional[BackendPreviewResult] = None
        self._factory = get_factory()

    def select(self, image: np.ndarray, timeout_per_backend=None) -> BackendPreviewResult:
        if timeout_per_backend is not None:
            self._max_preview_time = timeout_per_backend
        preview_image = self._make_preview_crop(image)
        names = self._factory.list_registered()
        if not names:
            fb = BackendPreviewResult(name="none", available=False, score=0.0)
            self.results, self.best = [fb], fb
            return fb
        self.results = []
        for name in names:
            self.results.append(self._evaluate_backend(name, preview_image, image.shape))
        valid = [r for r in self.results if r.available and r.word_count >= self._min_words]
        if not valid:
            first = next((r for r in self.results if r.available), self.results[0])
            first.score = 0.0
            self.best = first
        else:
            self.best = max(valid, key=lambda r: r.score)
        return self.best

    def get_results_table(self) -> str:
        if not self.results:
            return "(sin resultados)"
        hdr = f"{'Backend':<15s} {'Score':>6s} {'Conf':>6s} {'Words':>6s} {'Time':>7s} {'Digits':>6s} {'Cov':>6s}"
        sep = "-" * len(hdr)
        lines = [hdr, sep]
        for r in sorted(self.results, key=lambda x: x.score, reverse=True):
            if not r.available:
                lines.append(f"{r.name:<15s} {'N/A':>6s} {'N/A':>6s} {'N/A':>6s} {'N/A':>7s} {'N/A':>6s} {'N/A':>6s}")
            else:
                mk = " <<" if self.best and r.name == self.best.name else ""
                lines.append(f"{r.name:<15s} {r.score:>6.3f} {r.avg_confidence:>6.1%} {r.word_count:>6d} {r.time_ms:>6.1f}ms {r.digit_ratio:>6.1%} {r.coverage:>6.1%}{mk}")
        if self.best:
            lines.append(f"\nSeleccionado: {self.best.name} (score: {self.best.score:.3f})")
        return "\n".join(lines)

    def _make_preview_crop(self, image: np.ndarray) -> np.ndarray:
        h, w = image.shape[:2]
        new_w = max(200, int(w * self._preview_scale))
        new_h = max(200, int(h * self._preview_scale))
        try:
            import cv2
            return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        except ImportError:
            sy = max(1, h // new_h)
            sx = max(1, w // new_w)
            return image[::sy, ::sx]

    def _evaluate_backend(self, name: str, preview: np.ndarray, shape: Tuple) -> BackendPreviewResult:
        r = BackendPreviewResult(name=name, available=False)
        bk = self._factory.create(name)
        if bk is None or not bk.is_available():
            return r
        r.available = True
        t0 = time.time()
        try:
            words = bk.recognize(preview, confidence_threshold=0.1)
        except Exception:
            return r
        r.time_ms = round((time.time() - t0) * 1000, 1)
        if not words:
            return r
        words = [(t, b, c) for t, b, c in words if c >= 0.1]
        if not words:
            return r
        r.word_count = len(words)
        confs = [c for _, _, c in words]
        r.avg_confidence = float(np.mean(confs)) if confs else 0.0
        h, w = shape[:2]
        r.text_density = r.word_count / max((h * w) / 1_000_000.0, 0.001)
        total_ba = total_ch = digit_c = long_w = 0
        for txt, (x1, y1, x2, y2), _ in words:
            total_ba += (x2 - x1) * (y2 - y1)
            total_ch += len(txt)
            digit_c += sum(1 for c in txt if c.isdigit())
            if len(txt) > 5: long_w += 1
        ph, pw = preview.shape[:2]
        r.coverage = min(1.0, total_ba / max(ph * pw, 1))
        r.digit_ratio = digit_c / max(total_ch, 1)
        r.long_word_ratio = long_w / max(r.word_count, 1)
        r.score = self._compute_score(r)
        return r

    def _compute_score(self, r: BackendPreviewResult) -> float:
        w = self._weights
        score = (w.get("avg_confidence", 0.40) * r.avg_confidence +
                 w.get("word_count", 0.15) * min(1.0, r.word_count / 50.0) +
                 w.get("coverage", 0.15) * r.coverage +
                 w.get("digit_ratio", 0.20) * r.digit_ratio +
                 w.get("text_density", 0.10) * min(1.0, r.text_density / 10.0))
        if r.time_ms > self._max_preview_time * 1000:
            penalty = min(0.3, (r.time_ms / 1000 - self._max_preview_time) / self._max_preview_time * 0.1)
            score = max(0.0, score - penalty)
        return round(score, 4)


# ============================================================
#  BackendHistoryEntry — Una entrada en el historial
# ============================================================

@dataclass
class BackendHistoryEntry:
    """Una seleccion de backend registrada en el historial."""
    timestamp: float = 0.0
    doc_type: str = "desconocido"
    backend_name: str = ""
    score: float = 0.0
    word_count: int = 0
    avg_confidence: float = 0.0
    preview_time_ms: float = 0.0
    used_history: bool = False  # True si se salto el preview por historial

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class DocTypeStats:
    """Estadisticas agregadas por tipo de documento."""
    total_scans: int = 0
    by_backend: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    by_backend_score: Dict[str, List[float]] = field(default_factory=lambda: defaultdict(list))
    by_backend_confidence: Dict[str, List[float]] = field(default_factory=lambda: defaultdict(list))
    last_backend: str = ""
    last_timestamp: float = 0.0

    @property
    def best_backend(self) -> Optional[str]:
        """Backend con mejor score promedio para este tipo de documento."""
        if not self.by_backend_score:
            return None
        avg_scores = {}
        for bk, scores in self.by_backend_score.items():
            if scores:
                avg_scores[bk] = float(np.mean(scores))
        if not avg_scores:
            return None
        return max(avg_scores, key=avg_scores.get)

    @property
    def best_backend_score(self) -> float:
        bk = self.best_backend
        if bk and bk in self.by_backend_score and self.by_backend_score[bk]:
            return float(np.mean(self.by_backend_score[bk]))
        return 0.0

    @property
    def total_by_backend(self) -> Dict[str, int]:
        return dict(self.by_backend)

    def record(self, backend_name: str, score: float, confidence: float, timestamp: float):
        self.total_scans += 1
        self.by_backend[backend_name] += 1
        self.by_backend_score[backend_name].append(score)
        self.by_backend_confidence[backend_name].append(confidence)
        self.last_backend = backend_name
        self.last_timestamp = timestamp

    def to_dict(self) -> Dict:
        return {
            "total_scans": self.total_scans,
            "by_backend": dict(self.by_backend),
            "best_backend": self.best_backend,
            "best_backend_score": round(self.best_backend_score, 4),
            "last_backend": self.last_backend,
        }


# ============================================================
#  BackendHistory — Historial completo de selecciones
# ============================================================

class BackendHistory:
    """
    Historial de selecciones de backend por tipo de documento.

    Permite:
      - Registrar selecciones con todas las metricas
      - Consultar el mejor backend para un tipo de documento
      - Obtener estadisticas de rendimiento por tipo
      - Persistir/cargar desde JSON
      - Limitar el tamano del historial (FIFO)
    """

    def __init__(self, max_entries_per_type: int = 50, persist_path: Optional[str] = None):
        self._max_entries = max_entries_per_type
        self._persist_path = persist_path

        # Historial cronologico completo
        self.entries: List[BackendHistoryEntry] = []

        # Estadisticas agregadas por tipo
        self.stats_by_type: Dict[str, DocTypeStats] = defaultdict(DocTypeStats)

        # Cargar datos persistidos si existen
        if persist_path and os.path.exists(persist_path):
            self._load()

    # ── Registro ──

    def record(self, doc_type: DocumentType, result: BackendPreviewResult,
               used_history: bool = False):
        """Registra una seleccion en el historial."""
        entry = BackendHistoryEntry(
            timestamp=time.time(),
            doc_type=doc_type.value,
            backend_name=result.name,
            score=result.score,
            word_count=result.word_count,
            avg_confidence=result.avg_confidence,
            preview_time_ms=result.time_ms,
            used_history=used_history,
        )
        self.entries.append(entry)

        # Actualizar stats por tipo
        dt_key = doc_type.value
        self.stats_by_type[dt_key].record(
            backend_name=result.name,
            score=result.score,
            confidence=result.avg_confidence,
            timestamp=entry.timestamp,
        )

        # Limitar tamano FIFO
        self._trim()

    def record_from_metrics(self, doc_type: DocumentType, backend_name: str,
                            score: float, confidence: float, word_count: int,
                            used_history: bool = False):
        """Registra una seleccion desde metricas directas (sin BackendPreviewResult)."""
        mock = BackendPreviewResult(
            name=backend_name, available=True,
            score=score, avg_confidence=confidence,
            word_count=word_count,
        )
        self.record(doc_type, mock, used_history=used_history)

    # ── Consulta ──

    def best_for_type(self, doc_type: DocumentType) -> Optional[str]:
        """Retorna el mejor backend para un tipo de documento."""
        stats = self.stats_by_type.get(doc_type.value)
        if stats is None or stats.total_scans < 3:
            return None
        return stats.best_backend

    def best_score_for_type(self, doc_type: DocumentType) -> float:
        """Retorna el score promedio del mejor backend para un tipo."""
        stats = self.stats_by_type.get(doc_type.value)
        if stats is None:
            return 0.0
        return stats.best_backend_score

    def should_skip_preview(self, doc_type: DocumentType, min_records: int = 3,
                            min_score: float = 0.6) -> bool:
        """
        Determina si se puede saltar el preview para un tipo de documento.

        Args:
            doc_type: Tipo de documento.
            min_records: Minimo de registros para confiar en el historial.
            min_score: Score minimo del mejor backend para considerarlo confiable.

        Returns:
            True si se puede saltar el preview.
        """
        stats = self.stats_by_type.get(doc_type.value)
        if stats is None:
            return False
        if stats.total_scans < min_records:
            return False
        best = stats.best_backend
        if best is None:
            return False
        avg_score = float(np.mean(stats.by_backend_score.get(best, [0])))
        return avg_score >= min_score

    def best_backend_for(self, doc_type: DocumentType) -> Tuple[Optional[str], float]:
        """Retorna (backend_name, avg_score) si hay suficiente historial."""
        stats = self.stats_by_type.get(doc_type.value)
        if stats is None or stats.total_scans < 3:
            return None, 0.0
        best = stats.best_backend
        if best is None:
            return None, 0.0
        return best, stats.best_backend_score

    # ── Estadisticas ──

    def get_history_table(self) -> str:
        """Tabla formateada del historial por tipo de documento."""
        if not self.stats_by_type:
            return "(sin historial)"
        lines = []
        lines.append(f"{'Tipo Doc.':<20s} {'Escaneos':>9s} {'Mejor Backend':<18s} {'Score Prom.':>11s} {'Conf Prom.':>10s}")
        lines.append("-" * 70)
        for dt_key in sorted(self.stats_by_type.keys()):
            st = self.stats_by_type[dt_key]
            best = st.best_backend or "-"
            n = st.total_scans
            score = st.best_backend_score
            conf = float(np.mean(st.by_backend_confidence.get(best, [0]))) if best in st.by_backend_confidence else 0.0
            lines.append(f"{dt_key:<20s} {n:>9d} {best:<18s} {score:>10.2%} {conf:>9.1%}")
        lines.append(f"\nTotal registros: {len(self.entries)}")
        return "\n".join(lines)

    def to_dict(self) -> Dict:
        return {
            "total_entries": len(self.entries),
            "by_type": {k: v.to_dict() for k, v in self.stats_by_type.items()},
            "recent_entries": [e.to_dict() for e in self.entries[-20:]],
        }

    # ── Persistencia ──

    def save(self, path: Optional[str] = None):
        """Guarda el historial a JSON."""
        p = path or self._persist_path
        if not p:
            return
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        data = {
            "entries": [e.to_dict() for e in self.entries],
            "stats": {k: v.to_dict() for k, v in self.stats_by_type.items()},
        }
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _load(self):
        """Carga el historial desde JSON."""
        if not self._persist_path or not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for e_data in data.get("entries", []):
                entry = BackendHistoryEntry(**e_data)
                self.entries.append(entry)
                dt = entry.doc_type
                self.stats_by_type[dt].record(
                    backend_name=entry.backend_name,
                    score=entry.score,
                    confidence=entry.avg_confidence,
                    timestamp=entry.timestamp,
                )
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    def _trim(self):
        """Elimina entradas viejas si se supera el maximo."""
        if len(self.entries) <= self._max_entries * len(DocumentType):
            return
        # Mantener solo las ultimas N entradas
        max_total = self._max_entries * len(DocumentType) * 2
        if len(self.entries) > max_total:
            self.entries = self.entries[-max_total:]


# ============================================================
#  ContinuousLearner — Aprendizaje continuo por tipo de documento
# ============================================================

class ContinuousLearner:
    """
    Wrapper de BackendSelector con aprendizaje continuo.

    Para cada imagen:
      1. Clasifica el tipo de documento (INVOICE, ID, RECEIPT, BOOK, ...)
      2. Consulta el historial: si hay suficientes registros (>3) con score
         confiable (>0.6), salta el preview y usa el mejor backend directamente
      3. Si no hay suficiente historial, ejecuta preview completo
      4. Registra el resultado en el historial para futuras consultas
      5. Persiste el historial a JSON

    Uso:
        learner = ContinuousLearner(persist_path="backend_history.json")
        best = learner.select(image)
        print(learner.get_history_table())

        # Forzar preview (ignorar historial)
        best = learner.select(image, force_preview=True)
    """

    def __init__(self, persist_path: str = "backend_history.json",
                 min_records_for_skip: int = 3, min_score_for_skip: float = 0.6,
                 preview_scale: float = 0.25, max_preview_time_ms: float = 100.0):
        """
        Args:
            persist_path: Ruta para persistir el historial (None = no persistir).
            min_records_for_skip: Minimo de registros por tipo para saltar preview.
            min_score_for_skip: Score minimo del mejor backend para saltar preview.
            preview_scale: Escala del crop para preview.
            max_preview_time_ms: Tiempo maximo por backend en preview.
        """
        self._selector = BackendSelector(
            preview_scale=preview_scale,
            max_preview_time_ms=max_preview_time_ms,
        )
        self._history = BackendHistory(persist_path=persist_path)
        self._min_records = min_records_for_skip
        self._min_score = min_score_for_skip

        # Ultimo resultado
        self.last_result: Optional[BackendPreviewResult] = None
        self.last_doc_type: DocumentType = DocumentType.UNKNOWN
        self.last_used_history: bool = False

    def select(self, image: np.ndarray, force_preview: bool = False,
               doc_type_override: Optional[DocumentType] = None) -> BackendPreviewResult:
        """
        Selecciona el mejor backend para la imagen.

        Args:
            image: Imagen BGR.
            force_preview: Si True, ignora el historial y ejecuta preview completo.
            doc_type_override: Forzar tipo de documento (None = detectar automaticamente).

        Returns:
            BackendPreviewResult del backend seleccionado.
        """
        # 1. Preview rapido para obtener metricas y detectar tipo
        preview = self._selector._make_preview_crop(image)
        names = self._selector._factory.list_registered()
        if not names:
            fb = BackendPreviewResult(name="none", available=False, score=0.0)
            self.last_result = fb
            return fb

        # Ejecutar preview en el primer backend disponible para clasificar
        first_backend = None
        for name in names:
            bk = self._selector._factory.create(name)
            if bk and bk.is_available():
                first_backend = name
                break

        doc_type = doc_type_override or DocumentType.UNKNOWN

        if first_backend and doc_type == DocumentType.UNKNOWN:
            # Ejecutar preview minimo para clasificar tipo
            preview_result = self._selector._evaluate_backend(first_backend, preview, image.shape)
            doc_type = DocumentTypeDetector.detect(preview_result)

        self.last_doc_type = doc_type

        # 2. Priorizar PaddleOCR-VL para facturas (motor primario)
        if doc_type == DocumentType.INVOICE and 'paddleocr_vl' in names:
            if not force_preview:
                vl_backend = self._selector._factory.create('paddleocr_vl')
                if vl_backend and vl_backend.is_available():
                    result = BackendPreviewResult(
                        name='paddleocr_vl', available=True,
                        score=1.0, avg_confidence=1.0,
                        word_count=0, time_ms=0,
                    )
                    self.last_result = result
                    self.last_used_history = False

                    # Registrar en historial
                    self._history.record(doc_type, result, used_history=False)
                    self._history.save()

                    print(f"  [Bench] PaddleOCR-VL priorizado para factura")
                    return result

        # 3. Consultar historial
        if not force_preview and self._history.should_skip_preview(
                doc_type, min_records=self._min_records, min_score=self._min_score):
            best_name, best_score = self._history.best_backend_for(doc_type)
            if best_name is not None:
                result = BackendPreviewResult(
                    name=best_name, available=True,
                    score=best_score, avg_confidence=best_score,
                    word_count=0, time_ms=0,
                )
                self.last_result = result
                self.last_used_history = True

                # Registrar en historial (marcado como usado historial)
                self._history.record(doc_type, result, used_history=True)
                self._history.save()

                print(f"  [Bench] Usando historial para '{doc_type.value}': {best_name} (score: {best_score:.3f})")
                return result

        # 4. Preview completo
        self.last_used_history = False
        best = self._selector.select(image)
        self.last_result = best

        # Registrar en historial siempre que tengamos tipo de documento
        # (incluso con score 0, para que el historial refleje el intento)
        if doc_type != DocumentType.UNKNOWN and best.available:
            self._history.record(doc_type, best, used_history=False)
            self._history.save()

            if best.score > 0:
                print(f"  [Bench] Preview para '{doc_type.value}': {best.name} (score: {best.score:.3f}, "
                      f"{best.word_count} words)")

        return best

    @property
    def history(self) -> BackendHistory:
        return self._history

    def get_history_table(self) -> str:
        return self._history.get_history_table()

    def get_selection_log(self) -> str:
        """Retorna las ultimas selecciones como texto."""
        if not self._history.entries:
            return "(sin selecciones)"
        lines = []
        for e in self._history.entries[-20:]:
            tag = " [H]" if e.used_history else " [P]"
            lines.append(f"{e.doc_type:<15s} {e.backend_name:<12s} score={e.score:.3f} conf={e.avg_confidence:.2%}{tag}")
        return "\n".join(lines)

    def get_doc_type(self) -> str:
        """Retorna el tipo del ultimo documento procesado."""
        return self.last_doc_type.value if self.last_doc_type else "?"

    def reset_history(self):
        """Reinicia el historial de aprendizaje."""
        self._history = BackendHistory(persist_path=self._history._persist_path)
        if self._history._persist_path:
            self._history.save()


# ============================================================
#  Funciones de alto nivel
# ============================================================

_global_selector: Optional[BackendSelector] = None
_global_learner: Optional[ContinuousLearner] = None


def get_selector() -> BackendSelector:
    global _global_selector
    if _global_selector is None:
        _global_selector = BackendSelector()
    return _global_selector


def get_learner(persist_path: str = "backend_history.json") -> ContinuousLearner:
    """Retorna la instancia global del learner continuo."""
    global _global_learner
    if _global_learner is None:
        _global_learner = ContinuousLearner(persist_path=persist_path)
    return _global_learner


def select_best_backend(image: np.ndarray) -> Tuple[str, float]:
    selector = get_selector()
    best = selector.select(image)
    return best.name, best.score


def select_with_learning(image: np.ndarray, force_preview: bool = False) -> Tuple[str, float, str]:
    """
    Selecciona backend con aprendizaje continuo.

    Args:
        image: Imagen BGR.
        force_preview: Ignorar historial.

    Returns:
        (nombre_backend, score, tipo_documento)
    """
    learner = get_learner()
    best = learner.select(image, force_preview=force_preview)
    return best.name, best.score, learner.get_doc_type()


def compare_backends(image: np.ndarray) -> List[Dict]:
    selector = get_selector()
    selector.select(image)
    return [r.to_dict() for r in selector.results]


# ============================================================
#  Auto-test
# ============================================================

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        import cv2
        img = cv2.imread(sys.argv[1])
        if img is not None:
            print(f"Imagen: {sys.argv[1]} ({img.shape[1]}x{img.shape[0]})\n")
            learner = ContinuousLearner(persist_path=None)
            best = learner.select(img)
            print(learner._selector.get_results_table())
            print(f"\nTipo detectado: {learner.get_doc_type()}")
            print(f"Usando historial: {learner.last_used_history}")
            print(f"\nHistorial:\n{learner.get_history_table()}")
        else:
            print(f"Error: No se pudo cargar '{sys.argv[1]}'")
    else:
        print("Uso: python -m ocr.backend_selector <ruta_imagen>")
        print()
        print("Demo con imagenes sinteticas:\n")
        # Simular aprendizaje con tipos de documento
        learner = ContinuousLearner(persist_path=None)
        for i, (doc_type, w, h) in enumerate([
            ("factura", 600, 400), ("factura", 650, 420), ("factura", 580, 390),
            ("recibo", 300, 200), ("recibo", 320, 210),
            ("identificacion", 250, 350),
        ]):
            img = np.ones((h, w, 3), dtype=np.uint8) * 255
            dt = DocumentType.from_label(doc_type)
            best = learner.select(img, doc_type_override=dt)
            print(f"  [{i+1}] {doc_type:<15s} -> {best.name:<12s} score={best.score:.3f} {'[H]' if learner.last_used_history else '[P]'}")

        print(f"\nHistorial final:\n{learner.get_history_table()}")
