#!/usr/bin/env python3
"""
NAD Scanner Web Server
=======================
Sirve una interfaz HTML optimizada para móviles que permite capturar
5 fotos de una factura desde la cámara del dispositivo, enviarlas al
servidor para procesamiento (alineación → fusión → detección → realce → OCR)
y devolver el resultado.

Uso:
    python web_server.py

Esto inicia el servidor en http://0.0.0.0:5000
Accesible desde cualquier dispositivo en la misma red local.
"""

import os
import sys
import json
import base64
import io
import logging
import tempfile
import time
from pathlib import Path
from datetime import datetime
from functools import wraps
from collections import defaultdict
from typing import Optional, Dict, List, Any

import cv2
import numpy as np
from flask import Flask, request, jsonify, render_template, send_file, send_from_directory, Response, g, redirect
from flask_socketio import SocketIO, emit


# ══════════════════════════════════════════════════════════════
#  Rate Limiter simple (en memoria)
# ══════════════════════════════════════════════════════════════

class RateLimiter:
    """Rate limiter por IP con ventana deslizante."""
    
    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._requests = defaultdict(list)
    
    def is_allowed(self, key: str) -> bool:
        now = time.time()
        self._requests[key] = [t for t in self._requests[key] if now - t < self.window]
        if len(self._requests[key]) >= self.max_requests:
            return False
        self._requests[key].append(now)
        return True
    
    def get_remaining(self, key: str) -> int:
        now = time.time()
        self._requests[key] = [t for t in self._requests[key] if now - t < self.window]
        return max(0, self.max_requests - len(self._requests[key]))


# ══════════════════════════════════════════════════════════════
#  API Key authentication (opcional)
# ══════════════════════════════════════════════════════════════

API_KEY = os.environ.get('NAD_SCANNER_API_KEY', '')  # Vacío = sin auth

# Silenciar logs de Flask/Werkzeug
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# ── Configurar path del proyecto ──
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

# ── Importar pipeline ──
from utils.config import CONFIG, CaptureMode
from core.align import align_shots
from core.fusion import fuse_shots
from core.detector import detect_document, get_mode_params

# ── Versión del servidor ──
VERSION = "1.3.0"
from core.enhancer import perspective_correct, enhance_document, auto_detect_mode
from core.advanced_enhancer import enhanced_pipeline, assess_scan_quality, detect_document_type as detect_doc_type
from core.realtime_preview import RealtimePreview, PreviewMode
from core.batch_processor import BatchProcessor, BatchPDFExporter, BatchPriority
from core.document_advisor import DocumentAdvisor
from ocr.extractor import extract_invoice_data


def _extract_best_invoice(enhanced_img, corrected_img=None):
    """
    Corre OCR sobre la imagen realzada; si la confianza sale baja y hay
    disponible una versión SIN el filtro de realce, la intenta también y
    se queda con el mejor resultado de las dos.

    El realce "limpio" (CLAHE + bilateralFilter) ayuda a que la imagen se
    vea mejor a simple vista, pero el suavizado bilateral puede difuminar
    texto pequeño — es el mismo motivo por el que un código QR deja de
    poder leerse después del realce (ver detect_codes() en /process).
    Aplicando el mismo criterio al OCR de texto: no asumir ciegamente que
    el realce siempre ayuda, comprobarlo.

    NOTA: antes había un early-exit aquí que detectaba confianza 0 sin texto
    y asumía "fallo estructural" para saltarse el segundo OCR. Pero PaddleOCR
    puede ejecutarse correctamente (modelos cargados, sin errores) y aun así
    devolver 0 palabras si la imagen no tiene suficiente contraste — el
    early-exit impedía probar la imagen sin filtrar en ese caso. Ahora se
    confía en que el singleton OCREngine con _dead_backends ya evita los
    34s de reintentos si los backends están verdaderamente caídos.
    """
    invoice = extract_invoice_data(enhanced_img, interactive=False)
    # Convertir ocr_confidence a float para comparación
    try:
        confidence = float(invoice.ocr_confidence)
    except (ValueError, TypeError):
        confidence = 0.0
    
    if corrected_img is not None and confidence < 0.55:
        # NOTA: No chequeamos si es "fallo estructural" aquí porque
        # PaddleOCR puede ejecutarse correctamente y devolver 0 palabras
        # (imagen sin contraste, texto muy pequeño). En ese caso SÍ
        # queremos reintentar con la imagen sin filtrar. El singleton
        # OCREngine con _dead_backends ya evita los 34s de reintentos
        # cuando los backends están verdaderamente caídos.
        try:
            alt_invoice = extract_invoice_data(corrected_img, interactive=False)
        except Exception as e:
            print(f"  [OCR] Intento con imagen sin filtrar falló: {e}")
            return invoice
        
        # Convertir confianzas a float para comparación
        try:
            alt_confidence = float(alt_invoice.ocr_confidence)
        except (ValueError, TypeError):
            alt_confidence = 0.0
        
        try:
            invoice_confidence = float(invoice.ocr_confidence)
        except (ValueError, TypeError):
            invoice_confidence = 0.0
        
        if alt_confidence > invoice_confidence:
            print(f"  [OCR] La versión sin filtrar dio mejor confianza "
                  f"({alt_confidence:.2f} vs {invoice_confidence:.2f}) — se usa esa.")
            return alt_invoice
    return invoice

from core.stitch import stitch_sequential
from core.stitch_session import StitchingSessionManager, get_session_manager
from core.stitch_jobs import BackgroundJobManager, get_job_manager
from core.auto_calibrate import get_calibrator, reset_calibrator
from utils.calibration_profiles import get_profile_into_calibrated_params
from ocr.exchange_alert import check_exchange_alerts
from ocr.format_learner import get_format_learner, correct_ocr_field
from ocr.supabase_corrections import get_supabase_sync, pull_corrections_from_cloud, merge_corrections_from_cloud
from core.id_card_processor import IdCardProcessor, process_id_card, get_id_card_info
from utils.tenant_db import (
    init_tenant_db, seed_demo_data,
    create_tenant, get_tenant, list_tenants, update_tenant, delete_tenant,
    add_tenant_user, list_tenant_users, delete_tenant_user,
    get_global_usage_summary, get_tenant_usage_summary,
    get_invoices_by_tenant, assign_invoice_to_tenant, record_usage,
)

# ── Supabase Authentication Middleware ──
try:
    from auth.supabase_middleware import (
        supabase_auth_required,
        optional_supabase_auth,
        validate_supabase_token,
        get_user_from_token,
    )
    SUPABASE_AUTH_ENABLED = True
except ImportError:
    SUPABASE_AUTH_ENABLED = False
    print("[WARN] Supabase auth middleware not available. Running without auth.")

# ── Sync Module ──
try:
    from sync.sync_queue import (
        init_sync_queue,
        enqueue_operation,
        get_pending_operations,
        update_operation_status,
        delete_operation,
        get_sync_stats,
        SyncOperation,
        SyncStatus,
    )
    SYNC_ENABLED = True
except ImportError:
    SYNC_ENABLED = False
    print("[WARN] Sync module not available. Running without sync.")

# ── Helper: obtener parámetros calibrados del detector ──
def _get_calibrated_params() -> Optional[dict]:
    """Retorna dict de thresholds calibrados, o None si no hay calibración.

    Usado por detect_document() en todos los pipelines (/process,
    /batch-process, /process-z, /finalize) para ajustar Canny, Gauss,
    approx_epsilon y min_area_ratio dinámicamente según el documento.

    Estrategia (3 niveles):
      1. Perfil persistente activo (aprendido de >= 5 facturas del mismo tipo)
      2. Calibración dinámica de la sesión actual (si se envió a /calibrate)
      3. None → usar valores por defecto de DetectorConfig.mode_params
    """
    cal = get_calibrator()

    # Nivel 1: perfil persistente (si existe y está activo)
    mode = getattr(cal, '_capture_mode', 'factura')
    profile_params = get_profile_into_calibrated_params(mode)
    if profile_params:
        return profile_params

    # Nivel 2: calibración de sesión (si se calibró explícitamente)
    if cal.is_calibrated:
        p = cal.get_params()
        return {
            "canny_low": p.canny_low,
            "canny_high": p.canny_high,
            "gaussian_kernel": p.gaussian_kernel,
            "approx_epsilon": p.approx_epsilon,
            "min_area_ratio": p.min_area_ratio,
        }
    return None


# ── Mapping de modos de captura ──
CAPTURE_MODE_MAP = {
    "factura": CaptureMode.FACTURA,
    "id": CaptureMode.ID,
    "libro": CaptureMode.LIBRO,
    "foto": CaptureMode.FOTO,
    "pizarra": CaptureMode.PIZARRA,
}

MODE_DISPLAY_NAMES = {
    "factura": "📄 Factura",
    "id": "🆔 ID/Cédula",
    "libro": "📖 Libro",
    "foto": "🖼️ Foto",
    "pizarra": "📝 Pizarra",
}

# ── App Flask con SocketIO ──
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max upload
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')

# Inicializar SocketIO para WebSocket
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Crear directorio para archivos temporales
TEMP_DIR = os.path.join(PROJECT_ROOT, "output", "web_temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# Session manager para stitching incremental asynchronic
_session_dir = os.path.join(TEMP_DIR, "stitch_sessions")
_shot_session_mgr = get_session_manager(_session_dir)

# Job manager para stitching asincrono con polling
_job_mgr = get_job_manager()

# Rate limiter global
_limiter = RateLimiter(max_requests=30, window_seconds=60)


def require_rate_limit(f):
    """Decorator para rate limiting por IP."""
    @wraps(f)
    def decorated(*args, **kwargs):
        client_ip = request.remote_addr or 'unknown'
        if not _limiter.is_allowed(client_ip):
            return jsonify({
                'success': False,
                'error': 'Demasiadas solicitudes. Intenta de nuevo en un momento.',
                'retry_after': _limiter.window,
            }), 429
        return f(*args, **kwargs)
    return decorated


def require_api_key(f):
    """Decorator para autenticación por API key (opcional)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if API_KEY:
            provided = request.headers.get('X-API-Key', '') or request.args.get('api_key', '')
            if provided != API_KEY:
                return jsonify({
                    'success': False,
                    'error': 'API key inválida o no proporcionada.',
                }), 401
        return f(*args, **kwargs)
    return decorated


# ═══════════════════════════════════════════════════
#  Rutas
# ═══════════════════════════════════════════════════

@app.route('/')
def index():
    """Sirve la página principal con la cámara."""
    return render_template('scan.html')

@app.route('/pwa')
def pwa_index():
    """Sirve la PWA para pruebas locales."""
    return send_file(os.path.join(PROJECT_ROOT, 'static', 'pwa', 'index.html'))

@app.route('/static/pwa/<path:filename>')
def serve_pwa_files(filename):
    """Sirve archivos estáticos de la PWA."""
    return send_from_directory(os.path.join(PROJECT_ROOT, 'static', 'pwa'), filename)


@app.route('/health')
def health():
    """Endpoint de salud para verificar que el servidor está vivo."""
    return jsonify({
        'status': 'ok',
        'version': VERSION,
        'time': datetime.now().isoformat(),
        'supabase_auth': SUPABASE_AUTH_ENABLED,
    })


# ═══════════════════════════════════════════════════
#  Supabase Authentication Endpoints
# ═══════════════════════════════════════════════════

@app.route('/auth/validate', methods=['POST'])
def auth_validate():
    """
    Valida un token JWT de Supabase y retorna información del usuario.
    
    Request body:
        {
            "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
        }
    
    Returns:
        {
            "valid": true,
            "user": {
                "user_id": "...",
                "email": "...",
                "role": "authenticated"
            },
            "tenant_id": null  # To be populated from tenant_users table
        }
    """
    if not SUPABASE_AUTH_ENABLED:
        return jsonify({
            'valid': False,
            'error': 'Supabase auth not enabled on server'
        }), 501
    
    try:
        data = request.get_json()
        if not data or 'token' not in data:
            return jsonify({
                'valid': False,
                'error': 'Missing token in request body'
            }), 400
        
        token = data['token']
        is_valid, user_info, error = validate_supabase_token(token)
        
        if not is_valid:
            return jsonify({
                'valid': False,
                'error': error or 'Invalid token'
            }), 401
        
        # Try to find tenant_id from tenant_users table
        tenant_id = None
        if user_info and user_info.get('email'):
            from utils.tenant_db import init_tenant_db
            init_tenant_db()
            import sqlite3
            from utils.tenant_db import DB_PATH
            conn = sqlite3.connect(DB_PATH, timeout=10)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT tenant_id FROM tenant_users WHERE user_email = ? AND is_active = 1",
                    (user_info['email'],)
                ).fetchone()
                if row:
                    tenant_id = row['tenant_id']
            finally:
                conn.close()
        
        return jsonify({
            'valid': True,
            'user': user_info,
            'tenant_id': tenant_id
        })
        
    except Exception as e:
        return jsonify({
            'valid': False,
            'error': str(e)
        }), 500


@app.route('/auth/user', methods=['GET'])
@optional_supabase_auth
def auth_user():
    """
    Retorna información del usuario autenticado desde el token.
    
    Authorization header: Bearer <token>
    
    Returns:
        {
            "user": { ... } or null,
            "authenticated": true/false
        }
    """
    try:
        if not SUPABASE_AUTH_ENABLED:
            return jsonify({
                'user': None,
                'authenticated': False,
                'error': 'Supabase auth not enabled on server'
            }), 501
        
        if hasattr(g, 'user') and g.user:
            return jsonify({
                'user': g.user,
                'authenticated': True
            })
        
        return jsonify({
            'user': None,
            'authenticated': False
        })
    except Exception as e:
        return jsonify({
            'user': None,
            'authenticated': False,
            'error': str(e)
        }), 500


# ═══════════════════════════════════════════════════
#  Sync Endpoints
# ═══════════════════════════════════════════════════

@app.route('/sync/status', methods=['GET'])
def sync_status():
    """
    Retorna el estado de la cola de sincronización.
    
    Returns:
        {
            "enabled": bool,
            "stats": {
                "pending": int,
                "in_progress": int,
                "completed": int,
                "failed": int,
                "by_direction": {...},
                "by_table": {...}
            }
        }
    """
    if not SYNC_ENABLED:
        return jsonify({
            'enabled': False,
            'error': 'Sync module not enabled'
        }), 501
    
    init_sync_queue()
    stats = get_sync_stats()
    
    return jsonify({
        'enabled': True,
        'stats': stats
    })


@app.route('/sync/push', methods=['POST'])
@require_rate_limit
def sync_push():
    """
    Envía cambios locales a Supabase (push).
    
    Request body:
        {
            "table": "invoices",  // optional, if not specified syncs all tables
            "limit": 50
        }
    
    Returns:
        {
            "success": bool,
            "results": {...}
        }
    """
    if not SYNC_ENABLED:
        return jsonify({
            'success': False,
            'error': 'Sync module not enabled'
        }), 501
    
    try:
        data = request.get_json() or {}
        table_name = data.get('table')
        limit = data.get('limit', 50)
        
        # For now, return pending operations info
        # Full sync implementation would require async processing
        operations = get_pending_operations(limit=limit, direction='push')
        
        if table_name:
            operations = [op for op in operations if op['table_name'] == table_name]
        
        return jsonify({
            'success': True,
            'pending_operations': len(operations),
            'operations': operations[:10],  # Return first 10 for preview
            'message': 'Sync push endpoint - operations queued for processing'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/sync/pull', methods=['POST'])
@require_rate_limit
def sync_pull():
    """
    Recibe cambios desde Supabase (pull).
    
    Request body:
        {
            "table": "invoices",  // optional
            "since": "2024-01-01T00:00:00"  // optional ISO timestamp
        }
    
    Returns:
        {
            "success": bool,
            "results": {...}
        }
    """
    if not SYNC_ENABLED:
        return jsonify({
            'success': False,
            'error': 'Sync module not enabled'
        }), 501
    
    try:
        data = request.get_json() or {}
        table_name = data.get('table')
        since = data.get('since')
        
        # For now, return pending operations info
        # Full sync implementation would require async processing with Supabase client
        operations = get_pending_operations(limit=50, direction='pull')
        
        if table_name:
            operations = [op for op in operations if op['table_name'] == table_name]
        
        return jsonify({
            'success': True,
            'pending_operations': len(operations),
            'operations': operations[:10],
            'message': 'Sync pull endpoint - requires Supabase client configuration'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/sync/resolve-conflict', methods=['POST'])
@require_rate_limit
def sync_resolve_conflict():
    """
    Resuelve manualmente un conflicto de sincronización.
    
    Request body:
        {
            "operation_id": int,
            "resolution": "local_wins" | "remote_wins" | "merge",
            "merged_data": {...}  // required merge
        }
    
    Returns:
        {
            "success": bool
        }
    """
    if not SYNC_ENABLED:
        return jsonify({
            'success': False,
            'error': 'Sync module not enabled'
        }), 501
    
    try:
        data = request.get_json()
        if not data or 'operation_id' not in data:
            return jsonify({
                'success': False,
                'error': 'Missing operation_id'
            }), 400
        
        op_id = data['operation_id']
        resolution = data.get('resolution', 'local_wins')
        
        # Mark as completed with resolution info
        update_operation_status(
            op_id,
            SyncStatus.COMPLETED,
            f"Manually resolved: {resolution}"
        )
        
        return jsonify({
            'success': True,
            'message': f'Conflict resolved with strategy: {resolution}'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/notifications', methods=['GET'])
@require_rate_limit
def get_notifications():
    """
    Obtiene notificaciones del usuario.
    
    Query params:
        - user_id: ID del usuario (requerido)
        - unread_only: Si True, solo no leídas
        - limit: Máximo de notificaciones (default 50)
    
    Returns:
        {
            "success": bool,
            "notifications": [...],
            "unread_count": int
        }
    """
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({
                'success': False,
                'error': 'Missing user_id parameter'
            }), 400
        
        unread_only = request.args.get('unread_only', 'false').lower() == 'true'
        limit = int(request.args.get('limit', 50))
        
        from core.notifications import (
            get_user_notifications,
            get_unread_count
        )
        
        notifications = get_user_notifications(user_id, unread_only, limit)
        unread_count = get_unread_count(user_id)
        
        return jsonify({
            'success': True,
            'notifications': [n.to_dict() for n in notifications],
            'unread_count': unread_count,
            'total': len(notifications)
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/notifications/<int:notification_id>/read', methods=['POST'])
@require_rate_limit
def mark_notification_as_read(notification_id):
    """
    Marca una notificación como leída.
    
    Returns:
        {"success": bool}
    """
    try:
        from core.notifications import mark_notification_read
        
        success = mark_notification_read(notification_id)
        
        return jsonify({
            'success': success
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/notifications/read-all', methods=['POST'])
@require_rate_limit
def mark_all_notifications_read():
    """
    Marca todas las notificaciones de un usuario como leídas.
    
    Request body:
        {"user_id": str}
    
    Returns:
        {"success": bool, "count": int}
    """
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        
        if not user_id:
            return jsonify({
                'success': False,
                'error': 'Missing user_id'
            }), 400
        
        from core.notifications import mark_all_read
        
        count = mark_all_read(user_id)
        
        return jsonify({
            'success': True,
            'count': count
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/notifications/<int:notification_id>', methods=['DELETE'])
@require_rate_limit
def delete_notification(notification_id):
    """
    Elimina una notificación.
    
    Returns:
        {"success": bool}
    """
    try:
        from core.notifications import delete_notification
        
        success = delete_notification(notification_id)
        
        return jsonify({
            'success': success
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/notifications/create', methods=['POST'])
@require_rate_limit
def create_notification():
    """
    Crea una nueva notificación.
    
    Request body:
        {
            "user_id": str,
            "title": str,
            "body": str,
            "icon": str (optional),
            "data": dict (optional),
            "type": str (optional, default "info")
        }
    
    Returns:
        {"success": bool, "notification": {...}}
    """
    try:
        data = request.get_json()
        
        user_id = data.get('user_id')
        title = data.get('title')
        body = data.get('body')
        
        if not all([user_id, title, body]):
            return jsonify({
                'success': False,
                'error': 'Missing required fields: user_id, title, body'
            }), 400
        
        from core.notifications import create_notification
        
        notification = create_notification(
            user_id=user_id,
            title=title,
            body=body,
            icon=data.get('icon', ''),
            data=data.get('data'),
            notification_type=data.get('type', 'info')
        )
        
        return jsonify({
            'success': True,
            'notification': notification.to_dict()
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/reports/invoice', methods=['POST'])
@require_rate_limit
def generate_invoice_pdf():
    """
    Genera un reporte PDF de una factura.
    
    Request body (multipart/form-data):
        - invoice_data: JSON con datos de la factura
        - image: archivo de imagen (opcional)
    
    Returns:
        PDF file
    """
    try:
        import json
        from reports.pdf_generator import generate_invoice_report
        
        # Obtener datos de factura
        invoice_data_str = request.form.get('invoice_data')
        if not invoice_data_str:
            return jsonify({
                'success': False,
                'error': 'Missing invoice_data'
            }), 400
        
        invoice_data = json.loads(invoice_data_str)
        
        # Obtener imagen si se proporciona
        image_bytes = None
        if 'image' in request.files:
            image_bytes = request.files['image'].read()
        
        # Generar PDF
        output_dir = os.path.join(CONFIG.output_dir, 'reports')
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = os.path.join(output_dir, f'invoice_{timestamp}.pdf')
        
        generate_invoice_report(
            invoice_data=invoice_data,
            output_path=output_path,
            include_image=image_bytes is not None,
            image_bytes=image_bytes
        )
        
        # Retornar PDF
        return send_file(output_path, mimetype='application/pdf', as_attachment=True)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/users/profile', methods=['GET'])
@require_rate_limit
@optional_supabase_auth
def get_user_profile():
    """
    Obtiene el perfil del usuario autenticado.
    
    Returns:
        {
            "success": bool,
            "profile": {...}
        }
    """
    try:
        if not hasattr(g, 'user') or not g.user:
            return jsonify({
                'success': False,
                'error': 'Not authenticated'
            }), 401
        
        user_id = g.user_id
        user_email = g.user_email
        
        # Buscar información del usuario en tenant_users
        from utils.tenant_db import init_tenant_db
        init_tenant_db()
        
        import sqlite3
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Obtener información del usuario
        cursor.execute(
            "SELECT * FROM tenant_users WHERE user_email = ? AND is_active = 1",
            (user_email,)
        )
        user_row = cursor.fetchone()
        
        profile = {
            'user_id': user_id,
            'email': user_email,
        }
        
        if user_row:
            profile.update({
                'tenant_id': user_row['tenant_id'],
                'user_name': user_row['user_name'],
                'role': user_row['role'],
                'last_active': user_row['last_active'],
            })
            
            # Obtener información del tenant
            cursor.execute(
                "SELECT * FROM tenants WHERE id = ?",
                (user_row['tenant_id'],)
            )
            tenant_row = cursor.fetchone()
            
            if tenant_row:
                profile['tenant'] = {
                    'id': tenant_row['id'],
                    'name': tenant_row['name'],
                    'slug': tenant_row['slug'],
                }
        
        conn.close()
        
        return jsonify({
            'success': True,
            'profile': profile
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/users/profile', methods=['PUT'])
@require_rate_limit
@optional_supabase_auth
def update_user_profile():
    """
    Actualiza el perfil del usuario autenticado.
    
    Request body:
        {
            "user_name": str (optional),
            "preferences": dict (optional)
        }
    
    Returns:
        {
            "success": bool,
            "profile": {...}
        }
    """
    try:
        if not hasattr(g, 'user') or not g.user:
            return jsonify({
                'success': False,
                'error': 'Not authenticated'
            }), 401
        
        data = request.get_json()
        user_email = g.user_email
        
        from utils.tenant_db import init_tenant_db
        init_tenant_db()
        
        import sqlite3
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        
        # Actualizar información del usuario
        updates = []
        params = []
        
        if 'user_name' in data:
            updates.append("user_name = ?")
            params.append(data['user_name'])
        
        if updates:
            params.append(user_email)
            cursor.execute(
                f"UPDATE tenant_users SET {', '.join(updates)} WHERE user_email = ?",
                params
            )
            conn.commit()
        
        conn.close()
        
        # Retornar perfil actualizado
        return get_user_profile()
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/users/preferences', methods=['GET'])
@require_rate_limit
@optional_supabase_auth
def get_user_preferences():
    """
    Obtiene las preferencias del usuario.
    
    Returns:
        {
            "success": bool,
            "preferences": {...}
        }
    """
    try:
        if not hasattr(g, 'user') or not g.user:
            return jsonify({
                'success': False,
                'error': 'Not authenticated'
            }), 401
        
        user_id = g.user_id
        
        # Por ahora, retornar preferencias por defecto
        # En el futuro, esto se almacenaría en una tabla de user_preferences
        preferences = {
            'language': 'es',
            'theme': 'light',
            'notifications_enabled': True,
            'auto_sync': True,
            'scan_quality': 'high',
        }
        
        return jsonify({
            'success': True,
            'preferences': preferences
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/users/preferences', methods=['PUT'])
@require_rate_limit
@optional_supabase_auth
def update_user_preferences():
    """
    Actualiza las preferencias del usuario.
    
    Request body:
        {
            "language": str (optional),
            "theme": str (optional),
            "notifications_enabled": bool (optional),
            "auto_sync": bool (optional),
            "scan_quality": str (optional)
        }
    
    Returns:
        {
            "success": bool,
            "preferences": {...}
        }
    """
    try:
        if not hasattr(g, 'user') or not g.user:
            return jsonify({
                'success': False,
                'error': 'Not authenticated'
            }), 401
        
        data = request.get_json()
        
        # Por ahora, simular actualización
        # En el futuro, esto se almacenaría en una tabla de user_preferences
        preferences = {
            'language': data.get('language', 'es'),
            'theme': data.get('theme', 'light'),
            'notifications_enabled': data.get('notifications_enabled', True),
            'auto_sync': data.get('auto_sync', True),
            'scan_quality': data.get('scan_quality', 'high'),
        }
        
        return jsonify({
            'success': True,
            'preferences': preferences
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/reports/usage', methods=['POST'])
@require_rate_limit
def generate_usage_pdf():
    """
    Genera un reporte PDF de uso del sistema.
    
    Request body:
        {
            "usage_data": {...}
        }
    
    Returns:
        PDF file
    """
    try:
        import json
        from reports.pdf_generator import generate_usage_report
        
        data = request.get_json()
        usage_data = data.get('usage_data', {})
        
        # Generar PDF
        output_dir = os.path.join(CONFIG.output_dir, 'reports')
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = os.path.join(output_dir, f'usage_{timestamp}.pdf')
        
        generate_usage_report(usage_data=usage_data, output_path=output_path)
        
        # Retornar PDF
        return send_file(output_path, mimetype='application/pdf', as_attachment=True)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/formula/recognize', methods=['POST'])
@require_rate_limit
def recognize_formula():
    """
    Endpoint para reconocer fórmulas matemáticas en una imagen.
    
    Request body (multipart/form-data):
        - image: archivo de imagen
        - bbox: JSON string con coordenadas [x1, y1, x2, y2] (opcional)
    
    Returns:
        {
            "success": bool,
            "formulas": [
                {
                    "latex": str,
                    "confidence": float,
                    "bbox": [x1, y1, x2, y2]
                }
            ]
        }
    """
    try:
        if 'image' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No image provided'
            }), 400
        
        file = request.files['image']
        bbox_str = request.form.get('bbox')
        
        # Leer imagen
        img_bytes = file.read()
        nparr = np.frombuffer(img_bytes, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if image is None:
            return jsonify({
                'success': False,
                'error': 'Failed to decode image'
            }), 400
        
        # Parsear bbox si se proporciona
        bbox = None
        if bbox_str:
            try:
                import json
                bbox = json.loads(bbox_str)
                bbox = [int(b) for b in bbox]
            except:
                pass
        
        # Reconocer fórmulas
        from core.formula_recognizer import detect_formulas
        formulas = detect_formulas(image, bbox)
        
        return jsonify({
            'success': True,
            'formulas': [f.to_dict() for f in formulas],
            'count': len(formulas)
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/sync/upload', methods=['POST'])
@require_rate_limit
def sync_upload():
    """
    Endpoint para recibir archivos sincronizados desde el service worker offline.
    
    Request body (multipart/form-data):
        - file: archivo binario
        - queueId: ID único de la cola
        - options: JSON con opciones adicionales (opcional)
    
    Returns:
        {
            "success": bool,
            "queueId": str,
            "processed": bool
        }
    """
    try:
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No file provided'
            }), 400
        
        file = request.files['file']
        queue_id = request.form.get('queueId')
        
        if not queue_id:
            return jsonify({
                'success': False,
                'error': 'Missing queueId'
            }), 400
        
        # Procesar el archivo (similar a /process pero para un solo archivo)
        # Por ahora, guardar en el directorio de output
        import uuid
        filename = f"sync_{queue_id}_{uuid.uuid4().hex[:8]}_{file.filename}"
        filepath = os.path.join(CONFIG.output_dir, filename)
        
        file.save(filepath)
        
        # Enqueue para procesamiento OCR
        if SYNC_ENABLED:
            init_sync_queue()
            enqueue_operation(
                'invoices',
                SyncOperation.INSERT,
                0,  # ID temporal
                {
                    'file_path': filepath,
                    'file_name': file.filename,
                    'queue_id': queue_id,
                    'sync_source': 'service_worker',
                },
                direction='push'
            )
        
        return jsonify({
            'success': True,
            'queueId': queue_id,
            'processed': True,
            'filepath': filepath
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/process', methods=['GET', 'POST', 'OPTIONS'])
@require_rate_limit
@require_api_key
def process_shots():
    """
    GET  → info
    POST → recibe 5 fotos y ejecuta el pipeline
    OPTIONS → CORS preflight

    Espera 5 archivos multipart: shot_0, shot_1, ..., shot_4
    Query param opcional: mode=documento|grises|color|auto

    Retorna JSON con:
        - success: bool
        - enhanced_image: imagen procesada en base64 (JPEG)
        - ocr_data: dict con campos extraídos
        - stats: dict con métricas del pipeline
        - error: mensaje de error si falla
    """
    # CORS preflight
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    if request.method == 'GET':
        return jsonify({
            'status': 'ready',
            'endpoint': 'NAD Scanner Pipeline',
            'mode': request.args.get('mode', 'documento'),
        })

    start_time = datetime.now()
    output_mode = request.args.get('mode', 'limpio')  # Default: limpio (sin binarización)
    capture_mode_str = request.args.get('capture_mode', '').strip().lower()
    # No mutar CONFIG global: usar variable local para evitar race condition
    local_capture_mode = CONFIG.capture.mode
    if capture_mode_str in CAPTURE_MODE_MAP:
        local_capture_mode = CAPTURE_MODE_MAP[capture_mode_str]
        print(f"  📐 Modo de captura: {MODE_DISPLAY_NAMES.get(capture_mode_str, capture_mode_str)}")

    try:
        # ── 1. Recibir imágenes ──
        shots = []
        for i in range(5):
            file_key = f'shot_{i}'
            if file_key not in request.files:
                return jsonify({
                    'success': False,
                    'error': f'Falta la imagen {file_key}'
                }), 400

            file = request.files[file_key]
            img_bytes = file.read()

            if len(img_bytes) < 100:
                return jsonify({
                    'success': False,
                    'error': f'Imagen {file_key} vacía o muy pequeña'
                }), 400

            nparr = np.frombuffer(img_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if img is None:
                return jsonify({
                    'success': False,
                    'error': f'No se pudo decodificar la imagen {file_key}'
                }), 400

            shots.append(img)

        # ── 1b. Redimensionar si es necesario (móviles con cámaras de alta res) ──
        MAX_DIM = 4000  # Máximo lado en píxeles
        for i in range(len(shots)):
            h, w = shots[i].shape[:2]
            if max(h, w) > MAX_DIM:
                scale = MAX_DIM / max(h, w)
                shots[i] = cv2.resize(shots[i], (int(w * scale), int(h * scale)))
                print(f"  📐 Redimensionada imagen {i}: {w}x{h} → {int(w*scale)}x{int(h*scale)}")

        # ── 2. Alineación ──
        print("📐 Alineando tomas...")
        aligned = align_shots(shots)
        valid_aligned = [a for a in aligned if a is not None]
        if len(valid_aligned) < 3:
            return jsonify({
                'success': False,
                'error': f'Solo {len(valid_aligned)}/5 tomas alineadas correctamente'
            }), 400

        # ── 3. Fusión — MEDIANA primero (anti-reflejos por paralaje) ──
        print("✨ Fusionando (mediana, anti-glare)...")
        fused = fuse_shots(aligned, method='median')
        if fused is None:
            from core.fusion import fuse_with_depth_weights
            print("  ⚙ Fallback a fusión por nitidez (profundidad de campo)...")
            fused = fuse_with_depth_weights(aligned)
        if fused is None:
            return jsonify({
                'success': False,
                'error': 'No se pudo fusionar las imágenes'
            }), 500

        # ── 4. Detección de documento (con calibración si está disponible) ──
        print("🔍 Detectando documento...")
        cal_dict = _get_calibrated_params()
        corners, _ = detect_document(fused, mode=local_capture_mode, calibrated_params=cal_dict)
        if corners is None:
            h, w = fused.shape[:2]
            corners = np.array([
                [0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]
            ], dtype=np.float32)

        # ── 5. Perspectiva + Realce LIMPIO ──
        print(f"🎨 Enderezando (modo: {output_mode})...")
        corrected = perspective_correct(fused, corners)

        # Realce mínimo: solo enderezar, sin sombras ni arrugas
        # El usuario quiere la imagen limpia, no procesada pesadamente
        if output_mode == "color":
            # Color: CLAHE suave + bilateral
            enhanced, enhance_meta = enhanced_pipeline(
                corrected,
                mode="color",
                enable_shadow_removal=False,
                enable_wrinkle_correction=False,
                enable_color_restoration=True,
            )
        else:
            # Documento/Grises: realce estándar (no avanzado)
            from core.enhancer import enhance_document
            enhanced = enhance_document(corrected, output_mode)
            enhance_meta = {"steps": [output_mode], "improvement": 0}

        # Calidad
        quality = {"score": 0.8, "level": "buena"}
        try:
            quality = assess_scan_quality(enhanced)
        except Exception:
            pass
        print(f"  → Calidad: {quality.get('level', 'ok')} ({quality.get('score', 0):.2f})")

        # ── 6. OCR ──
        print("📝 Ejecutando OCR...")
        invoice = _extract_best_invoice(enhanced, corrected)

        # ── 7. Codificar imagen resultado ──
        _, buffer = cv2.imencode('.jpg', enhanced, [cv2.IMWRITE_JPEG_QUALITY, 90])
        enhanced_b64 = base64.b64encode(buffer).decode('utf-8')

        # ── 8. Preparar respuesta ──
        elapsed = (datetime.now() - start_time).total_seconds()

        # ── 8a. Calibración continua: actualizar perfil con EMA 80/20 ──
        # Después de cada escaneo exitoso, medimos el detectability_score
        # de la imagen fusionada y lo incorporamos al perfil persistente.
        # Esto permite que el detector se adapte incrementalmente al tipo
        # de documentos que el usuario escanea más frecuentemente.
        try:
            cal = get_calibrator()
            cal.update_continuous_calibration(
                enhanced,
                capture_mode=capture_mode_str or cal._capture_mode,
                alpha=0.20,
            )
        except Exception as cal_err:
            print(f"  [Calibrate] [WARN] Calibración continua: {cal_err}")

        # ── 8b. Alertas de tasa de cambio ──
        exchange_alerts_raw = []
        exchange_alert_summary = {"has_alerts": False, "count": 0, "alerts": []}
        if CONFIG.ocr.alert_enabled and invoice.all_rates:
            from ocr.exchange_alert import ExchangeAlert
            alert_engine = ExchangeAlert()
            exchange_alerts_raw = alert_engine.check_all_currencies(invoice.all_rates)
            alert_engine.print_alerts(exchange_alerts_raw)
            exchange_alert_summary = alert_engine.get_alert_summary(exchange_alerts_raw)

        # ── 8c. QR / código de barras — validación cruzada exacta ──
        # Ningún competidor (PhotoScan/CamScanner/MinerU) lee esto. Si la
        # factura trae un QR de verificación fiscal, es más confiable que
        # el OCR para el RIF y el total — se usa para CONFIRMAR o marcar
        # discrepancias, no para reemplazar el resto del pipeline.
        #
        # IMPORTANTE: se busca primero en 'corrected' (recién enderezada,
        # SIN el realce "limpio"), no en 'enhanced'. El bilateralFilter que
        # aplica enhance_document() para mejorar la lectura de texto por
        # OCR difumina justo el patrón de alto contraste que un QR necesita
        # para decodificarse — probado: un QR que decodifica perfecto antes
        # del realce deja de detectarse después. Se intenta también sobre
        # 'enhanced' como respaldo por si la corrección de perspectiva
        # dejó el QR más nítido ahí (poco común, pero no cuesta intentarlo).
        from core.qr_scanner import detect_codes, cross_check_with_ocr
        qr_codes = []
        qr_notes = []
        try:
            qr_codes = detect_codes(corrected)
            if not qr_codes:
                qr_codes = detect_codes(enhanced)
            if qr_codes:
                qr_notes = cross_check_with_ocr(qr_codes, invoice.to_dict())
        except Exception as qr_err:
            print(f"  [WARN] Error leyendo QR/código de barras: {qr_err}")

        # ── 9. Preparar respuesta ──
        ocr_data = invoice.to_dict()
        ocr_data['raw_text'] = invoice.raw_text  # incluir texto OCR crudo para el frontend
        all_validation_notes = list(invoice.validation_errors) + qr_notes

        # ── 9b. Guardar en el historial (Libro de Compras/Ventas) ──
        # Se puede desactivar con ?save=false (por ejemplo, para pruebas).
        saved_invoice_id = None
        if request.args.get('save', 'true').strip().lower() != 'false':
            try:
                from utils.database import save_invoice
                saved_invoice_id = save_invoice(
                    ocr_data=ocr_data,
                    validation_errors=all_validation_notes,
                    ocr_confidence=invoice.ocr_confidence,
                    qr_data={"codes": qr_codes} if qr_codes else None,
                    source="guided",
                    enhanced_image_b64=enhanced_b64,
                )
                # Registrar métricas de uso multi-tenant
                # (modo mono-tenant: asigna al primer tenant activo)
                tenants = list_tenants(include_inactive=False)
                if tenants:
                    record_usage(tenants[0]["id"], invoices_processed=1,
                                 processing_time_seconds=elapsed, ocr_requests=1)
            except Exception as db_err:
                print(f"  [WARN] No se pudo guardar en el historial: {db_err}")
        
        # ── 9c. Integración Drive ↔ Supabase (nueva) ──
        # Si Supabase está configurado, subir a Drive y guardar en DB
        supabase_factura_id = None
        if request.args.get('sync_supabase', 'true').strip().lower() != 'false':
            try:
                from integrations.drive_supabase import upload_to_drive_with_db, get_or_create_cliente
                from utils.supabase_client import is_configured
                
                if is_configured():
                    # Obtener o crear cliente (usar tenant_id como cliente_id)
                    tenant_id = request.args.get('tenant_id', 'default')
                    cliente_nombre = request.args.get('cliente_nombre', 'Cliente Default')
                    cliente_rif = request.args.get('cliente_rif', 'J-00000000-0')
                    
                    cliente_id = get_or_create_cliente(cliente_rif, cliente_nombre)
                    
                    if cliente_id:
                        # Subir a Drive y guardar en Supabase
                        supabase_factura_id = upload_to_drive_with_db(
                            image=enhanced,
                            invoice_data=invoice,
                            cliente_id=cliente_id
                        )
                        if supabase_factura_id:
                            print(f"  ✅ Factura sincronizada con Supabase: {supabase_factura_id}")
                else:
                    print(f"  [WARN] Supabase no configurado, omitiendo sincronización")
            except Exception as supabase_err:
                print(f"  [WARN] Error en sincronización Supabase: {supabase_err}")

        response = {
            'success': True,
            'enhanced_image': enhanced_b64,
            'ocr_data': ocr_data,
            'validation_errors': all_validation_notes,
            'ocr_confidence': round(float(invoice.ocr_confidence), 4) if invoice.ocr_confidence else 0.0,
            'exchange_alerts': exchange_alert_summary,
            'quality': quality,
            'qr_codes': qr_codes,
            'invoice_id': saved_invoice_id,
            'supabase_factura_id': supabase_factura_id,  # Nuevo: ID en Supabase
            'enhancement': {
                'mode': output_mode,
                'steps': enhance_meta.get('steps', []),
                'improvement': enhance_meta.get('improvement', 0),
            },
            'stats': {
                'aligned_shots': len(valid_aligned),
                'time_seconds': round(elapsed, 2),
                'original_size': enhance_meta.get('original_size', 'unknown'),
                'final_size': enhance_meta.get('final_size', 'unknown'),
            }
        }

        print(f"✅ Procesamiento completado en {elapsed:.1f}s")
        return jsonify(response)

    except Exception as e:
        import traceback
        traceback.print_exc()
        elapsed = (datetime.now() - start_time).total_seconds()
        # No exponer detalles del error al cliente (seguridad)
        error_msg = 'Error interno del servidor'
        if 'timeout' in str(e).lower():
            error_msg = 'Tiempo de procesamiento excedido'
        elif 'memory' in str(e).lower():
            error_msg = 'Memoria insuficiente para procesar la imagen'
        return jsonify({
            'success': False,
            'error': error_msg,
            'time_seconds': round(elapsed, 2),
        }), 500


# ═══════════════════════════════════════════════════
#  Financial Endpoints (Motor Financiero)
# ═══════════════════════════════════════════════════

@app.route('/api/financial/monthly', methods=['GET'])
@require_rate_limit
def get_monthly_summary():
    """
    Obtiene resumen mensual de facturas.
    
    Query params:
        - cliente_id: ID del cliente (requerido)
        - year: Año (ej. 2026)
        - month: Mes (1-12)
    
    Returns:
        {
            "periodo": str,
            "total_facturado": float,
            "iva_acumulado": float,
            "num_facturas": int,
            "por_moneda": dict,
            "top_proveedores": dict
        }
    """
    try:
        cliente_id = request.args.get('cliente_id')
        year = int(request.args.get('year', datetime.now().year))
        month = int(request.args.get('month', datetime.now().month))
        
        if not cliente_id:
            return jsonify({
                'success': False,
                'error': 'Missing cliente_id'
            }), 400
        
        from financial.engine import get_financial_engine
        engine = get_financial_engine()
        summary = engine.get_monthly_summary(cliente_id, year, month)
        
        return jsonify({
            'success': True,
            'summary': summary
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/financial/top-providers', methods=['GET'])
@require_rate_limit
def get_top_providers():
    """
    Obtiene top proveedores por monto total.
    
    Query params:
        - cliente_id: ID del cliente (requerido)
        - limit: Número de proveedores (default: 10)
    
    Returns:
        {
            "success": bool,
            "providers": [...]
        }
    """
    try:
        cliente_id = request.args.get('cliente_id')
        limit = int(request.args.get('limit', 10))
        
        if not cliente_id:
            return jsonify({
                'success': False,
                'error': 'Missing cliente_id'
            }), 400
        
        from financial.engine import get_financial_engine
        engine = get_financial_engine()
        providers = engine.get_top_providers(cliente_id, limit)
        
        return jsonify({
            'success': True,
            'providers': providers
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/financial/currency-breakdown', methods=['GET'])
@require_rate_limit
def get_currency_breakdown():
    """
    Obtiene desglose por moneda de un periodo.
    
    Query params:
        - cliente_id: ID del cliente (requerido)
        - year: Año
        - month: Mes
    
    Returns:
        {
            "success": bool,
            "breakdown": {moneda: total}
        }
    """
    try:
        cliente_id = request.args.get('cliente_id')
        year = int(request.args.get('year', datetime.now().year))
        month = int(request.args.get('month', datetime.now().month))
        
        if not cliente_id:
            return jsonify({
                'success': False,
                'error': 'Missing cliente_id'
            }), 400
        
        from financial.engine import get_financial_engine
        engine = get_financial_engine()
        breakdown = engine.get_currency_breakdown(cliente_id, year, month)
        
        return jsonify({
            'success': True,
            'breakdown': breakdown
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/financial/yearly', methods=['GET'])
@require_rate_limit
def get_yearly_summary():
    """
    Obtiene resumen anual.
    
    Query params:
        - cliente_id: ID del cliente (requerido)
        - year: Año
    
    Returns:
        {
            "success": bool,
            "summary": {...}
        }
    """
    try:
        cliente_id = request.args.get('cliente_id')
        year = int(request.args.get('year', datetime.now().year))
        
        if not cliente_id:
            return jsonify({
                'success': False,
                'error': 'Missing cliente_id'
            }), 400
        
        from financial.engine import get_financial_engine
        engine = get_financial_engine()
        summary = engine.get_yearly_summary(cliente_id, year)
        
        return jsonify({
            'success': True,
            'summary': summary
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ═══════════════════════════════════════════════════
#  Procesamiento por lote (varias facturas de una vez)
# ═══════════════════════════════════════════════════

def _process_single_invoice_image(item) -> dict:
    """
    Procesa UNA imagen ya capturada (una sola foto por factura, sin el
    flujo de 5 tomas — pensado para lotes de fotos/recaudos ya tomados,
    como en 'Reportes Z' o facturas sueltas que el contador sube juntas).

    Reusa exactamente el mismo pipeline core que /process: detección de
    documento → perspectiva → realce → OCR → validación.
    """
    img_bytes = item.file_path  # aquí guardamos los bytes crudos, no una ruta
    nparr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("No se pudo decodificar la imagen")

    MAX_DIM = 4000
    h, w = img.shape[:2]
    if max(h, w) > MAX_DIM:
        scale = MAX_DIM / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)))

    cal_dict_batch = _get_calibrated_params()
    corners, _ = detect_document(img, calibrated_params=cal_dict_batch)
    if corners is None:
        h, w = img.shape[:2]
        corners = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)

    corrected = perspective_correct(img, corners)
    enhanced = enhance_document(corrected, "limpio")

    invoice = _extract_best_invoice(enhanced, corrected)

    _, buffer = cv2.imencode('.jpg', enhanced, [cv2.IMWRITE_JPEG_QUALITY, 88])
    enhanced_b64 = base64.b64encode(buffer).decode('utf-8')

    from core.qr_scanner import detect_codes, cross_check_with_ocr
    qr_codes = []
    qr_notes = []
    try:
        qr_codes = detect_codes(corrected)
        if not qr_codes:
            qr_codes = detect_codes(enhanced)
        if qr_codes:
            qr_notes = cross_check_with_ocr(qr_codes, invoice.to_dict())
    except Exception as qr_err:
        print(f"  [WARN] Error leyendo QR/código de barras en lote: {qr_err}")

    ocr_data = invoice.to_dict()
    ocr_data['raw_text'] = invoice.raw_text
    all_validation_notes = list(invoice.validation_errors) + qr_notes

    saved_invoice_id = None
    try:
        from utils.database import save_invoice
        saved_invoice_id = save_invoice(
            ocr_data=ocr_data,
            validation_errors=all_validation_notes,
            ocr_confidence=invoice.ocr_confidence,
            qr_data={"codes": qr_codes} if qr_codes else None,
            source="batch",
            enhanced_image_b64=enhanced_b64,
            filename=getattr(item, "filename", None),
        )
    except Exception as db_err:
        print(f"  [WARN] No se pudo guardar factura de lote en el historial: {db_err}")

    return {
        'enhanced_image': enhanced_b64,
        'ocr_data': ocr_data,
        'validation_errors': all_validation_notes,
        'ocr_confidence': round(invoice.ocr_confidence, 4),
        'qr_codes': qr_codes,
        'invoice_id': saved_invoice_id,
    }


@app.route('/process-id', methods=['GET', 'POST', 'OPTIONS'])
@require_rate_limit
@require_api_key
def process_id_card_endpoint():
    """
    Endpoint especializado para documentos de identidad (cédula, pasaporte, DNI).

    GET  → información sobre formatos soportados.
    POST → recibe 1-5 fotos y ejecuta el pipeline ID:
            detección fina → perspectiva a formato oficial → fondo blanco
            puro → escalado a DPI de impresión → exportación PNG/JPEG.

    POST multipart: shot_0..shot_4 (al menos 1 imagen requerida)
    Query params:
        dpi=300 (200|300|600)
        format=cedula_ve (standard_card, dni_ar, cedula_col, pasaporte_page)
        output=png (jpeg)
        auto_detect=true (detectar formato automáticamente)

    Retorna JSON con:
        - success: bool
        - processed_image: base64 de la imagen procesada
        - media_type: image/png | image/jpeg
        - width_px, height_px: dimensiones finales
        - width_mm, height_mm: dimensiones del formato
        - dpi: DPI usado
        - format_detected: formato de ID usado
        - stats: métricas del pipeline
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    if request.method == 'GET':
        return jsonify({
            'success': True,
            'info': get_id_card_info(),
        })

    start_time = datetime.now()

    try:
        # ── 1. Recibir imágenes ──
        shots = []
        for i in range(5):
            file_key = f'shot_{i}'
            if file_key in request.files:
                file = request.files[file_key]
                img_bytes = file.read()
                if len(img_bytes) >= 100:
                    nparr = np.frombuffer(img_bytes, np.uint8)
                    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    if img is not None:
                        shots.append(img)

        if not shots:
            return jsonify({
                'success': False,
                'error': 'No se recibieron imágenes válidas (campo "shot_0" requerido)'
            }), 400

        # ── 2. Parámetros ──
        target_dpi = int(request.args.get('dpi', '300'))
        if target_dpi not in (200, 300, 600):
            target_dpi = 300

        id_format = request.args.get('format', 'cedula_ve')
        output_format = request.args.get('output', 'png').lower()
        if output_format not in ('png', 'jpeg'):
            output_format = 'png'

        auto_detect = request.args.get('auto_detect', 'true').lower() != 'false'

        # ── 3. Elegir mejor imagen (la más nítida) ──
        best_img = shots[0]
        best_sharpness = 0
        for img in shots:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            lap = cv2.Laplacian(gray, cv2.CV_64F)
            sharpness = lap.var()
            if sharpness > best_sharpness:
                best_sharpness = sharpness
                best_img = img

        # ── 4. Redimensionar si es necesario ──
        MAX_DIM = 4000
        h, w = best_img.shape[:2]
        if max(h, w) > MAX_DIM:
            scale = MAX_DIM / max(h, w)
            best_img = cv2.resize(best_img, (int(w * scale), int(h * scale)))

        # ── 5. Procesar ID ──
        processor = IdCardProcessor(target_dpi=target_dpi)
        result = processor.process(
            best_img,
            corners=None,
            output_format=output_format,
            id_format=id_format,
            auto_detect_format=auto_detect,
        )

        if not result.get('success'):
            return jsonify({
                'success': False,
                'error': result.get('error', 'Error desconocido en el pipeline ID'),
            }), 500

        # ── 6. Métricas ──
        elapsed = (datetime.now() - start_time).total_seconds()

        response = {
            'success': True,
            'processed_image': result['processed_image'],
            'media_type': result.get('media_type', 'image/png'),
            'width_px': result.get('width_px_final', result.get('width_px', 0)),
            'height_px': result.get('height_px_final', result.get('height_px', 0)),
            'width_mm': result.get('width_mm', 0),
            'height_mm': result.get('height_mm', 0),
            'dpi': target_dpi,
            'format_detected': result.get('format_detected', id_format),
            'has_white_background': result.get('has_white_background', False),
            'stats': {
                'images_received': len(shots),
                'time_seconds': round(elapsed, 2),
                'best_sharpness': round(best_sharpness, 1),
            },
        }

        print(f"✅ ID Card procesado en {elapsed:.1f}s "
              f"({response['width_px']}x{response['height_px']}px @ {target_dpi}DPI, "
              f"formato: {response['format_detected']})")
        return jsonify(response)

    except Exception as e:
        import traceback
        traceback.print_exc()
        elapsed = (datetime.now() - start_time).total_seconds()
        error_msg = 'Error interno del servidor'
        if 'timeout' in str(e).lower():
            error_msg = 'Tiempo de procesamiento excedido'
        elif 'memory' in str(e).lower():
            error_msg = 'Memoria insuficiente'
        return jsonify({
            'success': False,
            'error': error_msg,
            'time_seconds': round(elapsed, 2),
        }), 500


@app.route('/batch-process', methods=['POST', 'OPTIONS'])
@require_rate_limit
@require_api_key
def batch_process():
    """
    Procesa varias facturas/recaudos de una sola vez (una foto por
    documento — no el flujo guiado de 5 tomas).

    POST multipart: files (uno o más archivos de imagen, campo repetido)

    Usa BatchProcessor (cola con reintentos automáticos y backoff) en vez
    de un simple for-loop, así una factura borrosa o corrupta no tumba el
    lote completo: se reintenta hasta 3 veces y si sigue fallando, se
    reporta en 'failed' sin afectar al resto.

    Límite: 20 archivos por request (evita bloquear el servidor con lotes
    gigantes de forma síncrona).

    Retorna:
        results: lista de {filename, success, ocr_data / error}
        stats: resumen del lote (completados, fallidos, tiempo)
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    MAX_BATCH_FILES = 20
    files = request.files.getlist('files')
    if not files:
        return jsonify({'success': False, 'error': 'No se recibieron archivos (campo "files")'}), 400
    if len(files) > MAX_BATCH_FILES:
        return jsonify({
            'success': False,
            'error': f'Máximo {MAX_BATCH_FILES} archivos por lote (recibidos: {len(files)})',
        }), 400

    processor = BatchProcessor(max_workers=1)
    filenames = []
    for f in files:
        raw = f.read()
        if len(raw) < 100:
            continue  # archivo vacío/corrupto — se omite antes de encolar
        item_id = processor.add_item(raw, priority=BatchPriority.NORMAL)
        filenames.append((item_id, f.filename or f"archivo_{len(filenames)}.jpg"))

    if not filenames:
        return jsonify({'success': False, 'error': 'Ningún archivo válido en el lote'}), 400

    stats = processor.process(_process_single_invoice_image)

    name_by_id = dict(filenames)
    results = []
    for item in processor.items:
        results.append({
            'filename': name_by_id.get(item.id, item.id),
            'success': item.status.value == 'completed',
            'ocr_data': item.result.get('ocr_data') if item.result else None,
            'ocr_confidence': item.result.get('ocr_confidence') if item.result else None,
            'validation_errors': item.result.get('validation_errors') if item.result else None,
            'enhanced_image': item.result.get('enhanced_image') if item.result else None,
            'qr_codes': item.result.get('qr_codes') if item.result else None,
            'invoice_id': item.result.get('invoice_id') if item.result else None,
            'error': item.error,
            'attempts': item.attempts + (1 if item.status.value == 'completed' else 0),
            'processing_time': round(item.processing_time, 2),
        })

    return jsonify({
        'success': True,
        'results': results,
        'stats': {
            'total': stats.total,
            'completed': stats.completed,
            'failed': stats.failed,
            'avg_processing_time': round(stats.avg_processing_time, 2),
            'total_processing_time': round(stats.total_processing_time, 2),
        },
    })


@app.after_request
def add_cors_headers(response):
    """Permite CORS para que dispositivos móviles puedan acceder.
    
    En producción, configurar NAD_CORS_ORIGINS como lista de orígenes permitidos.
    Si no está configurado, permite todo (desarrollo local).
    """
    allowed_origins = os.environ.get('NAD_CORS_ORIGINS', '*')
    response.headers['Access-Control-Allow-Origin'] = allowed_origins
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-API-Key, Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response


# ═══════════════════════════════════════════════════
#  Corrección de OCR (feedback loop)
# ═══════════════════════════════════════════════════

@app.route('/correct', methods=['POST', 'OPTIONS'])
@require_rate_limit
@require_api_key
def correct_field():
    """
    Recibe una corrección de campo del usuario y la registra
    en el FormatLearner para evitar el mismo error en el futuro.

    POST JSON body:
        {
            "field_name": "total",
            "wrong_value": "13.920,00",
            "correct_value": "14.000,00"
        }

    Returns:
        {"success": true, "field": "total", "corrections_total": 5}
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    try:
        data = request.get_json(force=True)
        field_name = data.get('field_name', '').strip()
        wrong_value = data.get('wrong_value', '').strip()
        correct_value = data.get('correct_value', '').strip()

        if not field_name or not correct_value:
            return jsonify({
                'success': False,
                'error': "Se requieren 'field_name' y 'correct_value'"
            }), 400

        learner = get_format_learner()
        result = learner.correct_field(field_name, wrong_value, correct_value)

        if result:
            print(f"  [Feedback] Corrección registrada: {field_name}: "
                  f"'{wrong_value}' → '{correct_value}'")
            return jsonify({
                'success': True,
                'field': field_name,
                'corrections_total': learner.get_correction_counts().get(field_name, 0),
            })
        else:
            return jsonify({
                'success': False,
                'error': 'No se registró la corrección (mismos valores o dato inválido)',
            }), 400

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/corrections', methods=['GET'])
def list_corrections():
    """
    Lista todas las correcciones registradas localmente y remotas.

    Query params:
        source: 'local' | 'remote' | 'all' (default: 'local')

    Returns:
        {
            "success": true,
            "corrections": {field: {wrong: correct}},
            "counts": {field: count},
            "source": "local"
        }
    """
    try:
        learner = get_format_learner()
        source = request.args.get('source', 'local')

        result = {
            'success': True,
            'corrections': {},
            'counts': {},
            'source': source,
        }

        if source in ('local', 'all'):
            result['corrections'] = learner.get_corrections()
            result['counts'] = learner.get_correction_counts()

        if source in ('remote', 'all'):
            if CONFIG.supabase.sync_enabled:
                remote = pull_corrections_from_cloud()
                # Convertir a formato {field: {wrong: correct}}
                remote_dict = {}
                remote_counts = {}
                for c in remote:
                    fn = c.get('field_name', '')
                    wv = c.get('wrong_value', '')
                    cv = c.get('correct_value', '')
                    if fn and wv:
                        if fn not in remote_dict:
                            remote_dict[fn] = {}
                        remote_dict[fn][wv] = cv
                        remote_counts[fn] = remote_counts.get(fn, 0) + 1
                result['remote_corrections'] = remote_dict
                result['remote_counts'] = remote_counts
                result['remote_total'] = len(remote)

        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/sync/corrections', methods=['POST', 'GET'])
def sync_corrections():
    """
    Sincroniza correcciones con Supabase.

    POST: Envía correcciones locales pendientes a Supabase y descarga las remotas.
    GET:  Muestra estado de sincronización.

    POST body opcional:
        {
            "push": true,  // Enviar locales a Supabase
            "pull": true   // Descargar remotas a local
        }

    Returns:
        {
            "success": true,
            "pushed": 5,
            "pulled": 12,
            "merged": 8
        }
    """
    try:
        learner = get_format_learner()

        if request.method == 'GET':
            sync = get_supabase_sync()
            stats = sync.get_stats() if sync.connected else {}
            return jsonify({
                'success': True,
                'sync_enabled': CONFIG.supabase.sync_enabled,
                'supabase_configured': bool(CONFIG.supabase.url and CONFIG.supabase.anon_key),
                'stats': stats,
                'local_corrections': len(learner.get_correction_counts()),
            })

        # POST
        data = request.get_json(force=True) or {}
        should_push = data.get('push', True)
        should_pull = data.get('pull', True)

        result = {'success': True, 'pushed': 0, 'pulled': 0, 'merged': 0}

        if not CONFIG.supabase.sync_enabled or not CONFIG.supabase.anon_key:
            return jsonify({
                'success': False,
                'error': 'Supabase no configurado. Establezca SUPABASE_URL y SUPABASE_ANON_KEY'
            }), 400

        if should_push:
            # Enviar todas las correcciones locales a Supabase
            corrections = learner.get_corrections()
            sync = get_supabase_sync()
            for field_name, wrong_map in corrections.items():
                for wrong_value, correct_value in wrong_map.items():
                    # wrong_value en wrong_map está normalizado; recuperamos original
                    # El valor original no está disponible directamente, usamos el normalizado
                    if sync.push_correction(field_name, wrong_value, correct_value):
                        result['pushed'] += 1

        if should_pull:
            # Descargar y fusionar correcciones remotas
            merged = merge_corrections_from_cloud(learner)
            result['merged'] = merged
            result['pulled'] = len(pull_corrections_from_cloud())

        return jsonify(result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════
#  Estado de backends OCR (BackendSelector)
# ═══════════════════════════════════════════════════

@app.route('/backend-status')
def backend_status():
    """
    Estado de todos los backends OCR registrados.

    Retorna:
        available: lista de backends disponibles
        registered: todos los backends registrados
        selector_history: historial del ContinuousLearner si está disponible
        current_engine: motor OCR activo según CONFIG
    """
    try:
        from ocr.plugin_manager import get_factory
        factory = get_factory()
        registered = factory.list_registered()
        all_meta = factory.list_all_with_status()

        # Intentar obtener historial del backend selector
        selector_history = None
        try:
            from ocr.backend_selector import get_learner
            learner = get_learner()
            if learner and hasattr(learner, 'history'):
                selector_history = {
                    'total_entries': len(learner.history.entries),
                    'by_type': {k: v.to_dict() for k, v in learner.history.stats_by_type.items()},
                    'last_doc_type': learner.get_doc_type(),
                    'last_used_history': learner.last_used_history,
                }
        except Exception:
            pass

        return jsonify({
            'success': True,
            'available': [m.name for m in all_meta if m.available],
            'unavailable': [m.name for m in all_meta if not m.available],
            'registered': registered,
            'current_engine': CONFIG.ocr.engine if hasattr(CONFIG.ocr, 'engine') else 'paddle',
            'selector_history': selector_history,
            'available_details': [
                {
                    'name': m.name,
                    'display_name': m.display_name,
                    'version': m.version,
                    'languages': list(m.languages) if m.languages else [],
                    'requires_gpu': m.requires_gpu,
                }
                for m in all_meta if m.available
            ],
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════
#  Auto-Calibración de Detector
# ═══════════════════════════════════════════════════

@app.route('/calibrate', methods=['POST', 'OPTIONS'])
@require_rate_limit
@require_api_key
def calibrate_detector():
    """
    Analiza la primera toma de un documento y calibra los thresholds
    de detección dinámicamente.

    POST multipart: image (archivo JPEG/PNG de la primera toma)
    Query params:
        reset: 'true' para reiniciar la calibración (nuevo documento)
        capture_mode: tipo de documento (factura, id, libro, foto, pizarra)
                      default: factura. Determina el perfil persistente.

    Retorna JSON con:
        - success: bool
        - calibrated: bool
        - session_id: str
        - profile_used: bool (true si se usó un perfil persistente)
        - profile: dict con estado del perfil persistente
        - params: dict con thresholds calibrados (canny_low, canny_high,
                  gaussian_kernel, approx_epsilon, min_area_ratio,
                  ncc_overlap_ok, ncc_overlap_warn)
        - stats: dict con métricas de la imagen (contrast, entropy,
                  ncc_self, sharpness, detectability_score)
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    try:
        # Reset si se solicita
        if request.args.get('reset', '').lower() == 'true':
            reset_calibrator()
            return jsonify({
                'success': True,
                'calibrated': False,
                'message': 'Calibración reiniciada',
            })

        # Obtener imagen
        if 'image' not in request.files:
            return jsonify({'success': False, 'error': 'No se recibió imagen (campo "image")'}), 400

        file = request.files['image']
        img_bytes = file.read()
        if len(img_bytes) < 100:
            return jsonify({'success': False, 'error': 'Imagen vacía o muy pequeña'}), 400

        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return jsonify({'success': False, 'error': 'No se pudo decodificar la imagen'}), 400

        # Redimensionar si es muy grande (solo para calibración)
        MAX_CALIB_DIM = 2000
        h, w = img.shape[:2]
        if max(h, w) > MAX_CALIB_DIM:
            scale = MAX_CALIB_DIM / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)))

        # Establecer modo de captura (para perfil persistente correcto)
        capture_mode = request.args.get('capture_mode', 'factura').strip().lower()
        cal = get_calibrator()
        cal.set_capture_mode(capture_mode)

        # Intentar cargar perfil persistente primero
        profile_params = cal.try_load_profile(capture_mode)
        if profile_params:
            # Perfil encontrado: devolver parámetros sin recalibrar
            stats = cal.get_stats()
            params = cal.get_params()
            profile_info = cal.to_dict().get('profile', {})
            return jsonify({
                'success': True,
                'calibrated': True,
                'profile_used': True,
                'profile': profile_info,
                'session_id': cal.get_session_id(),
                'capture_mode': capture_mode,
                'params': {
                    'canny_low': params.canny_low,
                    'canny_high': params.canny_high,
                    'gaussian_kernel': list(params.gaussian_kernel) if params.gaussian_kernel else None,
                    'approx_epsilon': params.approx_epsilon,
                    'min_area_ratio': params.min_area_ratio,
                },
                'stats': {
                    'detectability_score': profile_params.get('avg_detectability_score', 0),
                    'source': 'profile',
                    'samples': profile_params.get('sample_count', 0),
                },
                'detectability_label': 'perfil persistente',
            })

        # Sin perfil: ejecutar calibración completa y guardar muestra
        params = cal.calibrate(img)
        stats = cal.get_stats()

        # Construir respuesta
        resp = {
            'success': True,
            'calibrated': True,
            'session_id': cal.get_session_id(),
            'params': {
                'canny_low': params.canny_low,
                'canny_high': params.canny_high,
                'gaussian_kernel': list(params.gaussian_kernel) if params.gaussian_kernel else None,
                'approx_epsilon': params.approx_epsilon,
                'min_area_ratio': params.min_area_ratio,
                'ncc_overlap_ok': params.ncc_overlap_ok,
                'ncc_overlap_warn': params.ncc_overlap_warn,
            },
            'stats': {
                'contrast': round(stats.contrast, 3),
                'entropy': round(stats.entropy, 3),
                'ncc_self': round(stats.ncc_self, 3),
                'sharpness': round(stats.sharpness, 1),
                'detectability_score': round(stats.detectability_score, 3),
                'resolution': list(stats.resolution),
            },
            'detectability_label': (
                'muy alto' if stats.detectability_score > 0.75 else
                'alto' if stats.detectability_score > 0.55 else
                'normal' if stats.detectability_score > 0.35 else
                'bajo' if stats.detectability_score > 0.20 else
                'muy bajo'
            ),
        }

        return jsonify(resp)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════
#  Estado del FormatLearner
# ═══════════════════════════════════════════════════

@app.route('/format-learner-status')
def format_learner_status():
    """
    Estado del FormatLearner con resumen ejecutivo.
    Diseñado para ser consumido por ScannerBridge desde la UI web.

    Retorna:
        available: bool
        clusters: resumen de clusters de layout
        memory: uso de memoria
        corrections: total de correcciones registradas
        status: 'learning' | 'stable' | 'empty'
    """
    try:
        from ocr.format_learner import get_format_learner, _FORMAT_LEARNER_AVAILABLE

        if not _FORMAT_LEARNER_AVAILABLE:
            return jsonify({
                'success': True,
                'available': False,
                'status': 'unavailable',
                'message': 'FormatLearner no disponible (dependencias faltantes)',
            })

        learner = get_format_learner()
        if learner is None:
            return jsonify({
                'success': True,
                'available': False,
                'status': 'not_initialized',
            })

        n_clusters = len(learner.clusters) if hasattr(learner, 'clusters') else 0
        total_examples = sum(c.example_count for c in learner.clusters.values()) if hasattr(learner, 'clusters') else 0
        memory_stats = learner.get_memory_stats() if hasattr(learner, 'get_memory_stats') else {}
        corrections = learner.get_correction_counts() if hasattr(learner, 'get_correction_counts') else {}
        n_corrections = sum(corrections.values())

        # Determinar estado
        if n_clusters == 0:
            status_text = 'empty'
        elif (n_examples := total_examples) < 50:
            status_text = 'learning'
        else:
            status_text = 'stable'

        return jsonify({
            'success': True,
            'available': True,
            'status': status_text,
            'clusters': n_clusters,
            'total_examples': total_examples,
            'total_corrections': n_corrections,
            'corrections_per_field': corrections,
            'memory': memory_stats,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════
#  Preview rápida del pipeline (para UI en vivo)
# ═══════════════════════════════════════════════════

@app.route('/pipeline-preview', methods=['POST', 'OPTIONS'])
def pipeline_preview():
    """
    Versión rápida del pipeline que retorta imágenes de cada etapa
    para mostrar en la UI web: aligned, fused, detected, corrected,
    enhanced.

    POST multipart: shot_0 (requerido), shot_1..shot_4 (opcional)

    Retorna:
        stages: lista de {name, image_base64, description}
        stats: métricas de cada etapa
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    try:
        # Recibir imágenes
        shots = []
        for i in range(5):
            file_key = f'shot_{i}'
            if file_key in request.files:
                file = request.files[file_key]
                nparr = np.frombuffer(file.read(), np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if img is not None:
                    shots.append(img)

        if not shots:
            return jsonify({'success': False, 'error': 'No se recibieron imágenes'}), 400

        stages = []
        current = shots[0]

        # Etapa 1: Imagen original
        _, buf = cv2.imencode('.jpg', current, [cv2.IMWRITE_JPEG_QUALITY, 85])
        stages.append({
            'name': 'original',
            'image': base64.b64encode(buf).decode('utf-8'),
            'description': f'Imagen original ({current.shape[1]}x{current.shape[0]})',
        })

        # Etapa 2: Alineación (si multi-shot)
        if len(shots) > 1:
            aligned = align_shots(shots)
            valid = [a for a in aligned if a is not None]
            if valid:
                current = valid[0]
                _, buf = cv2.imencode('.jpg', current, [cv2.IMWRITE_JPEG_QUALITY, 85])
                stages.append({
                    'name': 'aligned',
                    'image': base64.b64encode(buf).decode('utf-8'),
                    'description': f'Alineación ({len(valid)}/{len(shots)} tomas válidas)',
                })

        # Etapa 3: Detección de contornos
        corners, contour_img = detect_document(current)
        if contour_img is not None:
            _, buf = cv2.imencode('.jpg', contour_img, [cv2.IMWRITE_JPEG_QUALITY, 85])
            stages.append({
                'name': 'detection',
                'image': base64.b64encode(buf).decode('utf-8'),
                'description': 'Contorno del documento detectado' if corners is not None else 'Sin detección (imagen completa)',
            })

        # Etapa 4: Corrección de perspectiva
        if corners is not None:
            corrected = perspective_correct(current, corners)
            _, buf = cv2.imencode('.jpg', corrected, [cv2.IMWRITE_JPEG_QUALITY, 85])
            stages.append({
                'name': 'corrected',
                'image': base64.b64encode(buf).decode('utf-8'),
                'description': 'Perspectiva corregida',
            })
            current = corrected

        return jsonify({
            'success': True,
            'stages': stages,
            'count': len(stages),
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════
#  Estadísticas del feedback loop
# ═══════════════════════════════════════════════════

@app.route('/stats/feedback')
def feedback_stats():
    """
    Estadísticas completas del feedback loop de correcciones OCR.

    Retorna:
        corrections_per_field: {field: count} con total y ranking
        accuracy_estimate: métricas de acierto/error del OCR
        field_positions: posiciones aprendidas por campo
        region_profiles: perfiles de región por cluster
        memory_stats: uso de memoria del FormatLearner
        clusters: resumen de clusters de layout
    """
    try:
        learner = get_format_learner()

        # 1. Correcciones por campo
        counts = learner.get_correction_counts()
        corrections = learner.get_corrections()

        total_corrections = sum(counts.values())
        most_corrected = sorted(
            [{"field": k, "count": v} for k, v in counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )

        # 2. Estimar precisión del OCR
        # Basado en: total de campos extraídos estimados vs correcciones
        total_examples = sum(c.example_count for c in learner.clusters.values())
        estimated_fields_extracted = total_examples * 12  # ~12 campos por factura
        accuracy_pct = 0.0
        if estimated_fields_extracted > 0:
            error_rate = total_corrections / estimated_fields_extracted
            accuracy_pct = max(0.0, (1.0 - error_rate) * 100.0)

        accuracy_estimate = {
            "total_examples_processed": total_examples,
            "estimated_fields_extracted": estimated_fields_extracted,
            "total_corrections": total_corrections,
            "error_rate": round(error_rate, 4) if estimated_fields_extracted > 0 else 0,
            "accuracy_pct": round(accuracy_pct, 1),
            "fields_with_corrections": len(counts),
        }

        # 3. Posiciones de campo aprendidas por cluster
        field_positions = []
        for cluster in learner.clusters.values():
            for fname, fp in cluster.fields.items():
                field_positions.append({
                    "field": fname,
                    "confidence": round(fp.confidence, 4),
                    "cluster_id": cluster.cluster_id,
                    "cluster_name": cluster.format_key or cluster.cluster_id,
                    "x": round(fp.x, 4),
                    "y": round(fp.y, 4),
                    "width": round(fp.width, 4),
                    "height": round(fp.height, 4),
                })
        field_positions.sort(key=lambda x: x["confidence"], reverse=True)

        # 4. Perfiles de región por cluster
        region_profiles = []
        for cluster in learner.clusters.values():
            cluster_info = {
                "cluster_id": cluster.cluster_id,
                "cluster_name": cluster.format_key or cluster.cluster_id,
                "examples": cluster.example_count,
            }
            regions = []
            for rp in cluster.region_profiles:
                regions.append({
                    "region": rp.region_name,
                    "y_range": list(rp.y_range),
                    "fields_present": rp.fields,
                    "description": rp.description,
                })
            cluster_info["regions"] = regions
            region_profiles.append(cluster_info)

        # 5. Memoria
        memory_stats = learner.get_memory_stats()

        # 6. Correcciones recientes (últimas 20 para tabla)
        recent_corrections = []
        for field_name, wrong_map in corrections.items():
            for wrong_val, correct_val in wrong_map.items():
                recent_corrections.append({
                    "field": field_name,
                    "wrong": wrong_val,
                    "correct": correct_val,
                })
        recent_corrections = recent_corrections[:20]

        return jsonify({
            "success": True,
            "corrections_per_field": {
                "counts": counts,
                "total": total_corrections,
                "most_corrected": most_corrected,
            },
            "accuracy_estimate": accuracy_estimate,
            "field_positions": field_positions,
            "region_profiles": region_profiles,
            "memory_stats": memory_stats,
            "recent_corrections": recent_corrections,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════
#  Análisis de documento (DocumentAdvisor)
# ═══════════════════════════════════════════════════

advisor = DocumentAdvisor()


@app.route('/analyze', methods=['POST', 'OPTIONS'])
@require_rate_limit
@require_api_key
def analyze_document():
    """
    Analiza un documento y retorna problemas detectados con soluciones.
    
    POST multipart: file (imagen)
    o POST JSON: { "image_base64": "..." }
    
    Retorna:
        - problems: lista de problemas detectados
        - recommendation: recomendación general
        - overall_score: score de calidad (0-1)
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        # Obtener imagen
        if 'file' in request.files:
            file = request.files['file']
            img_bytes = file.read()
            nparr = np.frombuffer(img_bytes, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        elif request.is_json:
            data = request.get_json(force=True)
            import base64
            img_b64 = data.get('image_base64', '')
            if img_b64:
                img_bytes = base64.b64decode(img_b64)
                nparr = np.frombuffer(img_bytes, np.uint8)
                image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            else:
                return jsonify({'success': False, 'error': 'No se proporcionó imagen'}), 400
        else:
            return jsonify({'success': False, 'error': 'Formato no soportado'}), 400
        
        if image is None:
            return jsonify({'success': False, 'error': 'No se pudo decodificar la imagen'}), 400
        
        # Analizar
        analysis = advisor.analyze(image)
        
        return jsonify({
            'success': True,
            'analysis': analysis,
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Error al analizar'}), 500


@app.route('/compare', methods=['POST', 'OPTIONS'])
@require_rate_limit
@require_api_key
def compare_images():
    """
    Compara imagen original con enhancement.
    
    POST multipart: original, enhanced
    o POST JSON: { "original_base64": "...", "enhanced_base64": "..." }
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        import base64
        
        # Obtener imágenes
        if 'original' in request.files and 'enhanced' in request.files:
            orig_bytes = request.files['original'].read()
            enh_bytes = request.files['enhanced'].read()
            original = cv2.imdecode(np.frombuffer(orig_bytes, np.uint8), cv2.IMREAD_COLOR)
            enhanced = cv2.imdecode(np.frombuffer(enh_bytes, np.uint8), cv2.IMREAD_COLOR)
        elif request.is_json:
            data = request.get_json(force=True)
            orig_b64 = data.get('original_base64', '')
            enh_b64 = data.get('enhanced_base64', '')
            original = cv2.imdecode(np.frombuffer(base64.b64decode(orig_b64), np.uint8), cv2.IMREAD_COLOR)
            enhanced = cv2.imdecode(np.frombuffer(base64.b64decode(enh_b64), np.uint8), cv2.IMREAD_COLOR)
        else:
            return jsonify({'success': False, 'error': 'Formato no soportado'}), 400
        
        if original is None or enhanced is None:
            return jsonify({'success': False, 'error': 'No se pudieron decodificar las imágenes'}), 400
        
        # Comparar
        comparison = advisor.compare(original, enhanced)
        
        return jsonify({
            'success': True,
            'comparison': comparison,
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Error al comparar'}), 500


# ═══════════════════════════════════════════════════
#  Endpoint de calidad
# ═══════════════════════════════════════════════════

@app.route('/quality', methods=['POST', 'OPTIONS'])
@require_rate_limit
@require_api_key
def assess_quality():
    """
    Evalúa la calidad de una imagen.
    
    POST multipart: file
    o POST JSON: { "image_base64": "..." }
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        import base64
        
        if 'file' in request.files:
            file = request.files['file']
            img_bytes = file.read()
            image = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
        elif request.is_json:
            data = request.get_json(force=True)
            img_b64 = data.get('image_base64', '')
            image = cv2.imdecode(np.frombuffer(base64.b64decode(img_b64), np.uint8), cv2.IMREAD_COLOR)
        else:
            return jsonify({'success': False, 'error': 'Formato no soportado'}), 400
        
        if image is None:
            return jsonify({'success': False, 'error': 'No se pudo decodificar la imagen'}), 400
        
        quality = assess_scan_quality(image)
        
        return jsonify({
            'success': True,
            'quality': quality,
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': 'Error al evaluar calidad'}), 500


# ═══════════════════════════════════════════════════
#  Layout Detection + Document Parsing (NUEVO)
# ═══════════════════════════════════════════════════

@app.route('/layout', methods=['POST', 'OPTIONS'])
@require_rate_limit
@require_api_key
def detect_layout_endpoint():
    """
    Detecta layout de una imagen.

    POST multipart: file (imagen)
    o POST JSON: { "image_base64": "..." }

    Retorna:
        regions: lista de regiones detectadas
        summary: conteo por tipo
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    try:
        from core.layout_detector import detect_layout

        # Obtener imagen
        if 'file' in request.files:
            file = request.files['file']
            img_bytes = file.read()
            nparr = np.frombuffer(img_bytes, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        elif request.is_json:
            data = request.get_json(force=True)
            img_b64 = data.get('image_base64', '')
            if img_b64:
                import base64
                img_bytes = base64.b64decode(img_b64)
                nparr = np.frombuffer(img_bytes, np.uint8)
                image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            else:
                return jsonify({'success': False, 'error': 'No se proporcionó imagen'}), 400
        else:
            return jsonify({'success': False, 'error': 'Formato no soportado'}), 400

        if image is None:
            return jsonify({'success': False, 'error': 'No se pudo decodificar la imagen'}), 400

        # Detectar layout
        layout = detect_layout(image)

        # Extraer el contenido real de cada tabla detectada (antes esta
        # ruta solo devolvía la posición de la tabla, sin su contenido).
        from core.table_extractor import extract_table
        for region in layout.regions:
            if region.region_type == "table" and not region.html:
                try:
                    table_result = extract_table(image, bbox=region.bbox)
                    if table_result.html:
                        region.html = table_result.html
                        region.metadata["table_markdown"] = table_result.markdown
                        region.metadata["table_rows"] = table_result.rows
                        region.metadata["table_cols"] = table_result.cols
                except Exception as table_err:
                    print(f"  [WARN] No se pudo extraer tabla en {region.bbox}: {table_err}")

        return jsonify({
            'success': True,
            'layout': layout.to_dict(),
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/parse-document', methods=['POST', 'OPTIONS'])
@require_rate_limit
@require_api_key
def parse_document_endpoint():
    """
    Parsea un documento (PDF, DOCX, PPTX, XLSX, HTML).

    POST multipart: file (documento)

    Retorna:
        document: contenido del documento
        pages: número de páginas
        format: formato detectado
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    try:
        from core.document_parser import DocumentParser
        from core.layout_detector import detect_layout
        from core.structured_output import StructuredOutputGenerator

        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No se proporcionó archivo'}), 400

        file = request.files['file']
        filename = file.filename

        # Guardar temporalmente
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name

        try:
            # Parsear documento
            parser = DocumentParser(dpi=CONFIG.layout.pdf_dpi)
            doc = parser.parse(tmp_path)

            # Procesar cada página con layout detection
            output_gen = StructuredOutputGenerator()
            pages_data = []

            for page in doc.pages:
                page_info = {
                    "page_number": page.page_number,
                    "text": page.text[:2000] if page.text else "",
                    "tables": page.tables[:5] if page.tables else [],
                }

                # Detectar layout si hay imagen
                if page.image is not None:
                    layout = detect_layout(page.image)

                    # Extraer el contenido REAL de cada tabla detectada
                    # (antes quedaba como texto placeholder "[Tabla detectada]").
                    from core.table_extractor import extract_table
                    for region in layout.regions:
                        if region.region_type == "table" and not region.html:
                            try:
                                table_result = extract_table(page.image, bbox=region.bbox)
                                if table_result.html:
                                    region.html = table_result.html
                                    region.metadata["table_markdown"] = table_result.markdown
                                    region.metadata["table_rows"] = table_result.rows
                                    region.metadata["table_cols"] = table_result.cols
                            except Exception as table_err:
                                print(f"  [WARN] No se pudo extraer tabla en {region.bbox}: {table_err}")

                    page_info["layout"] = layout.to_dict()
                    page_info["markdown"] = output_gen.to_markdown(layout)

                pages_data.append(page_info)

            return jsonify({
                'success': True,
                'filename': filename,
                'format': doc.format,
                'num_pages': doc.num_pages,
                'pages': pages_data,
                'full_text': doc.get_full_text()[:5000],
            })

        finally:
            # Limpiar archivo temporal
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════
#  Historial de facturas — Libro de Compras/Ventas
# ═══════════════════════════════════════════════════

@app.route('/invoices', methods=['GET'])
def list_invoices_endpoint():
    """
    Lista/busca facturas guardadas en el historial.

    Query params:
        search: texto libre (razón social, número de factura, RIF, cliente)
        rif: filtra por RIF exacto
        date_from, date_to: filtran por fecha (formato tal como quedó en la factura)
        limit, offset: paginación (limit máx. 500)
        order: 'created_at DESC' (default) | 'created_at ASC' | 'fecha DESC' |
               'fecha ASC' | 'total DESC' | 'total ASC'
    """
    try:
        from utils.database import list_invoices
        result = list_invoices(
            limit=int(request.args.get('limit', 50)),
            offset=int(request.args.get('offset', 0)),
            search=request.args.get('search') or None,
            rif=request.args.get('rif') or None,
            date_from=request.args.get('date_from') or None,
            date_to=request.args.get('date_to') or None,
            order=request.args.get('order', 'created_at DESC'),
        )
        return jsonify({'success': True, **result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/invoices/summary', methods=['GET'])
def invoices_summary_endpoint():
    """Resumen contable: totales por moneda, RIFs más frecuentes, confianza promedio."""
    try:
        from utils.database import get_summary
        summary = get_summary(
            date_from=request.args.get('date_from') or None,
            date_to=request.args.get('date_to') or None,
        )
        return jsonify({'success': True, 'summary': summary})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/invoices/export', methods=['GET'])
def export_invoices_endpoint():
    """
    Descarga el historial filtrado como Excel o CSV — el libro de
    compras/ventas listo para el cierre mensual.

    Query params: fmt ('xlsx' default | 'csv'), search, rif, date_from, date_to
    """
    try:
        from utils.database import export_to_excel, export_to_csv
        fmt = request.args.get('fmt', 'xlsx').lower()
        kwargs = dict(
            search=request.args.get('search') or None,
            rif=request.args.get('rif') or None,
            date_from=request.args.get('date_from') or None,
            date_to=request.args.get('date_to') or None,
        )
        if fmt == 'csv':
            data = export_to_csv(**kwargs)
            return Response(
                data, mimetype='text/csv',
                headers={'Content-Disposition': 'attachment; filename=facturas_nad.csv'},
            )
        else:
            data = export_to_excel(**kwargs)
            return Response(
                data,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                headers={'Content-Disposition': 'attachment; filename=facturas_nad.xlsx'},
            )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/invoices/<int:invoice_id>', methods=['GET', 'DELETE'])
def invoice_detail_endpoint(invoice_id):
    """Obtiene o elimina una factura específica del historial."""
    try:
        from utils.database import get_invoice, delete_invoice
        if request.method == 'DELETE':
            ok = delete_invoice(invoice_id)
            if not ok:
                return jsonify({'success': False, 'error': 'Factura no encontrada'}), 404
            return jsonify({'success': True, 'deleted': invoice_id})

        inv = get_invoice(invoice_id)
        if not inv:
            return jsonify({'success': False, 'error': 'Factura no encontrada'}), 404
        return jsonify({'success': True, 'invoice': inv})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════
#  Exportar lote a PDF multipágina
# ═══════════════════════════════════════════════════

@app.route('/batch-pdf', methods=['POST', 'OPTIONS'])
@require_rate_limit
@require_api_key
def batch_pdf_endpoint():
    """
    Combina varias facturas ya procesadas en un único PDF multipágina.

    POST JSON: { "invoice_ids": [1, 2, 3] }
        Usa las miniaturas guardadas en el historial, O
    POST multipart: files (varias imágenes ya realzadas)
        Genera el PDF directamente de los archivos subidos.

    Retorna el PDF como descarga binaria.
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    try:
        images = []

        if request.is_json:
            data = request.get_json(force=True) or {}
            ids = data.get('invoice_ids', [])
            from utils.database import get_invoice
            for iid in ids:
                inv = get_invoice(iid)
                if inv and inv.get('thumbnail_b64'):
                    raw = base64.b64decode(inv['thumbnail_b64'])
                    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                    if img is not None:
                        images.append(img)
        else:
            for f in request.files.getlist('files'):
                raw = f.read()
                img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    images.append(img)

        if not images:
            return jsonify({'success': False, 'error': 'No hay imágenes válidas para el PDF'}), 400

        tmp_pdf = os.path.join(TEMP_DIR, f"lote_{int(datetime.now().timestamp())}.pdf")
        BatchPDFExporter.create_pdf(images, tmp_pdf, metadata={
            'title': 'NAD Scanner — Lote de Facturas',
            'author': 'NAD Scanner',
        })

        with open(tmp_pdf, 'rb') as f:
            pdf_bytes = f.read()
        try:
            os.remove(tmp_pdf)
        except Exception:
            pass

        return Response(
            pdf_bytes, mimetype='application/pdf',
            headers={'Content-Disposition': 'attachment; filename=facturas_nad.pdf'},
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════
#  Procesamiento modo Z (documentos largos, N shots + stitching)
# ═══════════════════════════════════════════════════

@app.route('/process-z', methods=['POST', 'OPTIONS'])
@require_rate_limit
@require_api_key
def process_z_shots():
    """
    Pipeline para documentos largos (Modo Z / formato Z).
    Recibe N fotos (8-12+) tomadas en secuencia vertical (top→bottom)
    con ~30% de overlap, las cose en una sola imagen continua mediante
    stitching pairwise (ORB + homografía + feathering/graphcut), y luego
    ejecuta el pipeline estándar (detección → realce → OCR).

    Query params:
        count: Número de shots enviados (default: 8)
        mode: 'limpio' | 'color' | 'grises'
        seam: 'feather' | 'graphcut' (default: 'feather')
        overlap: overlap esperado entre tomas (default: 0.30)

    POST multipart: shot_0, shot_1, ..., shot_{N-1}
        Cada campo debe ser un archivo JPEG/PNG.

    Retorna JSON con:
        - success: bool
        - stitched_image: imagen cosida en base64 (JPEG)
        - enhanced_image: imagen procesada final en base64 (JPEG)
        - ocr_data: dict con campos extraídos
        - validation_errors: lista de advertencias
        - qr_codes: códigos QR detectados
        - invoice_id: id en el historial
        - stats: métricas del pipeline
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    start_time = datetime.now()
    output_mode = request.args.get('mode', 'limpio')
    seam_method = request.args.get('seam', 'feather')
    overlap_pct = float(request.args.get('overlap', '0.30'))
    n_expected = int(request.args.get('count', '8'))
    n_expected = max(2, min(n_expected, 20))  # Límite: 2-20 tomas

    print(f"\n{'='*60}")
    print(f"  📐 MODO Z — {n_expected} tomas, seam={seam_method}, overlap={overlap_pct*100:.0f}%")
    print(f"{'='*60}")

    try:
        # ── 1. Recibir N imágenes ──
        shots = []
        for i in range(n_expected):
            file_key = f'shot_{i}'
            if file_key not in request.files:
                # Si falta alguna, usar las que llegaron (tolerante)
                print(f"  ⚠ Falta {file_key}, usando {len(shots)} imágenes disponibles")
                break

            file = request.files[file_key]
            img_bytes = file.read()

            if len(img_bytes) < 100:
                continue

            nparr = np.frombuffer(img_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                continue

            shots.append(img)

        if len(shots) < 2:
            return jsonify({'success': False, 'error': 'Se necesitan al menos 2 tomas para stitching'}), 400

        print(f"  📸 Recibidas {len(shots)}/{n_expected} imágenes")

        # ── 1b. Redimensionar ──
        MAX_DIM = 4000
        for i in range(len(shots)):
            h, w = shots[i].shape[:2]
            if max(h, w) > MAX_DIM:
                scale = MAX_DIM / max(h, w)
                shots[i] = cv2.resize(shots[i], (int(w * scale), int(h * scale)))

        # ── 2. Stitching pairwise secuencial ──
        print(f"🧵 Stitching pairwise ({seam_method})...")
        stitched = stitch_sequential(
            shots,
            overlap_pct=overlap_pct,
            seam_method=seam_method,
            show_debug=True,
        )

        if stitched is None:
            return jsonify({
                'success': False,
                'error': 'Stitching falló. Verifica que las imágenes tengan suficiente overlap (~30%)',
                'shots_received': len(shots),
            }), 500

        print(f"  ✅ Stitched: {stitched.shape[1]}x{stitched.shape[0]}")

        # ── 3. Codificar imagen cosida ──
        _, buf_stitch = cv2.imencode('.jpg', stitched, [cv2.IMWRITE_JPEG_QUALITY, 88])
        stitched_b64 = base64.b64encode(buf_stitch).decode('utf-8')

        # ── 4. Detección de documento (con calibración) ──
        print("🔍 Detectando documento en imagen cosida...")
        cal_dict_z = _get_calibrated_params()
        corners, _ = detect_document(stitched, calibrated_params=cal_dict_z)
        if corners is None:
            h, w = stitched.shape[:2]
            corners = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)

        # ── 5. Perspectiva + Realce ──
        print(f"🎨 Enderezando (modo: {output_mode})...")
        corrected = perspective_correct(stitched, corners)

        if output_mode == "color":
            enhanced, enhance_meta = enhanced_pipeline(
                corrected,
                mode="color",
                enable_shadow_removal=False,
                enable_wrinkle_correction=False,
                enable_color_restoration=True,
            )
        else:
            from core.enhancer import enhance_document
            enhanced = enhance_document(corrected, output_mode)
            enhance_meta = {"steps": [output_mode], "improvement": 0}

        quality = {"score": 0.8, "level": "buena"}
        try:
            quality = assess_scan_quality(enhanced)
        except Exception:
            pass
        print(f"  → Calidad: {quality.get('level', 'ok')} ({quality.get('score', 0):.2f})")

        # ── 6. OCR ──
        print("📝 Ejecutando OCR sobre imagen cosida...")
        invoice = _extract_best_invoice(enhanced, corrected)

        # ── 7. Codificar imagen final ──
        _, buffer = cv2.imencode('.jpg', enhanced, [cv2.IMWRITE_JPEG_QUALITY, 90])
        enhanced_b64 = base64.b64encode(buffer).decode('utf-8')

        elapsed = (datetime.now() - start_time).total_seconds()

        # ── 8. QR codes ──
        from core.qr_scanner import detect_codes, cross_check_with_ocr
        qr_codes = []
        qr_notes = []
        try:
            qr_codes = detect_codes(corrected)
            if not qr_codes:
                qr_codes = detect_codes(enhanced)
            if qr_codes:
                qr_notes = cross_check_with_ocr(qr_codes, invoice.to_dict())
        except Exception as qr_err:
            print(f"  [WARN] Error leyendo QR: {qr_err}")

        # ── 9. Alertas de tasa de cambio ──
        exchange_alert_summary = {"has_alerts": False, "count": 0, "alerts": []}
        if CONFIG.ocr.alert_enabled and invoice.all_rates:
            from ocr.exchange_alert import ExchangeAlert
            alert_engine = ExchangeAlert()
            alerts = alert_engine.check_all_currencies(invoice.all_rates)
            exchange_alert_summary = alert_engine.get_alert_summary(alerts)

        # ── 10. Respuesta ──
        ocr_data = invoice.to_dict()
        ocr_data['raw_text'] = invoice.raw_text
        all_validation_notes = list(invoice.validation_errors) + qr_notes

        # Guardar en historial
        saved_invoice_id = None
        if request.args.get('save', 'true').strip().lower() != 'false':
            try:
                from utils.database import save_invoice
                saved_invoice_id = save_invoice(
                    ocr_data=ocr_data,
                    validation_errors=all_validation_notes,
                    ocr_confidence=invoice.ocr_confidence,
                    qr_data={"codes": qr_codes} if qr_codes else None,
                    source="modo_z",
                    enhanced_image_b64=enhanced_b64,
                )
            except Exception as db_err:
                print(f"  [WARN] No se pudo guardar en el historial: {db_err}")

        response = {
            'success': True,
            'stitched_image': stitched_b64,
            'enhanced_image': enhanced_b64,
            'ocr_data': ocr_data,
            'validation_errors': all_validation_notes,
            'ocr_confidence': round(invoice.ocr_confidence, 4),
            'qr_codes': qr_codes,
            'invoice_id': saved_invoice_id,
            'exchange_alerts': exchange_alert_summary,
            'quality': quality,
            'stats': {
                'shots_received': len(shots),
                'stitched_size': f"{stitched.shape[1]}x{stitched.shape[0]}",
                'seam_method': seam_method,
                'time_seconds': round(elapsed, 2),
            }
        }

        print(f"✅ Modo Z completado en {elapsed:.1f}s — {len(shots)} tomas cosidas")
        return jsonify(response)

    except Exception as e:
        import traceback
        traceback.print_exc()
        elapsed = (datetime.now() - start_time).total_seconds()
        error_msg = 'Error interno del servidor'
        if 'timeout' in str(e).lower():
            error_msg = 'Tiempo de procesamiento excedido'
        elif 'memory' in str(e).lower():
            error_msg = 'Memoria insuficiente para procesar'
        return jsonify({'success': False, 'error': error_msg, 'time_seconds': round(elapsed, 2)}), 500

# ═══════════════════════════════════════════════════
#  Pipeline Asincrono (shot-by-shot) — Modo Z
# ═══════════════════════════════════════════════════

@app.route('/process-shot', methods=['POST', 'OPTIONS'])
@require_rate_limit
@require_api_key
def process_shot():
    """
    Recibe un shot individual para stitching incremental asincronico.

    Cada shot se envia individualmente (no espera a tener N fotos),
    se guarda en disco y se hace stitching incremental inmediato.
    Cuando el usuario ha capturado todos los shots, llama a
    POST /process-shot/<session_id>/finalize para completar el pipeline.

    Query params:
        session_id: ID de sesion existente, o 'new' para crear una nueva.
        total_shots: Numero total de shots esperados (obligatorio si session_id=new).
        shot_index: Indice de este shot (0-based). Si no se provee, se auto-asigna.
        overlap: Overlap esperado entre tomas (default: 0.30).
        seam: 'feather' | 'graphcut' (default: 'feather').
        mode: 'limpio' | 'color' | 'grises' (default: 'limpio').

    POST multipart: image (archivo JPEG/PNG)

    Retorna JSON con:
        - success: bool
        - session_id: str
        - shot_index: int
        - received: int (shots recibidos hasta ahora)
        - total_shots: int
        - incremental_matched: int (pares stitchados incrementalmente)
        - canvas_preview: base64 JPEG opcional (cada 3 shots para feedback visual)
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    try:
        # ── Parametros ──
        session_id = request.args.get('session_id', '').strip()
        total_shots = request.args.get('total_shots', '0').strip()
        shot_index = request.args.get('shot_index', '-1').strip()
        overlap_pct = float(request.args.get('overlap', '0.30'))
        seam_method = request.args.get('seam', 'feather')
        output_mode = request.args.get('mode', 'limpio')
        ghost_offset_y = float(request.args.get('ghost_offset_y', '0.0'))
        ghost_scale = float(request.args.get('ghost_scale', '1.0'))

        # ── Imagen ──
        if 'image' not in request.files:
            return jsonify({'success': False, 'error': 'No se recibio imagen (campo "image")'}), 400

        file = request.files['image']
        img_bytes = file.read()
        if len(img_bytes) < 100:
            return jsonify({'success': False, 'error': 'Imagen vacia o muy pequena'}), 400

        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return jsonify({'success': False, 'error': 'No se pudo decodificar la imagen'}), 400

        # Redimensionar si es necesario
        MAX_DIM = 4000
        h, w = img.shape[:2]
        if max(h, w) > MAX_DIM:
            scale = MAX_DIM / max(h, w)
            old_dim = (w, h)
            img = cv2.resize(img, (int(w * scale), int(h * scale)))
            h, w = img.shape[:2]
            print(f"  [Async] Shot redimensionado: {old_dim[0]}x{old_dim[1]} -> {w}x{h}")

        # ── Gestion de sesion ──
        mgr = get_session_manager(_session_dir)

        if not session_id or session_id == 'new':
            # Crear nueva sesion
            n_total = int(total_shots) if total_shots and total_shots.isdigit() else 10
            session_id = mgr.create_session(
                total_shots=n_total,
                overlap_pct=overlap_pct,
                seam_method=seam_method,
                output_mode=output_mode,
            )
            shot_idx = 0
        else:
            # Sesion existente
            state = mgr.get_session(session_id)
            if not state:
                return jsonify({'success': False, 'error': 'Sesion no encontrada. Puede haber expirado.'}), 404

            # Determinar indice del shot
            if shot_index and shot_index.isdigit():
                shot_idx = int(shot_index)
            else:
                # Auto-asignar: primer indice disponible
                existing_indices = {s.index for s in state.shots}
                shot_idx = 0
                while shot_idx in existing_indices:
                    shot_idx += 1

        # ── Agregar shot a la sesion ──
        success, msg = mgr.add_shot(
            session_id, shot_idx, img,
            ghost_offset_y=ghost_offset_y,
            ghost_scale=ghost_scale,
        )
        if not success:
            return jsonify({'success': False, 'error': msg}), 400

        # Obtener estado actualizado
        status = mgr.get_status(session_id)

        # Generar preview del canvas cada 3 shots (para feedback visual)
        canvas_b64 = None
        state = mgr.get_session(session_id)
        if state and state.current_canvas is not None and len(state.shots) % 3 == 0:
            try:
                hc, wc = state.current_canvas.shape[:2]
                pw = 320
                ph = int(pw * hc / wc)
                preview = cv2.resize(state.current_canvas, (pw, ph))
                _, buf = cv2.imencode('.jpg', preview, [cv2.IMWRITE_JPEG_QUALITY, 70])
                canvas_b64 = base64.b64encode(buf).decode('utf-8')
            except Exception:
                pass

        received = status['received_shots']
        total = status['total_shots']
        print(f"  [Async] Shot {shot_idx} recibido -> sesion {session_id} ({received}/{total})")

        response = {
            'success': True,
            'session_id': session_id,
            'shot_index': shot_idx,
            'received': received,
            'total_shots': total,
            'missing': status['missing_shots'],
            'incremental_matched': status['incremental_matched'],
            'canvas_preview': canvas_b64,
            'server_version': VERSION,
        }

        return jsonify(response)

    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = 'Error interno del servidor'
        if 'timeout' in str(e).lower():
            error_msg = 'Tiempo de procesamiento excedido'
        return jsonify({'success': False, 'error': error_msg}), 500


@app.route('/process-shot/<session_id>/status', methods=['GET', 'OPTIONS'])
@require_rate_limit
def process_shot_status(session_id):
    """
    Retorna el estado actual de una sesion de stitching incremental.

    Util para que la UI muestre progreso: cuantos shots recibidos,
    cuantos faltan, y si el stitching incremental ha avanzado.

    GET query params (opcional):
        preview: 'true' para incluir thumbnail del canvas actual.

    Retorna:
        - success: bool
        - session_id: str
        - status: 'active' | 'finalizing' | 'completed' | 'failed'
        - received_shots: int
        - total_shots: int
        - missing_shots: int
        - shot_indices: [int, ...]
        - incremental_matched: int
        - canvas: {width, height} o null
        - canvas_preview: base64 JPEG (solo si preview=true)
        - elapsed_seconds: float
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    try:
        mgr = get_session_manager(_session_dir)
        st = mgr.get_status(session_id)

        if st is None:
            return jsonify({'success': False, 'error': 'Sesion no encontrada'}), 404

        # Incluir thumbnail si se solicita
        if request.args.get('preview', '').lower() == 'true':
            state = mgr.get_session(session_id)
            if state and state.current_canvas is not None:
                try:
                    h, w = state.current_canvas.shape[:2]
                    pw = 320
                    ph = int(pw * h / w)
                    preview = cv2.resize(state.current_canvas, (pw, ph))
                    _, buf = cv2.imencode('.jpg', preview, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    st['canvas_preview'] = base64.b64encode(buf).decode('utf-8')
                except Exception:
                    st['canvas_preview'] = None

        return jsonify({'success': True, **st})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/process-shot/<session_id>/finalize', methods=['POST', 'OPTIONS'])
@require_rate_limit
@require_api_key
def process_shot_finalize(session_id):
    """
    Finaliza una sesion de stitching incremental.

    Completa el stitching de todos los shots recibidos, recorta bordes
    negros, ejecuta el pipeline de OCR completo, y retorna el resultado.

    POST query params:
        ocr: 'true' | 'false' (default: 'true') -- ejecutar OCR.
        save: 'true' | 'false' (default: 'true') -- guardar en historial.

    Retorna JSON con:
        - success: bool
        - session_id: str
        - stitched_image: base64 JPEG
        - enhanced_image: base64 JPEG (si ocr=true)
        - ocr_data: dict (si ocr=true)
        - validation_errors: [str] (si ocr=true)
        - qr_codes: [dict] (si ocr=true)
        - invoice_id: int o null (si ocr=true y save=true)
        - canvas: {width, height}
        - elapsed_seconds: float
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    start_time = datetime.now()

    try:
        mgr = get_session_manager(_session_dir)
        run_ocr = request.args.get('ocr', 'true').lower() != 'false'

        result = mgr.finalize(session_id, run_ocr=run_ocr)

        if result is None:
            return jsonify({'success': False, 'error': 'Sesion no encontrada'}), 404

        if not result.get('success'):
            return jsonify(result), 500

        elapsed = (datetime.now() - start_time).total_seconds()
        result['elapsed_seconds'] = round(elapsed, 2)

        # Alertas de tasa de cambio
        if run_ocr and result.get('ocr_data') and CONFIG.ocr.alert_enabled:
            try:
                from ocr.exchange_alert import ExchangeAlert
                alert_engine = ExchangeAlert()
                exchange_alerts = alert_engine.check_all_currencies(
                    result['ocr_data'].get('all_rates', {})
                )
                alert_engine.print_alerts(exchange_alerts)
                result['exchange_alerts'] = alert_engine.get_alert_summary(exchange_alerts)
            except Exception:
                pass

        # Limpiar sesiones expiradas despues de finalizar
        mgr.cleanup_expired()

        print(f"  [Async] Sesion {session_id} finalizada en {elapsed:.1f}s")
        return jsonify(result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        elapsed = (datetime.now() - start_time).total_seconds()
        return jsonify({
            'success': False,
            'error': 'Error interno del servidor',
            'elapsed_seconds': round(elapsed, 2),
        }), 500


@app.route('/process-shot/<session_id>', methods=['DELETE', 'OPTIONS'])
@require_rate_limit
@require_api_key
def process_shot_delete(session_id):
    """
    Elimina una sesion de stitching y libera sus recursos.

    DELETE /process-shot/<session_id>

    Retorna:
        - success: bool
        - deleted: session_id
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    try:
        mgr = get_session_manager(_session_dir)
        ok = mgr.delete_session(session_id)
        if not ok:
            return jsonify({'success': False, 'error': 'Sesion no encontrada'}), 404
        return jsonify({'success': True, 'deleted': session_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/process-shot/sessions', methods=['GET', 'OPTIONS'])
@require_rate_limit
def list_shot_sessions():
    """
    Lista todas las sesiones de stitching activas.

    GET /process-shot/sessions

    Retorna:
        - success: bool
        - sessions: [{session_id, status, total_shots, received, ...}]
        - count: int
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    try:
        mgr = get_session_manager(_session_dir)
        sessions = mgr.list_active_sessions()
        return jsonify({
            'success': True,
            'sessions': sessions,
            'count': len(sessions),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════

# ═══════════════════════════════════════════════════
#  Background Jobs — Stitching Asíncrono con Polling
# ═══════════════════════════════════════════════════

def _run_background_stitch(job_id: str):
    """Worker de background para stitching + OCR.

    Ejecuta el pipeline completo en un hilo separado y actualiza
    el progreso en el JobManager para que el cliente pueda hacer polling.

    Etapas con pesos:
      queued(0%) → stitching(35%) → detecting(10%) → enhancing(10%)
      → ocr(25%) → qr(8%) → saving(7%) → completed(100%)
    """
    mgr = get_job_manager()
    jm = get_session_manager(_session_dir)

    job_status = mgr.get_status(job_id)
    if not job_status:
        return

    session_id = job_status.get('session_id')

    # ── Etapa 1: Stitching ──
    mgr.set_progress(job_id, "stitching", sub_progress=0.0,
                     sub_message="Cargando imagenes del disco...")

    try:
        state = jm.get_session(session_id) if session_id else None
        if session_id and state:
            sorted_shots = sorted(state.shots, key=lambda s: s.index)
            images = []
            for sd in sorted_shots:
                if mgr.is_cancelled(job_id):
                    return
                img = cv2.imread(sd.stored_path)
                if img is not None:
                    images.append(img)

            if len(images) < 1:
                raise ValueError("No hay imagenes para procesar")

            # Stitching con progreso incremental
            from core.stitch import stitch_sequential

            for i in range(len(images)):
                if mgr.is_cancelled(job_id):
                    return
                sub_pct = (i + 1) / max(len(images), 1)
                mgr.set_progress(job_id, "stitching", sub_progress=sub_pct,
                                 sub_message=f"Par {i+1}/{len(images)-1} — ORB + homografia")

            canvas = stitch_sequential(
                images,
                overlap_pct=state.overlap_pct,
                seam_method=state.seam_method,
                show_debug=False,
            )
            if canvas is None:
                raise ValueError("Stitching completo fallo")

            mgr.set_progress(job_id, "stitching", sub_progress=1.0,
                             sub_message=f"Canvas: {canvas.shape[1]}x{canvas.shape[0]}")

            # ── Etapa 2: Deteccion de documento ──
            mgr.set_progress(job_id, "detecting", sub_progress=0.0,
                             sub_message="Buscando contornos del documento...")

            from core.detector import detect_document
            corners, _ = detect_document(canvas)
            if corners is None:
                h, w = canvas.shape[:2]
                corners = np.array([
                    [0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]
                ], dtype=np.float32)

            mgr.set_progress(job_id, "detecting", sub_progress=0.5,
                             sub_message="Corrigiendo perspectiva...")

            from core.enhancer import perspective_correct
            corrected = perspective_correct(canvas, corners)

            mgr.set_progress(job_id, "detecting", sub_progress=1.0)

            # ── Etapa 3: Realce ──
            mgr.set_progress(job_id, "enhancing", sub_progress=0.0,
                             sub_message="Aplicando realce de contraste...")

            from core.enhancer import enhance_document
            output_mode = state.output_mode
            enhanced = enhance_document(corrected, output_mode)

            mgr.set_progress(job_id, "enhancing", sub_progress=1.0)

            # ── Etapa 4: OCR ──
            mgr.set_progress(job_id, "ocr", sub_progress=0.0,
                             sub_message="Ejecutando OCR (PaddleOCR)...")

            from ocr.extractor import extract_invoice_data
            invoice = extract_invoice_data(enhanced, interactive=False)

            if corrected is not None and invoice.ocr_confidence < 0.55:
                mgr.set_progress(job_id, "ocr", sub_progress=0.6,
                                 sub_message="Confianza baja — reintentando con imagen sin filtrar...")
                try:
                    alt = extract_invoice_data(corrected, interactive=False)
                    if alt.ocr_confidence > invoice.ocr_confidence:
                        invoice = alt
                except Exception:
                    pass

            mgr.set_progress(job_id, "ocr", sub_progress=0.9,
                             sub_message=f"OCR completado ({invoice.ocr_confidence:.0%} confianza)")

            # Codificar enhanced
            _, enh_buffer = cv2.imencode('.jpg', enhanced, [cv2.IMWRITE_JPEG_QUALITY, 90])
            enhanced_b64 = base64.b64encode(enh_buffer).decode('utf-8')
            _, stitch_buffer = cv2.imencode('.jpg', canvas, [cv2.IMWRITE_JPEG_QUALITY, 92])
            stitched_b64 = base64.b64encode(stitch_buffer).decode('utf-8')

            mgr.set_progress(job_id, "ocr", sub_progress=1.0)

            # ── Etapa 5: QR ──
            mgr.set_progress(job_id, "qr", sub_progress=0.0,
                             sub_message="Buscando codigos QR...")

            from core.qr_scanner import detect_codes, cross_check_with_ocr
            qr_codes = []
            qr_notes = []
            try:
                qr_codes = detect_codes(corrected)
                if not qr_codes:
                    qr_codes = detect_codes(enhanced)
                if qr_codes:
                    qr_notes = cross_check_with_ocr(qr_codes, invoice.to_dict())
            except Exception as qr_err:
                print(f"  [Job] QR fallo: {qr_err}")

            mgr.set_progress(job_id, "qr", sub_progress=1.0,
                             sub_message=f"QR: {len(qr_codes)} codigos detectados")

            # ── Etapa 6: Guardar ──
            mgr.set_progress(job_id, "saving", sub_progress=0.0,
                             sub_message="Guardando en historial...")

            ocr_data = invoice.to_dict()
            ocr_data['raw_text'] = invoice.raw_text
            all_validation = list(invoice.validation_errors) + qr_notes

            saved_invoice_id = None
            try:
                from utils.database import save_invoice
                saved_invoice_id = save_invoice(
                    ocr_data=ocr_data,
                    validation_errors=all_validation,
                    ocr_confidence=invoice.ocr_confidence,
                    qr_data={"codes": qr_codes} if qr_codes else None,
                    source="z_async_job",
                    enhanced_image_b64=enhanced_b64,
                )
            except Exception as db_err:
                print(f"  [Job] DB save fallo: {db_err}")

            mgr.set_progress(job_id, "saving", sub_progress=1.0)

            # Resultado final
            result = {
                "success": True,
                "stitched_image": stitched_b64,
                "enhanced_image": enhanced_b64,
                "ocr_data": ocr_data,
                "validation_errors": all_validation,
                "ocr_confidence": round(invoice.ocr_confidence, 4),
                "qr_codes": qr_codes,
                "invoice_id": saved_invoice_id,
                "stitched_width": canvas.shape[1],
                "stitched_height": canvas.shape[0],
                "total_shots_used": len(images),
                "incremental_matched": state.incremental_matched if state else 0,
            }

            mgr.set_completed(job_id, result)

        else:
            raise ValueError("Sesion no encontrada o sin datos")

    except Exception as e:
        import traceback
        traceback.print_exc()
        mgr._set_failed(job_id, str(e))


def _run_background_finalize(job_id: str):
    """Worker de background para finalize de sesion shot-by-shot."""
    mgr = get_job_manager()
    jm = get_session_manager(_session_dir)

    job_status = mgr.get_status(job_id)
    if not job_status:
        return

    session_id = job_status.get('session_id')

    try:
        mgr.set_progress(job_id, "stitching", sub_progress=0.0,
                         sub_message="Finalizando stitching incremental...")

        result = jm.finalize(session_id, run_ocr=True)

        if result is None:
            raise ValueError("Sesion no encontrada para finalizar")

        if not result.get('success'):
            raise ValueError(result.get('error', 'Error desconocido en finalize'))

        mgr.set_completed(job_id, result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        mgr._set_failed(job_id, str(e))


@app.route('/process-z-async', methods=['POST', 'OPTIONS'])
@require_rate_limit
@require_api_key
def process_z_async():
    """
    Version asincrona de /process-z con polling.

    Recibe N fotos (8-12+), crea un job de background, devuelve
    job_id inmediatamente. El cliente hace polling a /job-status/<id>.

    Query params:
        count: Numero de shots (default: 8)
        mode: 'limpio' | 'color' | 'grises'
        seam: 'feather' | 'graphcut'
        overlap: overlap esperado (default: 0.30)

    POST multipart: shot_0, shot_1, ..., shot_{N-1}

    Retorna:
        - success: bool
        - job_id: str (para polling a /job-status/<job_id>)
        - status_url: str (URL completa para polling)
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    start_time = datetime.now()

    try:
        count = int(request.args.get('count', '8'))
        output_mode = request.args.get('mode', 'limpio')
        seam_method = request.args.get('seam', 'feather')
        overlap_pct = float(request.args.get('overlap', '0.30'))

        if count < 2 or count > 30:
            return jsonify({
                'success': False,
                'error': f'count debe estar entre 2 y 30 (recibido: {count})'
            }), 400

        # Recibir imagenes
        shots = []
        for i in range(count):
            file_key = f'shot_{i}'
            if file_key not in request.files:
                return jsonify({
                    'success': False,
                    'error': f'Falta la imagen {file_key}'
                }), 400

            file = request.files[file_key]
            nparr = np.frombuffer(file.read(), np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                return jsonify({
                    'success': False,
                    'error': f'No se pudo decodificar {file_key}'
                }), 400
            shots.append(img)

        if len(shots) < 2:
            return jsonify({'success': False, 'error': 'Se necesitan al menos 2 fotos'}), 400

        # Redimensionar si necesario
        MAX_DIM = 4000
        for i in range(len(shots)):
            h, w = shots[i].shape[:2]
            if max(h, w) > MAX_DIM:
                scale = MAX_DIM / max(h, w)
                shots[i] = cv2.resize(shots[i], (int(w * scale), int(h * scale)))

        # Crear sesion temporal con las imagenes
        session_id = _shot_session_mgr.create_session(
            total_shots=len(shots),
            overlap_pct=overlap_pct,
            seam_method=seam_method,
            output_mode=output_mode,
        )

        for idx, img in enumerate(shots):
            success, msg = _shot_session_mgr.add_shot(session_id, idx, img)
            if not success:
                _shot_session_mgr.delete_session(session_id)
                return jsonify({'success': False, 'error': f'Error agregando shot {idx}: {msg}'}), 500

        # Crear job
        job_id = _job_mgr.create_job(session_id=session_id, total_shots=len(shots))
        _job_mgr.start_job(job_id, _run_background_stitch)

        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"  [AsyncJob] Job {job_id} creado ({len(shots)} shots, setup en {elapsed:.2f}s)")

        stats = _job_mgr.get_worker_stats()
        return jsonify({
            'success': True,
            'job_id': job_id,
            'session_id': session_id,
            'status_url': f'/job-status/{job_id}',
            'total_shots': len(shots),
            'estimated_time_seconds': max(10, int(len(shots) * 1.5)),
            'queue_position': 0,
            'max_workers': stats['max_workers'],
            'active_workers': stats['active_workers'],
            'queue_length': stats['queue_length'],
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/process-shot/<session_id>/finalize-async', methods=['POST', 'OPTIONS'])
@require_rate_limit
@require_api_key
def process_shot_finalize_async(session_id):
    """
    Version asincrona de /process-shot/<session_id>/finalize con polling.

    Retorna job_id inmediatamente. El estado del stitching+OCR se
    puede consultar via /job-status/<job_id>.

    POST query params:
        ocr: 'true' | 'false' (default: 'true')

    Retorna:
        - success: bool
        - job_id: str
        - status_url: str
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    start_time = datetime.now()

    try:
        # Verificar que la sesion existe
        state = _shot_session_mgr.get_session(session_id)
        if not state:
            return jsonify({'success': False, 'error': 'Sesion no encontrada'}), 404
        if state.status != "active" and state.status != "completed":
            return jsonify({
                'success': False,
                'error': f'Sesion en estado "{state.status}". Debe estar "active".'
            }), 400

        n_shots = len(state.shots)
        if n_shots == 0:
            return jsonify({'success': False, 'error': 'Sesion sin shots'}), 400

        # Crear job
        job_id = _job_mgr.create_job(session_id=session_id, total_shots=n_shots)
        _job_mgr.start_job(job_id, _run_background_finalize)

        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"  [AsyncJob] Job {job_id} creado para finalize de {session_id} ({elapsed:.2f}s)")

        stats = _job_mgr.get_worker_stats()
        return jsonify({
            'success': True,
            'job_id': job_id,
            'session_id': session_id,
            'status_url': f'/job-status/{job_id}',
            'total_shots': n_shots,
            'shots_received': len(state.shots),
            'estimated_time_seconds': max(8, int(n_shots * 1.2)),
            'queue_position': 0,
            'max_workers': stats['max_workers'],
            'active_workers': stats['active_workers'],
            'queue_length': stats['queue_length'],
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/job-status/<job_id>', methods=['GET', 'OPTIONS'])
def job_status(job_id):
    """
    Retorna el estado actual de un job de background.

    GET /job-status/<job_id>

    Retorna:
        - success: bool
        - job_id: str
        - status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
        - progress: {stage, percent, message, sub_message, elapsed_seconds, estimated_remaining_seconds}
        - result: dict (solo si status=completed)
        - error: str (solo si status=failed)
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    mgr = get_job_manager()
    status = mgr.get_status(job_id)

    if status is None:
        return jsonify({'success': False, 'error': 'Job no encontrado'}), 404

    return jsonify({'success': True, **status})


@app.route('/job-status/<job_id>', methods=['DELETE', 'OPTIONS'])
@require_rate_limit
def job_delete(job_id):
    """
    Cancela y/o elimina un job.

    DELETE /job-status/<job_id>
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    mgr = get_job_manager()
    # Intentar cancelar primero (si esta corriendo)
    mgr.cancel_job(job_id)
    # Luego eliminar
    ok = mgr.delete_job(job_id)
    if not ok:
        return jsonify({'success': False, 'error': 'Job no encontrado'}), 404
    return jsonify({'success': True, 'deleted': job_id})


@app.route('/job-status', methods=['GET', 'OPTIONS'])
@require_rate_limit
def job_list_active():
    """
    Lista jobs activos (queued + running).

    GET /job-status

    Retorna:
        - success: bool
        - jobs: [{job_id, status, stage, percent, total_shots, elapsed, ...}]
        - count: int
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    mgr = get_job_manager()
    jobs = mgr.list_active_jobs()
    return jsonify({
        'success': True,
        'jobs': jobs,
        'count': len(jobs),
    })


# ═══════════════════════════════════════════════════
#  ADMIN — Multi-Tenant Panel
# ═══════════════════════════════════════════════════

@app.route('/admin')
def admin_panel():
    """Sirve el panel de administración multi-tenant."""
    init_tenant_db()
    seed_demo_data()
    return render_template('admin.html')


# ── Tenants ────────────────────────────────────────

@app.route('/api/admin/tenants', methods=['GET', 'POST', 'OPTIONS'])
@require_rate_limit
def admin_tenants():
    """
    GET  → lista de todos los tenants con stats
    POST → crear nuevo tenant
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    if request.method == 'GET':
        search = request.args.get('search', '').strip()
        try:
            tenants = list_tenants(search=search or None)
            return jsonify(tenants)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # POST
    try:
        data = request.get_json(force=True)
        tenant = create_tenant(
            name=data.get('name', ''),
            email=data.get('email', ''),
            phone=data.get('phone', ''),
            address=data.get('address', ''),
            rif=data.get('rif', ''),
            max_users=int(data.get('max_users', 10)),
            max_storage_mb=int(data.get('max_storage_mb', 500)),
            notes=data.get('notes', ''),
        )
        if not tenant:
            return jsonify({'error': 'No se pudo crear el tenant'}), 400
        print(f"  [Admin] Tenant creado: {tenant['name']} (slug: {tenant['slug']})")
        return jsonify(tenant), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/tenants/<int:tenant_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@require_rate_limit
def admin_tenant_detail(tenant_id):
    """
    GET    → detalle de un tenant
    PUT    → actualizar tenant
    DELETE → desactivar/eliminar tenant
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    if request.method == 'GET':
        tenant = get_tenant(tenant_id)
        if not tenant:
            return jsonify({'error': 'Tenant no encontrado'}), 404
        return jsonify(tenant)

    if request.method == 'PUT':
        try:
            data = request.get_json(force=True)
            tenant = update_tenant(
                tenant_id,
                name=data.get('name'),
                email=data.get('email'),
                phone=data.get('phone'),
                address=data.get('address'),
                rif=data.get('rif'),
                max_users=int(data['max_users']) if 'max_users' in data else None,
                max_storage_mb=int(data['max_storage_mb']) if 'max_storage_mb' in data else None,
                is_active=data.get('is_active'),
                notes=data.get('notes'),
            )
            if not tenant:
                return jsonify({'error': 'Tenant no encontrado'}), 404
            print(f"  [Admin] Tenant actualizado: {tenant['name']} (id={tenant_id})")
            return jsonify(tenant)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # DELETE
    try:
        hard = request.args.get('hard', '').lower() == 'true'
        ok = delete_tenant(tenant_id, hard=hard)
        if not ok:
            return jsonify({'error': 'Tenant no encontrado'}), 404
        print(f"  [Admin] Tenant {'eliminado' if hard else 'desactivado'}: id={tenant_id}")
        return jsonify({'success': True, 'hard': hard})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Tenant Users ───────────────────────────────────

@app.route('/api/admin/tenants/<int:tenant_id>/users', methods=['GET', 'POST', 'OPTIONS'])
@require_rate_limit
def admin_tenant_users(tenant_id):
    """
    GET  → lista de usuarios de un tenant
    POST → agregar usuario a un tenant
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    if request.method == 'GET':
        try:
            users = list_tenant_users(tenant_id)
            return jsonify(users)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # POST
    try:
        data = request.get_json(force=True)
        user = add_tenant_user(
            tenant_id,
            user_email=data.get('user_email', ''),
            user_name=data.get('user_name', ''),
            role=data.get('role', 'user'),
        )
        if not user:
            tenant = get_tenant(tenant_id)
            if not tenant:
                return jsonify({'error': 'Tenant no encontrado'}), 404
            if not tenant['is_active']:
                return jsonify({'error': 'Tenant inactivo'}), 400
            return jsonify({'error': 'Límite de usuarios alcanzado o usuario ya existe'}), 400
        print(f"  [Admin] Usuario agregado: {user['user_email']} ({user['role']}) en tenant {tenant_id}")
        return jsonify(user), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/tenants/<int:tenant_id>/users/<int:user_id>', methods=['DELETE', 'OPTIONS'])
@require_rate_limit
def admin_tenant_user_delete(tenant_id, user_id):
    """DELETE → eliminar usuario de un tenant."""
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    try:
        ok = delete_tenant_user(user_id)
        if not ok:
            return jsonify({'error': 'Usuario no encontrado'}), 404
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Usage Metrics ──────────────────────────────────

@app.route('/api/admin/usage', methods=['GET', 'OPTIONS'])
@require_rate_limit
def admin_usage():
    """GET → métricas globales de uso de todos los tenants."""
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    try:
        data = get_global_usage_summary()
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Invoices by Tenant ────────────────────────────

@app.route('/api/admin/invoices', methods=['GET', 'OPTIONS'])
@require_rate_limit
def admin_invoices():
    """
    GET → listar facturas con filtro por tenant.

    Query params:
        tenant_id: opcional, filtrar por tenant
        limit: default 20
        offset: default 0
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    try:
        tenant_id = request.args.get('tenant_id')
        limit = min(int(request.args.get('limit', 20)), 100)
        offset = int(request.args.get('offset', 0))

        from utils.database import DB_PATH
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row

        if tenant_id:
            total = conn.execute(
                "SELECT COUNT(*) FROM invoices WHERE tenant_id = ?", (int(tenant_id),)
            ).fetchone()[0]
            rows = conn.execute(
                """SELECT i.*, COALESCE(t.name, 'Sin asignar') as tenant_name
                   FROM invoices i
                   LEFT JOIN tenants t ON i.tenant_id = t.id
                   WHERE i.tenant_id = ?
                   ORDER BY i.created_at DESC LIMIT ? OFFSET ?""",
                (int(tenant_id), limit, offset),
            ).fetchall()
        else:
            total = conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
            rows = conn.execute(
                """SELECT i.*, COALESCE(t.name, 'Sin asignar') as tenant_name
                   FROM invoices i
                   LEFT JOIN tenants t ON i.tenant_id = t.id
                   ORDER BY i.created_at DESC LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()

        items = []
        for r in rows:
            d = dict(r)
            d["validation_errors"] = json.loads(d.get("validation_errors") or "[]")
            d["qr_data"] = json.loads(d["qr_data"]) if d.get("qr_data") else None
            items.append(d)
        conn.close()

        return jsonify({"items": items, "total": total, "limit": limit, "offset": offset})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/invoices/<int:invoice_id>', methods=['GET', 'OPTIONS'])
@require_rate_limit
def admin_invoice_detail(invoice_id):
    """GET → detalle de una factura."""
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    try:
        from utils.database import get_invoice, DB_PATH
        inv = get_invoice(invoice_id)
        if not inv:
            return jsonify({'error': 'Factura no encontrada'}), 404
        # Agregar nombre del tenant con JOIN simple
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT COALESCE(t.name, 'Sin asignar') as tenant_name
               FROM (SELECT ? as tenant_id) src
               LEFT JOIN tenants t ON src.tenant_id = t.id""",
            (inv.get('tenant_id'),),
        ).fetchone()
        inv['tenant_name'] = row['tenant_name'] if row else 'Sin asignar'
        conn.close()
        return jsonify(inv)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ═══════════════════════════════════════════════════

def _resolve_tenant_id_for_request() -> Optional[int]:
    """
    Resuelve el tenant_id de la petición actual.

    Prioridad:
    1. Sesión Supabase válida (g.user_email) -> busca en tenant_users.
    2. `tenant_id` explícito en el body/query (modo sin Supabase, ej. solo
       API key) — solo se acepta si NO hay sesión Supabase activa, para no
       permitir que un usuario autenticado suplante a otro tenant.
    """
    user_email = getattr(g, 'user_email', None)
    if user_email:
        from utils.tenant_db import DB_PATH, init_tenant_db
        import sqlite3
        init_tenant_db()
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT tenant_id FROM tenant_users WHERE user_email = ? AND is_active = 1",
                (user_email,)
            ).fetchone()
            return row['tenant_id'] if row else None
        finally:
            conn.close()

    raw = request.args.get('tenant_id') or (request.get_json(silent=True) or {}).get('tenant_id')
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


@app.route('/drive/status', methods=['GET'])
@require_rate_limit
@require_api_key
def drive_status_endpoint():
    """Indica si Drive está configurado en el servidor y si el tenant actual ya lo conectó."""
    from drive.uploader import is_drive_oauth_configured
    tenant_id = _resolve_tenant_id_for_request()
    if not tenant_id:
        return jsonify({'success': False, 'error': 'No se pudo determinar el tenant (inicia sesión o envía tenant_id).'}), 400

    from utils.tenant_db import get_drive_token
    token_row = get_drive_token(tenant_id)
    return jsonify({
        'success': True,
        'configured': is_drive_oauth_configured(),
        'connected': token_row is not None,
        'google_email': (token_row or {}).get('google_email', ''),
    })


@app.route('/drive/connect', methods=['GET'])
@require_rate_limit
@require_api_key
def drive_connect_endpoint():
    """
    Inicia el flujo de OAuth para que el tenant conecte SU Google Drive.
    Redirige el navegador a la pantalla de consentimiento de Google.
    """
    from drive.uploader import build_authorization_url, is_drive_oauth_configured
    if not is_drive_oauth_configured():
        return jsonify({
            'success': False,
            'error': 'Google Drive no está configurado en este servidor. '
                     'Faltan GOOGLE_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI en el .env.',
        }), 501

    tenant_id = _resolve_tenant_id_for_request()
    if not tenant_id:
        return jsonify({'success': False, 'error': 'No se pudo determinar el tenant (inicia sesión o envía tenant_id).'}), 400

    auth_url = build_authorization_url(tenant_id)
    if not auth_url:
        return jsonify({'success': False, 'error': 'No se pudo generar el enlace de autorización.'}), 500

    return redirect(auth_url)


def _has_template(name: str) -> bool:
    try:
        app.jinja_loader.get_source(app.jinja_env, name)
        return True
    except Exception:
        return False


@app.route('/drive/oauth2callback', methods=['GET'])
def drive_oauth2callback_endpoint():
    """
    Google redirige aquí tras el consentimiento del usuario. Esta ruta NO
    lleva @require_api_key/@supabase_auth_required a propósito: Google no
    manda esos headers/cookies en la redirección. La seguridad viene del
    parámetro 'state' (anti-CSRF, ligado al tenant que inició el flujo,
    de un solo uso y expira en 1 hora) — ver drive/uploader.py.
    """
    from drive.uploader import handle_oauth_callback

    error = request.args.get('error')
    if error:
        return (f"<h3>Autorización cancelada: {error}</h3><p>Puedes cerrar esta ventana.</p>", 400)

    state = request.args.get('state', '')
    ok, message = handle_oauth_callback(request.url, state)

    body = (
        f"<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
        f"<h2>{'✅ Google Drive conectado' if ok else '❌ No se pudo conectar Google Drive'}</h2>"
        f"<p>{message}</p>"
        f"<p>Puedes cerrar esta ventana y volver a la aplicación.</p>"
        f"</body></html>"
    )
    return body, (200 if ok else 400)


@app.route('/drive/disconnect', methods=['POST'])
@require_rate_limit
@require_api_key
def drive_disconnect_endpoint():
    """Desconecta el Google Drive del tenant actual (borra el token guardado)."""
    tenant_id = _resolve_tenant_id_for_request()
    if not tenant_id:
        return jsonify({'success': False, 'error': 'No se pudo determinar el tenant.'}), 400

    from utils.tenant_db import delete_drive_token
    deleted = delete_drive_token(tenant_id)
    return jsonify({'success': True, 'was_connected': deleted})


@app.route('/save-to-drive', methods=['POST', 'OPTIONS'])
@require_rate_limit
@require_api_key
def save_to_drive_endpoint():
    """
    Sube una factura del historial al Google Drive del tenant (usa
    drive/uploader.py). Cada tenant debe conectar su propio Drive una vez
    vía GET /drive/connect — si no lo ha hecho, o si no hay conexión, el
    archivo queda encolado localmente y se reintenta solo.

    POST JSON: { "invoice_id": 5 }
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    try:
        data = request.get_json(force=True) or {}
        invoice_id = data.get('invoice_id')
        if not invoice_id:
            return jsonify({'success': False, 'error': "Se requiere 'invoice_id'"}), 400

        tenant_id = _resolve_tenant_id_for_request()
        if not tenant_id:
            return jsonify({'success': False, 'error': 'No se pudo determinar el tenant (inicia sesión o envía tenant_id).'}), 400

        from utils.database import get_invoice
        inv = get_invoice(invoice_id)
        if not inv:
            return jsonify({'success': False, 'error': 'Factura no encontrada'}), 404
        if not inv.get('thumbnail_b64'):
            return jsonify({'success': False, 'error': 'Esta factura no tiene imagen guardada para subir'}), 400

        # Guardar la miniatura temporalmente para poder usar upload_to_drive
        # (que trabaja con rutas de archivo, no bytes en memoria)
        raw = base64.b64decode(inv['thumbnail_b64'])
        tmp_path = os.path.join(TEMP_DIR, f"drive_{invoice_id}.png")
        with open(tmp_path, 'wb') as f:
            f.write(raw)

        from drive.uploader import upload_to_drive
        date_str = (inv.get('fecha') or '').replace('/', '-') or datetime.now().strftime('%d-%m-%Y')
        result = upload_to_drive(
            tenant_id=tenant_id,
            render_path=tmp_path,
            invoice_data={k: v for k, v in inv.items() if k not in ('thumbnail_b64', 'raw_text')},
            invoice_number=inv.get('numero_factura') or f'SIN_NUMERO_{invoice_id}',
            date_str=date_str,
        )
        try:
            os.remove(tmp_path)
        except Exception:
            pass

        return jsonify({
            'success': result['status'] in ('uploaded', 'queued'),
            'status': result['status'],
            'message': result['detail'],
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════
#  Punto de entrada
# ═══════════════════════════════════════════════════

def get_local_ip():
    """Obtiene la IP local del servidor en la red."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def create_ssl_context(port):
    """
    Crea un contexto SSL con certificado auto-firmado para HTTPS.
    Intenta múltiples métodos: archivos existentes → OpenSSL → adhoc.
    """
    import ssl

    cert_file = os.path.join(PROJECT_ROOT, 'cert.pem')
    key_file = os.path.join(PROJECT_ROOT, 'key.pem')

    # Método 1: Usar certificados existentes
    if os.path.exists(cert_file) and os.path.exists(key_file):
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert_file, key_file)
            print("  [OK] Usando certificados existentes")
            return ctx
        except Exception as e:
            print(f"  [WARN] Error cargando certificados: {e}")

    # Método 2: Generar con OpenSSL
    try:
        import subprocess
        subprocess.run([
            'openssl', 'req', '-x509', '-newkey', 'rsa:2048',
            '-keyout', key_file, '-out', cert_file,
            '-days', '365', '-nodes',
            '-subj', '/CN=localhost/O=NAD Scanner/C=VE',
            '-addext', 'subjectAltName=IP:127.0.0.1,IP:0.0.0.0,DNS:localhost'
        ], check=True, capture_output=True, timeout=10)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_file, key_file)
        print("  [OK] Certificado generado con OpenSSL")
        return ctx
    except Exception:
        pass

    # Método 3: Usar werkzeug adhoc (requiere cryptography)
    try:
        import cryptography  # noqa: F401
        print("  [OK] Usando certificado adhoc (werkzeug)")
        return 'adhoc'
    except ImportError:
        pass

    print("  [ERROR] No se pudo crear contexto SSL")
    print("  Instale: pip install cryptography")
    return None



@app.route('/sw.js')
@app.route('/sw-classic.js')
def service_worker():
    from flask import send_file, make_response, request
    filename = 'static/service-worker-classic.js' if 'sw-classic' in request.path else 'static/service-worker.js'
    resp = make_response(send_file(filename))
    resp.headers['Service-Worker-Allowed'] = '/'
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['Content-Type'] = 'application/javascript'
    return resp
def service_worker():
    """Sirve el service worker con el header Service-Worker-Allowed.
    Necesario para que el SW registrado desde /static/ tenga scope en /."""
    from flask import send_file, make_response
    resp = make_response(send_file('static/service-worker.js'))
    resp.headers['Service-Worker-Allowed'] = '/'
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['Content-Type'] = 'application/javascript'
    return resp


# ═══════════════════════════════════════════════════
#  WebSocket Event Handlers para Realtime Preview
# ═══════════════════════════════════════════════════

# Instancia global de RealtimePreview para WebSocket
_preview_engine = None

def get_preview_engine():
    """Retorna la instancia de RealtimePreview (singleton)."""
    global _preview_engine
    if _preview_engine is None:
        from core.realtime_preview import RealtimePreview, PreviewMode
        _preview_engine = RealtimePreview()
        _preview_engine.set_mode(PreviewMode.FULL_PIPELINE)
    return _preview_engine


@socketio.on('connect')
def handle_connect():
    """Maneja conexión de cliente WebSocket."""
    print(f'[WebSocket] Cliente conectado: {request.sid}')
    emit('connected', {'sid': request.sid, 'message': 'Conectado al servidor de preview'})


@socketio.on('disconnect')
def handle_disconnect():
    """Maneja desconexión de cliente WebSocket."""
    print(f'[WebSocket] Cliente desconectado: {request.sid}')


@socketio.on('preview_frame')
def handle_preview_frame(data):
    """
    Recibe un frame de cámara del cliente, lo procesa y retorna el resultado.
    
    Expected data:
        {
            "image": base64_encoded_jpeg,
            "mode": "edges" | "alignment" | "enhancement" | "quality" | "full"
        }
    
    Returns:
        {
            "processed_image": base64_encoded_jpeg,
            "stats": {...}
        }
    """
    try:
        import base64
        import io
        
        # Decodificar imagen base64
        image_data = data.get('image', '')
        if not image_data:
            emit('error', {'message': 'No image data provided'})
            return
        
        # Remover header data URL si presente
        if ',' in image_data:
            image_data = image_data.split(',')[1]
        
        # Decodificar a bytes
        image_bytes = base64.b64decode(image_data)
        
        # Convertir a numpy array
        nparr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if frame is None:
            emit('error', {'message': 'Failed to decode image'})
            return
        
        # Obtener modo de preview
        mode_str = data.get('mode', 'full')
        from core.realtime_preview import PreviewMode
        mode_map = {
            'edges': PreviewMode.EDGE_DETECTION,
            'alignment': PreviewMode.ALIGNMENT_GUIDE,
            'enhancement': PreviewMode.ENHANCEMENT_PREVIEW,
            'quality': PreviewMode.QUALITY_OVERLAY,
            'full': PreviewMode.FULL_PIPELINE,
        }
        mode = mode_map.get(mode_str, PreviewMode.FULL_PIPELINE)
        
        # Procesar frame
        preview = get_preview_engine()
        preview.set_mode(mode)
        processed_frame = preview.process_frame(frame)
        
        # Codificar resultado a JPEG
        _, buffer = cv2.imencode('.jpg', processed_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        processed_bytes = buffer.tobytes()
        processed_base64 = base64.b64encode(processed_bytes).decode('utf-8')
        
        # Obtener estadísticas
        stats = preview.get_stats()
        
        # Enviar resultado
        emit('preview_result', {
            'processed_image': processed_base64,
            'stats': stats,
            'mode': mode_str
        })
        
    except Exception as e:
        print(f'[WebSocket] Error processing frame: {e}')
        emit('error', {'message': str(e)})


@socketio.on('set_preview_mode')
def handle_set_preview_mode(data):
    """
    Cambia el modo de preview.
    
    Expected data:
        {"mode": "edges" | "alignment" | "enhancement" | "quality" | "full"}
    """
    try:
        mode_str = data.get('mode', 'full')
        from core.realtime_preview import PreviewMode
        mode_map = {
            'edges': PreviewMode.EDGE_DETECTION,
            'alignment': PreviewMode.ALIGNMENT_GUIDE,
            'enhancement': PreviewMode.ENHANCEMENT_PREVIEW,
            'quality': PreviewMode.QUALITY_OVERLAY,
            'full': PreviewMode.FULL_PIPELINE,
        }
        mode = mode_map.get(mode_str, PreviewMode.FULL_PIPELINE)
        
        preview = get_preview_engine()
        preview.set_mode(mode)
        
        emit('mode_changed', {'mode': mode_str, 'message': f'Modo cambiado a {mode_str}'})
        
    except Exception as e:
        emit('error', {'message': str(e)})


@socketio.on('ping')
def handle_ping():
    """Responde a ping del cliente para mantener conexión viva."""
    emit('pong', {'timestamp': datetime.now().isoformat()})


# ══════════════════════════════════════════════════════════════
#  Billing / Plan Management Endpoints
# ══════════════════════════════════════════════════════════════

@app.route('/billing/plans', methods=['GET'])
def get_billing_plans():
    """Obtener todos los planes disponibles."""
    try:
        from billing.plans import plan_manager
        plans = plan_manager.get_all_plans()
        return jsonify({
            'success': True,
            'plans': plans
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/billing/plans/<plan_id>', methods=['GET'])
def get_billing_plan(plan_id):
    """Obtener un plan específico por ID."""
    try:
        from billing.plans import plan_manager
        plan = plan_manager.get_plan(plan_id)
        if not plan:
            return jsonify({
                'success': False,
                'error': 'Plan no encontrado'
            }), 404
        return jsonify({
            'success': True,
            'plan': plan
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/billing/limits/<int:tenant_id>', methods=['GET'])
def get_tenant_limits(tenant_id):
    """Verificar límites de uso de un tenant."""
    try:
        from billing.limits import limits_checker
        from utils.tenant_db import get_tenant
        
        tenant = get_tenant(tenant_id)
        if not tenant:
            return jsonify({
                'success': False,
                'error': 'Tenant no encontrado'
            }), 404
        
        plan_id = tenant.get('plan_id', 'free')
        
        # Obtener datos de uso actual
        usage_data = {
            'scans_this_month': tenant.get('usage', {}).get('total_invoices', 0),
            'storage_used_mb': tenant.get('usage', {}).get('max_storage', 0) / (1024 * 1024) if tenant.get('usage', {}).get('max_storage') else 0,
            'user_count': tenant.get('user_count', 0),
            'ocr_pages_this_month': tenant.get('usage', {}).get('total_ocr', 0),
            'api_calls_this_month': tenant.get('usage', {}).get('total_ocr', 0),  # Usando OCR como proxy
        }
        
        status = limits_checker.get_all_limits_status(str(tenant_id), plan_id, usage_data)
        warnings = limits_checker.get_limit_warnings(status)
        
        return jsonify({
            'success': True,
            'status': status,
            'warnings': warnings
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/billing/upgrade', methods=['POST'])
def upgrade_tenant_plan():
    """Cambiar el plan de un tenant."""
    try:
        from billing.plans import plan_manager
        from utils.tenant_db import update_tenant
        
        data = request.get_json()
        tenant_id = data.get('tenant_id')
        new_plan_id = data.get('new_plan_id')
        
        if not tenant_id or not new_plan_id:
            return jsonify({
                'success': False,
                'error': 'Se requieren tenant_id y new_plan_id'
            }), 400
        
        # Validar transición de plan
        from utils.tenant_db import get_tenant
        tenant = get_tenant(tenant_id)
        if not tenant:
            return jsonify({
                'success': False,
                'error': 'Tenant no encontrado'
            }), 404
        
        current_plan_id = tenant.get('plan_id', 'free')
        validation = plan_manager.validate_plan_transition(current_plan_id, new_plan_id)
        
        if not validation['valid']:
            return jsonify({
                'success': False,
                'error': validation.get('reason', 'Transición de plan no válida')
            }), 400
        
        # Actualizar plan del tenant
        updated_tenant = update_tenant(tenant_id, plan_id=new_plan_id)
        
        if not updated_tenant:
            return jsonify({
                'success': False,
                'error': 'Error al actualizar el plan'
            }), 500
        
        # Calcular costo de upgrade si aplica
        cost_info = plan_manager.calculate_upgrade_cost(current_plan_id, new_plan_id)
        
        return jsonify({
            'success': True,
            'tenant': updated_tenant,
            'validation': validation,
            'cost_info': cost_info
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/billing/compare', methods=['GET'])
def compare_plans():
    """Obtener matriz de comparación de planes."""
    try:
        from billing.plans import plan_manager
        comparison = plan_manager.get_plan_comparison()
        return jsonify({
            'success': True,
            'comparison': comparison
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ══════════════════════════════════════════════════════════════
#  Stripe Integration Endpoints
# ══════════════════════════════════════════════════════════════

@app.route('/billing/stripe/checkout', methods=['POST'])
def stripe_checkout():
    """Crear sesión de checkout de Stripe."""
    try:
        from billing.stripe_client import get_stripe_client, is_stripe_configured
        
        if not is_stripe_configured():
            return jsonify({
                'success': False,
                'error': 'Stripe no está configurado'
            }), 503
        
        client = get_stripe_client()
        if not client:
            return jsonify({
                'success': False,
                'error': 'Error al inicializar cliente Stripe'
            }), 500
        
        data = request.get_json()
        customer_id = data.get('customer_id')
        plan_id = data.get('plan_id')
        success_url = data.get('success_url', f"{request.host_url}billing/success")
        cancel_url = data.get('cancel_url', f"{request.host_url}billing/cancel")
        metadata = data.get('metadata', {})
        
        if not customer_id or not plan_id:
            return jsonify({
                'success': False,
                'error': 'Se requieren customer_id y plan_id'
            }), 400
        
        result = client.create_checkout_session(
            customer_id=customer_id,
            plan_id=plan_id,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata
        )
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/billing/stripe/portal', methods=['POST'])
def stripe_portal():
    """Crear sesión del portal de cliente de Stripe."""
    try:
        from billing.stripe_client import get_stripe_client, is_stripe_configured
        
        if not is_stripe_configured():
            return jsonify({
                'success': False,
                'error': 'Stripe no está configurado'
            }), 503
        
        client = get_stripe_client()
        if not client:
            return jsonify({
                'success': False,
                'error': 'Error al inicializar cliente Stripe'
            }), 500
        
        data = request.get_json()
        customer_id = data.get('customer_id')
        return_url = data.get('return_url', f"{request.host_url}billing")
        
        if not customer_id:
            return jsonify({
                'success': False,
                'error': 'Se requiere customer_id'
            }), 400
        
        result = client.create_customer_portal_session(
            customer_id=customer_id,
            return_url=return_url
        )
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/billing/stripe/customer', methods=['POST'])
def stripe_create_customer():
    """Crear un cliente de Stripe."""
    try:
        from billing.stripe_client import get_stripe_client, is_stripe_configured
        
        if not is_stripe_configured():
            return jsonify({
                'success': False,
                'error': 'Stripe no está configurado'
            }), 503
        
        client = get_stripe_client()
        if not client:
            return jsonify({
                'success': False,
                'error': 'Error al inicializar cliente Stripe'
            }), 500
        
        data = request.get_json()
        email = data.get('email')
        name = data.get('name', '')
        metadata = data.get('metadata', {})
        
        if not email:
            return jsonify({
                'success': False,
                'error': 'Se requiere email'
            }), 400
        
        result = client.create_customer(
            email=email,
            name=name,
            metadata=metadata
        )
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/billing/stripe/webhook', methods=['POST'])
def stripe_webhook():
    """Manejar webhooks de Stripe."""
    try:
        from billing.stripe_client import get_stripe_client, is_stripe_configured
        from billing.webhooks import get_webhook_handler
        
        if not is_stripe_configured():
            return jsonify({
                'success': False,
                'error': 'Stripe no está configurado'
            }), 503
        
        webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')
        if not webhook_secret:
            return jsonify({
                'success': False,
                'error': 'Stripe webhook secret no configurado'
            }), 503
        
        payload = request.get_data(as_text=False)
        sig_header = request.headers.get('Stripe-Signature')
        
        if not sig_header:
            return jsonify({
                'success': False,
                'error': 'Falta header Stripe-Signature'
            }), 400
        
        client = get_stripe_client()
        if not client:
            return jsonify({
                'success': False,
                'error': 'Error al inicializar cliente Stripe'
            }), 500
        
        # Verify webhook signature
        result = client.construct_webhook_event(
            payload=payload.decode('utf-8'),
            sig_header=sig_header,
            webhook_secret=webhook_secret
        )
        
        if not result['success']:
            return jsonify(result), 400
        
        # Handle the event
        handler = get_webhook_handler()
        handler_result = handler.handle_event(result['event'])
        
        return jsonify(handler_result)
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ══════════════════════════════════════════════════════════════
#  Local Payments Endpoints (PagoMóvil, Zelle, USDT)
# ══════════════════════════════════════════════════════════════

@app.route('/billing/local/methods', methods=['GET'])
def get_local_payment_methods():
    """Obtener información de métodos de pago locales disponibles."""
    try:
        from billing.local_payments import get_local_payments_handler
        handler = get_local_payments_handler()
        info = handler.get_payment_methods_info()
        return jsonify(info)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/billing/local/pagomovil', methods=['POST'])
def initiate_pagomovil_payment():
    """Iniciar un pago PagoMóvil."""
    try:
        from billing.local_payments import get_local_payments_handler
        handler = get_local_payments_handler()
        
        data = request.get_json()
        tenant_id = data.get('tenant_id')
        amount = data.get('amount')
        phone = data.get('phone')
        reference = data.get('reference')
        metadata = data.get('metadata', {})
        
        if not all([tenant_id, amount, phone, reference]):
            return jsonify({
                'success': False,
                'error': 'Se requieren tenant_id, amount, phone y reference'
            }), 400
        
        result = handler.initiate_pagomovil_payment(
            tenant_id=tenant_id,
            amount=float(amount),
            phone=phone,
            reference=reference,
            metadata=metadata
        )
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/billing/local/zelle', methods=['POST'])
def initiate_zelle_payment():
    """Iniciar un pago Zelle."""
    try:
        from billing.local_payments import get_local_payments_handler
        handler = get_local_payments_handler()
        
        data = request.get_json()
        tenant_id = data.get('tenant_id')
        amount_usd = data.get('amount_usd')
        payer_email = data.get('payer_email')
        confirmation_number = data.get('confirmation_number')
        metadata = data.get('metadata', {})
        
        if not all([tenant_id, amount_usd, payer_email, confirmation_number]):
            return jsonify({
                'success': False,
                'error': 'Se requieren tenant_id, amount_usd, payer_email y confirmation_number'
            }), 400
        
        result = handler.initiate_zelle_payment(
            tenant_id=tenant_id,
            amount_usd=float(amount_usd),
            payer_email=payer_email,
            confirmation_number=confirmation_number,
            metadata=metadata
        )
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/billing/local/usdt', methods=['POST'])
def initiate_usdt_payment():
    """Iniciar un pago USDT."""
    try:
        from billing.local_payments import get_local_payments_handler
        handler = get_local_payments_handler()
        
        data = request.get_json()
        tenant_id = data.get('tenant_id')
        amount_usdt = data.get('amount_usdt')
        network = data.get('network', 'TRC20')
        tx_hash = data.get('tx_hash')
        metadata = data.get('metadata', {})
        
        if not all([tenant_id, amount_usdt]):
            return jsonify({
                'success': False,
                'error': 'Se requieren tenant_id y amount_usd'
            }), 400
        
        result = handler.initiate_usdt_payment(
            tenant_id=tenant_id,
            amount_usdt=float(amount_usdt),
            network=network,
            tx_hash=tx_hash,
            metadata=metadata
        )
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/billing/local/confirm', methods=['POST'])
def submit_payment_confirmation():
    """Enviar confirmación de pago para revisión manual."""
    try:
        from billing.payment_confirmation import get_confirmation_handler
        handler = get_confirmation_handler()
        
        data = request.get_json()
        payment_id = data.get('payment_id')
        proof_image = data.get('proof_image')
        notes = data.get('notes')
        
        if not payment_id:
            return jsonify({
                'success': False,
                'error': 'Se requiere payment_id'
            }), 400
        
        result = handler.submit_confirmation(
            payment_id=payment_id,
            proof_image=proof_image,
            notes=notes
        )
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/billing/local/approve', methods=['POST'])
def approve_local_payment():
    """Aprobar un pago local (solo admin)."""
    try:
        from billing.payment_confirmation import get_confirmation_handler
        handler = get_confirmation_handler()
        
        data = request.get_json()
        payment_id = data.get('payment_id')
        admin_id = data.get('admin_id')
        notes = data.get('notes')
        
        if not all([payment_id, admin_id]):
            return jsonify({
                'success': False,
                'error': 'Se requieren payment_id y admin_id'
            }), 400
        
        # TODO: Verificar que el usuario es admin
        
        result = handler.approve_payment(
            payment_id=payment_id,
            admin_id=admin_id,
            notes=notes
        )
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/billing/local/reject', methods=['POST'])
def reject_local_payment():
    """Rechazar un pago local (solo admin)."""
    try:
        from billing.payment_confirmation import get_confirmation_handler
        handler = get_confirmation_handler()
        
        data = request.get_json()
        payment_id = data.get('payment_id')
        admin_id = data.get('admin_id')
        reason = data.get('reason')
        
        if not all([payment_id, admin_id, reason]):
            return jsonify({
                'success': False,
                'error': 'Se requieren payment_id, admin_id y reason'
            }), 400
        
        # TODO: Verificar que el usuario es admin
        
        result = handler.reject_payment(
            payment_id=payment_id,
            admin_id=admin_id,
            reason=reason
        )
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ══════════════════════════════════════════════════════════════
#  Invoice & Subscription Management Endpoints
# ══════════════════════════════════════════════════════════════

@app.route('/billing/invoice/generate', methods=['POST'])
def generate_invoice():
    """Generar una factura PDF."""
    try:
        from billing.invoice_generator import get_invoice_generator
        from billing.recurring_billing import get_recurring_billing_handler
        
        data = request.get_json()
        invoice_id = data.get('invoice_id')
        tenant_id = data.get('tenant_id')
        tenant_name = data.get('tenant_name')
        tenant_email = data.get('tenant_email')
        items = data.get('items', [])
        subtotal = data.get('subtotal')
        tax_amount = data.get('tax_amount')
        total = data.get('total')
        currency = data.get('currency', 'USD')
        due_date = data.get('due_date')
        notes = data.get('notes')
        
        if not all([invoice_id, tenant_id, tenant_name, tenant_email, subtotal, total]):
            return jsonify({
                'success': False,
                'error': 'Se requieren invoice_id, tenant_id, tenant_name, tenant_email, subtotal y total'
            }), 400
        
        generator = get_invoice_generator()
        result = generator.generate_invoice(
            invoice_id=invoice_id,
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            tenant_email=tenant_email,
            items=items,
            subtotal=float(subtotal),
            tax_amount=float(tax_amount) if tax_amount else 0,
            total=float(total),
            currency=currency,
            due_date=due_date,
            notes=notes
        )
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/billing/subscription/create', methods=['POST'])
def create_subscription():
    """Crear una nueva suscripción."""
    try:
        from billing.recurring_billing import get_recurring_billing_handler
        
        data = request.get_json()
        tenant_id = data.get('tenant_id')
        plan_id = data.get('plan_id')
        billing_cycle = data.get('billing_cycle', 'monthly')
        start_date = data.get('start_date')
        payment_method = data.get('payment_method', 'stripe')
        payment_method_id = data.get('payment_method_id')
        
        if not all([tenant_id, plan_id]):
            return jsonify({
                'success': False,
                'error': 'Se requieren tenant_id y plan_id'
            }), 400
        
        handler = get_recurring_billing_handler()
        result = handler.create_subscription(
            tenant_id=tenant_id,
            plan_id=plan_id,
            billing_cycle=billing_cycle,
            start_date=start_date,
            payment_method=payment_method,
            payment_method_id=payment_method_id
        )
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/billing/subscription/<subscription_id>/invoice', methods=['POST'])
def generate_subscription_invoice(subscription_id):
    """Generar factura para una suscripción."""
    try:
        from billing.recurring_billing import get_recurring_billing_handler
        
        handler = get_recurring_billing_handler()
        result = handler.generate_invoice_for_subscription(subscription_id)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/billing/subscription/<subscription_id>/cancel', methods=['POST'])
def cancel_subscription(subscription_id):
    """Cancelar una suscripción."""
    try:
        from billing.recurring_billing import get_recurring_billing_handler
        
        data = request.get_json()
        cancel_at_period_end = data.get('cancel_at_period_end', True)
        
        handler = get_recurring_billing_handler()
        result = handler.cancel_subscription(
            subscription_id=subscription_id,
            cancel_at_period_end=cancel_at_period_end
        )
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ══════════════════════════════════════════════════════════════
#  Billing Analytics Endpoints (Admin Dashboard)
# ══════════════════════════════════════════════════════════════

@app.route('/billing/analytics', methods=['GET'])
def get_billing_analytics():
    """Obtener analytics completos de billing (MRR, churn, LTV, etc.)."""
    try:
        from billing.analytics import get_billing_analytics
        
        # Analytics ahora obtiene datos reales de la base de datos automáticamente
        analytics = get_billing_analytics()
        result = analytics.get_comprehensive_analytics()
        
        return jsonify({
            'success': True,
            'analytics': result
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/billing/maintenance', methods=['POST'])
def run_billing_maintenance():
    """Ejecutar mantenimiento diario de suscripciones (procesar expiradas, enviar notificaciones)."""
    try:
        from billing.subscription_renewal import get_subscription_renewal
        
        renewal = get_subscription_renewal()
        result = renewal.run_daily_maintenance()
        
        return jsonify({
            'success': True,
            'maintenance': result
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/billing/analytics/mrr', methods=['GET'])
def get_mrr():
    """Obtener MRR (Monthly Recurring Revenue)."""
    try:
        from billing.analytics import get_billing_analytics
        
        # TODO: Obtener suscripciones reales de la base de datos
        subscriptions = []
        
        analytics = get_billing_analytics()
        result = analytics.calculate_mrr(subscriptions)
        
        return jsonify({
            'success': True,
            'mrr': result
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/billing/analytics/churn', methods=['GET'])
def get_churn():
    """Obtener tasa de churn."""
    try:
        from billing.analytics import get_billing_analytics
        
        period_days = request.args.get('period_days', 30, type=int)
        
        # TODO: Obtener suscripciones reales de la base de datos
        subscriptions = []
        
        analytics = get_billing_analytics()
        result = analytics.calculate_churn_rate(subscriptions, period_days)
        
        return jsonify({
            'success': True,
            'churn': result
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/billing/subscriptions', methods=['GET'])
def list_subscriptions():
    """Listar todas las suscripciones."""
    try:
        from billing.recurring_billing import get_recurring_billing_handler
        
        tenant_id = request.args.get('tenant_id')
        status = request.args.get('status')
        
        handler = get_recurring_billing_handler()
        result = handler.list_subscriptions(tenant_id=tenant_id, status=status)
        
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/billing/invoices', methods=['GET'])
def list_invoices():
    """Listar todas las facturas."""
    try:
        # TODO: Implementar consulta a base de datos
        return jsonify({
            'success': True,
            'invoices': [],
            'message': 'Requiere implementación de base de datos'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')

    local_ip = get_local_ip()

    # Verificar si SSL está desactivado por variable de entorno
    disable_ssl = os.environ.get('DISABLE_SSL', '').lower() in ('true', '1', 'yes')

    # Crear contexto SSL para HTTPS (requerido para cámara en móviles)
    ssl_ctx = None
    ssl_available = False
    protocol = "http"

    if not disable_ssl:
        ssl_ctx = create_ssl_context(port)
        ssl_available = ssl_ctx is not None
        protocol = "https" if ssl_available else "http"

    print("\n" + "=" * 60)
    print(f"  ⬡ NAD Scanner — Servidor Web v{VERSION}")
    print("=" * 60)
    print(f"\n  🌐 Servidor iniciado en:")
    print(f"     Local:    {protocol}://127.0.0.1:{port}")
    print(f"     Red:      {protocol}://{local_ip}:{port}")
    
    if disable_ssl:
        print(f"\n  ⚠ SSL desactivado (modo HTTP)")
    
    print(f"\n  📱 PARA USAR LA CÁMARA DEL TELÉFONO:")
    print(f"     1. Conecte su PC y teléfono a la misma red WiFi")
    print(f"     2. Abra el navegador del teléfono")
    print(f"     3. Escriba: {protocol}://{local_ip}:{port}")
    
    if ssl_available and not disable_ssl:
        print(f"\n  ⚠ SI EL NAVEGADOR MUESTRA ADVERTENCIA DE SEGURIDAD:")
        print(f"     Chrome:  'Avanzado' → 'Proceder a {local_ip} (no seguro)'")
        print(f"     Firefox: 'Avanzado' → 'Aceptar el riesgo y continuar'")
        print(f"     Samsung: 'Configuración' → 'Continuar de todas formas'")
    
    print(f"\n  📷 Instrucciones de captura:")
    print(f"     1. Coloque la factura sobre una superficie plana")
    print(f"     2. Alinee los 4 círculos guía con las esquinas")
    print(f"     3. Presione el botón para capturar cada toma")
    print(f"     4. Capture 5 fotos (1 centro + 4 esquinas)")
    print(f"     5. Presione 'Procesar' para enviar al servidor")
    print(f"\n  🔌 WebSocket habilitado para Realtime Preview")
    print(f"\n  ⏹  Presione Ctrl+C para detener el servidor")
    print("=" * 60 + "\n")

    try:
        if ssl_available and not disable_ssl:
            socketio.run(app, host=host, port=port, ssl_context=ssl_ctx)
        else:
            socketio.run(app, host=host, port=port)
    except KeyboardInterrupt:
        print("\n\nServidor detenido.")
