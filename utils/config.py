"""
Configuración central del sistema NAD Scanner.
===============================================
Parámetros ajustables por el operador.
"""

import os
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from enum import Enum


# ──────────────────────────────────────────────
#  Modos de captura disponibles
# ──────────────────────────────────────────────
class CaptureMode(str, Enum):
    """Modos de captura para diferentes tipos de documento."""
    FACTURA     = "factura"      # Factura / invoice — detección estándar
    ID          = "id"           # Cédula / pasaporte — detección fina, recorte preciso
    LIBRO       = "libro"        # Libro / páginas — detección con margen, sin glare
    FOTO        = "foto"         # Foto general — preservar color, detección laxa
    PIZARRA     = "pizarra"      # Pizarra / whiteboard — alto contraste, detección de bordes


# ──────────────────────────────────────────────
#  Configuración de cámara y captura
# ──────────────────────────────────────────────
@dataclass
class CaptureConfig:
    """Parámetros del Bloque 1 — Captura múltiple tipo PhotoScan."""

    camera_id: int = 0
    """ID del dispositivo de cámara (0 = webcam por defecto)."""

    resolution: Tuple[int, int] = (1920, 1080)
    """Resolución mínima de captura."""

    num_shots: int = 5
    """Número de tomas: 1 central + 4 anguladas."""

    guide_circles: List[Tuple[int, int]] = field(
        default_factory=lambda: [
            (960, 540),   # centro
            (480, 270),   # arriba-izquierda
            (1440, 270),  # arriba-derecha
            (480, 810),   # abajo-izquierda
            (1440, 810),  # abajo-derecha
        ]
    )
    """Posiciones (x, y) de los 4 círculos guía en pantalla (para 1920×1080)."""

    auto_capture_radius: int = 40
    """Píxeles de tolerancia para considerar un círculo alineado."""

    settle_frames: int = 5
    """Fotogramas consecutivos que debe mantenerse la alineación antes de capturar."""

    window_name: str = "NAD Scanner — Captura Multi-Toma"
    """Nombre de la ventana OpenCV."""

    # ── Nuevo: modo de captura activo ──
    mode: CaptureMode = CaptureMode.FACTURA
    """Modo de captura activo. Cambia parámetros de detección y overlay."""

    # ── Nuevo: edge detection en vivo ──
    edge_overlay_enabled: bool = True
    """Mostrar detección de bordes en vivo sobre la preview."""

    edge_overlay_opacity: float = 0.35
    """Opacidad del overlay de bordes (0 = invisible, 1 = sólido)."""

    # ── Nuevo: preview de perspectiva ──
    perspective_preview_enabled: bool = True
    """Mostrar ventana secundaria con preview de corrección de perspectiva en vivo."""

    perspective_preview_width: int = 640
    """Ancho máximo de la preview de perspectiva."""

    perspective_preview_update_interval: int = 10
    """Cada N frames, actualizar la preview de perspectiva (ahorra CPU)."""


# ──────────────────────────────────────────────
#  Configuración de detección de documento
# ──────────────────────────────────────────────
@dataclass
class DetectorConfig:
    """Parámetros del Bloque 4 — Detección de contornos."""

    gaussian_kernel: Tuple[int, int] = (5, 5)
    """Kernel del desenfoque gaussiano."""

    canny_low: int = 50
    """Umbral bajo de Canny (por defecto)."""

    canny_high: int = 150
    """Umbral alto de Canny (por defecto)."""

    approx_epsilon_percent: float = 0.02
    """Porcentaje del perímetro para approxPolyDP."""

    # ── Parámetros por modo de captura ──
    mode_params: dict = field(default_factory=lambda: {
        "factura": {
            "canny_low": 50,
            "canny_high": 150,
            "gaussian_kernel": (5, 5),
            "min_area_ratio": 0.05,
            "approx_epsilon": 0.02,
            "edge_color": (0, 255, 0),      # verde
        },
        "id": {
            "canny_low": 30,
            "canny_high": 100,
            "gaussian_kernel": (3, 3),
            "min_area_ratio": 0.02,
            "approx_epsilon": 0.015,
            "edge_color": (255, 200, 0),     # celeste
        },
        "libro": {
            "canny_low": 40,
            "canny_high": 130,
            "gaussian_kernel": (7, 7),
            "min_area_ratio": 0.10,
            "approx_epsilon": 0.025,
            "edge_color": (0, 200, 255),     # amarillo
        },
        "foto": {
            "canny_low": 60,
            "canny_high": 180,
            "gaussian_kernel": (5, 5),
            "min_area_ratio": 0.03,
            "approx_epsilon": 0.03,
            "edge_color": (255, 100, 100),   # rojo claro
        },
        "pizarra": {
            "canny_low": 20,
            "canny_high": 80,
            "gaussian_kernel": (7, 7),
            "min_area_ratio": 0.15,
            "approx_epsilon": 0.02,
            "edge_color": (255, 0, 255),     # magenta
        },
    })
    """Parámetros de detección específicos por modo."""


# ──────────────────────────────────────────────
#  Configuración de alineación
# ──────────────────────────────────────────────
@dataclass
class AlignConfig:
    """Parámetros del Bloque 2 — Alineación por características."""

    max_features: int = 5000
    """Número máximo de puntos clave a detectar (ORB)."""

    lowe_ratio: float = 0.75
    """Umbral del Lowe's ratio test para filtrar matches ambiguos."""

    min_matches: int = 10
    """Mínimo de matches válidos para aceptar una homografía."""

    ransac_reproj_threshold: float = 4.0
    """Umbral de reproyección para RANSAC en findHomography."""


# ──────────────────────────────────────────────
#  Configuración de fusión
# ──────────────────────────────────────────────
@dataclass
class FusionConfig:
    """Parámetros del Bloque 3 — Fusión anti-glare."""

    method: str = "median"
    """Método de fusión: 'median' o 'min'."""

    clahe_clip_limit: float = 2.0
    """Clip limit para CLAHE post-fusión."""

    clahe_grid_size: Tuple[int, int] = (8, 8)
    """Tamaño de la cuadrícula para CLAHE."""


# ──────────────────────────────────────────────
#  Configuración de realce
# ──────────────────────────────────────────────
@dataclass
class EnhanceConfig:
    """Parámetros del Bloque 5 — Realce tipo CamScanner."""

    output_mode: str = "documento"
    """Modo de salida: 'documento' (BN), 'grises', 'color'."""

    clahe_clip_limit: float = 2.0

    clahe_grid_size: Tuple[int, int] = (8, 8)

    adaptive_block_size: int = 11
    """Tamaño de bloque para adaptiveThreshold (debe ser impar)."""

    adaptive_c: int = 2
    """Constante restada en adaptiveThreshold."""

    morph_kernel_size: int = 3
    """Tamaño del kernel de morfología (limpieza de puntos)."""


# ──────────────────────────────────────────────
#  Configuración de OCR
# ──────────────────────────────────────────────
@dataclass
class OcrConfig:
    """Parámetros del Bloque 6 — OCR y extracción."""

    engine: str = "easyocr"
    """Motor OCR: 'easyocr' (Python puro, funciona en plataformas gratuitas),
        'tesseract' (requiere binarios del sistema), 'paddleocr_vl', 'paddle_ve', o 'paddle'.
        EasyOCR está configurado como motor principal para deployment en plataformas gratuitas
        porque no requiere binarios del sistema."""

    lang: str = "es"
    """Idioma para OCR."""

    confidence_threshold: float = 0.1
    """Confianza mínima para aceptar una palabra.
        Reducido temporalmente para diagnosticar problemas de Tesseract."""

    paddle_use_angle_cls: bool = True
    """Usar clasificador de ángulo en PaddleOCR."""

    tesseract_cmd: str = ""
    """Ruta al binario de Tesseract. En Render.com se instala vía apt-get,
        así que no se necesita ruta específica. En Windows local apunta a:
        C:/Program Files/Tesseract-OCR/tesseract.exe"""

    # ── Configuración VE ──
    ve_mode: bool = True
    """Activar post-procesamiento especializado para facturas venezolanas."""

    ve_rif_validation: bool = True
    """Validar dígito verificador de RIF."""

    ve_iva_rate_default: float = 16.0
    """Alícuota de IVA por defecto en Venezuela (%)."""

    ve_iva_rates: Tuple[float, ...] = (16.0, 8.0)
    """Alícuotas de IVA permitidas en Venezuela."""

    ve_cross_validate: bool = True
    """Validar coherencia Base + IVA = Total."""

    ve_dict_path: str = ""
    """Ruta al diccionario VE personalizado (vacío = usar el embebido)."""

    # ── Configuración de moneda multi-divisa ──
    bcv_enabled: bool = True
    """Activar detección de moneda y consulta de tasas."""

    bcv_default_rate: float = 60.50
    """Tasa por defecto BS/USD si no se puede obtener online."""

    bcv_api_url: str = "https://www.bcv.org.ve/tasas-cambio"
    """URL del sitio oficial del BCV para scraping."""

    bcv_cache_ttl: int = 21600
    """TTL de caché de tasas en segundos (default: 6h)."""

    dolarapi_url: str = "https://ve.dolarapi.com/v1/dolares"
    """API de dolarapi.com para tasas BCV oficial y paralelo."""

    dolarvzla_url: str = "https://rates.dolarvzla.com/v1/usd/bcv.json"
    """API de dolarvzla.com (datos desde CDN, sin rate limiting)."""

    pydolarve_url: str = "https://pydolarve.org/api/v1/dollar"
    """API de pydolarve.org para tasas BCV + paralelo."""

    cotizave_url: str = "https://api.cotizave.com/v1/fx/rates/reference"
    """API de cotizave.com (requiere API key en X-API-Key header)."""

    cotizave_api_key: str = ""
    """API key para cotizave.com (vacío = no usar esta fuente)."""

    exchange_sources_enabled: Tuple[str, ...] = (
        "exchangerate", "dolarapi", "dolarvzla", "pydolarve", "bcv_scrape", "cotizave"
    )
    """Orden de fuentes para obtener tasas. Vacío = usar todas."""

    currency_default: str = "BS"
    """Moneda por defecto: 'BS', 'USD', 'EUR', 'COP', 'ARS'."""

    currency_auto_detect: bool = True
    """Detectar automáticamente la moneda desde el texto de la factura."""

    enabled_currencies: Tuple[str, ...] = ("BS", "USD", "EUR", "COP", "ARS")
    """Monedas habilitadas para detección y conversión."""

    currency_default_rates: str = '{"BS":60.0,"VES":60.0,"USD":1.0,"EUR":0.92,"COP":4100.0,"ARS":980.0}'
    """JSON con tasas por defecto relativas a USD (fallback offline)."""

    exchange_api_url: str = "https://api.exchangerate.host/latest?base=USD&symbols=VES,EUR,COP,ARS"
    """API multi-moneda para obtener tasas actualizadas (VES, EUR, COP, ARS)."""

    alert_enabled: bool = True
    """Activar alertas de cambio de tasa entre sesiones."""

    alert_threshold_pct: float = 5.0
    """Umbral de cambio porcentual para generar alerta (default: 5%)."""

    alert_devaluation_window: int = 5
    """Ventana de sesiones para detectar tendencia devaluatoria."""

    alert_history_max: int = 50
    """Máximo de entradas en el historial de tasas."""


# ──────────────────────────────────────────────
#  Configuración de Supabase
# ──────────────────────────────────────────────
@dataclass
class SupabaseConfig:
    """Parámetros de conexión a Supabase."""

    url: str = os.environ.get('SUPABASE_URL', '')
    """URL del proyecto Supabase (leer de variable de entorno SUPABASE_URL)."""

    anon_key: str = os.environ.get('SUPABASE_ANON_KEY', '')
    """Anon/public key de Supabase (leer de variable de entorno SUPABASE_ANON_KEY)."""

    corrections_table: str = "ocr_corrections"
    """Nombre de la tabla para correcciones colaborativas."""

    sync_enabled: bool = True
    """Activar sincronización de correcciones con Supabase."""

    sync_on_push: bool = True
    """Enviar correcciones a Supabase inmediatamente."""

    sync_on_start: bool = True

    realtime_enabled: bool = True
    """Activar Realtime para correcciones en vivo (WebSocket)."""

    realtime_reconnect_interval: int = 5
    """Intervalo en segundos entre reconexiones si la suscripción se cae."""
    """Descargar correcciones de Supabase al iniciar."""


# ──────────────────────────────────────────────
#  Configuración de Google Drive
# ──────────────────────────────────────────────
@dataclass
class DriveConfig:
    """Parámetros del Bloque 7 — Subida a Google Drive."""

    credentials_path: str = "credentials.json"
    """Ruta al archivo credentials.json de Google Cloud."""

    token_path: str = "token.json"
    """Ruta al archivo token.json (refresh token)."""

    scopes: List[str] = field(
        default_factory=lambda: ["https://www.googleapis.com/auth/drive.file"]
    )
    """Scopes de OAuth 2.0."""

    root_folder_name: str = "Facturas_NAD_Auto"
    """Nombre de la carpeta raíz en Drive."""

    local_queue_dir: str = "output/queue"
    """Directorio local para cola offline."""

    retry_interval_seconds: int = 60
    """Intervalo entre reintentos de subida (offline → online)."""


# ──────────────────────────────────────────────
#  Configuración de Layout Detection (NUEVO)
# ──────────────────────────────────────────────
@dataclass
class LayoutConfig:
    """Parámetros para layout detection y análisis de documentos."""

    prefer_paddle: bool = True
    """Usar PaddleOCR ppstructure cuando esté disponible."""

    layout_threshold: float = 0.3
    """Umbral de confianza para detección de regiones."""

    reading_order: str = "xy_cut"
    """Algoritmo de orden de lectura: 'xy_cut', 'column', 'simple'."""

    enable_table_extraction: bool = True
    """Activar extracción de tablas → HTML/Markdown."""

    enable_formula_recognition: bool = True
    """Activar reconocimiento de fórmulas → LaTeX."""

    enable_multi_format: bool = True
    """Activar parseo de PDF/DOCX/PPTX/XLSX/HTML."""

    pdf_dpi: int = 150
    """Resolución para rendering de PDF."""

    supported_formats: Tuple[str, ...] = (
        ".pdf", ".docx", ".doc", ".pptx", ".ppt",
        ".xlsx", ".xls", ".html", ".htm",
        ".png", ".jpg", ".jpeg", ".bmp", ".tiff",
    )
    """Formatos de archivo soportados."""


# ──────────────────────────────────────────────
#  Configuración global
# ──────────────────────────────────────────────
@dataclass
class AppConfig:
    """Configuración completa de la aplicación."""

    capture: CaptureConfig = field(default_factory=CaptureConfig)
    align: AlignConfig = field(default_factory=AlignConfig)
    fusion: FusionConfig = field(default_factory=FusionConfig)
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    enhance: EnhanceConfig = field(default_factory=EnhanceConfig)
    ocr: OcrConfig = field(default_factory=OcrConfig)
    drive: DriveConfig = field(default_factory=DriveConfig)
    supabase: SupabaseConfig = field(default_factory=SupabaseConfig)
    layout: LayoutConfig = field(default_factory=LayoutConfig)

    output_dir: str = "output"
    """Directorio raíz de salida."""

    render_subdir: str = "render"
    """Subdirectorio para imágenes renderizadas."""

    data_subdir: str = "data"
    """Subdirectorio para archivos JSON extraídos."""


# Instancia global de configuración
CONFIG = AppConfig()
