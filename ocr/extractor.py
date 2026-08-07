"""
Bloque 6 — OCR + Extracción estructurada de datos
===================================================
Aplica OCR sobre la imagen renderizada, extrae texto con coordenadas,
y parsea campos estructurados de una factura venezolana.

Campos extraídos:
  - numero_factura, numero_control, fecha, rif_emisor, razon_social,
    direccion, telefono, base_imponible, iva, total, condicion_pago.

Validaciones:
  - IVA debe corresponder a la alícuota (16% u 8%).
  - Total debe ser base_imponible + iva.
  - RIF con dígito verificador válido.

Motores:
  - paddle_ve: PaddleOCR con post-procesamiento VE (recomendado)
  - paddle:    PaddleOCR estándar
  - tesseract: Tesseract OCR
"""

import re
import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from utils.config import CONFIG
from ocr.backend_base import OCRBackend, WordResult

# ── Integración con FormatLearner (FASE 2) ──
_FORMAT_LEARNER_AVAILABLE = False
try:
    from ocr.format_learner import (
        FormatLearner,
        ContextFieldExtractor as LearnerFieldExtractor,
        RegionDetector,
    )
    _FORMAT_LEARNER_AVAILABLE = True
except ImportError:
    pass

_global_learner_instance = None


def _get_learner():
    """Lazy init del FormatLearner."""
    global _global_learner_instance
    if _FORMAT_LEARNER_AVAILABLE and _global_learner_instance is None:
        try:
            _global_learner_instance = FormatLearner()
        except Exception:
            pass
    return _global_learner_instance


# ──────────────────────────────────────────────
#  Modelo de datos de la factura
# ──────────────────────────────────────────────
@dataclass
class InvoiceData:
    """Datos estructurados extraídos de una factura.

    Campos expandidos para cubrir:
      - Identificación del tipo de comprobante (Compra/Venta/Recibo/etc.)
      - Datos bancarios (banco, cuenta, cheque)
      - Identificación del cliente (cédula, RIF)
      - Detalle de items (productos, cantidades, precios)
      - Retenciones ISLR
    """

    # ── Identificación del documento ──
    numero_factura: str = ""
    """Número de factura o comprobante."""
    numero_control: str = ""
    """Número de control fiscal (NCF)."""
    fecha: str = ""
    """Fecha del comprobante (DD/MM/AAAA)."""

    # ── Tipo de comprobante ──
    tipo_comprobante: str = ""
    """Tipo: 'Factura de Venta', 'Factura de Compra', 'Recibo',
        'Nota de Débito', 'Nota de Crédito', 'Presupuesto', etc."""
    tipo_documento: str = ""
    """Clasificación general: 'Compra', 'Venta', 'Otro'."""

    # ── Emisor / Proveedor ──
    rif_emisor: str = ""
    """RIF del emisor/proveedor."""
    razon_social: str = ""
    """Razón social o nombre del emisor."""
    direccion: str = ""
    """Dirección del emisor."""
    telefono: str = ""
    """Teléfono del emisor."""

    # ── Cliente / Receptor ──
    cliente: str = ""
    """Nombre del cliente o receptor."""
    cedula_cliente: str = ""
    """Cédula o identificación del cliente (V-12345678, E-87654321, etc.)."""
    rif_cliente: str = ""
    """RIF del cliente si aplica."""

    # ── Montos ──
    base_imponible: str = ""
    """Base imponible (monto antes de IVA)."""
    iva: str = ""
    """Monto del IVA."""
    total: str = ""
    """Total general del comprobante."""
    monto_letras: str = ""
    """Monto en letras (si está presente)."""
    retencion_islr: str = ""
    """Retención de ISLR si aplica."""
    exento: str = ""
    """Monto exento de IVA."""

    # ── Condiciones ──
    condicion_pago: str = ""
    """Constición de pago: Contado, Crédito, Cheque, Transferencia, etc."""
    banco: str = ""
    """Nombre del banco (para cheques/depósitos/transferencias)."""
    numero_cuenta: str = ""
    """Número de cuenta bancaria o de cheque."""

    # ── Detalle de items ──
    items: str = ""
    """Items del comprobante en formato texto (descripción, cantidad,
        precio unitario, total por línea)."""

    # ── Moneda y tipo de cambio ──
    currency: str = ""
    """Moneda detectada: 'BS', 'USD', 'EUR', 'COP', 'ARS', o vacío."""

    exchange_rate: float = 0.0
    """Tasa de cambio BS/USD (compatibilidad con código anterior)."""

    total_bs: float = 0.0
    """Total convertido a Bolívares."""

    total_usd: float = 0.0
    """Total convertido a Dólares."""

    total_eur: float = 0.0
    """Total convertido a Euros."""

    total_cop: float = 0.0
    """Total convertido a Pesos Colombianos."""

    total_ars: float = 0.0
    """Total convertido a Pesos Argentinos."""

    all_rates: Dict[str, float] = field(default_factory=dict)
    """Todas las tasas de cambio obtenidas: {USD: 1.0, EUR: 0.92, ...}"""

    # ── Metadatos ──
    raw_text: str = ""
    ocr_confidence: float = 0.0
    validation_errors: List[str] = field(default_factory=list)
    ocr_stats: Dict = field(default_factory=dict)
    
    # ── Campos para validación cruzada VLM ──
    motor_ocr: str = ""
    """Motor OCR utilizado: 'paddleocr_vl', 'paddle_classico', 'tesseract'."""
    requiere_revision: bool = False
    """True si hubo discrepancias en validación cruzada y requiere revisión manual."""
    confidence: float = 0.0
    """Confianza del motor OCR primario."""

    def __post_init__(self):
        """Asegura que los campos numéricos siempre sean del tipo correcto."""
        # Asegurar que ocr_confidence siempre sea float
        if self.ocr_confidence is not None:
            try:
                self.ocr_confidence = float(self.ocr_confidence)
            except (ValueError, TypeError):
                self.ocr_confidence = 0.0
        
        # Asegurar que confidence siempre sea float
        if self.confidence is not None:
            try:
                self.confidence = float(self.confidence)
            except (ValueError, TypeError):
                self.confidence = 0.0
        
        # Asegurar que exchange_rate siempre sea float
        if self.exchange_rate is not None:
            try:
                self.exchange_rate = float(self.exchange_rate)
            except (ValueError, TypeError):
                self.exchange_rate = 0.0

    def to_dict(self) -> Dict[str, str]:
        """Convierte a diccionario para serialización JSON."""
        return {
            k: v for k, v in asdict(self).items()
            if k not in ("raw_text", "validation_errors", "ocr_stats")
        }

    def to_json(self, indent: int = 2) -> str:
        """Serializa a JSON."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ──────────────────────────────────────────────
#  Motor OCR — Plugin System
# ──────────────────────────────────────────────
class OCREngine:
    """
    Motor OCR con sistema de plugins intercambiables.

    El motor delega a backends registrados vía OCRBackendFactory.
    Esto permite cambiar el backend (PaddleOCR, Tesseract, docTR, Surya,
    EasyOCR) sin modificar el pipeline de extracción.

    Uso:
        engine = OCREngine("paddle_ve")
        words = engine.recognize(image)

        # Cambiar backend sobre la marcha
        engine.switch_backend("tesseract")

        # Listar backends disponibles
        available = engine.list_available()
    """

    def __init__(self, engine: Optional[str] = None, lang: str = "es", auto_select: bool = False):
        """
        Args:
            engine: Nombre del backend a usar (None = usar CONFIG o auto-select).
            lang: Idioma para OCR.
            auto_select: Si True, ejecuta BackendSelector para elegir el mejor backend
                         antes del OCR completo. Si False, usa CONFIG.ocr.auto_select_backend
                         como fallback si existe.
        """
        self.lang = lang
        # auto_select: prioriza parametro explicito, luego CONFIG
        config_auto = getattr(CONFIG.ocr, 'auto_select_backend', False) if hasattr(CONFIG, 'ocr') else False
        self._auto_select_enabled = auto_select or config_auto

        # Lock: esta instancia ahora puede ser un singleton compartido entre
        # requests concurrentes (ver get_ocr_engine() más abajo). La mayoría
        # de los backends (Tesseract vía subprocess) son seguros de por sí,
        # pero backends que mantienen un modelo cargado en memoria (PaddleOCR)
        # no garantizan inferencia concurrente seguro sobre la misma instancia.
        # Serializar recognize() evita corrupción de estado sin sacrificar
        # el ahorro de no recargar el modelo en cada request.
        import threading
        self._lock = threading.Lock()

        # Backends que han fallado permanentemente en tiempo de ejecución
        # (ej: modelo corrupto, archivo faltante, dependencia rota). Una vez
        # marcados aquí, no se reintentan en esta ni en futuras llamadas —
        # crítico para el singleton global donde _extract_best_invoice() llama
        # a recognize() DOS veces: si paddle falla estructuralmente la primera
        # vez, la segunda debe saltarlo inmediatamente sin perder 17s más.
        self._dead_backends: set = set()

        # Inicializar factory con todos los backends
        from ocr.plugin_manager import OCRBackendFactory
        self._factory = OCRBackendFactory()
        self._factory.register_all()

        # Backend activo
        engine_name = engine or CONFIG.ocr.engine
        self._backend: Optional[OCRBackend] = None
        self._backend_name = engine_name

        # Intentar crear el backend inmediatamente
        self._backend = self._factory.create(engine_name)
        if self._backend is None or not self._backend.is_available():
            # Fallback: buscar el primer backend REALMENTE disponible.
            # OJO: factory.create() siempre devuelve una instancia si la
            # clase no lanza excepción en __init__ (nunca lo hace), aunque
            # sus dependencias no estén instaladas — por eso NO basta con
            # comprobar "is None": hay que comprobar is_available().
            reason = "no disponible" if self._backend is None else (self._backend.get_info().init_error or "no disponible")
            available = self._factory.list_available()
            if available:
                first = available[0]
                self._backend = self._factory.create(first.name)
                self._backend_name = first.name
                print(f"  [OCR] Fallback a backend '{first.name}': "
                      f"'{engine_name}' no disponible ({reason})")
            else:
                print(f"  [OCR] [WARN] No hay backends disponibles")

    @property
    def engine_name(self) -> str:
        """Nombre del backend activo."""
        return self._backend_name

    @property
    def available_backends(self) -> List[str]:
        """Lista de nombres de backends disponibles."""
        return [m.name for m in self._factory.list_available()]

    def switch_backend(self, name: str) -> bool:
        """
        Cambia el backend activo sobre la marcha.

        Args:
            name: Nombre del backend (paddle, paddle_ve, tesseract, doctr, ...).

        Returns:
            True si el cambio fue exitoso.
        """
        backend = self._factory.create(name)
        if backend is not None and backend.is_available():
            self._backend = backend
            self._backend_name = name
            print(f"  [OCR] Backend cambiado a: {name}")
            return True
        print(f"  [OCR] [WARN] No se pudo cambiar a backend '{name}': no disponible")
        return False

    def auto_select_backend(self, image: np.ndarray) -> str:
        """
        Ejecuta BackendSelector para elegir el mejor backend para esta imagen.

        Realiza un preview rapido (~50ms por backend) midiendo confianza,
        densidad de texto, cobertura y ratio de digitos.

        Returns:
            Nombre del backend seleccionado.
        """
        try:
            from ocr.backend_selector import BackendSelector
            selector = BackendSelector()
            best = selector.select(image)
            if best.available and best.score > 0:
                print(f"  [OCR] Auto-select: {best.name} (score: {best.score:.3f}, "
                      f"{best.word_count} words, {best.avg_confidence:.1%} conf)")
                if best.name != self._backend_name:
                    self.switch_backend(best.name)
                return best.name
        except Exception as e:
            print(f"  [OCR] Auto-select fallback: {e}")
        return self._backend_name

    def recognize(self, image: np.ndarray) -> List[WordResult]:
        """
        Reconoce texto en la imagen.

        Si auto_select esta habilitado, ejecuta BackendSelector antes
        del OCR completo para elegir el mejor backend.

        Args:
            image: Imagen BGR.

        Returns:
            Lista de (texto, (x1, y1, x2, y2), confianza).
        """
        # Auto-seleccion de backend si esta habilitado
        if self._auto_select_enabled:
            self.auto_select_backend(image)

        if self._backend is None:
            print("  [OCR] [WARN] No hay backend disponible")
            return []

        with self._lock:
            # ── Si el backend activo ya está en la lista negra, saltarlo ──
            if self._backend_name in self._dead_backends:
                print(f"  [OCR] Backend '{self._backend_name}' está en lista negra "
                      f"(falló estructuralmente antes) — buscando respaldo…")
                return self._try_fallback(image)

            try:
                return self._backend.recognize(image)
            except (FileNotFoundError, OSError) as e:
                # Error ESTRUCTURAL del backend (modelo corrupto, archivo faltante,
                # permiso denegado). No es un error transitorio — reintentar es
                # perder tiempo. Se marca como permanentemente muerto.
                print(f"  [OCR] Error ESTRUCTURAL en backend '{self._backend_name}': {e}")
                print(f"  [OCR] Marcando '{self._backend_name}' como permanentemente no disponible")
                self._dead_backends.add(self._backend_name)
                return self._try_fallback(image)
            except Exception as e:
                print(f"  [OCR] Error en backend '{self._backend_name}': {e}")
                # Error transitorio (p.ej. timeout de GPU, memoria temporal).
                # Se intenta con otro backend pero NO se marca como muerto —
                # podría funcionar en el próximo request.
                return self._try_fallback(image)

    def _try_fallback(self, image: np.ndarray) -> List[WordResult]:
        """
        Intenta reconocer la imagen con algún backend de respaldo que no
        esté en la lista negra. Si encuentra uno, lo adopta como activo.

        NOTA: primero llama a initialize() explícitamente en vez de esperar
        a que recognize() lo haga internamente (vía ensure_initialized()).
        Esto captura errores de inicialización (modelo corrupto, versión
        incompatible de PaddlePaddle) SIN ejecutar la lógica completa de
        recognize() — que podría incluir preprocesamiento innecesario antes
        de descubrir que el backend no funciona.
        """
        for meta in self._factory.list_available():
            if meta.name == self._backend_name or meta.name in self._dead_backends:
                continue
            fallback = self._factory.create(meta.name)
            if fallback is None or not fallback.is_available():
                continue

            # Verificar initialize() ANTES de recognize()
            try:
                fallback.initialize()
            except (FileNotFoundError, OSError) as e2:
                print(f"  [OCR] Backend de respaldo '{meta.name}' falló en inicialización "
                      f"(ESTRUCTURAL): {e2}")
                print(f"  [OCR] Marcando '{meta.name}' como permanentemente no disponible")
                self._dead_backends.add(meta.name)
                continue
            except Exception as e2:
                print(f"  [OCR] Backend de respaldo '{meta.name}' falló en inicialización: {e2}")
                self._dead_backends.add(meta.name)
                continue

            try:
                words = fallback.recognize(image)
                print(f"  [OCR] Recuperado con backend de respaldo '{meta.name}' "
                      f"({len(words)} palabras)")
                self._backend = fallback
                self._backend_name = meta.name
                return words
            except (FileNotFoundError, OSError) as e2:
                print(f"  [OCR] Backend de respaldo '{meta.name}' falló en runtime "
                      f"(ESTRUCTURAL): {e2}")
                print(f"  [OCR] Marcando '{meta.name}' como permanentemente no disponible")
                self._dead_backends.add(meta.name)
                continue
            except Exception as e2:
                print(f"  [OCR] Backend de respaldo '{meta.name}' también falló en runtime: {e2}")
                continue
        print("  [OCR] [WARN] Ningún backend disponible pudo procesar la imagen")
        return []

    def list_available(self) -> List[Dict]:
        """Lista backends disponibles con metadatos."""
        return [
            {
                "name": m.name,
                "display_name": m.display_name,
                "version": m.version,
                "description": m.description,
                "requires_gpu": m.requires_gpu,
                "languages": list(m.languages),
            }
            for m in self._factory.list_available()
        ]

    def initialize(self):
        """Inicialización explícita (lazy)."""
        if self._backend is not None:
            self._backend.ensure_initialized()

    def ensure_initialized(self):
        """Asegura que el backend esté inicializado."""
        self.initialize()

    def get_backend_info(self) -> Optional[Dict]:
        """Retorna información del backend activo."""
        if self._backend is None:
            return None
        meta = self._backend.get_info()
        return {
            "name": meta.name,
            "display_name": meta.display_name,
            "version": meta.version,
            "description": meta.description,
            "available": meta.available,
            "error": meta.init_error,
        }


# ──────────────────────────────────────────────
#  Instancia global del motor OCR (singleton por proceso)
# ──────────────────────────────────────────────
_global_ocr_engine: Optional["OCREngine"] = None


def get_ocr_engine() -> "OCREngine":
    """
    Retorna la instancia global del motor OCR.

    IMPORTANTE: antes, cada factura procesada creaba un OCREngine nuevo
    (InvoiceParser.__init__ hacía `OCREngine(...)` directo). Si el backend
    configurado carga un modelo pesado (PaddleOCR carga pesos de red
    neuronal en memoria), eso significaba recargar el modelo en CADA
    request HTTP — carísimo para un servidor que atiende muchas facturas.
    Ahora se reutiliza la misma instancia entre requests, igual que ya
    hacían get_format_learner() y get_currency_provider().
    """
    global _global_ocr_engine
    if _global_ocr_engine is None:
        _global_ocr_engine = OCREngine(
            engine=CONFIG.ocr.engine,
            lang=CONFIG.ocr.lang,
        )
    return _global_ocr_engine


def reset_ocr_engine():
    """Fuerza recrear el motor OCR en la próxima llamada (tests / cambio de config en caliente)."""
    global _global_ocr_engine
    _global_ocr_engine = None


# ──────────────────────────────────────────────
#  Parser de factura venezolana
# ──────────────────────────────────────────────
class InvoiceParser:
    """
    Parsea los resultados del OCR para extraer campos
    estructurados de una factura venezolana.

    Usa reglas de posición (coordenadas Y) y regex.
    """

    PATTERNS = {
        "numero_factura": [
            r"FACTURA\s*(?:N[°ºO]?\.?\s*)?#?\s*(\S+)",
            r"(?:N[°º]?\s*)?(?:FACTURA|FACT\.?|FC[OA]?)\s*[:.\-]?\s*(\S+)",
            r"\b(\d{2}[-]\d{4,8})\b",
        ],
        "numero_control": [
            r"(?:N[°º]?\s*)?(?:CONTROL|CTRL|CTL)\s*[:.\-]?\s*(\S+)",
            r"\b(\d{2}[-]\d{8})\b",
        ],
        "fecha": [
            r"\b(\d{2}[/\-.]\d{2}[/\-.]\d{4})\b",
            r"\b(\d{4}[/\-.]\d{2}[/\-.]\d{2})\b",
            r"FECHA/HORA\s*[:.\-]?\s*(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}[AP]M)",
        ],
        "rif_emisor": [
            r"RIF\s*[:.\-]?\s*([VJEGPC][\-.\s]?\d{8}[\-.\s]?\d)",
            r"\b([VJEGPC])[\-.\s]?(\d{8})[\-.\s]?(\d)\b",
        ],
        "telefono": [
            r"\b(0\d{3}[\-.\s]?\d{7})\b",
            r"\b(\+58\s?\d{3}[\-.\s]?\d{7})\b",
            r"T[EÉ]L[EÉ]FONO\s*[:.\-]?\s*(\S+)",
        ],
        "base_imponible": [
            r"(?:BASE|SUBTOTAL|EXENTO|GRAVABLE)\s*(?:IM[Pp]ONIBLE)?\s*[:.\-]?\s*([\d.,]+)",
            r"BASE\s*[:.\-]?\s*([\d.,]+)",
        ],
        "iva": [
            r"(?:I\.?\s*V\.?\s*A\.?|IVA)\s*(?:\d{1,2}\s*%?\s*)?[:.\-]?\s*([\d.,]+)",
        ],
        "total": [
            r"(?:TOTAL\s*(?:GENERAL|COMPROBANTE|A\s*PAGAR|BS\.?)?)\s*[:.\-]?\s*([\d.,]+)",
            r"(?:MONTO\s*TOTAL)\s*[:.\-]?\s*([\d.,]+)",
            r"(?:GRAN\s*TOTAL)\s*[:.\-]?\s*([\d.,]+)",
        ],
        "currency": [
            # Bolívares
            r"\b(BS|Bs|bs\.?|BOL[IÍ]VAR(?:ES)?|VES)\b",
            # Dólares
            r"\b(\$|USD|D[OÓ]LAR(?:ES)?|DIVISAS|AMERICANO)\b",
            # Euros
            r"\b(€|EUR(?:O)?(?:S)?|EUROS?)\b",
            # Pesos Colombianos
            r"\b(COP|COL|PESO(?:S)?\s*COLOMBIANO(?:S)?)\b",
            # Pesos Argentinos
            r"\b(ARS|ARG|PESO(?:S)?\s*ARGENTINO(?:S)?)\b",
            # Genérico: MONEDA/DIVISA
            r"(?:MONEDA|DIVISA)\s*[:.\-]?\s*(\S+)",
        ],
        "condicion_pago": [
            r"(?:CONDICI[OÓ]N\s*(?:DE\s*)?PAGO)\s*[:.\-]?\s*(.+?)(?:\d|\n|$)",
            r"\b(CONTADO|CR[EÉ]DITO\s*\d*\s*D[IÍ]AS|CHEQUE|TRANSFERENCIA)\b",
        ],
        # Campos adicionales para facturas de punto de venta
        "serial": [
            r"SERIAL\s*[:.\-]?\s*(\d+)",
            r"S/N\s*[:.\-]?\s*(\d+)",
        ],
        "ter": [
            r"TER\s*[:.\-]?\s*(\d+)",
            r"TERMINAL\s*[:.\-]?\s*(\d+)",
        ],
        "afil": [
            r"AFIL\s*[:.\-]?\s*(\d+)",
            r"AFILIADO\s*[:.\-]?\s*(\d+)",
        ],
        "adquirente": [
            r"ADQUIRIENTE\s*::?\s*(\d+)",
            r"ADQUIRENTE\s*[:.\-]?\s*(\d+)",
        ],
        "lote": [
            r"LOTE\s*[:.\-]?\s*(\d*)",
        ],
        "trace": [
            r"TRACE\s*[:.\-]?\s*(\d*)",
        ],
        "banco": [
            r"BANCAMIGA|BANCO\s*DE\s*VENEZUELA|MERCANTIL|PROVINCIAL|BANESCO|BNC|BOD|TESORO",
        ],
        "tipo_transaccion": [
            r"(COMPRA|VENTA)",
        ],
        "ubicacion": [
            r"(ARAGUA|MIRANDA|CARACAS|VALLES|CENTRO|ZULIA|TACHIRA|MERIDA|TRUJILLO|PORTUGUESA)",
        ],
        "copia": [
            r"(COPIA\s+CLIENTE|ORIGINAL|DUPLICADO)",
        ],
    }

    def __init__(self):
        self.ocr_engine = get_ocr_engine()

    def extract(self, image: np.ndarray) -> InvoiceData:
        """
        Extrae los datos de la factura desde la imagen renderizada.

        FASE 2: Integra FormatLearner + ContextFieldExtractor para
        extracción semántica que mejora con cada factura procesada.

        FASE 4: Integra nuevos módulos mejorados:
          - Preprocesamiento de imágenes
          - Extracción avanzada de campos
          - Detección de layout
          - Corrección automática de errores OCR
          - Detección de campos POS
          - Cache de resultados OCR
          - Métricas de calidad
          - Soporte para PDF

        Args:
            image: Imagen BGR del documento enderezado y realzado.

        Returns:
            InvoiceData con los campos extraídos y validados.
        """
        import time
        start_time = time.time()
        
        # Soporte para PDF (FASE 4)
        if isinstance(image, str):
            print("  [PDF] Detectado archivo PDF, convirtiendo a imagen...")
            try:
                from ocr.pdf_processor import convert_pdf_to_ocr_images
                images = convert_pdf_to_ocr_images(image)
                if images:
                    image = images[0]  # Usar primera página
                    print(f"  [PDF] PDF convertido a imagen ({len(images)} páginas)")
                else:
                    print("  [PDF] Error: No se pudo convertir PDF")
                    inv = InvoiceData()
                    inv.validation_errors.append("No se pudo convertir PDF")
                    return inv
            except ImportError:
                print("  [PDF] Error: pdf2image no instalado")
                inv = InvoiceData()
                inv.validation_errors.append("pdf2image no instalado")
                return inv
        
        # 0a. Verificar cache (FASE 4)
        print("  [CACHE] Verificando cache...")
        try:
            from ocr.ocr_cache import get_cached_ocr_result, cache_ocr_result
            import cv2
            image_bytes = cv2.imencode('.png', image)[1].tobytes()
            cached_result = get_cached_ocr_result(image_bytes)
            if cached_result:
                print("  [CACHE] Resultado encontrado en cache")
                inv = InvoiceData()
                for key, value in cached_result.items():
                    if hasattr(inv, key):
                        setattr(inv, key, value)
                return inv
        except ImportError:
            pass
        
        # 0b. Preprocesamiento de imagen (FASE 4)
        print("  [PRE] Preprocesando imagen...")
        try:
            from core.image_preprocessor import enhance_invoice_for_ocr
            image = enhance_invoice_for_ocr(image)
            print("  [PRE] Imagen mejorada para OCR")
        except ImportError:
            pass  # Continuar sin preprocesamiento si no está disponible

        # 1. OCR
        print("  [GEAR] Ejecutando OCR...")
        words = self.ocr_engine.recognize(image)

        if not words:
            print("  [WARN] No se detectó texto en la imagen.")
            inv = InvoiceData()
            inv.validation_errors.append("No se detectó texto")
            return inv

        # Filtrar por confianza
        threshold = CONFIG.ocr.confidence_threshold
        words = [(t, b, c) for t, b, c in words if c >= threshold]

        if not words:
            print("  [WARN] Todo el texto detectado tiene baja confianza.")

        # 2. Reconstruir texto completo
        words_sorted = sorted(words, key=lambda w: (w[1][1], w[1][0]))
        full_text = " ".join(t for t, _, _ in words_sorted)

        avg_conf = sum(c for _, _, c in words_sorted) / max(len(words_sorted), 1)
        print(f"  → OCR: {len(words_sorted)} palabras, confianza media: {avg_conf:.2f}")

        # 3. Aplicar post-procesamiento VE (si está activado)
        if CONFIG.ocr.ve_mode:
            try:
                from ocr.paddle_ve import VETextPostProcessor
                ve_pp = VETextPostProcessor()
                processed_text, ve_warnings = ve_pp.process_full_text(full_text)
                if ve_warnings:
                    for w in ve_warnings:
                        print(f"  [VE] {w}")
                full_text = processed_text
            except ImportError:
                pass  # No disponible, usar texto crudo

        # 4. Expandir abreviaciones antes del parseo
        full_text_expandido = self._expandir_abreviaciones(full_text)

        # 5. Extracción mejorada con nuevos módulos (FASE 4)
        inv = InvoiceData()
        inv.raw_text = full_text
        inv.ocr_confidence = avg_conf

        # 5a. Extracción avanzada de campos
        print("  [ADV] Extrayendo campos con patrones avanzados...")
        try:
            from ocr.advanced_field_extractor import extract_fields_advanced
            advanced_fields = extract_fields_advanced(full_text_expandido, words)
            for key, value in advanced_fields.items():
                if value and not getattr(inv, key, None):
                    setattr(inv, key, value)
        except ImportError:
            pass  # Usar extracción clásica si no está disponible

        # 5b. Detección de layout (FASE 4)
        print("  [LAYOUT] Detectando layout de factura...")
        try:
            from ocr.layout_detector import extract_fields_by_layout
            layout_fields = extract_fields_by_layout(words)
            for key, value in layout_fields.items():
                if value and not getattr(inv, key, None):
                    setattr(inv, key, value)
        except ImportError:
            pass

        # 5c. Detección de campos POS (FASE 4)
        print("  [POS] Detectando campos de punto de venta...")
        try:
            from ocr.pos_fields_detector import detect_pos_fields, is_pos_invoice
            if is_pos_invoice(full_text):
                pos_fields = detect_pos_fields(full_text)
                for key, value in pos_fields.items():
                    setattr(inv, key, value)
                print(f"  [POS] Factura POS detectada, {len(pos_fields)} campos extraídos")
        except ImportError:
            pass

        # 5d. Extracción clásica por regex (fallback)
        self._parse_fields(inv, full_text_expandido, words_sorted)

        # 5e. Intentar extracción por contexto (FASE 2)
        context_fields = self._try_context_extraction(full_text_expandido, words, image)
        for key, value in context_fields.items():
            if value and not getattr(inv, key, None):
                setattr(inv, key, value)

        # 5f. Corrección automática de errores OCR (FASE 4)
        print("  [CORR] Aplicando correcciones automáticas de OCR...")
        try:
            from ocr.ocr_corrector import correct_ocr_fields
            inv_dict = inv.to_dict()
            corrected_fields, corrections = correct_ocr_fields(inv_dict, use_context=True)
            for key, value in corrected_fields.items():
                setattr(inv, key, value)
            if corrections:
                print(f"  [CORR] {len(corrections)} correcciones aplicadas")
        except ImportError:
            pass

        # 5f-bis. Corrección NLP avanzada (FASE 4)
        print("  [NLP] Aplicando corrección NLP avanzada...")
        try:
            from ocr.nlp_corrector import NLPCorrector
            nlp_corrector = NLPCorrector()
            inv_dict = inv.to_dict()
            nlp_corrections = []
            for key, value in inv_dict.items():
                if isinstance(value, str) and len(value) > 0:
                    corrected, corrections = nlp_corrector.correct_text(value, field_name=key)
                    if corrected != value:
                        setattr(inv, key, corrected)
                        nlp_corrections.extend(corrections)
            if nlp_corrections:
                print(f"  [NLP] {len(nlp_corrections)} correcciones NLP aplicadas")
        except ImportError:
            pass

        # 5g. Aplicar correcciones aprendidas (FASE 4)
        print("  [LEARN] Aplicando correcciones aprendidas...")
        try:
            from ocr.correction_learner import apply_learned_corrections
            inv_dict = inv.to_dict()
            learned_corrected, learned_corrections = apply_learned_corrections(inv_dict)
            for key, value in learned_corrected.items():
                setattr(inv, key, value)
            if learned_corrections:
                print(f"  [LEARN] {len(learned_corrections)} correcciones aprendidas aplicadas")
        except ImportError:
            pass

        # 5h. Extracción de items/líneas de factura (FASE 4)
        print("  [ITEMS] Extrayendo items de factura...")
        try:
            from ocr.items_extractor import extract_invoice_items
            items = extract_invoice_items(full_text_expandido, words)
            if items:
                # Convertir items a string para el campo items (que es str en InvoiceData)
                items_text = "\n".join([
                    f"{i.quantity or 0} x {i.description} = {i.line_total or 0}"
                    for i in items
                ])
                inv.items = items_text
                print(f"  [ITEMS] {len(items)} items extraídos")
        except ImportError:
            pass

        # 5h-bis. Detección de tablas complejas (FASE 4)
        print("  [TABLE] Detectando tablas complejas...")
        try:
            from ocr.table_detector import TableDetector
            table_detector = TableDetector()
            tables = table_detector.detect(image, words)
            if tables:
                table_data = table_detector.extract_table_data(tables[0])
                inv.tables = table_data
                print(f"  [TABLE] {len(tables)} tablas detectadas, {len(table_data)} filas")
        except ImportError:
            pass

        # 5i. Detección de tipo de documento (FASE 4)
        print("  [DOCTYPE] Detectando tipo de documento...")
        try:
            from ocr.document_type_detector import detect_document_type
            doc_detection = detect_document_type(full_text)
            inv.document_type = doc_detection.document_type.value
            inv.document_subtype = doc_detection.subtype
            print(f"  [DOCTYPE] Tipo: {doc_detection.document_type.value}, Subtipo: {doc_detection.subtype}")
        except ImportError:
            pass

        # 5j. Validación de RIF (FASE 4)
        print("  [RIF] Validando RIF...")
        try:
            from ocr.rif_validator import validate_rif, normalize_rif
            if inv.rif_emisor:
                rif_validation = validate_rif(inv.rif_emisor)
                if rif_validation.is_valid_format:
                    inv.rif_emisor = rif_validation.normalized_rif
                    if rif_validation.is_valid_checksum:
                        print(f"  [RIF] RIF válido: {rif_validation.normalized_rif}")
                    else:
                        print(f"  [RIF] RIF con checksum inválido (formato OK)")
                        inv.validation_errors.append(f"RIF con checksum inválido: {inv.rif_emisor}")
                else:
                    print(f"  [RIF] RIF con formato inválido: {rif_validation.errors}")
                    inv.validation_errors.extend(rif_validation.errors)
        except ImportError:
            pass

        # 4c-bis. Aplicar correcciones de usuario (feedback loop)
        # Si el usuario ha corregido algún campo antes, el valor corregido
        # reemplaza automáticamente al valor extraído.
        if _FORMAT_LEARNER_AVAILABLE:
            try:
                learner = _get_learner()
                if learner:
                    inv_dict = inv.to_dict()
                    corrected = learner.apply_corrections_to_fields(inv_dict)
                    for key, value in corrected.items():
                        if value != getattr(inv, key, None):
                            setattr(inv, key, value)
            except Exception:
                pass

        # 4d. Aprender (FASE 2) - registrar esta factura para mejorar futuras
        self._try_learn_from_invoice(image, words, inv)

        # Si hay motor VE, recolectar estadísticas
        if hasattr(self.ocr_engine, '_paddle_ve') and self.ocr_engine._paddle_ve:
            inv.ocr_stats = self.ocr_engine._paddle_ve.get_stats()

        # 5. Obtener tasas multi-moneda y convertir montos
        if CONFIG.ocr.bcv_enabled:
            try:
                from ocr.bcv_rate import CurrencyRateProvider, convert_currency, get_currency_provider
                provider = get_currency_provider()
                all_rates = provider.get_all_rates()
                inv.all_rates = {k: v for k, v in all_rates.items()
                                 if isinstance(v, (int, float))}
                inv.exchange_rate = all_rates.get('BS', all_rates.get('VES', CONFIG.ocr.bcv_default_rate))
                inv.ocr_stats['exchange_rates'] = dict(inv.all_rates)

                # Convertir total a todas las monedas si hay monto detectado
                if inv.total:
                    total_num = self._parse_ve_decimal(inv.total)
                    if total_num and total_num > 0:
                        src_currency = inv.currency if inv.currency else 'BS'
                        if src_currency not in CONFIG.ocr.enabled_currencies:
                            src_currency = 'BS'

                        conv = provider.convert_to_all(total_num, src_currency)
                        inv.total_bs = conv.get('BS', 0.0)
                        inv.total_usd = conv.get('USD', 0.0)
                        inv.total_eur = conv.get('EUR', 0.0)
                        inv.total_cop = conv.get('COP', 0.0)
                        inv.total_ars = conv.get('ARS', 0.0)
            except ImportError:
                pass

        # 6. Validacion clasica VE (compatibilidad hacia atras)
        # Corre primero para no duplicar con FASE 3
        self._validate(inv)

        # 7. Post-procesamiento FASE 3 (tipado, cross-validation, inconsistencias)
        # Agrega capa extra de validacion sin duplicar errores de _validate()
        try:
            from ocr.postprocessor import PostProcessor
            pp = PostProcessor()
            typed = pp.process(inv)
            # Solo agregar inconsistencias que _validate() no cubrio
            for inc in typed.inconsistencies:
                if inc["severity"] in ("error", "critical"):
                    msg = f"[F3:{inc['severity'].upper()}] {inc['message']}"
                    if msg not in inv.validation_errors:
                        inv.validation_errors.append(msg)
        except ImportError:
            pass

        # 8. Guardar resultado en cache (FASE 4)
        print("  [CACHE] Guardando resultado en cache...")
        try:
            from ocr.ocr_cache import cache_ocr_result
            import cv2
            image_bytes = cv2.imencode('.png', image)[1].tobytes()
            cache_ocr_result(image_bytes, inv.to_dict())
            print("  [CACHE] Resultado guardado en cache")
        except ImportError:
            pass

        # 9. Registrar métricas de procesamiento (FASE 4)
        print("  [METRICS] Registrando métricas...")
        try:
            from ocr.ocr_metrics import log_ocr_processing
            processing_time_ms = (time.time() - start_time) * 1000
            log_ocr_processing(inv.to_dict(), processing_time_ms)
            print(f"  [METRICS] Tiempo de procesamiento: {processing_time_ms:.2f}ms")
        except ImportError:
            pass

        # 10. Sistema de notificaciones (FASE 4)
        print("  [NOTIF] Verificando notificaciones...")
        try:
            from ocr.notifications import NotificationSystem, notify_ocr_quality
            notification_system = NotificationSystem()
            
            # Notificar calidad
            if inv.ocr_confidence:
                notification_system.notify_low_confidence(inv.ocr_confidence)
            
            # Notificar tiempo de procesamiento
            processing_time_ms = (time.time() - start_time) * 1000
            notification_system.notify_slow_processing(processing_time_ms)
            
            # Notificar errores de validación
            if inv.validation_errors:
                notification_system.notify_validation_error(inv.validation_errors)
            
            # Notificación de conveniencia
            notify_ocr_quality(inv.ocr_confidence or 0, processing_time_ms, inv.validation_errors)
            print("  [NOTIF] Sistema de notificaciones activo")
        except ImportError:
            pass

        return inv

    def export_result(self, inv: InvoiceData, output_path: str, format: str = 'json'):
        """
        Exporta el resultado OCR a diferentes formatos.
        
        Args:
            inv: InvoiceData a exportar
            output_path: Ruta del archivo de salida
            format: Formato de exportación (csv, excel, json, pdf)
        """
        try:
            from ocr.exporter import export_ocr_result
            export_ocr_result(inv.to_dict(), output_path, format)
            print(f"[EXPORT] Resultado exportado a {format}: {output_path}")
        except ImportError:
            print("[EXPORT] Error: módulo de exportación no disponible")

    def export_all_formats(self, inv: InvoiceData, base_path: str):
        """
        Exporta el resultado OCR a todos los formatos disponibles.
        
        Args:
            inv: InvoiceData a exportar
            base_path: Ruta base sin extensión
        """
        try:
            from ocr.exporter import OCRResultExporter
            exporter = OCRResultExporter()
            exporter.export_all_formats(inv.to_dict(), base_path)
            print(f"[EXPORT] Resultado exportado a todos los formatos: {base_path}")
        except ImportError:
            print("[EXPORT] Error: módulo de exportación no disponible")

    def _try_context_extraction(
        self,
        text: str,
        words: List[Tuple[str, Tuple[float, float, float, float], float]],
        image: np.ndarray,
    ) -> Dict[str, str]:
        """
        Intenta extracción por contexto semántico (FASE 2).
        Retorna dict de campos extraídos, vacío si no disponible.
        """
        if not _FORMAT_LEARNER_AVAILABLE:
            return {}
        try:
            learner = _get_learner()
            if learner is None:
                return {}

            # Buscar cluster similar
            cluster = learner.match_cluster(image)

            # Extraer por contexto
            extractor = LearnerFieldExtractor(cluster)
            return extractor.extract(text, words, image.shape)
        except Exception as e:
            print(f"  [F2] Context extraction error: {e}")
            return {}

    def _try_learn_from_invoice(
        self,
        image: np.ndarray,
        words: List[Tuple[str, Tuple[float, float, float, float], float]],
        inv: InvoiceData,
    ):
        """
        Intenta aprender de esta factura (FASE 2).
        Silencioso si no disponible.
        """
        if not _FORMAT_LEARNER_AVAILABLE:
            return
        try:
            learner = _get_learner()
            if learner is None:
                return

            invoice_data = {
                k: str(v) for k, v in inv.to_dict().items()
                if v and str(v).strip()
            }
            cid = learner.learn_from_invoice(image, words, invoice_data)
            print(f"  [F2] Aprendido en cluster {cid}")
        except Exception as e:
            pass  # Aprendizaje silencioso

    # Palabras que NO son números de factura/control aunque aparezcan justo
    # después de "FACTURA" (evita que el patrón greedy capture la siguiente
    # etiqueta del documento, ej. "FACTURA \n RIF: J-..." → antes capturaba "RIF").
    # ═══════════════════════════════════════════════════════════
    #  Lista de bancos venezolanos + abreviaciones comunes
    # ═══════════════════════════════════════════════════════════
    _BANCOS_VE = [
        # Diccionario: (nombre_completo, [abreviaciones, siglas, variaciones])
        ("Banco de Venezuela", ["BDV", "Bco de Venezuela", "Banco Venezuela", "BdV"]),
        ("Banco Mercantil", ["MERCANTIL", "Bco Mercantil", "Mercantil Ban"]),
        ("Banco Provincial", ["PROVINCIAL", "Bco Provincial", "Provincial BBVA", "BBVA Provincial"]),
        ("Banesco", ["BANESCO", "Bco Banesco"]),
        ("Banco Nacional de Crédito", ["BNC", "Bco Nacional Credito", "BNC Bco"]),
        ("Banco Exterior", ["EXTERIOR", "Bco Exterior", "Exterior Bco"]),
        ("Banco Occidental de Descuento", ["BOD", "Bco Occidental", "Occidental Descuento"]),
        ("Banco del Tesoro", ["TESORO", "Bco Tesoro", "Del Tesoro"]),
        ("Banco Bicentenario", ["BICENTENARIO", "Bco Bicentenario"]),

        ("Banco Sofitasa", ["SOFITASA", "Sofitasa Bco"]),
        ("Banco Caroní", ["CARONI", "CARONÍ", "Bco Caroni"]),
        ("Banco Fondo Común", ["BFC", "Fondo Comun", "Fdo Comun"]),
        ("Banco Activo", ["ACTIVO", "Bco Activo"]),
        ("Banco Plaza", ["PLAZA", "Bco Plaza"]),
        ("Mi Banco", ["MI BANCO", "Microbanco"]),
        ("100% Banco", ["100%", "CIEN POR CIENTO"]),
        ("Banco del Sur", ["SUR", "Bco del Sur"]),
        ("Bancamiga", ["BANCAMIGA", "Banco Amiga"]),
        ("Citibank", ["CITI", "Citibank Venezuela"]),
        ("Banco Industrial de Venezuela", ["BIV", "Industrial Venezuela"]),
        # Cooperativas y otros
        ("Cooperativa", ["COOP", "Cooperativa"]),
        ("Instituto Municipal de Crédito", ["IMC"]),
    ]

    # ═══════════════════════════════════════════════════════════
    #  Patrones de tipo de comprobante
    # ═══════════════════════════════════════════════════════════
    _TIPO_COMPROBANTE = [
        # (patron_regex, tipo_asignado, clasificacion)
        # Facturas de Venta
        (r"FACTURA\s*(?:DE\s*)?VENTA", "Factura de Venta", "Venta"),
        (r"FACTURA\s*(?:DE\s*)?COMPRA", "Factura de Compra", "Compra"),
        (r"FACTURA", "Factura", "Venta"),  # generico
        # Notas
        (r"NOTA\s*(?:DE\s*)?D[EÉ]BITO", "Nota de Débito", "Otro"),
        (r"NOTA\s*(?:DE\s*)?CR[EÉ]DITO", "Nota de Crédito", "Otro"),
        (r"NOTA\s*(?:DE\s*)?ENTREGA", "Nota de Entrega", "Otro"),
        # Recibos
        (r"RECIBO\s*(?:DE\s*)?(?:PAGO|CAJA|INGRESO)", "Recibo", "Otro"),
        (r"RECIBO", "Recibo", "Otro"),
        # Presupuesto / Cotización
        (r"PRESUPUESTO", "Presupuesto", "Otro"),
        (r"COTIZACI[OÓ]N", "Cotización", "Otro"),
        # Otros
        (r"ORDEN\s*(?:DE\s*)?(?:COMPRA|PAGO|SERVICIO)", "Orden", "Otro"),
    ]

    # ═══════════════════════════════════════════════════════════
    #  Patrones para extraer items / detalle
    # ═══════════════════════════════════════════════════════════
    _ITEM_PATTERNS = [
        r"CANT[IÍ]DAD.*DESCRIPCI[OÓ]N.*PRECIO.*TOTAL",
        r"DESCRIPCI[OÓ]N.*CANT[IÍ]DAD.*PRECIO",
        r"CANT\s*PROD[UÚ]CTO.*P\.?\s*UNIT\.?.*TOTAL",
        r"ART[IÍ]CULO.*CANT\.?.*PRECIO",
    ]

    # ═══════════════════════════════════════════════════════════
    #  Diccionario de abreviaciones contables/fiscales VE
    # ═══════════════════════════════════════════════════════════
    # Mapea abreviaturas comunes en facturas venezolanas a su forma
    # completa. Se aplica ANTES de los regex para que patrones como
    # "C.I.", "TELF.", "CTA. CTE.", "COND. PAGO", "P/U", "BS.",
    # "NRO.", "OBS." sean reconocidos como si estuvieran escritos
    # completos.
    #
    # Ordenados de más específico a más genérico para evitar que
    # "NRO" sea reemplazado antes que "NRO FACT" (más específico).
    _ABREVIACIONES: Dict[str, str] = {
        # ── Documento ──
        r"\bNRO\s+FACT\b": "NUMERO FACTURA",
        r"\bNRO\s+CTRL\b": "NUMERO CONTROL",
        r"\bNRO\b": "NUMERO",
        r"\bN°\b": "NUMERO",
        r"\bNº\b": "NUMERO",
        r"\bNO\.\b": "NUMERO",
        r"\bFACT\.?\b": "FACTURA",
        r"\bFC[OA]?\.?\b": "FACTURA",
        r"\bCTRL\b": "CONTROL",
        r"\bCTL\b": "CONTROL",

        # ── Identificación ──
        r"\bC\.?\s*I\.?\s*[\-:]?\b": "CEDULA IDENTIDAD",
        r"\bCI\b": "CEDULA IDENTIDAD",
        r"\bIDENTIF\.?\b": "IDENTIFICACION",
        r"\bR\.?\s*I\.?\s*F\.?\b": "RIF",
        r"\bRFC\b": "RIF",

        # ── Razón Social / Empresa ──
        r"\bRAZ\.?\s*SOC\.?\b": "RAZON SOCIAL",
        r"\bRS\b": "RAZON SOCIAL",
        r"\bDENOM\.?\s*SOC\.?\b": "DENOMINACION SOCIAL",
        r"\bC\.?\s*A\.?\b": "COMPANIA ANONIMA",
        r"\bCIA\b": "COMPANIA",
        r"\bCOM\.?\b": "COMERCIAL",
        r"\bPROV\.?\b": "PROVEEDOR",
        r"\bCLTE\.?\b": "CLIENTE",

        # ── Dirección ──
        r"\bDIR\.?\b": "DIRECCION",
        r"\bDCC\b": "DIRECCION",
        r"\bAVDA\.?\b": "AVENIDA",
        r"\bAV\.?\b": "AVENIDA",
        r"\bCLL\.?\b": "CALLE",
        r"\bEDIF\.?\b": "EDIFICIO",
        r"\bEDO\.?\b": "ESTADO",
        r"\bMUNIC\.?\b": "MUNICIPIO",
        r"\bURB\.?\b": "URBANIZACION",
        r"\bSEC\.?\b": "SECTOR",
        r"\bDPTO\.?\b": "DEPARTAMENTO",
        r"\bOFC\.?\b": "OFICINA",
        r"\bTDA\.?\b": "TIENDA",
        r"\bPISO\b": "PISO",
        r"\bLOCAL\b": "LOCAL",

        # ── Teléfono ──
        r"\bTELF\.?\b": "TELEFONO",
        r"\bTEL\.?\b": "TELEFONO",
        r"\bTFNO\b": "TELEFONO",
        r"\bTLF\b": "TELEFONO",
        r"\bTELEF\.?\b": "TELEFONO",
        r"\bCEL\.?\b": "CELULAR",

        # ── Banco / Cuenta ──
        r"\bBCO\.?\b": "BANCO",
        r"\bCTA\.?\b": "CUENTA",
        r"\bCTACTE\b": "CUENTA CORRIENTE",
        r"\bCTAC\b": "CUENTA CORRIENTE",
        r"\bCTE\.?\b": "CORRIENTE",
        r"\bCTAAH\b": "CUENTA AHORROS",
        r"\bC/C\b": "CUENTA CORRIENTE",
        r"\bCHQ\.?\b": "CHEQUE",
        r"\bCH\.?\b": "CHEQUE",
        r"\bCHEQ\.?\b": "CHEQUE",
        r"\bCH/\b": "CHEQUE",

        # ── Montos ──
        r"\bBS\.?\s*$": "BOLIVARES",
        r"\bBS\.?\s": "BOLIVARES ",
        r"\bBOL\.?\s*$": "BOLIVARES",
        r"\bBOL\b": "BOLIVARES",  # sin punto al final
        r"\bVES\b": "BOLIVARES",
        r"\bUSD\b": "DOLARES",
        r"\bDLS\b": "DOLARES",
        r"\bDOL\.?\b": "DOLARES",
        r"\bP\s*U\b": "PRECIO UNITARIO",
        r"\bP\.?\s*UNIT\.?\b": "PRECIO UNITARIO",
        r"\bP\s*TOTAL\b": "PRECIO TOTAL",
        r"\bP\s*TOT\b": "PRECIO TOTAL",
        r"\bTOT\.?\b": "TOTAL",
        r"\bSUB\.?\s*TOT\.?\b": "SUBTOTAL",
        r"\bSUBTOT\.?\b": "SUBTOTAL",
        r"\bSUBT\.?\b": "SUBTOTAL",
        r"\bBASE\s*IMP\.?\b": "BASE IMPONIBLE",
        r"\bIMP\.?\b": "IMPORTE",
        r"\bIMPONIBLE\b": "IMPORTE",
        r"\bEXENTO\b": "EXENTO",  # mantiene igual pero ayuda a stopwords

        # ── IVA / Impuestos ──
        r"\bI\.?\s*V\.?\s*A\.?\b": "IVA",
        r"\bI\.?\s*S\.?\s*L\.?\s*R\.?\b": "ISLR",
        r"\bRET\.?\s*IVA\b": "RETENCION IVA",
        r"\bRET\.?\s*ISLR\b": "RETENCION ISLR",
        r"\bRET\.?\b": "RETENCION",

        # ── Condiciones ──
        r"\bCOND\.?\s*PAG\.?\b": "CONDICION DE PAGO",
        r"\bCOND\.?\s*PAGO\b": "CONDICION DE PAGO",
        r"\bCOND\.?\b": "CONDICION",
        r"\bFORMA\s*PAGO\b": "FORMA DE PAGO",
        r"\bF\.?\s*PAGO\b": "FORMA DE PAGO",
        r"\bPAG\.?\b": "PAGO",
        r"\bPLAZO\b": "PLAZO",
        r"\bCRED\.?\b": "CREDITO",
        r"\bCONT\.?\b": "CONTADO",

        # ── Items / Detalle ──
        r"\bCANT\.?\b": "CANTIDAD",
        r"\bDESC\.?\b": "DESCRIPCION",
        r"\bDCTO\.?\b": "DESCUENTO",
        r"\bDTO\.?\b": "DESCUENTO",
        r"\bDESCTO\b": "DESCUENTO",
        r"\bCOD\.?\b": "CODIGO",
        r"\bUND\.?\b": "UNIDAD",
        r"\bUNID\.?\b": "UNIDAD",

        # ── Otros ──
        r"\bOBS\.?\b": "OBSERVACIONES",
        r"\bREF\.?\b": "REFERENCIA",
        r"\bS/N\b": "SIN NUMERO",
        r"\bO/C\b": "ORDEN COMPRA",
        r"\bSR\.?\b": "SENOR",
        r"\bSRA\.?\b": "SENORA",
        r"\bSRES\.?\b": "SENORES",
        r"\bGRAL\.?\b": "GENERAL",
        r"\bCANT\.?\s*X\b": "CANTIDAD POR",

        # ── Meses (abreviados) ──
        r"\bENE\.?\b": "ENERO",
        r"\bFEB\.?\b": "FEBRERO",
        r"\bMAR\.?\b": "MARZO",
        r"\bABR\.?\b": "ABRIL",
        r"\bMAY\.?\b": "MAYO",
        r"\bJUN\.?\b": "JUNIO",
        r"\bJUL\.?\b": "JULIO",
        r"\bAGO\.?\b": "AGOSTO",
        r"\bSEP\.?\b": "SEPTIEMBRE",
        r"\bOCT\.?\b": "OCTUBRE",
        r"\bNOV\.?\b": "NOVIEMBRE",
        r"\bDIC\.?\b": "DICIEMBRE",
    }

    _FIELD_LABEL_STOPWORDS = {
        "RIF", "FECHA", "CLIENTE", "CONTROL", "TOTAL", "TELEFONO", "TELÉFONO",
        "DIRECCION", "DIRECCIÓN", "RAZON", "RAZÓN", "SOCIAL", "BASE", "IVA",
        "SUBTOTAL", "CONDICION", "CONDICIÓN", "PAGO", "NUMERO", "NO", "NRO",
    }

    def _is_plausible_id(self, candidate: str) -> bool:
        """Un número de factura/control real debe tener al menos un dígito
        y no ser en realidad la etiqueta de otro campo."""
        if not candidate:
            return False
        stripped = candidate.strip(":.-# ").upper()
        if stripped in self._FIELD_LABEL_STOPWORDS:
            return False
        if not any(c.isdigit() for c in stripped):
            return False
        return True

    def _parse_fields(self, inv: InvoiceData, full_text: str, words: List[Tuple]):
        """Aplica regex para extraer cada campo."""
        # Número de factura
        for pattern in self.PATTERNS["numero_factura"]:
            m = re.search(pattern, full_text, re.IGNORECASE)
            if m:
                candidate = m.group(1) if m.lastindex else m.group(0)
                candidate = re.sub(r'[^A-Z0-9/\-]', '', candidate.upper())
                if not self._is_plausible_id(candidate):
                    continue
                inv.numero_factura = candidate
                break

        # Número de control
        for pattern in self.PATTERNS["numero_control"]:
            m = re.search(pattern, full_text, re.IGNORECASE)
            if m:
                candidate = m.group(1) if m.lastindex else m.group(0)
                candidate = re.sub(r'[^A-Z0-9/\-]', '', candidate.upper())
                if not self._is_plausible_id(candidate):
                    continue
                inv.numero_control = candidate
                break

        # Fecha
        for pattern in self.PATTERNS["fecha"]:
            m = re.search(pattern, full_text, re.IGNORECASE)
            if m:
                inv.fecha = m.group(1).replace("-", "/")
                parts = inv.fecha.split("/")
                if len(parts) == 3 and len(parts[0]) == 4:
                    inv.fecha = f"{parts[2]}/{parts[1]}/{parts[0]}"
                break

        # RIF
        for pattern in self.PATTERNS["rif_emisor"]:
            m = re.search(pattern, full_text, re.IGNORECASE)
            if m:
                if m.lastindex and m.lastindex >= 3:
                    inv.rif_emisor = f"{m.group(1).upper()}-{m.group(2)}-{m.group(3)}"
                else:
                    inv.rif_emisor = m.group(1) if m.lastindex else m.group(0).upper()
                rif_clean = re.sub(r'[^VJEGPC\d]', '', inv.rif_emisor)
                if len(rif_clean) >= 10:
                    inv.rif_emisor = f"{rif_clean[0]}-{rif_clean[1:9]}-{rif_clean[9]}"
                break

        # Razón social: texto cerca del RIF
        razon_text = self._extract_nearby_text(words, ["RAZ[OÓ]N SOCIAL", "RIF"], 100)
        for pattern in [
            r"RAZ[OÓ]N SOCIAL\s*[:.\-]?\s*(.+?)(?:\d|\||$)",
            r"(?:COMERCIALIZADORA|EMPRESA|SERVICIOS|C\.A\.|S\.A\.|C\.,A\.)\s*[\w\sÁÉÍÓÚÑáéíóúñ]+",
        ]:
            m = re.search(pattern, razon_text, re.IGNORECASE)
            if m:
                inv.razon_social = (m.group(1) if m.lastindex else m.group(0)).strip().rstrip(",")
                break
        if not inv.razon_social:
            for t, _, _ in words:
                if len(t) > 10 and not re.search(r"\d", t) and re.search(r"[A-ZÁÉÍÓÚÑ]{4,}", t):
                    inv.razon_social = t[:100]
                    break

        # Cliente
        for pattern in [r"CLIENTE\s*[:.\-]?\s*(.+?)(?:\bRIF|\bTEL|$|\n)", r"RECEPTOR\s*[:.\-]?\s*(.+?)(?:\bRIF|$|\n)"]:
            m = re.search(pattern, full_text, re.IGNORECASE)
            if m:
                inv.cliente = m.group(1).strip().rstrip(",")
                break

        # Dirección
        for pattern in [r"DIRECCI[OÓ]N\s*[:.\-]?\s*(.+?)(?:\bTEL|$|\n)",
                        r"DIRECCION\s*[:.\-]?\s*(.+?)(?:\bTEL|$|\n)"]:
            m = re.search(pattern, full_text, re.IGNORECASE)
            if m:
                inv.direccion = m.group(1).strip()[:200]
                break

        # Teléfono
        for pattern in self.PATTERNS["telefono"]:
            m = re.search(pattern, full_text, re.IGNORECASE)
            if m:
                inv.telefono = m.group(1).strip() if m.lastindex else m.group(0).strip()
                inv.telefono = re.sub(r'[^\d+]', '', inv.telefono)
                break

        # Base imponible
        for pattern in self.PATTERNS["base_imponible"]:
            m = re.search(pattern, full_text, re.IGNORECASE)
            if m:
                inv.base_imponible = m.group(1).strip() if m.lastindex else m.group(0).strip()
                break

        # IVA
        for pattern in self.PATTERNS["iva"]:
            m = re.search(pattern, full_text, re.IGNORECASE)
            if m:
                inv.iva = m.group(1).strip() if m.lastindex else m.group(0).strip()
                break

        # Total
        for pattern in self.PATTERNS["total"]:
            m = re.search(pattern, full_text, re.IGNORECASE)
            if m:
                inv.total = next((g for g in m.groups() if g), None) or m.group(0)
                inv.total = inv.total.strip()
                break

        # Moneda (BS/USD/EUR/COP/ARS)
        inv.currency = CONFIG.ocr.currency_default  # por defecto
        if CONFIG.ocr.currency_auto_detect:
            for pattern in self.PATTERNS.get("currency", []):
                m = re.search(pattern, full_text, re.IGNORECASE)
                if m:
                    raw = m.group(1) if m.lastindex else m.group(0)
                    if re.search(r'(BS|Bs|bs\.?|BOL[IÍ]VAR(?:ES)?|VES)', raw, re.IGNORECASE):
                        inv.currency = "BS"; break
                    elif re.search(r'(€|EUR(?:O)?(?:S)?)', raw, re.IGNORECASE):
                        inv.currency = "EUR"; break
                    elif re.search(r'(COP|COL|PESO(?:S)?\s*COLOMBIANO)', raw, re.IGNORECASE):
                        inv.currency = "COP"; break
                    elif re.search(r'(ARS|ARG|PESO(?:S)?\s*ARGENTINO)', raw, re.IGNORECASE):
                        inv.currency = "ARS"; break
                    elif re.search(r'(\$|USD|D[OÓ]LAR(?:ES)?|DIVISAS)', raw, re.IGNORECASE):
                        inv.currency = "USD"; break

        # Condición de pago
        for pattern in self.PATTERNS["condicion_pago"]:
            m = re.search(pattern, full_text, re.IGNORECASE)
            if m:
                inv.condicion_pago = m.group(1).strip() if m.lastindex else m.group(0).strip()
                break

        # ── NUEVOS CAMPOS ──────────────────────────────────
        # Campos específicos de punto de venta (SERIAL/TER/AFIL/LOTE/TRACE
        # son campos de un comprobante de datáfono, no de una factura fiscal
        # normal). IMPORTANTE: cada `if not inv.<campo>` de aquí abajo es a
        # propósito — antes esto pisaba SIEMPRE el valor ya extraído
        # correctamente arriba (ej. un numero_factura real "0001-2345"
        # quedaba reemplazado por un SERIAL de datáfono si el documento
        # también traía esa palabra en otra sección). Estos campos ahora
        # solo RELLENAN huecos, nunca sobrescriben una extracción ya hecha.
        if not inv.numero_factura:
            for pattern in self.PATTERNS.get("serial", []):
                m = re.search(pattern, full_text, re.IGNORECASE)
                if m:
                    inv.numero_factura = m.group(1).strip() if m.lastindex else m.group(0).strip()
                    break

        if not inv.numero_control:
            for pattern in self.PATTERNS.get("ter", []):
                m = re.search(pattern, full_text, re.IGNORECASE)
                if m:
                    inv.numero_control = m.group(1).strip() if m.lastindex else m.group(0).strip()
                    break

        if not inv.cliente:
            for pattern in self.PATTERNS.get("afil", []):
                m = re.search(pattern, full_text, re.IGNORECASE)
                if m:
                    inv.cliente = m.group(1).strip() if m.lastindex else m.group(0).strip()
                    break

        if not inv.cedula_cliente:
            for pattern in self.PATTERNS.get("adquirente", []):
                m = re.search(pattern, full_text, re.IGNORECASE)
                if m:
                    inv.cedula_cliente = m.group(1).strip() if m.lastindex else m.group(0).strip()
                    break

        if not inv.items:
            for pattern in self.PATTERNS.get("lote", []):
                m = re.search(pattern, full_text, re.IGNORECASE)
                if m:
                    inv.items = m.group(1).strip() if m.lastindex else m.group(0).strip()
                    break

        if not inv.monto_letras:
            for pattern in self.PATTERNS.get("trace", []):
                m = re.search(pattern, full_text, re.IGNORECASE)
                if m:
                    inv.monto_letras = m.group(1).strip() if m.lastindex else m.group(0).strip()
                    break

        if not inv.banco:
            for pattern in self.PATTERNS.get("banco", []):
                m = re.search(pattern, full_text, re.IGNORECASE)
                if m:
                    inv.banco = m.group(0).strip()
                    break

        if not inv.tipo_comprobante:
            for pattern in self.PATTERNS.get("tipo_transaccion", []):
                m = re.search(pattern, full_text, re.IGNORECASE)
                if m:
                    inv.tipo_comprobante = m.group(1).strip() if m.lastindex else m.group(0).strip()
                    inv.tipo_documento = m.group(1).strip() if m.lastindex else m.group(0).strip()
                    break

        if not inv.direccion:
            for pattern in self.PATTERNS.get("ubicacion", []):
                m = re.search(pattern, full_text, re.IGNORECASE)
                if m:
                    inv.direccion = m.group(1).strip() if m.lastindex else m.group(0).strip()
                    break

        if not inv.condicion_pago:
            for pattern in self.PATTERNS.get("copia", []):
                m = re.search(pattern, full_text, re.IGNORECASE)
                if m:
                    inv.condicion_pago = m.group(1).strip() if m.lastindex else m.group(0).strip()
                    break

        # Tipo de comprobante (método existente)
        tipo_comp, tipo_doc = self._clasificar_tipo_comprobante(full_text)
        if tipo_comp:
            inv.tipo_comprobante = tipo_comp
            inv.tipo_documento = tipo_doc

        # Banco (método existente)
        banco = self._detectar_banco(full_text)
        if banco:
            inv.banco = banco

        # Numero de cuenta/cheque
        cuenta = self._extraer_numero_cuenta(full_text)
        if cuenta:
            inv.numero_cuenta = cuenta

        # Cedula del cliente
        cedula = self._extraer_cedula_cliente(full_text, inv)
        if cedula:
            inv.cedula_cliente = cedula

        # RIF del cliente
        for p in [
            r"RIF\s*(?:DEL\s*)?(?:CLIENTE|RECEPTOR|ADQUIRENTE)\s*[:.\-]?\s*([VJEGPC][\-.\s]?\d{8}[\-.\s]?\d)",
            r"(?:CLIENTE|RECEPTOR).*?RIF\s*[:.\-]?\s*([VJEGPC][\-.\s]?\d{8}[\-.\s]?\d)",
        ]:
            m = re.search(p, full_text, re.IGNORECASE)
            if m:
                rif_raw = m.group(1).upper().replace(" ", "").replace(".", "").replace("-", "").replace("\u2014", "")
                if len(rif_raw) >= 10:
                    inv.rif_cliente = f"{rif_raw[0]}-{rif_raw[1:9]}-{rif_raw[9]}"
                    break

        # Monto en letras
        monto_letras = self._extraer_monto_letras(full_text)
        if monto_letras:
            inv.monto_letras = monto_letras

        # Exento
        exento = self._extraer_exento(full_text)
        if exento:
            inv.exento = exento

        # Retencion ISLR
        retencion = self._extraer_retencion_islr(full_text)
        if retencion:
            inv.retencion_islr = retencion

        # Items / detalle
        items = self._extraer_items(full_text, words)
        if items:
            inv.items = items

    # ═══════════════════════════════════════════════════════════
    #  Nuevos métodos de extracción
    # ═══════════════════════════════════════════════════════════

    def _detectar_banco(self, full_text: str) -> str:
        """
        Detecta el nombre del banco en el texto de la factura.
        Busca coincidencias exactas y por abreviaciones en la lista
        de bancos venezolanos.
        """
        text_upper = full_text.upper()
        candidatos = []

        for nombre, variantes in self._BANCOS_VE:
            # Buscar cada variante en el texto
            for v in variantes:
                if v in text_upper:
                    candidatos.append((nombre, text_upper.index(v)))
                    break
            # Buscar el nombre completo
            if nombre.upper() in text_upper:
                idx = text_upper.index(nombre.upper())
                # Evitar duplicados
                if not any(c[0] == nombre for c in candidatos):
                    candidatos.append((nombre, idx))

        if not candidatos:
            return ""

        # Ordenar por posición de aparición (el primero es el más relevante)
        candidatos.sort(key=lambda c: c[1])
        return candidatos[0][0]

    def _clasificar_tipo_comprobante(self, full_text: str) -> Tuple[str, str]:
        """
        Clasifica el tipo de comprobante y su clasificación (Compra/Venta/Otro).
        Retorna (tipo_comprobante, tipo_documento).
        """
        text_upper = full_text.upper()

        for patron, tipo, clasif in self._TIPO_COMPROBANTE:
            m = re.search(patron, text_upper)
            if m:
                return tipo, clasif

        return "", ""

    def _extraer_items(self, full_text: str, words: List[Tuple]) -> str:
        """
        Intenta extraer el detalle de items de la factura.
        Busca la sección entre el encabezado (header) y los totales,
        donde suelen estar las líneas de productos/servicios.
        Retorna el texto de items encontrado.
        """
        if not full_text:
            return ""

        # Estrategia 1: Buscar entre keywords de header y total
        header_keywords = ["FACTURA", "CANT", "DESCRIPCIÓN", "DESCRIPCION",
                          "PRODUCTO", "ARTÍCULO", "ARTICULO", "CÓDIGO", "CODIGO"]
        total_keywords = ["SUBTOTAL", "TOTAL", "BASE", "IVA", "EXENTO",
                         "GRAVABLE", "SON:", "MONTO"]

        # Encontrar posiciones de inicio y fin de items
        start_pos = len(full_text)
        for kw in header_keywords:
            idx = full_text.upper().find(kw)
            if idx >= 0 and idx < start_pos:
                start_pos = idx

        end_pos = 0
        for kw in total_keywords:
            idx = full_text.upper().find(kw, start_pos + 10)
            if idx >= 0 and (idx > end_pos or end_pos == 0):
                end_pos = idx

        if start_pos < end_pos and end_pos - start_pos > 20:
            items_text = full_text[start_pos:end_pos].strip()
            return items_text[:1000]  # Max 1000 chars

        # Estrategia 2: Buscar líneas con patron de cantidad + descripción + precio
        item_lines = []
        for text, (x1, y1, x2, y2), conf in words:
            # Detectar si es una línea de item: número + texto + número
            if re.match(r'^\d+', text) and re.search(r'[\d.,]+$', text):
                item_lines.append(text)
            # O si tiene formato de precio
            elif re.match(r'^[\d.,]+$', text) and conf > 0.7:
                item_lines.append(text)

        if item_lines:
            return " ".join(item_lines[:30])

        return ""

    def _extraer_monto_letras(self, full_text: str) -> str:
        """Extrae el monto en letras (texto)."""
        # Buscar patron: "SON:" seguido de texto hasta número
        m = re.search(r'SON\s*[:.\-]?\s*(.+?)(?:\d[\.\d,]*|[A-Z]{3,}|$)', full_text, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            if len(candidate) > 15:  # Debe ser suficientemente largo
                return candidate[:200]

        # Buscar patron más genérico de monto en letras
        m = re.search(r'(?:SON|TOTAL)\s*:?\s*([A-ZÁÉÍÓÚÑ\s]+?)(?:\d)', full_text, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            if len(candidate) > 15:
                return candidate[:200]

        return ""

    def _extraer_cedula_cliente(self, full_text: str, inv: InvoiceData) -> str:
        """
        Extrae la cédula o identificación del cliente.
        Busca patrones como V-12345678, E-87654321, etc.
        Distingue entre RIF del emisor (ya extraído) y cédula del cliente.
        """
        # Buscar cédula: V-12345678, E-12345678, etc. que NO sea RIF letra
        ced_patterns = [
            r"(?:C[IÉ]DULA|C\.I\.|IDENTIFICACI[OÓ]N)\s*[:.\-]?\s*([VE]\-?\d{6,8})",
            r"(?:CLIENTE|RECEPTOR|COMPRADOR)\s*[:.\-]?[^\n]*?\b([VE]\-?\d{6,8})\b",
            r"\b([VE]\-?\d{6,8})\b",  # catch-all, filtraremos
        ]

        text_blocks = [full_text]
        # Separar por saltos de línea para mejor análisis contextual
        if "\n" in full_text:
            text_blocks = full_text.split("\n")

        for pattern in ced_patterns:
            for block in text_blocks:
                m = re.search(pattern, block, re.IGNORECASE)
                if m:
                    candidate = m.group(1)
                    # Normalizar
                    candidate = re.sub(r'[^VE\d]', '', candidate.upper())
                    if len(candidate) >= 7:
                        cedula = f"{candidate[0]}-{candidate[1:]}"
                        # Asegurar que NO sea el RIF del emisor
                        if inv.rif_emisor and inv.rif_emisor.replace('-', '').replace(' ', '')[:10] == cedula.replace('-', ''):
                            continue  # Es el mismo RIF del emisor, saltar
                        return cedula

        return ""

    def _extraer_exento(self, full_text: str) -> str:
        """Extrae el monto exento de IVA si está presente."""
        patterns = [
            r"EXENTO\s*[:.\-]?\s*([\d.,]+)",
            r"EXENTOS\s*[:.\-]?\s*([\d.,]+)",
        ]
        for p in patterns:
            m = re.search(p, full_text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

    def _extraer_retencion_islr(self, full_text: str) -> str:
        """Extrae retención de ISLR si está presente."""
        patterns = [
            r"(?:RETENCI[OÓ]N|RET\.?)\s*(?:ISLR|I\.?\s*S\.?\s*L\.?\s*R\.?)\s*[:.\-]?\s*([\d.,]+)",
            r"ISLR\s*[:.\-]?\s*([\d.,]+)",
        ]
        for p in patterns:
            m = re.search(p, full_text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

    def _extraer_numero_cuenta(self, full_text: str) -> str:
        """Extrae número de cuenta bancaria o de cheque.
        Solo patrones EXPLÍCITOS (CUENTA, CHEQUE) — el catch-all de
        9-20 dígitos causa falsos positivos con teléfonos y RIFs."""
        patterns = [
            # Cuenta corriente / ahorros
            r"(?:CUENTA|CTA\.?)\s*(?:CORRIENTE|AHORROS|AHORRO)?\s*[:.\-]?\s*(\d{9,20})",
            r"N[°º]?\s*(?:CUENTA|CTA)\s*[:.\-]?\s*(\d{9,20})",
            # Número de cheque
            r"(?:CHEQUE|CH\.?|N[°º]?\s*CHEQUE)\s*[:.\-]?\s*(\d{4,15})",
        ]
        for p in patterns:
            m = re.search(p, full_text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

    def _expandir_abreviaciones(self, texto: str) -> str:
        """
        Normaliza abreviaturas de facturas venezolanas a su forma completa.

        Aplica el diccionario _ABREVIACIONES secuencialmente sobre el texto,
        reemplazando formas abreviadas ("TELF.", "C.I.", "CTA. CTE.", "P/U",
        "NRO.", etc.) por su versión expandida ("TELEFONO", "CEDULA IDENTIDAD",
        "CUENTA CORRIENTE", "PRECIO UNITARIO", "NUMERO", etc.).

        Esto permite que los patrones regex de _parse_fields() funcionen
        incluso cuando la factura usa abreviaturas — el regex busca la
        palabra completa, y la abreviatura ya fue expandida.

        Args:
            texto: Texto crudo del OCR.

        Returns:
            Texto con abreviaturas reemplazadas por su forma completa.
        """
        if not texto:
            return texto

        resultado = texto
        # Aplicar cada abreviatura en orden (las más específicas primero)
        for patron, reemplazo in self._ABREVIACIONES.items():
            resultado = re.sub(patron, reemplazo, resultado, flags=re.IGNORECASE)

        return resultado

    def _extract_nearby_text(self, words: List[Tuple], keywords: List[str], y_margin: int = 100) -> str:
        """Extrae texto cercano a keywords."""
        keyword_ys = []
        for text, (x1, y1, x2, y2), _ in words:
            for kw in keywords:
                if kw.lower() in text.lower():
                    keyword_ys.append((y1 + y2) / 2)

        if not keyword_ys:
            return ""

        nearby = []
        ref_y = sum(keyword_ys) / len(keyword_ys)
        for text, (x1, y1, x2, y2), _ in words:
            center_y = (y1 + y2) / 2
            if abs(center_y - ref_y) < y_margin:
                nearby.append(text)

        return " ".join(nearby)

    def _validate(self, inv: InvoiceData):
        """Valida coherencia de los datos extraídos con reglas VE."""
        errors = inv.validation_errors

        # Validar RIF (si está activado)
        if inv.rif_emisor and CONFIG.ocr.ve_rif_validation:
            try:
                from ocr.paddle_ve import normalize_and_verify_rif
                rif_norm, rif_errors = normalize_and_verify_rif(inv.rif_emisor)
                if rif_errors:
                    errors.extend(rif_errors)
                if rif_norm:
                    inv.rif_emisor = rif_norm
            except ImportError:
                # Fallback simple
                rif_digits = re.sub(r"[^\d]", "", inv.rif_emisor)
                if len(rif_digits) < 9:
                    errors.append(f"RIF inválido: {inv.rif_emisor}")

        # Validar IVA vs Base (si está activado y tenemos datos)
        if CONFIG.ocr.ve_cross_validate:
            base = self._parse_ve_decimal(inv.base_imponible)
            iva = self._parse_ve_decimal(inv.iva)
            total = self._parse_ve_decimal(inv.total)

            if base and iva and base > 0 and iva > 0:
                # Detectar alícuota
                iva_rates = tuple(r/100.0 for r in CONFIG.ocr.ve_iva_rates)
                expected_values = {r: round(base * r, 2) for r in iva_rates}
                diffs = {r: abs(iva - v) for r, v in expected_values.items()}
                best_rate = min(diffs, key=diffs.get)
                expected_iva = expected_values[best_rate]
                rate_str = f"{best_rate*100:.0f}%"
                if diffs[best_rate] <= 1.0:
                    pass  # rate_str and expected_iva already set
                else:
                    rate_str = f"({iva:.2f})"
                    expected_iva = iva

                if abs(iva - expected_iva) > 1.0 and iva > 0:
                    errors.append(
                        f"IVA inconsistente: extraído {iva:.2f}, "
                        f"esperado ≈{expected_iva:.2f} ({rate_str} de {base:.2f})"
                    )

            if base and iva and total and base > 0 and total > 0:
                expected_total = round(base + iva, 2) if iva else base
                if abs(total - expected_total) > 2.0:
                    errors.append(
                        f"Total inconsistente: extraído {total:.2f}, "
                        f"esperado {expected_total:.2f} (base {base:.2f} + iva {iva:.2f})"
                    )

        if errors:
            for e in errors:
                print(f"  [WARN] Validación: {e}")
        else:
            print("  ✓ Datos validados correctamente")

    def _parse_ve_decimal(self, value: str) -> Optional[float]:
        """Parsea un decimal en formato venezolano."""
        if not value:
            return None
        try:
            from ocr.paddle_ve import parse_ve_amount
            return parse_ve_amount(value)
        except ImportError:
            pass

        clean = value.strip()
        if "," in clean:
            if "." in clean:
                clean = clean.replace(".", "").replace(",", ".")
            else:
                clean = clean.replace(",", ".")
        try:
            return float(clean)
        except ValueError:
            return None

    def interactive_correction(self, inv: InvoiceData) -> InvoiceData:
        """Muestra y permite corregir campos extraídos."""
        print("\n" + "=" * 60)
        print("DATOS EXTRAÍDOS — Verifique y corrija si es necesario:")
        print("=" * 60)

        fields = [
            ("tipo_comprobante", "Tipo Comprobante"),
            ("tipo_documento", "Tipo Doc"),
            ("numero_factura", "N° Factura"),
            ("numero_control", "N° Control"),
            ("fecha", "Fecha"),
            ("rif_emisor", "RIF Emisor"),
            ("razon_social", "Razón Social"),
            ("cliente", "Cliente"),
            ("cedula_cliente", "Cédula Cliente"),
            ("rif_cliente", "RIF Cliente"),
            ("direccion", "Dirección"),
            ("telefono", "Teléfono"),
            ("banco", "Banco"),
            ("numero_cuenta", "N° Cuenta/Cheque"),
            ("condicion_pago", "Condición de Pago"),
            ("base_imponible", "Base Imponible"),
            ("exento", "Exento"),
            ("iva", "IVA"),
            ("retencion_islr", "Retención ISLR"),
            ("total", "Total"),
            ("monto_letras", "Monto en Letras"),
            ("currency", "Moneda"),
            ("items", "Items (detalle)"),
        ]

        for attr, label in fields:
            current = getattr(inv, attr) or "(vacío)"
            if isinstance(current, str) and len(current) > 80:
                current = current[:77] + "..."
            print(f"  {label:22s}: {current}")

        # Mostrar validaciones
        if inv.validation_errors:
            print("\n[WARN] Advertencias:")
            for e in inv.validation_errors:
                print(f"  • {e}")

        # Mostrar estadísticas OCR
        if inv.ocr_stats:
            print(f"\n📊 Estadísticas OCR-VE:")
            for k, v in inv.ocr_stats.items():
                print(f"  {k}: {v}")

        print("\n¿Desea corregir algún campo? (deje vacío para continuar)")
        for attr, label in fields:
            current = getattr(inv, attr) or ""
            if isinstance(current, str) and len(current) > 80:
                current = current[:77] + "..."
            respuesta = input(f"  {label:22s} [{current}]: ").strip()
            if respuesta:
                setattr(inv, attr, respuesta)

        return inv


# ──────────────────────────────────────────────
#  Validación cruzada (PaddleOCR-VL vs OCR clásico)
# ──────────────────────────────────────────────
def extract_invoice_data_with_validation(
    image: np.ndarray,
    interactive: bool = True,
) -> InvoiceData:
    """
    Extrae datos con validación cruzada entre PaddleOCR-VL y OCR clásico.

    Flujo:
      1. PaddleOCR-VL (motor primario) extrae datos estructurados
      2. OCR clásico (validador) extrae datos con reglas/regex
      3. Validación cruzada de campos críticos (RIF, total)
      4. Si coinciden → aceptar automáticamente
      5. Si difieren → marcar para revisión manual

    Args:
        image: Imagen BGR del documento enderezado.
        interactive: Si True, permite corrección manual de campos.

    Returns:
        InvoiceData con los datos extraídos y validados.
    """
    from ocr.plugin_manager import create_backend
    from ocr.paddleocr_vl_backend import PaddleOCRVLBackend

    # Paso 1: PaddleOCR-VL (motor primario)
    vl_backend = create_backend('paddleocr_vl')
    vl_data = {}
    vl_confidence = 0.0
    
    if vl_backend and vl_backend.is_available():
        try:
            vl_backend.initialize()
            vl_data = vl_backend.extract_structured(image)
            vl_confidence = vl_data.get('confidence', 0.0)
            print(f"  [VLM] PaddleOCR-VL: confidence={vl_confidence:.3f}")
        except Exception as e:
            print(f"  [VLM] Error en PaddleOCR-VL: {e}")
    
    # Paso 2: OCR clásico (validador cruzado)
    parser = InvoiceParser()
    classic_data = parser.extract(image)
    print(f"  [VLM] OCR clásico: confidence={classic_data.confidence:.3f}")
    
    # Paso 3: Validación cruzada
    validated_data = cross_validate(vl_data, classic_data, vl_confidence)
    
    # Paso 4: Corrección interactiva si es necesario
    if interactive and validated_data.raw_text:
        validated_data = parser.interactive_correction(validated_data)
    
    return validated_data


def cross_validate(
    vl_data: Dict,
    classic_data: InvoiceData,
    vl_confidence: float,
) -> InvoiceData:
    """
    Valida cruzadamente datos de PaddleOCR-VL vs OCR clásico.

    Campos críticos validados:
      - RIF emisor
      - Total
      - Número factura

    Args:
        vl_data: Datos extraídos por PaddleOCR-VL
        classic_data: Datos extraídos por OCR clásico
        vl_confidence: Confianza de PaddleOCR-VL

    Returns:
        InvoiceData con datos validados
    """
    # Usar datos de PaddleOCR-VL como base si está disponible
    if vl_data and vl_confidence >= 0.75:
        # PaddleOCR-VL tiene buena confianza → usar como base
        validated = InvoiceData(
            numero_factura=vl_data.get('numero_factura', classic_data.numero_factura),
            rif_emisor=vl_data.get('rif_emisor', classic_data.rif_emisor),
            fecha=vl_data.get('fecha', classic_data.fecha),
            total=vl_data.get('total', classic_data.total),
            base_imponible=vl_data.get('base_imponible', classic_data.base_imponible),
            iva=vl_data.get('iva', classic_data.iva),
            raw_text=vl_data.get('raw_text', classic_data.raw_text),
            confidence=vl_confidence,
            motor_ocr='paddleocr_vl',
        )
    else:
        # PaddleOCR-VL tiene baja confianza → usar OCR clásico
        validated = classic_data
        validated.motor_ocr = 'paddle_classico'
    
    # Validación cruzada de campos críticos
    critical_fields = ['rif_emisor', 'total', 'numero_factura']
    discrepancies = []
    
    for field in critical_fields:
        vl_value = vl_data.get(field, '')
        classic_value = getattr(classic_data, field, '')
        
        if vl_value and classic_value and vl_value != classic_value:
            discrepancies.append({
                'field': field,
                'vl_value': vl_value,
                'classic_value': classic_value,
            })
    
    # Si hay discrepancias en campos críticos → marcar para revisión
    if discrepancies:
        validated.requiere_revision = True
        validated.validation_errors = [
            f"Discrepancia en {d['field']}: VLM='{d['vl_value']}' vs Clásico='{d['classic_value']}'"
            for d in discrepancies
        ]
        print(f"  [VLM] ⚠️ Discrepancias detectadas: {len(discrepancies)} campos")
    else:
        validated.requiere_revision = False
        print(f"  [VLM] ✅ Validación cruzada exitosa")
    
    return validated


# ──────────────────────────────────────────────
#  Función de alto nivel
# ──────────────────────────────────────────────
def extract_invoice_data(
    image: np.ndarray,
    interactive: bool = True,
) -> InvoiceData:
    """
    Extrae datos de una factura desde la imagen renderizada.

    Args:
        image: Imagen BGR del documento enderezado.
        interactive: Si True, permite corrección manual de campos.

    Returns:
        InvoiceData con los datos extraídos y validados.
    """
    parser = InvoiceParser()
    inv = parser.extract(image)

    if interactive and inv.raw_text:
        inv = parser.interactive_correction(inv)

    return inv


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        import cv2
        img = cv2.imread(sys.argv[1])
        if img is not None:
            data = extract_invoice_data(img, interactive=True)
            print("\nRESULTADO FINAL:")
            print(data.to_json())
        else:
            print(f"Error: No se pudo cargar la imagen '{sys.argv[1]}'")
    else:
        print("Uso: python -m ocr.extractor <ruta_imagen>")
