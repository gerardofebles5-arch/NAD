"""
Billing Database Module for PINAD SaaS
Manages database tables for subscriptions, invoices, payments, etc.
"""

import os
import sqlite3
import threading
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from contextlib import contextmanager

from utils.config import CONFIG

DB_PATH = os.path.join(CONFIG.output_dir, "nadscanner.db")

_lock = threading.RLock()

# ── Schema ─────────────────────────────────────────────────────

_BILLING_SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id TEXT NOT NULL UNIQUE,
    tenant_id INTEGER NOT NULL,
    plan_id TEXT NOT NULL,
    billing_cycle TEXT NOT NULL DEFAULT 'monthly',
    status TEXT NOT NULL DEFAULT 'active',
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    payment_method TEXT NOT NULL,
    payment_method_id TEXT,
    amount REAL NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    cancelled_at TEXT DEFAULT NULL,
    cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_tenant ON subscriptions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_subscriptions_id ON subscriptions(subscription_id);

CREATE TABLE IF NOT EXISTS billing_invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id TEXT NOT NULL UNIQUE,
    tenant_id INTEGER NOT NULL,
    subscription_id TEXT,
    invoice_number TEXT NOT NULL,
    subtotal REAL NOT NULL,
    tax_amount REAL NOT NULL,
    total REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    status TEXT NOT NULL DEFAULT 'pending',
    due_date TEXT,
    paid_date TEXT,
    filepath TEXT,
    filename TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_billing_invoices_tenant ON billing_invoices(tenant_id);
CREATE INDEX IF NOT EXISTS idx_billing_invoices_subscription ON billing_invoices(subscription_id);
CREATE INDEX IF NOT EXISTS idx_billing_invoices_status ON billing_invoices(status);
CREATE INDEX IF NOT EXISTS idx_billing_invoices_id ON billing_invoices(invoice_id);

CREATE TABLE IF NOT EXISTS invoice_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id TEXT NOT NULL,
    description TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_price REAL NOT NULL,
    total REAL NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (invoice_id) REFERENCES billing_invoices(invoice_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_id);

CREATE TABLE IF NOT EXISTS local_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id TEXT NOT NULL UNIQUE,
    tenant_id INTEGER NOT NULL,
    method TEXT NOT NULL,
    amount REAL NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    reference TEXT,
    details TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    confirmed_at TEXT,
    rejected_at TEXT,
    rejection_reason TEXT,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_local_payments_tenant ON local_payments(tenant_id);
CREATE INDEX IF NOT EXISTS idx_local_payments_status ON local_payments(status);
CREATE INDEX IF NOT EXISTS idx_local_payments_id ON local_payments(payment_id);

CREATE TABLE IF NOT EXISTS payment_confirmations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    confirmation_id TEXT NOT NULL UNIQUE,
    payment_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_review',
    proof_image TEXT,
    notes TEXT,
    submitted_at TEXT NOT NULL,
    reviewed_at TEXT,
    reviewed_by INTEGER,
    FOREIGN KEY (payment_id) REFERENCES local_payments(payment_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_payment_confirmations_payment ON payment_confirmations(payment_id);
CREATE INDEX IF NOT EXISTS idx_payment_confirmations_status ON payment_confirmations(status);

CREATE TABLE IF NOT EXISTS stripe_customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL UNIQUE,
    stripe_customer_id TEXT NOT NULL UNIQUE,
    email TEXT,
    name TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_stripe_customers_tenant ON stripe_customers(tenant_id);
CREATE INDEX IF NOT EXISTS idx_stripe_customers_stripe_id ON stripe_customers(stripe_customer_id);

CREATE TABLE IF NOT EXISTS refunds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    refund_id TEXT NOT NULL UNIQUE,
    payment_id TEXT NOT NULL,
    invoice_id TEXT,
    tenant_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    reason TEXT NOT NULL,
    reason_details TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    processed_by INTEGER,
    processed_at TEXT,
    completed_at TEXT,
    failure_reason TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_refunds_payment ON refunds(payment_id);
CREATE INDEX IF NOT EXISTS idx_refunds_tenant ON refunds(tenant_id);
CREATE INDEX IF NOT EXISTS idx_refunds_status ON refunds(status);
CREATE INDEX IF NOT EXISTS idx_refunds_id ON refunds(refund_id);

CREATE TABLE IF NOT EXISTS coupons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    discount_type TEXT NOT NULL,
    discount_value REAL NOT NULL,
    max_uses INTEGER,
    used_count INTEGER NOT NULL DEFAULT 0,
    valid_from TEXT NOT NULL,
    valid_until TEXT,
    applicable_plans TEXT,
    min_amount REAL,
    first_time_only INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    created_by INTEGER,
    metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_coupons_code ON coupons(code);
CREATE INDEX IF NOT EXISTS idx_coupons_status ON coupons(status);

CREATE TABLE IF NOT EXISTS coupon_redemptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coupon_id INTEGER NOT NULL,
    tenant_id INTEGER NOT NULL,
    user_id INTEGER,
    subscription_id TEXT,
    discount_applied REAL NOT NULL,
    redeemed_at TEXT NOT NULL,
    FOREIGN KEY (coupon_id) REFERENCES coupons(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_coupon ON coupon_redemptions(coupon_id);
CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_tenant ON coupon_redemptions(tenant_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    tenant_id INTEGER,
    user_id INTEGER,
    entity_type TEXT,
    entity_id TEXT,
    old_value TEXT,
    new_value TEXT,
    metadata TEXT,
    ip_address TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_log(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
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


def init_billing_db():
    """Inicializa las tablas de billing. Seguro llamar varias veces."""
    from utils.tenant_db import init_tenant_db
    init_tenant_db()
    
    with _connect() as conn:
        conn.executescript(_BILLING_SCHEMA)


# ── Subscriptions ───────────────────────────────────────────────

def create_subscription(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Crear una nueva suscripción."""
    init_billing_db()
    now = datetime.now().isoformat()
    
    try:
        with _connect() as conn:
            cur = conn.execute(
                """INSERT INTO subscriptions (subscription_id, tenant_id, plan_id, billing_cycle,
                   status, start_date, end_date, payment_method, payment_method_id, amount,
                   created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data['subscription_id'],
                    data['tenant_id'],
                    data['plan_id'],
                    data['billing_cycle'],
                    data['status'],
                    data['start_date'],
                    data['end_date'],
                    data['payment_method'],
                    data.get('payment_method_id'),
                    data['amount'],
                    now,
                    now
                )
            )
            # Hacer la consulta dentro del mismo contexto
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE subscription_id = ?",
                (data['subscription_id'],)
            ).fetchone()
            return dict(row) if row else None
    except Exception as e:
        return None


def get_subscription_by_id(subscription_id: str) -> Optional[Dict[str, Any]]:
    """Obtener una suscripción por ID."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE subscription_id = ?",
            (subscription_id,)
        ).fetchone()
        return dict(row) if row else None


def get_subscriptions_by_tenant(tenant_id: int, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Obtener suscripciones de un tenant."""
    init_billing_db()
    with _connect() as conn:
        query = "SELECT * FROM subscriptions WHERE tenant_id = ?"
        params = [tenant_id]
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        query += " ORDER BY created_at DESC"
        
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def update_subscription(subscription_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Actualizar una suscripción."""
    init_billing_db()
    
    allowed_fields = {
        'status', 'end_date', 'payment_method_id', 'cancelled_at',
        'cancel_at_period_end', 'amount'
    }
    
    update_fields = {k: v for k, v in updates.items() if k in allowed_fields}
    
    if not update_fields:
        return get_subscription_by_id(subscription_id)
    
    set_clause = ', '.join([f"{field} = ?" for field in update_fields])
    values = list(update_fields.values())
    values.append(datetime.now().isoformat())  # updated_at
    values.append(subscription_id)
    
    with _connect() as conn:
        conn.execute(
            f"UPDATE subscriptions SET {set_clause}, updated_at = ? WHERE subscription_id = ?",
            values
        )
    
    return get_subscription_by_id(subscription_id)


def list_all_subscriptions(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Listar todas las suscripciones."""
    init_billing_db()
    with _connect() as conn:
        query = "SELECT * FROM subscriptions"
        params = []
        
        if status:
            query += " WHERE status = ?"
            params.append(status)
        
        query += " ORDER BY created_at DESC"
        
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


# ── Invoices ───────────────────────────────────────────────────

def create_invoice(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Crear una nueva factura."""
    init_billing_db()
    now = datetime.now().isoformat()
    
    try:
        with _connect() as conn:
            cur = conn.execute(
                """INSERT INTO billing_invoices (invoice_id, tenant_id, subscription_id, invoice_number,
                   subtotal, tax_amount, total, currency, status, due_date, filepath, filename,
                   notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data['invoice_id'],
                    data['tenant_id'],
                    data.get('subscription_id'),
                    data['invoice_number'],
                    data['subtotal'],
                    data['tax_amount'],
                    data['total'],
                    data.get('currency', 'USD'),
                    data.get('status', 'pending'),
                    data.get('due_date'),
                    data.get('filepath'),
                    data.get('filename'),
                    data.get('notes'),
                    now,
                    now
                )
            )
            # Hacer la consulta dentro del mismo contexto
            row = conn.execute(
                "SELECT * FROM billing_invoices WHERE invoice_id = ?",
                (data['invoice_id'],)
            ).fetchone()
            return dict(row) if row else None
    except Exception as e:
        return None


def get_invoice_by_id(invoice_id: str) -> Optional[Dict[str, Any]]:
    """Obtener una factura por ID."""
    init_billing_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM billing_invoices WHERE invoice_id = ?",
            (invoice_id,)
        ).fetchone()
        return dict(row) if row else None


def get_invoices_by_tenant(tenant_id: int, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Obtener facturas de un tenant."""
    init_billing_db()
    with _connect() as conn:
        query = "SELECT * FROM billing_invoices WHERE tenant_id = ?"
        params = [tenant_id]
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        query += " ORDER BY created_at DESC"
        
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def update_invoice(invoice_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Actualizar una factura."""
    init_billing_db()
    
    allowed_fields = {
        'status', 'paid_date', 'filepath', 'filename', 'notes'
    }
    
    update_fields = {k: v for k, v in updates.items() if k in allowed_fields}
    
    if not update_fields:
        return get_invoice_by_id(invoice_id)
    
    set_clause = ', '.join([f"{field} = ?" for field in update_fields])
    values = list(update_fields.values())
    values.append(datetime.now().isoformat())  # updated_at
    values.append(invoice_id)
    
    with _connect() as conn:
        conn.execute(
            f"UPDATE billing_invoices SET {set_clause}, updated_at = ? WHERE invoice_id = ?",
            values
        )
    
    return get_invoice_by_id(invoice_id)


def list_all_invoices(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Listar todas las facturas."""
    init_billing_db()
    with _connect() as conn:
        query = "SELECT * FROM billing_invoices"
        params = []
        
        if status:
            query += " WHERE status = ?"
            params.append(status)
        
        query += " ORDER BY created_at DESC"
        
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


# ── Invoice Items ──────────────────────────────────────────────

def add_invoice_item(invoice_id: str, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Agregar un item a una factura."""
    init_billing_db()
    now = datetime.now().isoformat()
    
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                invoice_id,
                item['description'],
                item.get('quantity', 1),
                item['unit_price'],
                item['total'],
                now
            )
        )
        return get_invoice_item(cur.lastrowid)


def get_invoice_items(invoice_id: str) -> List[Dict[str, Any]]:
    """Obtener items de una factura."""
    init_billing_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY id",
            (invoice_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_invoice_item(item_id: int) -> Optional[Dict[str, Any]]:
    """Obtener un item de factura por ID."""
    init_billing_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM invoice_items WHERE id = ?",
            (item_id,)
        ).fetchone()
        return dict(row) if row else None


# ── Local Payments ─────────────────────────────────────────────

def create_local_payment(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Crear un pago local."""
    init_billing_db()
    now = datetime.now().isoformat()
    
    try:
        with _connect() as conn:
            cur = conn.execute(
                """INSERT INTO local_payments (payment_id, tenant_id, method, amount, currency,
                   status, reference, details, metadata, created_at, updated_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data['payment_id'],
                    data['tenant_id'],
                    data['method'],
                    data['amount'],
                    data['currency'],
                    data.get('status', 'pending'),
                    data.get('reference'),
                    data.get('details'),
                    json.dumps(data.get('metadata', {})),
                    now,
                    now,
                    data.get('expires_at')
                )
            )
            # Hacer la consulta dentro del mismo contexto
            row = conn.execute(
                "SELECT * FROM local_payments WHERE payment_id = ?",
                (data['payment_id'],)
            ).fetchone()
            if row:
                d = dict(row)
                # Parse metadata JSON
                if d.get('metadata'):
                    try:
                        d['metadata'] = json.loads(d['metadata'])
                    except:
                        d['metadata'] = {}
                return d
            return None
    except Exception as e:
        return None


def get_local_payment_by_id(payment_id: str) -> Optional[Dict[str, Any]]:
    """Obtener un pago local por ID."""
    init_billing_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM local_payments WHERE payment_id = ?",
            (payment_id,)
        ).fetchone()
        if row:
            d = dict(row)
            # Parse metadata JSON
            if d.get('metadata'):
                try:
                    d['metadata'] = json.loads(d['metadata'])
                except:
                    d['metadata'] = {}
            return d
        return None


def get_local_payments_by_tenant(tenant_id: int, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Obtener pagos locales de un tenant."""
    init_billing_db()
    with _connect() as conn:
        query = "SELECT * FROM local_payments WHERE tenant_id = ?"
        params = [tenant_id]
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        query += " ORDER BY created_at DESC"
        
        rows = conn.execute(query, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get('metadata'):
                try:
                    d['metadata'] = json.loads(d['metadata'])
                except:
                    d['metadata'] = {}
            results.append(d)
        return results


def update_local_payment(payment_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Actualizar un pago local."""
    init_billing_db()
    
    allowed_fields = {
        'status', 'confirmed_at', 'rejected_at', 'rejection_reason'
    }
    
    update_fields = {k: v for k, v in updates.items() if k in allowed_fields}
    
    if not update_fields:
        return get_local_payment_by_id(payment_id)
    
    set_clause = ', '.join([f"{field} = ?" for field in update_fields])
    values = list(update_fields.values())
    values.append(datetime.now().isoformat())  # updated_at
    values.append(payment_id)
    
    with _connect() as conn:
        conn.execute(
            f"UPDATE local_payments SET {set_clause}, updated_at = ? WHERE payment_id = ?",
            values
        )
    
    return get_local_payment_by_id(payment_id)


def list_all_local_payments(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Listar todos los pagos locales."""
    init_billing_db()
    with _connect() as conn:
        query = "SELECT * FROM local_payments"
        params = []
        
        if status:
            query += " WHERE status = ?"
            params.append(status)
        
        query += " ORDER BY created_at DESC"
        
        rows = conn.execute(query, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get('metadata'):
                try:
                    d['metadata'] = json.loads(d['metadata'])
                except:
                    d['metadata'] = {}
            results.append(d)
        return results


# ── Payment Confirmations ──────────────────────────────────────

def create_payment_confirmation(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Crear una confirmación de pago."""
    init_billing_db()
    
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO payment_confirmations (confirmation_id, payment_id, status,
               proof_image, notes, submitted_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                data['confirmation_id'],
                data['payment_id'],
                data.get('status', 'pending_review'),
                data.get('proof_image'),
                data.get('notes'),
                data['submitted_at']
            )
        )
        return get_payment_confirmation_by_id(data['confirmation_id'])


def get_payment_confirmation_by_id(confirmation_id: str) -> Optional[Dict[str, Any]]:
    """Obtener una confirmación por ID."""
    init_billing_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM payment_confirmations WHERE confirmation_id = ?",
            (confirmation_id,)
        ).fetchone()
        return dict(row) if row else None


def get_pending_confirmations() -> List[Dict[str, Any]]:
    """Obtener confirmaciones pendientes de revisión."""
    init_billing_db()
    with _connect() as conn:
        rows = conn.execute(
            """SELECT pc.confirmation_id, pc.payment_id, pc.status, pc.proof_image, 
                      pc.notes, pc.submitted_at, pc.reviewed_at, pc.reviewed_by,
                      lp.tenant_id, lp.method, lp.amount, lp.currency, lp.status as payment_status
               FROM payment_confirmations pc
               JOIN local_payments lp ON pc.payment_id = lp.payment_id
               WHERE pc.status = 'pending_review'
               ORDER BY pc.submitted_at DESC"""
        ).fetchall()
        return [dict(r) for r in rows]


def update_payment_confirmation(confirmation_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Actualizar una confirmación de pago."""
    init_billing_db()
    
    allowed_fields = {
        'status', 'reviewed_at', 'reviewed_by'
    }
    
    update_fields = {k: v for k, v in updates.items() if k in allowed_fields}
    
    if not update_fields:
        return get_payment_confirmation_by_id(confirmation_id)
    
    set_clause = ', '.join([f"{field} = ?" for field in update_fields])
    values = list(update_fields.values())
    values.append(confirmation_id)
    
    with _connect() as conn:
        conn.execute(
            f"UPDATE payment_confirmations SET {set_clause} WHERE confirmation_id = ?",
            values
        )
    
    return get_payment_confirmation_by_id(confirmation_id)


# ── Stripe Customers ───────────────────────────────────────────

def create_stripe_customer(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Crear un mapeo de cliente Stripe."""
    init_billing_db()
    now = datetime.now().isoformat()
    
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO stripe_customers (tenant_id, stripe_customer_id, email, name, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                data['tenant_id'],
                data['stripe_customer_id'],
                data.get('email'),
                data.get('name'),
                now,
                now
            )
        )
        return get_stripe_customer_by_tenant(data['tenant_id'])


def get_stripe_customer_by_tenant(tenant_id: int) -> Optional[Dict[str, Any]]:
    """Obtener cliente Stripe por tenant ID."""
    init_billing_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM stripe_customers WHERE tenant_id = ?",
            (tenant_id,)
        ).fetchone()
        return dict(row) if row else None


def get_stripe_customer_by_id(stripe_customer_id: str) -> Optional[Dict[str, Any]]:
    """Obtener cliente Stripe por ID de Stripe."""
    init_billing_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM stripe_customers WHERE stripe_customer_id = ?",
            (stripe_customer_id,)
        ).fetchone()
        return dict(row) if row else None


def update_stripe_customer(tenant_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Actualizar cliente Stripe."""
    init_billing_db()
    
    allowed_fields = {
        'email', 'name'
    }
    
    update_fields = {k: v for k, v in updates.items() if k in allowed_fields}
    
    if not update_fields:
        return get_stripe_customer_by_tenant(tenant_id)
    
    set_clause = ', '.join([f"{field} = ?" for field in update_fields])
    values = list(update_fields.values())
    values.append(datetime.now().isoformat())  # updated_at
    values.append(tenant_id)
    
    with _connect() as conn:
        conn.execute(
            f"UPDATE stripe_customers SET {set_clause}, updated_at = ? WHERE tenant_id = ?",
            values
        )
    
    return get_stripe_customer_by_tenant(tenant_id)
