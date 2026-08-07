"""
OCR Backend — Abstract Base Class
===================================
Define la interfaz común que todo backend de OCR debe implementar
para poder ser intercambiado sin modificar el pipeline de extracción.

Cada backend retorna palabras en el formato canónico:
    [(texto, (x1, y1, x2, y2), confianza), ...]

Uso:
    class MiBackend(OCRBackend):
        def get_name(self) -> str: ...
        def get_info(self) -> dict: ...
        def initialize(self): ...
        def recognize(self, image) -> List[WordResult]: ...
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np


# ──────────────────────────────────────────────
#  Tipo canónico de salida
# ──────────────────────────────────────────────

WordResult = Tuple[str, Tuple[float, float, float, float], float]
"""
Formato canónico de cada palabra reconocida:
    (texto, (x1, y1, x2, y2), confianza)
"""


@dataclass
class BackendMetadata:
    """Metadatos del backend para diagnóstico y UI."""

    name: str
    """Nombre corto del backend (paddle, tesseract, doctr, surya, ...)."""

    display_name: str
    """Nombre para mostrar en la interfaz."""

    version: str = ""
    """Versión del backend."""

    description: str = ""
    """Descripción breve."""

    requires_gpu: bool = False
    """Si requiere GPU para funcionar."""

    supports_batch: bool = False
    """Si soporta procesamiento por lotes."""

    languages: Tuple[str, ...] = ("es",)
    """Idiomas soportados."""

    dependencies: Tuple[str, ...] = ()
    """Paquetes Python necesarios."""

    available: bool = False
    """Si el backend está disponible (dependencias instaladas)."""

    init_error: str = ""
    """Mensaje de error si falló la inicialización."""


class OCRBackend(ABC):
    """
    Clase base abstracta para todos los backends de OCR.

    Cualquier backend concreto debe implementar:
        - get_name()      → identificador único
        - get_info()      → metadatos
        - initialize()    → inicialización lazy
        - recognize()     → el método principal
    """

    def __init__(self):
        self._initialized = False
        self._metadata = self._build_metadata()

    @abstractmethod
    def _build_metadata(self) -> BackendMetadata:
        """Construye los metadatos del backend."""
        ...

    def get_name(self) -> str:
        """Nombre corto del backend."""
        return self._metadata.name

    def get_info(self) -> BackendMetadata:
        """Retorna los metadatos completos."""
        return self._metadata

    def is_available(self) -> bool:
        """Indica si el backend está disponible."""
        return self._metadata.available

    @abstractmethod
    def initialize(self):
        """
        Inicialización lazy del backend.

        Debe establecer self._initialized = True al finalizar.
        Si falla, debe establecer self._metadata.available = False
        y self._metadata.init_error con el mensaje de error.
        """
        ...

    def ensure_initialized(self):
        """Asegura que el backend esté inicializado."""
        if not self._initialized:
            self.initialize()

    @abstractmethod
    def recognize(
        self,
        image: np.ndarray,
        confidence_threshold: Optional[float] = None,
    ) -> List[WordResult]:
        """
        Reconoce texto en una imagen.

        Args:
            image: Imagen BGR (OpenCV format).
            confidence_threshold: Umbral de confianza mínimo (0-1).
                                  None = usar default del backend.

        Returns:
            Lista de WordResult: (texto, (x1, y1, x2, y2), confianza)
            Vacía si no se reconoció nada.
        """
        ...

    def get_stats(self) -> Dict:
        """Retorna estadísticas del backend (opcional)."""
        return {}

    def reset_stats(self):
        """Reinicia estadísticas (opcional)."""
        pass
