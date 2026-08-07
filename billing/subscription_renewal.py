"""
Subscription Renewal Module for PINAD SaaS
Handles automatic subscription renewals and expiry handling.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional
import threading

from .billing_db import (
    init_billing_db,
    list_all_subscriptions,
    update_subscription,
    get_subscription_by_id
)
from .recurring_billing import get_recurring_billing_handler
from utils.tenant_db import update_tenant, get_tenant

_lock = threading.RLock()


class SubscriptionRenewal:
    """Manages automatic subscription renewals."""
    
    def __init__(self):
        self.billing_handler = get_recurring_billing_handler()
    
    def check_expiring_subscriptions(self, days_before: int = 7) -> List[Dict]:
        """
        Check for subscriptions expiring within the next N days.
        
        Args:
            days_before: Number of days before expiry to check
        
        Returns:
            List of subscriptions expiring soon
        """
        init_billing_db()
        now = datetime.now()
        expiry_threshold = now + timedelta(days=days_before)
        
        subscriptions = list_all_subscriptions(status='active')
        expiring = []
        
        for sub in subscriptions:
            end_date = datetime.fromisoformat(sub['end_date'])
            
            # Si la suscripción expira pronto
            if now <= end_date <= expiry_threshold:
                expiring.append(sub)
        
        return expiring
    
    def check_expired_subscriptions(self) -> List[Dict]:
        """
        Check for subscriptions that have already expired.
        
        Returns:
            List of expired subscriptions
        """
        init_billing_db()
        now = datetime.now()
        
        subscriptions = list_all_subscriptions(status='active')
        expired = []
        
        for sub in subscriptions:
            end_date = datetime.fromisoformat(sub['end_date'])
            
            # Si la suscripción ya expiró
            if end_date < now:
                expired.append(sub)
        
        return expired
    
    def process_expired_subscriptions(self) -> Dict:
        """
        Process expired subscriptions by downgrading to free plan.
        
        Returns:
            Summary of processed subscriptions
        """
        expired = self.check_expired_subscriptions()
        processed = 0
        failed = 0
        
        for sub in expired:
            try:
                # Marcar suscripción como expirada
                update_subscription(sub['subscription_id'], {
                    'status': 'expired',
                    'cancelled_at': datetime.now().isoformat()
                })
                
                # Downgradear tenant a plan free
                tenant_id = sub.get('tenant_id')
                if tenant_id:
                    update_tenant(tenant_id, plan_id='free')
                
                processed += 1
            except Exception as e:
                print(f"Error procesando suscripción expirada {sub['subscription_id']}: {e}")
                failed += 1
        
        return {
            'processed': processed,
            'failed': failed,
            'total': len(expired)
        }
    
    def renew_subscription(self, subscription_id: str) -> Dict:
        """
        Renew a subscription manually.
        
        Args:
            subscription_id: ID of the subscription to renew
        
        Returns:
            Result of renewal operation
        """
        try:
            init_billing_db()
            sub = get_subscription_by_id(subscription_id)
            
            if not sub:
                return {
                    'success': False,
                    'error': 'Suscripción no encontrada'
                }
            
            # Calcular nueva fecha de fin
            billing_cycle = sub.get('billing_cycle', 'monthly')
            if billing_cycle == 'yearly':
                extension_days = 365
            else:
                extension_days = 30
            
            # Extender desde la fecha actual o desde la fecha de fin si aún no expiró
            end_date = datetime.fromisoformat(sub['end_date'])
            now = datetime.now()
            
            if end_date > now:
                new_end_date = end_date + timedelta(days=extension_days)
            else:
                new_end_date = now + timedelta(days=extension_days)
            
            # Actualizar suscripción
            updated = update_subscription(subscription_id, {
                'status': 'active',
                'end_date': new_end_date.isoformat()
            })
            
            if updated:
                # Reactivar plan del tenant
                tenant_id = sub.get('tenant_id')
                plan_id = sub.get('plan_id')
                if tenant_id and plan_id:
                    update_tenant(tenant_id, plan_id=plan_id)
                
                return {
                    'success': True,
                    'subscription': updated,
                    'new_end_date': new_end_date.isoformat()
                }
            else:
                return {
                    'success': False,
                    'error': 'Error al actualizar suscripción'
                }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def send_expiry_notifications(self, days_before: int = 7) -> Dict:
        """
        Send notifications for subscriptions expiring soon.
        
        Args:
            days_before: Number of days before expiry to notify
        
        Returns:
            Summary of notifications sent
        """
        expiring = self.check_expiring_subscriptions(days_before)
        sent = 0
        
        for sub in expiring:
            try:
                # TODO: Implementar envío de email/notification
                # Por ahora, solo registramos en consola
                tenant_id = sub.get('tenant_id')
                end_date = sub.get('end_date')
                print(f"Notificación: Suscripción {sub['subscription_id']} del tenant {tenant_id} expira el {end_date}")
                sent += 1
            except Exception as e:
                print(f"Error enviando notificación para suscripción {sub['subscription_id']}: {e}")
        
        return {
            'sent': sent,
            'total': len(expiring)
        }
    
    def run_daily_maintenance(self) -> Dict:
        """
        Run daily maintenance tasks:
        1. Process expired subscriptions
        2. Send expiry notifications
        3. Check for renewals needed
        
        Returns:
            Summary of maintenance operations
        """
        with _lock:
            results = {
                'expired_processed': self.process_expired_subscriptions(),
                'notifications_sent': self.send_expiry_notifications(days_before=7),
                'expiring_count': len(self.check_expiring_subscriptions(days_before=7)),
                'timestamp': datetime.now().isoformat()
            }
            
            return results


# Singleton instance
_renewal_instance: Optional[SubscriptionRenewal] = None
_renewal_lock = threading.Lock()


def get_subscription_renewal() -> SubscriptionRenewal:
    """Get the singleton subscription renewal instance."""
    global _renewal_instance
    with _renewal_lock:
        if _renewal_instance is None:
            _renewal_instance = SubscriptionRenewal()
        return _renewal_instance
