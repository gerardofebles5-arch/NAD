"""
πNAD — Multi-Tenant Admin Database
====================================
Gestión de empresas (tenants), usuarios por tenant, y métricas de uso.
SQLite local (mismo archivo DB que el historial de facturas).

Esquema:
  tenants          — Empresas/clientes del sistema
  tenant_users     — Usuarios asociados a cada tenant
  usage_metrics    — Métricas diarias de uso por tenant
"""

import os
import json
import hashlib
import sqlite3
import threading
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple
from contextlib import contextmanager

from utils.config import CONFIG

DB_PATH = os.path.join(CONFIG.output_dir, "nadscanner.db")

_lock = threading.RLock()  # RLock, no Lock: varias funciones de este módulo
# se llaman entre sí mientras ya sostienen el lock (ej. list_tenants() ->
# get_tenant_usage_summary() -> _connect() de nuevo). Con un Lock normal
# (no reentrante) eso es un deadlock garantizado del mismo hilo esperando
# a sí mismo — se confirmó reproduciendo el cuelgue real en /api/admin/tenants.

# ── Schema ─────────────────────────────────────────────────────

_TENANT_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    email TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    address TEXT DEFAULT '',
    rif TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    max_users INTEGER NOT NULL DEFAULT 10,
    max_storage_mb INTEGER NOT NULL DEFAULT 500,
    notes TEXT DEFAULT '',
    plan_id TEXT NOT NULL DEFAULT 'free'
);

CREATE INDEX IF NOT EXISTS idx_tenants_slug ON tenants(slug);
CREATE INDEX IF NOT EXISTS idx_tenants_active ON tenants(is_active);

CREATE TABLE IF NOT EXISTS tenant_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    user_email TEXT NOT NULL,
    user_name TEXT DEFAULT '',
    role TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    last_active TEXT DEFAULT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tenant_users_tenant ON tenant_users(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_users_email ON tenant_users(user_email);

CREATE TABLE IF NOT EXISTS usage_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    invoices_processed INTEGER NOT NULL DEFAULT 0,
    storage_bytes INTEGER NOT NULL DEFAULT 0,
    processing_time_seconds REAL NOT NULL DEFAULT 0.0,
    ocr_requests INTEGER NOT NULL DEFAULT 0,
    stitching_requests INTEGER NOT NULL DEFAULT 0,
    batch_requests INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_usage_tenant_date ON usage_metrics(tenant_id, date);
"""


@contextmanager
def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _lock:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def init_tenant_db():
    """Inicializa las tablas multi-tenant. Seguro llamar varias veces."""
    # FIX: la tabla 'invoices' vive en utils/database.py, no aquí. Antes,
    # si /admin (o cualquier ruta multi-tenant) era lo PRIMERO en tocar la
    # base de datos en una instalación nueva, 'invoices' todavía no existía
    # — el ALTER TABLE de abajo fallaba en silencio (ya estaba contemplado
    # con un try/except), pero _count_invoices() más adelante SÍ explotaba
    # con "no such table: invoices" porque nadie se había asegurado de que
    # la tabla existiera antes de consultarla.
    from utils.database import init_db as _init_invoices_db
    _init_invoices_db()

    with _connect() as conn:
        conn.executescript(_TENANT_SCHEMA)
        # Migración segura: agregar tenant_id a invoices si no existe
        # SQLite no soporta IF NOT EXISTS para ALTER TABLE
        cursor = conn.execute("PRAGMA table_info(invoices)")
        col_names = {row[1] for row in cursor.fetchall()}
        if 'tenant_id' not in col_names:
            try:
                conn.execute("ALTER TABLE invoices ADD COLUMN tenant_id INTEGER DEFAULT NULL")
            except Exception:
                pass  # Si la tabla invoices no existe, ignorar
        # Migración segura: agregar plan_id a tenants si no existe
        cursor = conn.execute("PRAGMA table_info(tenants)")
        col_names = {row[1] for row in cursor.fetchall()}
        if 'plan_id' not in col_names:
            try:
                conn.execute("ALTER TABLE tenants ADD COLUMN plan_id TEXT NOT NULL DEFAULT 'free'")
            except Exception:
                pass  # Si falla, ignorar


# ── Slug generation ────────────────────────────────────────────

def _make_slug(name: str) -> str:
    """Genera un slug único desde el nombre de la empresa."""
    slug = name.lower().strip()
    for ch in "áéíóúüñ":
        slug = slug.replace(ch, {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n"}[ch])
    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in slug)
    slug = "-".join(filter(None, slug.split("-")))
    slug = slug[:50] or "empresa"
    # Asegurar unicidad
    with _connect() as conn:
        existing = conn.execute(
            "SELECT slug FROM tenants WHERE slug LIKE ?", (f"{slug}%",)
        ).fetchall()
    existing_slugs = {r["slug"] for r in existing}
    if slug in existing_slugs:
        counter = 2
        while f"{slug}-{counter}" in existing_slugs:
            counter += 1
        slug = f"{slug}-{counter}"
    return slug


# ── CRUD Tenants ───────────────────────────────────────────────

def create_tenant(
    name: str,
    email: str = "",
    phone: str = "",
    address: str = "",
    rif: str = "",
    max_users: int = 10,
    max_storage_mb: int = 500,
    notes: str = "",
    plan_id: str = "free",
) -> Dict[str, Any]:
    """Crea una nueva empresa (tenant). Retorna el tenant creado."""
    init_tenant_db()
    slug = _make_slug(name)
    now = datetime.now().isoformat()

    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO tenants (name, slug, email, phone, address, rif,
               created_at, updated_at, max_users, max_storage_mb, notes, plan_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, slug, email, phone, address, rif, now, now, max_users, max_storage_mb, notes, plan_id),
        )
        tenant_id = cur.lastrowid

    return get_tenant(tenant_id)


def get_tenant(tenant_id: int) -> Optional[Dict[str, Any]]:
    """Retorna un tenant por ID con estadísticas agregadas."""
    init_tenant_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
    # Agregar stats
    d["user_count"] = _count_users(tenant_id)
    d["invoice_count"] = _count_invoices(tenant_id)
    d["usage"] = get_tenant_usage_summary(tenant_id)
    return d


def list_tenants(
    include_inactive: bool = False,
    search: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lista todos los tenants con estadísticas."""
    init_tenant_db()
    where = []
    params: List[Any] = []
    if not include_inactive:
        where.append("t.is_active = 1")
    if search:
        where.append("(t.name LIKE ? OR t.email LIKE ? OR t.rif LIKE ?)")
        like = f"%{search}%"
        params += [like, like, like]
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT t.*,
                (SELECT COUNT(*) FROM tenant_users tu WHERE tu.tenant_id = t.id AND tu.is_active = 1) as user_count,
                (SELECT COUNT(*) FROM invoices i WHERE i.tenant_id = t.id) as invoice_count
                FROM tenants t {where_sql}
                ORDER BY t.created_at DESC""",
            params,
        ).fetchall()

        results = []
        for r in rows:
            d = dict(r)
            d["usage"] = get_tenant_usage_summary(d["id"])
            results.append(d)
        return results


def update_tenant(
    tenant_id: int,
    name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    address: Optional[str] = None,
    rif: Optional[str] = None,
    max_users: Optional[int] = None,
    max_storage_mb: Optional[int] = None,
    is_active: Optional[bool] = None,
    notes: Optional[str] = None,
    plan_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Actualiza un tenant. Retorna el tenant actualizado o None si no existe."""
    init_tenant_db()
    existing = get_tenant(tenant_id)
    if not existing:
        return None

    updates = []
    params: List[Any] = []
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if email is not None:
        updates.append("email = ?")
        params.append(email)
    if phone is not None:
        updates.append("phone = ?")
        params.append(phone)
    if address is not None:
        updates.append("address = ?")
        params.append(address)
    if rif is not None:
        updates.append("rif = ?")
        params.append(rif)
    if max_users is not None:
        updates.append("max_users = ?")
        params.append(max_users)
    if max_storage_mb is not None:
        updates.append("max_storage_mb = ?")
        params.append(max_storage_mb)
    if is_active is not None:
        updates.append("is_active = ?")
        params.append(1 if is_active else 0)
    if notes is not None:
        updates.append("notes = ?")
        params.append(notes)
    if plan_id is not None:
        updates.append("plan_id = ?")
        params.append(plan_id)

    if not updates:
        return existing

    updates.append("updated_at = ?")
    params.append(datetime.now().isoformat())
    params.append(tenant_id)

    with _connect() as conn:
        conn.execute(
            f"UPDATE tenants SET {', '.join(updates)} WHERE id = ?",
            params,
        )

    return get_tenant(tenant_id)


def delete_tenant(tenant_id: int, hard: bool = False) -> bool:
    """Desactiva (o elimina) un tenant.
    Args:
        hard: Si True, elimina físicamente. Si False, solo desactiva.
    """
    init_tenant_db()
    with _connect() as conn:
        if hard:
            conn.execute("DELETE FROM usage_metrics WHERE tenant_id = ?", (tenant_id,))
            conn.execute("DELETE FROM tenant_users WHERE tenant_id = ?", (tenant_id,))
            # No eliminar facturas — mantener para referencia
            conn.execute("UPDATE invoices SET tenant_id = NULL WHERE tenant_id = ?", (tenant_id,))
            cur = conn.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
        else:
            cur = conn.execute(
                "UPDATE tenants SET is_active = 0, updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), tenant_id),
            )
        return cur.rowcount > 0


# ── CRUD Tenant Users ──────────────────────────────────────────

def add_tenant_user(
    tenant_id: int,
    user_email: str,
    user_name: str = "",
    role: str = "user",
) -> Optional[Dict[str, Any]]:
    """Agrega un usuario a un tenant. Retorna el usuario creado o None si el tenant está lleno."""
    init_tenant_db()

    # Verificar límite de usuarios
    tenant = get_tenant(tenant_id)
    if not tenant or not tenant["is_active"]:
        return None

    current_users = _count_users(tenant_id)
    if current_users >= tenant["max_users"]:
        return None

    now = datetime.now().isoformat()
    with _connect() as conn:
        # Verificar si ya existe
        existing = conn.execute(
            "SELECT id FROM tenant_users WHERE tenant_id = ? AND user_email = ?",
            (tenant_id, user_email),
        ).fetchone()
        if existing:
            # Reactivar
            conn.execute(
                "UPDATE tenant_users SET is_active = 1, last_active = ? WHERE id = ?",
                (now, existing["id"]),
            )
            return get_tenant_user(existing["id"])

        cur = conn.execute(
            """INSERT INTO tenant_users (tenant_id, user_email, user_name, role, created_at, last_active)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (tenant_id, user_email, user_name, role, now, now),
        )
        return get_tenant_user(cur.lastrowid)


def get_tenant_user(user_id: int) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tenant_users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def list_tenant_users(tenant_id: int, include_inactive: bool = False) -> List[Dict[str, Any]]:
    init_tenant_db()
    where = "tenant_id = ?"
    params: List[Any] = [tenant_id]
    if not include_inactive:
        where += " AND is_active = 1"
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM tenant_users WHERE {where} ORDER BY created_at DESC",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def update_tenant_user(
    user_id: int,
    user_name: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    init_tenant_db()
    updates = []
    params: List[Any] = []
    if user_name is not None:
        updates.append("user_name = ?")
        params.append(user_name)
    if role is not None:
        updates.append("role = ?")
        params.append(role)
    if is_active is not None:
        updates.append("is_active = ?")
        params.append(1 if is_active else 0)
    if not updates:
        return get_tenant_user(user_id)
    params.append(user_id)
    with _connect() as conn:
        conn.execute(
            f"UPDATE tenant_users SET {', '.join(updates)} WHERE id = ?",
            params,
        )
    return get_tenant_user(user_id)


def delete_tenant_user(user_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM tenant_users WHERE id = ?", (user_id,))
        return cur.rowcount > 0


# ── Usage Metrics ──────────────────────────────────────────────

def record_usage(
    tenant_id: Optional[int],
    invoices_processed: int = 0,
    processing_time_seconds: float = 0.0,
    ocr_requests: int = 0,
    stitching_requests: int = 0,
    batch_requests: int = 0,
    storage_bytes: int = 0,
):
    """Registra métricas de uso para un tenant en la fecha actual."""
    if tenant_id is None:
        return
    init_tenant_db()
    today = date.today().isoformat()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT id FROM usage_metrics WHERE tenant_id = ? AND date = ?",
            (tenant_id, today),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE usage_metrics SET
                   invoices_processed = invoices_processed + ?,
                   processing_time_seconds = processing_time_seconds + ?,
                   ocr_requests = ocr_requests + ?,
                   stitching_requests = stitching_requests + ?,
                   batch_requests = batch_requests + ?,
                   storage_bytes = storage_bytes + ?
                   WHERE id = ?""",
                (invoices_processed, processing_time_seconds, ocr_requests,
                 stitching_requests, batch_requests, storage_bytes, existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO usage_metrics
                   (tenant_id, date, invoices_processed, processing_time_seconds,
                    ocr_requests, stitching_requests, batch_requests, storage_bytes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (tenant_id, today, invoices_processed, processing_time_seconds,
                 ocr_requests, stitching_requests, batch_requests, storage_bytes),
            )


def get_tenant_usage_summary(tenant_id: int) -> Dict[str, Any]:
    """Retorna resumen de uso histórico para un tenant."""
    init_tenant_db()
    with _connect() as conn:
        row = conn.execute(
            """SELECT
                COUNT(*) as days_recorded,
                COALESCE(SUM(invoices_processed), 0) as total_invoices,
                COALESCE(SUM(processing_time_seconds), 0) as total_processing_time,
                COALESCE(SUM(ocr_requests), 0) as total_ocr,
                COALESCE(SUM(stitching_requests), 0) as total_stitching,
                COALESCE(SUM(batch_requests), 0) as total_batch,
                COALESCE(MAX(storage_bytes), 0) as max_storage
               FROM usage_metrics WHERE tenant_id = ?""",
            (tenant_id,),
        ).fetchone()
        d = dict(row) if row else {
            "days_recorded": 0, "total_invoices": 0, "total_processing_time": 0.0,
            "total_ocr": 0, "total_stitching": 0, "total_batch": 0, "max_storage": 0,
        }
        # Últimos 30 días
        thirty = conn.execute(
            """SELECT COALESCE(SUM(invoices_processed), 0) as invoices_30d,
                      COALESCE(SUM(processing_time_seconds), 0) as time_30d
               FROM usage_metrics
               WHERE tenant_id = ? AND date >= ?""",
            (tenant_id, (date.today() - timedelta(days=30)).isoformat()),
        ).fetchone()
        if thirty:
            d["invoices_30d"] = thirty["invoices_30d"]
            d["time_30d"] = round(thirty["time_30d"], 2)
        else:
            d["invoices_30d"] = 0
            d["time_30d"] = 0.0
        return d


def get_global_usage_summary() -> Dict[str, Any]:
    """Retorna métricas globales de todos los tenants."""
    init_tenant_db()
    with _connect() as conn:
        # Tenants activos
        active_tenants = conn.execute("SELECT COUNT(*) FROM tenants WHERE is_active = 1").fetchone()[0]
        total_tenants = conn.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]

        # Usuarios totales
        total_users = conn.execute("SELECT COUNT(*) FROM tenant_users WHERE is_active = 1").fetchone()[0]

        # Facturas procesadas (todas)
        total_invoices = conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]

        # Uso global
        usage = conn.execute(
            """SELECT
                COALESCE(SUM(invoices_processed), 0) as total_processed,
                COALESCE(SUM(processing_time_seconds), 0) as total_time,
                COALESCE(SUM(ocr_requests), 0) as total_ocr,
                COALESCE(SUM(stitching_requests), 0) as total_stitching,
                COALESCE(SUM(batch_requests), 0) as total_batch,
                COALESCE(MAX(storage_bytes), 0) as peak_storage
               FROM usage_metrics""",
        ).fetchone()

        # Últimos 30 días
        thirty_start = (date.today() - timedelta(days=30)).isoformat()
        recent = conn.execute(
            """SELECT COALESCE(SUM(invoices_processed), 0) as invoices_30d,
                      COALESCE(SUM(processing_time_seconds), 0) as time_30d
               FROM usage_metrics WHERE date >= ?""",
            (thirty_start,),
        ).fetchone()

        return {
            "active_tenants": active_tenants,
            "total_tenants": total_tenants,
            "total_users": total_users,
            "total_invoices": total_invoices,
            "total_processed": usage["total_processed"] if usage else 0,
            "total_processing_time": round(usage["total_time"], 2) if usage else 0,
            "total_ocr": usage["total_ocr"] if usage else 0,
            "total_stitching": usage["total_stitching"] if usage else 0,
            "total_batch": usage["total_batch"] if usage else 0,
            "peak_storage_mb": round((usage["peak_storage"] or 0) / (1024 * 1024), 2),
            "invoices_30d": recent["invoices_30d"] if recent else 0,
            "time_30d": round(recent["time_30d"], 2) if recent else 0,
        }


def get_tenant_daily_usage(
    tenant_id: int,
    days: int = 30,
) -> List[Dict[str, Any]]:
    """Retorna uso diario para un tenant (para gráficas)."""
    init_tenant_db()
    start = (date.today() - timedelta(days=days - 1)).isoformat()
    with _connect() as conn:
        rows = conn.execute(
            """SELECT date, invoices_processed, processing_time_seconds, ocr_requests
               FROM usage_metrics
               WHERE tenant_id = ? AND date >= ?
               ORDER BY date ASC""",
            (tenant_id, start),
        ).fetchall()
        return [dict(r) for r in rows]


def get_invoices_by_tenant(
    tenant_id: int,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """Retorna facturas asociadas a un tenant específico."""
    init_tenant_db()
    limit = max(1, min(limit, 500))
    with _connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM invoices WHERE tenant_id = ?",
            (tenant_id,),
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM invoices WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (tenant_id, limit, offset),
        ).fetchall()
        items = [dict(r) for r in rows]
        return {"items": items, "total": total, "limit": limit, "offset": offset}


# ── Helpers ────────────────────────────────────────────────────

def _count_users(tenant_id: int) -> int:
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM tenant_users WHERE tenant_id = ? AND is_active = 1",
            (tenant_id,),
        ).fetchone()[0]


def _count_invoices(tenant_id: int) -> int:
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM invoices WHERE tenant_id = ?",
            (tenant_id,),
        ).fetchone()[0]


def seed_demo_data():
    """Crea datos demo si no hay tenants. Útil para pruebas."""
    init_tenant_db()
    with _connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]
        if count > 0:
            return

    # Crear tenants demo
    demo_tenants = [
        ("Pi Administración y Asesoría", "admin@pinad.com", "0412-1234567",
         "Av. Principal, Caracas", "J-12345678-0", 25, 2000,
         "Cliente principal - Plan Enterprise"),
        ("Contabilidad Mérida C.A.", "contabilidad@merida.com", "0414-7654321",
         "Calle 24, Mérida", "J-23456789-1", 10, 500,
         "Plan Profesional - Contabilidad"),
        ("Bufete Jurídico Lex", "info@lex.com", "0416-9876543",
         "Av. Urdaneta, Caracas", "J-34567890-2", 15, 1000,
         "Plan Profesional - Legal"),
        ("Comercial del Este S.A.", "ventas@comercialeste.com", "0424-5554433",
         "CCCT, Chacao", "J-45678901-3", 8, 300,
         "Plan Básico - Comercio"),
        ("Dr. Ricardo Gómez (Indep.)", "rgomez@email.com", "0412-8887766",
         "Consultorio, Altamira", "V-12345678", 1, 100,
         "Plan Individual - Profesional liberal"),
    ]

    for name, email, phone, address, rif, max_users, storage, notes in demo_tenants:
        t = create_tenant(name, email, phone, address, rif, max_users, storage, notes)
        if t:
            # Agregar usuario admin por defecto
            admin_email = email.split("@")
            add_tenant_user(t["id"], email, name.split("/")[0].strip(), "admin")
            add_tenant_user(t["id"], f"user@{admin_email[1]}" if len(admin_email) > 1 else f"user@demo.com", "Usuario Demo", "user")


# ── Delegación: asociar factura a tenant ──────────────────────

def assign_invoice_to_tenant(invoice_id: int, tenant_id: Optional[int]):
    """Asigna una factura a un tenant."""
    init_tenant_db()
    with _connect() as conn:
        conn.execute("UPDATE invoices SET tenant_id = ? WHERE id = ?", (tenant_id, invoice_id))
