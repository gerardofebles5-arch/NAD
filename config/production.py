"""
Configuración de Producción del Sistema OCR NAD Scanner
=======================================================
Configuración optimizada para entorno de producción.
"""

import os
from utils.config import AppConfig, OcrConfig, SupabaseConfig

# Configuración de OCR para producción
PROD_OCR_CONFIG = OcrConfig(
    engine="tesseract",  # Tesseract es más estable en producción
    lang="es",
    confidence_threshold=0.4,  # Umbral más alto en producción
    tesseract_cmd="/usr/bin/tesseract",  # Ruta en Linux/producción
    ve_mode=True,
    ve_rif_validation=True,
    ve_iva_rate_default=16.0,
    bcv_enabled=True,
    bcv_default_rate=60.50,
    currency_auto_detect=True,
    enabled_currencies=("BS", "USD", "EUR", "COP", "ARS"),
)

# Configuración de Supabase para producción
PROD_SUPABASE_CONFIG = SupabaseConfig(
    url=os.environ.get('SUPABASE_URL', ''),
    anon_key=os.environ.get('SUPABASE_ANON_KEY', ''),
    corrections_table="ocr_corrections",
    sync_enabled=True,
    sync_on_push=True,
    sync_on_start=True,
    realtime_enabled=True,
)

# Configuración completa de producción
PROD_CONFIG = AppConfig(
    ocr=PROD_OCR_CONFIG,
    supabase=PROD_SUPABASE_CONFIG,
    output_dir="/var/lib/nadscanner/output",
    render_subdir="render",
    data_subdir="data",
)

# Configuración de logging para producción
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/var/log/nadscanner/ocr.log',
            'maxBytes': 10485760,  # 10MB
            'backupCount': 5,
            'formatter': 'standard',
        },
        'console': {
            'level': 'WARNING',
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'loggers': {
        '': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}
