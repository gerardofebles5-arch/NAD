"""
Refunds Module for PINAD SaaS
Handles refund processing and tracking for payments.
"""

import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum
from contextlib import contextmanager

from utils.config import CONFIG

DB_PATH = os.path.join(CONFIG.output_dir, "nadscanner.db")

import sqlite3
import threading

_lock = threading.RLock()


class RefundStatus(str, Enum):
    """Status of refunds."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RefundReason(str, Enum):
    """Reasons for refunds."""
    DUPLICATE_PAYMENT = "duplicate_payment"
    SERVICE_NOT_PROVIDED = "service_not_provided"
    CANCELLATION = "cancellation"
    CUSTOMER_REQUEST = "customer_request"
    TECHNICAL_ISSUE = "technical_issue"
    OTHER = "other"


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


_REFUNDS_SCHEMA = """
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
"""


def init_refunds_db():
    """Initialize refunds tables."""
    from .billing_db import init_billing_db
    init_billing_db()
    
    with _connect() as conn:
        conn.executescript(_REFUNDS_SCHEMA)


def generate_refund_id() -> str:
    """Generate a unique refund ID."""
    import secrets
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random_part = secrets.token_hex(4).upper()
    return f"REF-{timestamp}-{random_part}"


def create_refund(
    payment_id: str,
    tenant_id: int,
    amount: float,
    reason: RefundReason,
    reason_details: Optional[str] = None,
    invoice_id: Optional[str] = None,
    currency: str = 'USD',
    metadata: Optional[Dict] = None
) -> Optional[Dict[str, Any]]:
    """
    Create a refund request.
    
    Args:
        payment_id: Original payment ID
        tenant_id: Tenant ID
        amount: Refund amount
        reason: Reason for refund
        reason_details: Additional details
        invoice_id: Associated invoice ID
        currency: Currency code
        metadata: Additional metadata
    
    Returns:
        Created refund or None if failed
    """
    init_refunds_db()
    
    refund_id = generate_refund_id()
    
    try:
        with _connect() as conn:
            cur = conn.execute(
                """INSERT INTO refunds (refund_id, payment_id, invoice_id, tenant_id,
                   amount, currency, reason, reason_details, status, created_at, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    refund_id,
                    payment_id,
                    invoice_id,
                    tenant_id,
                    amount,
                    currency,
                    reason.value,
                    reason_details,
                    RefundStatus.PENDING.value,
                    datetime.now().isoformat(),
                    json.dumps(metadata) if metadata else None
                )
            )
            row = conn.execute(
                "SELECT * FROM refunds WHERE id = ?",
                (cur.lastrowid,)
            ).fetchone()
            
            if row:
                d = dict(row)
                if d.get('metadata'):
                    try:
                        d['metadata'] = json.loads(d['metadata'])
                    except:
                        d['metadata'] = {}
                return d
    except Exception as e:
        print(f"Error creating refund: {e}")
    
    return None


def get_refund_by_id(refund_id: str) -> Optional[Dict[str, Any]]:
    """Get a refund by ID."""
    init_refunds_db()
    
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM refunds WHERE refund_id = ?",
            (refund_id,)
        ).fetchone()
        
        if row:
            d = dict(row)
            if d.get('metadata'):
                try:
                    d['metadata'] = json.loads(d['metadata'])
                except:
                    d['metadata'] = {}
            return d
    
    return None


def get_refunds_by_tenant(tenant_id: int, status: Optional[RefundStatus] = None) -> List[Dict[str, Any]]:
    """Get refunds for a tenant."""
    init_refunds_db()
    
    with _connect() as conn:
        query = "SELECT * FROM refunds WHERE tenant_id = ?"
        params = [tenant_id]
        
        if status:
            query += " AND status = ?"
            params.append(status.value)
        
        query += " ORDER BY created_at DESC"
        
        rows = conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d.get('metadata'):
                try:
                    d['metadata'] = json.loads(d['metadata'])
                except:
                    d['metadata'] = {}
            results.append(d)
        
        return results


def process_refund(
    refund_id: str,
    processed_by: int,
    payment_method: str = 'stripe'
) -> bool:
    """
    Process a refund through the payment gateway.
    
    Args:
        refund_id: Refund ID
        processed_by: Admin user ID
        payment_method: Payment gateway to use
    
    Returns:
        True if processed successfully
    """
    init_refunds_db()
    
    refund = get_refund_by_id(refund_id)
    if not refund:
        return False
    
    if refund['status'] != RefundStatus.PENDING.value:
        return False
    
    try:
        # Update status to processing
        with _connect() as conn:
            conn.execute(
                """UPDATE refunds SET status = ?, processed_by = ?, 
                   processed_at = ? WHERE refund_id = ?""",
                (
                    RefundStatus.PROCESSING.value,
                    processed_by,
                    datetime.now().isoformat(),
                    refund_id
                )
            )
        
        # Process through payment gateway
        if payment_method == 'stripe':
            success = _process_stripe_refund(refund)
        else:
            success = _process_local_refund(refund)
        
        # Update final status
        with _connect() as conn:
            if success:
                conn.execute(
                    """UPDATE refunds SET status = ?, completed_at = ? 
                       WHERE refund_id = ?""",
                    (
                        RefundStatus.COMPLETED.value,
                        datetime.now().isoformat(),
                        refund_id
                    )
                )
                
                # Log audit event
                from .audit import AuditLogger, AuditAction
                AuditLogger.log_payment_refunded(
                    tenant_id=refund['tenant_id'],
                    payment_id=refund['payment_id'],
                    refund_id=refund_id,
                    amount=refund['amount'],
                    user_id=processed_by
                )
            else:
                conn.execute(
                    """UPDATE refunds SET status = ?, failure_reason = ? 
                       WHERE refund_id = ?""",
                    (
                        RefundStatus.FAILED.value,
                        "Payment gateway error",
                        refund_id
                    )
                )
        
        return success
    except Exception as e:
        print(f"Error processing refund: {e}")
        return False


def _process_stripe_refund(refund: Dict[str, Any]) -> bool:
    """Process refund through Stripe."""
    try:
        from .stripe_client import get_stripe_client
        stripe_client = get_stripe_client()
        
        if not stripe_client or not stripe_client.is_configured():
            return False
        
        # Create Stripe refund
        result = stripe_client.create_refund(
            payment_intent_id=refund['payment_id'],
            amount=int(refund['amount'] * 100)  # Convert to cents
        )
        
        return result.get('success', False)
    except Exception as e:
        print(f"Stripe refund error: {e}")
        return False


def _process_local_refund(refund: Dict[str, Any]) -> bool:
    """Process refund for local payment methods."""
    # For local payments, we just mark as completed
    # The actual refund would be processed manually
    return True


def cancel_refund(refund_id: str, cancelled_by: int) -> bool:
    """Cancel a pending refund."""
    init_refunds_db()
    
    try:
        with _connect() as conn:
            conn.execute(
                """UPDATE refunds SET status = ? WHERE refund_id = ?""",
                (RefundStatus.CANCELLED.value, refund_id)
            )
            return True
    except Exception as e:
        print(f"Error cancelling refund: {e}")
    
    return False


def list_all_refunds(status: Optional[RefundStatus] = None) -> List[Dict[str, Any]]:
    """List all refunds with optional status filter."""
    init_refunds_db()
    
    with _connect() as conn:
        query = "SELECT * FROM refunds"
        params = []
        
        if status:
            query += " WHERE status = ?"
            params.append(status.value)
        
        query += " ORDER BY created_at DESC"
        
        rows = conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d.get('metadata'):
                try:
                    d['metadata'] = json.loads(d['metadata'])
                except:
                    d['metadata'] = {}
            results.append(d)
        
        return results


def get_refund_statistics(days: int = 30) -> Dict[str, Any]:
    """Get refund statistics for a period."""
    init_refunds_db()
    
    from datetime import datetime, timedelta
    cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
    
    with _connect() as conn:
        # Total refunds
        total_refunds = conn.execute(
            """SELECT COUNT(*) FROM refunds WHERE created_at >= ?""",
            (cutoff_date,)
        ).fetchone()[0]
        
        # Completed refunds
        completed_refunds = conn.execute(
            """SELECT COUNT(*) FROM refunds WHERE created_at >= ? AND status = ?""",
            (cutoff_date, RefundStatus.COMPLETED.value)
        ).fetchone()[0]
        
        # Total amount refunded
        total_amount = conn.execute(
            """SELECT SUM(amount) FROM refunds WHERE created_at >= ? AND status = ?""",
            (cutoff_date, RefundStatus.COMPLETED.value)
        ).fetchone()[0] or 0
        
        # Refunds by reason
        reason_counts = {}
        rows = conn.execute(
            """SELECT reason, COUNT(*) FROM refunds WHERE created_at >= ? 
               GROUP BY reason""",
            (cutoff_date,)
        ).fetchall()
        for reason, count in rows:
            reason_counts[reason] = count
        
        return {
            'period_days': days,
            'total_refunds': total_refunds,
            'completed_refunds': completed_refunds,
            'pending_refunds': total_refunds - completed_refunds,
            'total_amount_refunded': total_amount,
            'refunds_by_reason': reason_counts
        }


class RefundManager:
    """Manager for refund operations."""
    
    def __init__(self):
        pass
    
    def calculate_refund_eligibility(
        self,
        payment_date: str,
        current_date: Optional[str] = None,
        refund_policy_days: int = 30
    ) -> Dict[str, Any]:
        """
        Calculate if a payment is eligible for refund based on time.
        
        Args:
            payment_date: Original payment date (ISO format)
            current_date: Current date (ISO format, defaults to now)
            refund_policy_days: Refund policy period in days
        
        Returns:
            Eligibility information
        """
        if not current_date:
            current_date = datetime.now().isoformat()
        
        payment_dt = datetime.fromisoformat(payment_date)
        current_dt = datetime.fromisoformat(current_date)
        
        days_since_payment = (current_dt - payment_dt).days
        is_eligible = days_since_payment <= refund_policy_days
        
        return {
            'eligible': is_eligible,
            'days_since_payment': days_since_payment,
            'refund_policy_days': refund_policy_days,
            'days_remaining': max(0, refund_policy_days - days_since_payment)
        }
    
    def auto_refund_failed_payment(self, payment_id: str, tenant_id: int) -> bool:
        """
        Automatically refund a failed payment.
        
        Args:
            payment_id: Payment ID
            tenant_id: Tenant ID
        
        Returns:
            True if refund created successfully
        """
        # Get payment details
        from .billing_db import get_local_payment_by_id
        payment = get_local_payment_by_id(payment_id)
        
        if not payment:
            return False
        
        # Create refund
        refund = create_refund(
            payment_id=payment_id,
            tenant_id=tenant_id,
            amount=payment['amount'],
            reason=RefundReason.TECHNICAL_ISSUE,
            reason_details="Payment processing failed",
            currency=payment['currency']
        )
        
        return refund is not None
