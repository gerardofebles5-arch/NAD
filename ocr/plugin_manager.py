"""
OCR Plugin Manager — Factory + Registry + Autodiscovery
==========================================================
Gestiona el registro y creación de backends de OCR.

El sistema permite:
  - Registrar backends con nombres únicos
  - Crear backends por nombre (factory)
  - Listar backends disponibles
  - Autodiscovery de backends instalados
  - Backend por defecto configurable

Uso:
    from ocr.plugin_manager import OCRBackendFactory

    factory = OCRBackendFactory()
    factory.register_all()

    backend = factory.create("paddle_ve")
    words = backend.recognize(image)
"""

from typing import Any, Dict, List, Optional, Type

from utils.config import CONFIG
from ocr.backend_base import OCRBackend, BackendMetadata


# ═══════════════════════════════════════════════════════════════
#  Registry de backends
# ═══════════════════════════════════════════════════════════════

class OCRBackendRegistry:
    """
    Registro central de clases de backend.

    Los backends se registran por nombre (string único).
    La factory los instancia bajo demanda.
    """

    def __init__(self):
        self._registry: Dict[str, Type[OCRBackend]] = {}

    def register(self, name: str, backend_class: Type[OCRBackend]):
        """
        Registra una clase de backend.

        Args:
            name: Nombre único del backend (ej: "paddle", "tesseract").
            backend_class: Clase que implementa OCRBackend.
        """
        if not issubclass(backend_class, OCRBackend):
            raise TypeError(
                f"{backend_class.__name__} debe heredar de OCRBackend"
            )
        self._registry[name] = backend_class

    def unregister(self, name: str):
        """Elimina un backend del registro."""
        self._registry.pop(name, None)

    def get_class(self, name: str) -> Optional[Type[OCRBackend]]:
        """Retorna la clase registrada para un nombre."""
        return self._registry.get(name)

    def list_names(self) -> List[str]:
        """Lista todos los nombres de backends registrados."""
        return list(self._registry.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._registry

    def __len__(self) -> int:
        return len(self._registry)


# ═══════════════════════════════════════════════════════════════
#  Instancia global del registro
# ═══════════════════════════════════════════════════════════════

_registry = OCRBackendRegistry()


def get_registry() -> OCRBackendRegistry:
    """Retorna el registro global de backends."""
    return _registry


# ═══════════════════════════════════════════════════════════════
#  Factory
# ═══════════════════════════════════════════════════════════════

class OCRBackendFactory:
    """
    Fábrica de backends de OCR.

    Crea instancias de backends por nombre, usando el registro global.
    Soporta creación lazy: el backend se instancia pero no se inicializa
    hasta que se llama a recognize().

    Uso:
        factory = OCRBackendFactory()

        # Crear backend: devuelve None si no existe o no está disponible
        backend = factory.create("paddle_ve")
        if backend and backend.is_available():
            words = backend.recognize(image)

        # Listar backends disponibles
        disponibles = factory.list_available()

        # Obtener backend por defecto (desde CONFIG)
        default = factory.get_default()
    """

    def __init__(self, registry: Optional[OCRBackendRegistry] = None):
        self._registry = registry or get_registry()

    # ── Registro ──

    def register(self, name: str, backend_class: Type[OCRBackend]):
        """Registra un backend en el registro global."""
        self._registry.register(name, backend_class)

    def register_all(self):
        """
        Registra todos los backends conocidos (autodiscovery).

        Cada backend se registra con su nombre canónico.
        Solo registra las clases — no las instancia.
        """
        from ocr.backends import (
            PaddleBackend, PaddleVEBackend, TesseractBackend,
        )
        self._registry.register("paddle", PaddleBackend)
        self._registry.register("paddle_ve", PaddleVEBackend)
        self._registry.register("tesseract", TesseractBackend)

        # Backends opcionales (disponibles solo si están instalados)
        try:
            from ocr.backends import DocTRBackend
            self._registry.register("doctr", DocTRBackend)
        except ImportError:
            pass

        try:
            from ocr.backends import SuryaBackend
            self._registry.register("surya", SuryaBackend)
        except ImportError:
            pass

        try:
            from ocr.backends import EasyOCRBackend
            self._registry.register("easyocr", EasyOCRBackend)
        except ImportError:
            pass

    # ── Creación ──

    def create(self, name: str) -> Optional[OCRBackend]:
        """
        Crea una instancia de backend por nombre.

        Args:
            name: Nombre del backend (paddle, paddle_ve, tesseract, doctr, ...).

        Returns:
            Instancia de OCRBackend, o None si el nombre no está registrado.
        """
        backend_class = self._registry.get_class(name)
        if backend_class is None:
            return None
        try:
            return backend_class()
        except Exception:
            return None

    def get_default(self) -> Optional[OCRBackend]:
        """
        Crea el backend por defecto según CONFIG.ocr.engine.

        Returns:
            Instancia de OCRBackend, o None si falla.
        """
        engine_name = CONFIG.ocr.engine if hasattr(CONFIG.ocr, 'engine') else "paddle_ve"
        return self.create(engine_name)

    # ── Consulta ──

    def list_registered(self) -> List[str]:
        """Lista todos los backends registrados."""
        return self._registry.list_names()

    def list_available(self) -> List[BackendMetadata]:
        """
        Lista los metadatos de todos los backends disponibles
        (dependencias instaladas).

        Crea una instancia temporal de cada backend para consultar
        su metadata. No inicializa el backend.
        """
        available = []
        for name in self._registry.list_names():
            backend = self.create(name)
            if backend and backend.is_available():
                available.append(backend.get_info())
        return available

    def list_all_with_status(self) -> List[BackendMetadata]:
        """
        Lista TODOS los backends registrados con su estado
        (disponible o no), incluyendo mensaje de error si no disponible.
        """
        all_meta = []
        for name in self._registry.list_names():
            backend = self.create(name)
            if backend:
                all_meta.append(backend.get_info())
            else:
                all_meta.append(BackendMetadata(
                    name=name,
                    display_name=name,
                    available=False,
                    init_error="Error al instanciar",
                ))
        return all_meta


# ═══════════════════════════════════════════════════════════════
#  Función de alto nivel
# ═══════════════════════════════════════════════════════════════

_global_factory: Optional[OCRBackendFactory] = None


def get_factory() -> OCRBackendFactory:
    """Retorna la instancia global de la factoría."""
    global _global_factory
    if _global_factory is None:
        _global_factory = OCRBackendFactory()
        _global_factory.register_all()
    return _global_factory


def create_backend(name: Optional[str] = None) -> Optional[OCRBackend]:
    """
    Crea un backend de OCR por nombre (o el default si no se especifica).

    Args:
        name: Nombre del backend. None = usar CONFIG.ocr.engine.

    Returns:
        Instancia de OCRBackend, o None si no disponible.
    """
    factory = get_factory()
    if name:
        return factory.create(name)
    return factory.get_default()


def list_backends() -> List[BackendMetadata]:
    """Lista todos los backends disponibles con sus metadatos."""
    factory = get_factory()
    return factory.list_all_with_status()
