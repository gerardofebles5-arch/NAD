"""
Transaction Audit Module for PINAD SaaS
Tracks all billing-related transactions and changes for security and compliance.
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum
from contextlib import contextmanager

from utils.config import CONFIG

DB_PATH = os.path.join(CONFIG.output_dir, "nadscanner.db")

import sqlite3
import threading

_lock = threading.RLock()


class AuditAction(str, Enum):
    """Types of audit actions."""
    # Subscription actions
    SUBSCRIPTION_CREATED = "subscription_created"
    SUBSCRIPTION_UPDATED = "subscription_updated"
    SUBSCRIPTION_CANCELLED = "subscription_cancelled"
    SUBSCRIPTION_RENEWED = "subscription_renewed"
    
    # Payment actions
    PAYMENT_INITIATED = "payment_initiated"
    PAYMENT_COMPLETED = "payment_completed"
    PAYMENT_FAILED = "payment_failed"
    PAYMENT_REFUNDED = "payment_refunded"
    
    # Invoice actions
    INVOICE_CREATED = "invoice_created"
    INVOICE_PAID = "invoice_paid"
    INVOICE_OVERDUE = "invoice_overdue"
    
    # Plan actions
    PLAN_UPGRADED = "plan_upgraded"
    PLAN_DOWNGRADED = "plan_downgraded"
    
    # Coupon actions
    COUPON_APPLIED = "coupon_applied"
    COUPON_REDEEMED = "coupon_redeemed"
    
    # Admin actions
    ADMIN_LOGIN = "admin_login"
    ADMIN_ACTION = "admin_action"


class AuditSeverity(str, Enum):
    """Severity levels for audit events."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@contextmanager
def _connect():
    with _lock:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


_AUDIT_SCHEMA = """
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
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
"""


def init_audit_db():
    """Initialize audit tables."""
    from .billing_db import init_billing_db
    init_billing_db()
    
    with _connect() as conn:
        conn.executescript(_AUDIT_SCHEMA)


def log_audit_event(
    action: AuditAction,
    severity: AuditSeverity = AuditSeverity.INFO,
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    old_value: Optional[Dict] = None,
    new_value: Optional[Dict] = None,
    metadata: Optional[Dict] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
) -> bool:
    """
    Log an audit event.
    
    Args:
        action: Type of action performed
        severity: Severity level
        tenant_id: Tenant ID if applicable
        user_id: User ID who performed the action
        entity_type: Type of entity affected
        entity_id: ID of entity affected
        old_value: Previous state (JSON)
        new_value: New state (JSON)
        metadata: Additional metadata
        ip_address: IP address of requester
        user_agent: User agent string
    
    Returns:
        True if logged successfully
    """
    init_audit_db()
    
    try:
        with _connect() as conn:
            conn.execute(
                """INSERT INTO audit_log (action, severity, tenant_id, user_id, entity_type, entity_id,
                   old_value, new_value, metadata, ip_address, user_agent, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    action.value,
                    severity.value,
                    tenant_id,
                    user_id,
                    entity_type,
                    entity_id,
                    json.dumps(old_value) if old_value else None,
                    json.dumps(new_value) if new_value else None,
                    json.dumps(metadata) if metadata else None,
                    ip_address,
                    user_agent,
                    datetime.now().isoformat()
                )
            )
        return True
    except Exception as e:
        print(f"Error logging audit event: {e}")
        return False


def get_audit_logs(
    tenant_id: Optional[int] = None,
    action: Optional[AuditAction] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Retrieve audit logs with optional filters.
    
    Args:
        tenant_id: Filter by tenant
        action: Filter by action type
        entity_type: Filter by entity type
        entity_id: Filter by entity ID
        limit: Maximum number of results
        offset: Offset for pagination
    
    Returns:
        List of audit log entries
    """
    init_audit_db()
    
    with _connect() as conn:
        query = "SELECT * FROM audit_log WHERE 1=1"
        params = []
        
        if tenant_id:
            query += " AND tenant_id = ?"
            params.append(tenant_id)
        
        if action:
            query += " AND action = ?"
            params.append(action.value)
        
        if entity_type:
            query += " AND entity_type = ?"
            params.append(entity_type)
        
        if entity_id:
            query += " AND entity_id = ?"
            params.append(entity_id)
        
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        rows = conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            # Parse JSON fields
            for field in ['old_value', 'new_value', 'metadata']:
                if d.get(field):
                    try:
                        d[field] = json.loads(d[field])
                    except:
                        d[field] = {}
            results.append(d)
        
        return results


def get_audit_summary(tenant_id: Optional[int] = None, days: int = 30) -> Dict[str, Any]:
    """
    Get audit summary statistics.
    
    Args:
        tenant_id: Filter by tenant
        days: Number of days to include
    
    Returns:
        Summary statistics
    """
    init_audit_db()
    
    from datetime import datetime, timedelta
    cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
    
    with _connect() as conn:
        query = "SELECT * FROM audit_log WHERE created_at >= ?"
        params = [cutoff_date]
        
        if tenant_id:
            query += " AND tenant_id = ?"
            params.append(tenant_id)
        
        rows = conn.execute(query, params).fetchall()
        
        # Calculate statistics
        total_events = len(rows)
        actions_count = {}
        severity_count = {}
        
        for row in rows:
            action = row['action']
            severity = row['severity']
            
            actions_count[action] = actions_count.get(action, 0) + 1
            severity_count[severity] = severity_count.get(severity, 0) + 1
        
        return {
            'total_events': total_events,
            'actions_count': actions_count,
            'severity_count': severity_count,
            'period_days': days
        }


class AuditLogger:
    """Helper class for logging common audit events."""
    
    @staticmethod
    def log_subscription_created(tenant_id: int, subscription_id: str, plan_id: str, user_id: Optional[int] = None):
        """Log subscription creation."""
        log_audit_event(
            action=AuditAction.SUBSCRIPTION_CREATED,
            tenant_id=tenant_id,
            user_id=user_id,
            entity_type='subscription',
            entity_id=subscription_id,
            new_value={'plan_id': plan_id, 'status': 'active'},
            severity=AuditSeverity.INFO
        )
    
    @staticmethod
    def log_payment_completed(tenant_id: int, payment_id: str, amount: float, method: str, user_id: Optional[int] = None):
        """Log successful payment."""
        log_audit_event(
            action=AuditAction.PAYMENT_COMPLETED,
            tenant_id=tenant_id,
            user_id=user_id,
            entity_type='payment',
            entity_id=payment_id,
            new_value={'amount': amount, 'method': method},
            severity=AuditSeverity.INFO
        )
    
    @staticmethod
    def log_plan_changed(tenant_id: int, old_plan: str, new_plan: str, user_id: Optional[int] = None):
        """Log plan change."""
        log_audit_event(
            action=AuditAction.PLAN_UPGRADED if new_plan != 'free' else AuditAction.PLAN_DOWNGRADED,
            tenant_id=tenant_id,
            user_id=user_id,
            entity_type='tenant',
            entity_id=str(tenant_id),
            old_value={'plan_id': old_plan},
            new_value={'plan_id': new_plan},
            severity=AuditSeverity.INFO
        )
    
    @staticmethod
    def log_admin_action(tenant_id: int, action: str, details: Dict, user_id: int, ip_address: Optional[str] = None):
        """Log admin action."""
        log_audit_event(
            action=AuditAction.ADMIN_ACTION,
            tenant_id=tenant_id,
            user_id=user_id,
            entity_type='admin',
            metadata={'action': action, 'details': details},
            ip_address=ip_address,
            severity=AuditSeverity.WARNING
        )
