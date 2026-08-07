"""
NAD Scanner — Módulo OCR
Reconocimiento óptico de caracteres y extracción estructurada de datos.
"""

from .extractor import extract_invoice_data, InvoiceData, OCREngine, InvoiceParser
from .paddle_ve import (
    PaddleOCRVEEngine,
    VEDictionary,
    VETextPostProcessor,
    normalize_and_verify_rif,
    parse_ve_amount,
    recognize_ve_invoice,
)
from .bcv_rate import (
    CurrencyRateProvider,
    get_bcv_rate,
    get_bcv_rates,
    get_currency_provider,
    convert_currency,
    format_amount_with_currency,
)
try:
    from .train_ve import VEFacturaGenerator, generate_dataset
except ImportError:
    pass  # train_ve es opcional (requiere GPU y dependencias extra)
# ── Plugin System (FASE 4) ──
from .backend_base import OCRBackend, BackendMetadata, WordResult
from .plugin_manager import (
    OCRBackendFactory,
    OCRBackendRegistry,
    get_factory,
    create_backend,
    list_backends,
)
from .backends import (
    PaddleBackend,
    PaddleVEBackend,
    TesseractBackend,
)

# Backends opcionales
_HAS_DOCTR = False
_HAS_SURYA = False
_HAS_EASYOCR = False
try:
    from .backends import DocTRBackend
    _HAS_DOCTR = True
except ImportError:
    pass
try:
    from .backends import SuryaBackend
    _HAS_SURYA = True
except ImportError:
    pass
try:
    from .backends import EasyOCRBackend
    _HAS_EASYOCR = True
except ImportError:
    pass

# ── Format Learner (FASE 2) — import protegido por si falla la dependencia
_HAS_FORMAT_LEARNER = False
try:
    from .format_learner import (
        FormatLearner,
        LayoutCluster,
        RegionProfile,
        FieldPosition,
        RegionDetector,
        ContextFieldExtractor,
        LayoutFeatureExtractor,
        get_format_learner,
        learn_from_invoice,
        extract_with_context,
        correct_ocr_field,
    )
    _HAS_FORMAT_LEARNER = True
except (ImportError, SyntaxError, AttributeError):
    pass

# ── Post-Processing Pipeline (FASE 3) ──
from .postprocessor import (
    PostProcessor,
    TypedInvoice,
    TypedRIF,
    TypedAmount,
    TypedDate,
    FieldConverter,
    CrossValidator,
    InconsistencyDetector,
    InconsistencyReport,
    CorrectionsPipeline,
    Severity,
    ValidationStatus,
    postprocess_invoice,
    validate_invoice,
    format_invoice_summary,
)

# ── Backend Selector + Continuous Learning (FASE 5) ──
from .backend_selector import (
    BackendSelector,
    BackendPreviewResult,
    BackendHistory,
    BackendHistoryEntry,
    ContinuousLearner,
    DocumentType,
    DocumentTypeDetector,
    get_selector,
    get_learner,
    select_best_backend,
    select_with_learning,
    compare_backends,
)

from .exchange_alert import (
    ExchangeAlert,
    RateHistory,
    get_alert_engine,
    check_exchange_alerts,
)
from .supabase_corrections import (
    SupabaseSync,
    get_supabase_sync,
    push_correction_to_cloud,
    pull_corrections_from_cloud,
    merge_corrections_from_cloud,
)

__all__ = [
    # Plugin system
    "OCRBackend",
    "BackendMetadata",
    "WordResult",
    "OCRBackendFactory",
    "OCRBackendRegistry",
    "get_factory",
    "create_backend",
    "list_backends",
    "PaddleBackend",
    "PaddleVEBackend",
    "TesseractBackend",
    # Extracción
    "extract_invoice_data",
    "InvoiceData",
    "OCREngine",
    "InvoiceParser",
    # VE
    "PaddleOCRVEEngine",
    "VEDictionary",
    "VETextPostProcessor",
    "normalize_and_verify_rif",
    "parse_ve_amount",
    "recognize_ve_invoice",
    # Tasas de cambio
    "CurrencyRateProvider",
    "get_bcv_rate",
    "get_bcv_rates",
    "get_currency_provider",
    "convert_currency",
    "format_amount_with_currency",
    # Entrenamiento
    "VEFacturaGenerator",
    "generate_dataset",
    # Format Learner (FASE 2)
    "FormatLearner",
    "LayoutCluster",
    "RegionProfile",
    "FieldPosition",
    "RegionDetector",
    "ContextFieldExtractor",
    "LayoutFeatureExtractor",
    "get_format_learner",
    "learn_from_invoice",
    "extract_with_context",
    "correct_ocr_field",
    "_HAS_FORMAT_LEARNER",
    # Post-processing (FASE 3)
    "PostProcessor",
    "TypedInvoice",
    "TypedRIF",
    "TypedAmount",
    "TypedDate",
    "FieldConverter",
    "CrossValidator",
    "InconsistencyDetector",
    "InconsistencyReport",
    "CorrectionsPipeline",
    "Severity",
    "ValidationStatus",
    "postprocess_invoice",
    "validate_invoice",
    "format_invoice_summary",
    # Backend selector (FASE 5)
    "BackendSelector",
    "BackendPreviewResult",
    "BackendHistory",
    "BackendHistoryEntry",
    "ContinuousLearner",
    "DocumentType",
    "DocumentTypeDetector",
    "get_selector",
    "get_learner",
    "select_best_backend",
    "select_with_learning",
    "compare_backends",
    # Alertas de cambio
    "ExchangeAlert",
    "RateHistory",
    "get_alert_engine",
    "check_exchange_alerts",
    # Correcciones colaborativas
    "SupabaseSync",
    "get_supabase_sync",
    "push_correction_to_cloud",
    "pull_corrections_from_cloud",
    "merge_corrections_from_cloud",
]
