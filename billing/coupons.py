"""
Coupons and Discounts Module for PINAD SaaS
Manages promotional codes, discounts, and special offers.
"""

import os
import json
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum
from contextlib import contextmanager

from utils.config import CONFIG

DB_PATH = os.path.join(CONFIG.output_dir, "nadscanner.db")

import sqlite3
import threading

_lock = threading.RLock()


class DiscountType(str, Enum):
    """Types of discounts."""
    PERCENTAGE = "percentage"
    FIXED_AMOUNT = "fixed_amount"
    TRIAL_DAYS = "trial_days"


class CouponStatus(str, Enum):
    """Status of coupons."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    EXPIRED = "expired"
    DEPLETED = "depleted"


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


_COUPONS_SCHEMA = """
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
CREATE INDEX IF NOT EXISTS idx_coupons_validity ON coupons(valid_from, valid_until);

CREATE TABLE IF NOT EXISTS coupon_redemptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coupon_id INTEGER NOT NULL,
    tenant_id INTEGER NOT NULL,
    user_id INTEGER,
    subscription_id TEXT,
    discount_applied REAL NOT NULL,
    redeemed_at TEXT NOT NULL,
    FOREIGN KEY (coupon_id) REFERENCES coupons(id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_coupon ON coupon_redemptions(coupon_id);
CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_tenant ON coupon_redemptions(tenant_id);
"""


def init_coupons_db():
    """Initialize coupons tables."""
    from .billing_db import init_billing_db
    init_billing_db()
    
    with _connect() as conn:
        conn.executescript(_COUPONS_SCHEMA)


def generate_coupon_code(prefix: str = "PROMO", length: int = 8) -> str:
    """Generate a unique coupon code."""
    random_part = secrets.token_urlsafe(length).upper()[:length]
    return f"{prefix}-{random_part}"


def create_coupon(
    code: Optional[str] = None,
    discount_type: DiscountType = DiscountType.PERCENTAGE,
    discount_value: float = 10.0,
    max_uses: Optional[int] = None,
    valid_days: int = 30,
    applicable_plans: Optional[List[str]] = None,
    min_amount: Optional[float] = None,
    first_time_only: bool = False,
    created_by: Optional[int] = None,
    metadata: Optional[Dict] = None
) -> Optional[Dict[str, Any]]:
    """
    Create a new coupon.
    
    Args:
        code: Coupon code (auto-generated if None)
        discount_type: Type of discount
        discount_value: Discount value (percentage or fixed amount)
        max_uses: Maximum number of uses (None for unlimited)
        valid_days: Number of days the coupon is valid
        applicable_plans: Plans this coupon applies to (None for all)
        min_amount: Minimum order amount required
        first_time_only: Only for first-time customers
        created_by: Admin user ID who created the coupon
        metadata: Additional metadata
    
    Returns:
        Created coupon or None if failed
    """
    init_coupons_db()
    
    if not code:
        code = generate_coupon_code()
    
    valid_from = datetime.now().isoformat()
    valid_until = (datetime.now() + timedelta(days=valid_days)).isoformat()
    
    try:
        with _connect() as conn:
            cur = conn.execute(
                """INSERT INTO coupons (code, discount_type, discount_value, max_uses,
                   valid_from, valid_until, applicable_plans, min_amount, first_time_only,
                   status, created_at, created_by, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    code,
                    discount_type.value,
                    discount_value,
                    max_uses,
                    valid_from,
                    valid_until,
                    json.dumps(applicable_plans) if applicable_plans else None,
                    min_amount,
                    1 if first_time_only else 0,
                    CouponStatus.ACTIVE.value,
                    valid_from,
                    created_by,
                    json.dumps(metadata) if metadata else None
                )
            )
            row = conn.execute(
                "SELECT * FROM coupons WHERE id = ?",
                (cur.lastrowid,)
            ).fetchone()
            
            if row:
                d = dict(row)
                # Parse JSON fields
                if d.get('applicable_plans'):
                    try:
                        d['applicable_plans'] = json.loads(d['applicable_plans'])
                    except:
                        d['applicable_plans'] = []
                if d.get('metadata'):
                    try:
                        d['metadata'] = json.loads(d['metadata'])
                    except:
                        d['metadata'] = {}
                return d
    except Exception as e:
        print(f"Error creating coupon: {e}")
    
    return None


def get_coupon_by_code(code: str) -> Optional[Dict[str, Any]]:
    """Get a coupon by code."""
    init_coupons_db()
    
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM coupons WHERE code = ?",
            (code,)
        ).fetchone()
        
        if row:
            d = dict(row)
            # Parse JSON fields
            if d.get('applicable_plans'):
                try:
                    d['applicable_plans'] = json.loads(d['applicable_plans'])
                except:
                    d['applicable_plans'] = []
            if d.get('metadata'):
                try:
                    d['metadata'] = json.loads(d['metadata'])
                except:
                    d['metadata'] = {}
            return d
    
    return None


def validate_coupon(
    code: str,
    tenant_id: int,
    plan_id: str,
    amount: float,
    is_first_time: bool = False
) -> Dict[str, Any]:
    """
    Validate if a coupon can be applied.
    
    Args:
        code: Coupon code
        tenant_id: Tenant ID
        plan_id: Plan being purchased
        amount: Order amount
        is_first_time: Whether this is a first-time customer
    
    Returns:
        Validation result with discount info
    """
    coupon = get_coupon_by_code(code)
    
    if not coupon:
        return {
            'valid': False,
            'reason': 'Coupon not found'
        }
    
    # Check status
    if coupon['status'] != CouponStatus.ACTIVE.value:
        return {
            'valid': False,
            'reason': f'Coupon is {coupon["status"]}'
        }
    
    # Check validity dates
    now = datetime.now()
    valid_from = datetime.fromisoformat(coupon['valid_from'])
    
    if now < valid_from:
        return {
            'valid': False,
            'reason': 'Coupon is not yet valid'
        }
    
    if coupon['valid_until']:
        valid_until = datetime.fromisoformat(coupon['valid_until'])
        if now > valid_until:
            return {
                'valid': False,
                'reason': 'Coupon has expired'
            }
    
    # Check usage limit
    if coupon['max_uses'] and coupon['used_count'] >= coupon['max_uses']:
        return {
            'valid': False,
            'reason': 'Coupon usage limit reached'
        }
    
    # Check first-time only
    if coupon['first_time_only'] and not is_first_time:
        return {
            'valid': False,
            'reason': 'Coupon is for first-time customers only'
        }
    
    # Check minimum amount
    if coupon['min_amount'] and amount < coupon['min_amount']:
        return {
            'valid': False,
            'reason': f'Minimum amount ${coupon["min_amount"]} required'
        }
    
    # Check applicable plans
    if coupon['applicable_plans']:
        applicable_plans = coupon['applicable_plans']
        if plan_id not in applicable_plans:
            return {
                'valid': False,
                'reason': f'Coupon not applicable to plan {plan_id}'
            }
    
    # Check if tenant already used this coupon
    if has_tenant_used_coupon(tenant_id, coupon['id']):
        return {
            'valid': False,
            'reason': 'Coupon already used by this tenant'
        }
    
    # Calculate discount
    discount_amount = calculate_discount(coupon, amount)
    
    return {
        'valid': True,
        'coupon_id': coupon['id'],
        'code': coupon['code'],
        'discount_type': coupon['discount_type'],
        'discount_value': coupon['discount_value'],
        'discount_amount': discount_amount,
        'final_amount': amount - discount_amount
    }


def calculate_discount(coupon: Dict[str, Any], amount: float) -> float:
    """Calculate discount amount based on coupon type."""
    discount_type = coupon['discount_type']
    discount_value = coupon['discount_value']
    
    if discount_type == DiscountType.PERCENTAGE.value:
        return amount * (discount_value / 100)
    elif discount_type == DiscountType.FIXED_AMOUNT.value:
        return min(discount_value, amount)  # Can't discount more than total
    elif discount_type == DiscountType.TRIAL_DAYS.value:
        return 0  # Trial doesn't affect amount
    
    return 0


def has_tenant_used_coupon(tenant_id: int, coupon_id: int) -> bool:
    """Check if tenant has already used a coupon."""
    init_coupons_db()
    
    with _connect() as conn:
        row = conn.execute(
            """SELECT id FROM coupon_redemptions 
               WHERE coupon_id = ? AND tenant_id = ?""",
            (coupon_id, tenant_id)
        ).fetchone()
        
        return row is not None


def redeem_coupon(
    coupon_id: int,
    tenant_id: int,
    user_id: Optional[int] = None,
    subscription_id: Optional[str] = None,
    original_amount: float = 0
) -> bool:
    """
    Redeem a coupon for a tenant.
    
    Args:
        coupon_id: Coupon ID
        tenant_id: Tenant ID
        user_id: User ID
        subscription_id: Subscription ID
        original_amount: Original order amount
    
    Returns:
        True if redeemed successfully
    """
    init_coupons_db()
    
    try:
        with _connect() as conn:
            # Get coupon info
            coupon = conn.execute(
                "SELECT * FROM coupons WHERE id = ?",
                (coupon_id,)
            ).fetchone()
            
            if not coupon:
                return False
            
            coupon_dict = dict(coupon)
            discount_amount = calculate_discount(coupon_dict, original_amount)
            
            # Record redemption
            conn.execute(
                """INSERT INTO coupon_redemptions (coupon_id, tenant_id, user_id, 
                   subscription_id, discount_applied, redeemed_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    coupon_id,
                    tenant_id,
                    user_id,
                    subscription_id,
                    discount_amount,
                    datetime.now().isoformat()
                )
            )
            
            # Update usage count
            conn.execute(
                "UPDATE coupons SET used_count = used_count + 1 WHERE id = ?",
                (coupon_id,)
            )
            
            # Log audit event
            from .audit import AuditLogger, AuditAction
            AuditLogger.log_coupon_redeemed(
                tenant_id=tenant_id,
                coupon_id=coupon_id,
                discount_amount=discount_amount,
                user_id=user_id
            )
            
            return True
    except Exception as e:
        print(f"Error redeeming coupon: {e}")
    
    return False


def list_coupons(status: Optional[CouponStatus] = None) -> List[Dict[str, Any]]:
    """List all coupons with optional status filter."""
    init_coupons_db()
    
    with _connect() as conn:
        query = "SELECT * FROM coupons"
        params = []
        
        if status:
            query += " WHERE status = ?"
            params.append(status.value)
        
        query += " ORDER BY created_at DESC"
        
        rows = conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            # Parse JSON fields
            if d.get('applicable_plans'):
                try:
                    d['applicable_plans'] = json.loads(d['applicable_plans'])
                except:
                    d['applicable_plans'] = []
            if d.get('metadata'):
                try:
                    d['metadata'] = json.loads(d['metadata'])
                except:
                    d['metadata'] = {}
            results.append(d)
        
        return results


def update_coupon_status(coupon_id: int, status: CouponStatus) -> bool:
    """Update coupon status."""
    init_coupons_db()
    
    try:
        with _connect() as conn:
            conn.execute(
                "UPDATE coupons SET status = ? WHERE id = ?",
                (status.value, coupon_id)
            )
            return True
    except Exception as e:
        print(f"Error updating coupon status: {e}")
    
    return False


class CouponManager:
    """Manager for coupon operations."""
    
    def __init__(self):
        pass
    
    def create_promo_coupon(
        self,
        discount_percent: float = 10,
        max_uses: int = 100,
        valid_days: int = 30
    ) -> Optional[Dict[str, Any]]:
        """Create a standard promotional coupon."""
        return create_coupon(
            discount_type=DiscountType.PERCENTAGE,
            discount_value=discount_percent,
            max_uses=max_uses,
            valid_days=valid_days
        )
    
    def create_trial_coupon(
        self,
        trial_days: int = 14,
        max_uses: int = 50
    ) -> Optional[Dict[str, Any]]:
        """Create a free trial coupon."""
        return create_coupon(
            discount_type=DiscountType.TRIAL_DAYS,
            discount_value=trial_days,
            max_uses=max_uses,
            valid_days=90
        )
    
    def get_coupon_stats(self) -> Dict[str, Any]:
        """Get coupon usage statistics."""
        init_coupons_db()
        
        with _connect() as conn:
            total_coupons = conn.execute(
                "SELECT COUNT(*) FROM coupons"
            ).fetchone()[0]
            
            active_coupons = conn.execute(
                "SELECT COUNT(*) FROM coupons WHERE status = 'active'"
            ).fetchone()[0]
            
            total_redemptions = conn.execute(
                "SELECT COUNT(*) FROM coupon_redemptions"
            ).fetchone()[0]
            
            total_discount = conn.execute(
                "SELECT SUM(discount_applied) FROM coupon_redemptions"
            ).fetchone()[0] or 0
            
            return {
                'total_coupons': total_coupons,
                'active_coupons': active_coupons,
                'total_redemptions': total_redemptions,
                'total_discount_given': total_discount
            }
