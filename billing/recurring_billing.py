"""
Recurring Billing for PINAD SaaS
Handles automatic billing for subscriptions.
"""

import os
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from enum import Enum
import json

from .invoice_generator import get_invoice_generator
from .plans import PlanManager


class BillingCycle(str, Enum):
    """Billing cycle types."""
    MONTHLY = "monthly"
    YEARLY = "yearly"


class SubscriptionStatus(str, Enum):
    """Subscription status."""
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class RecurringBillingHandler:
    """Handler for recurring billing operations."""
    
    def __init__(self):
        self.plan_manager = PlanManager()
        self.invoice_generator = get_invoice_generator()
    
    def create_subscription(
        self,
        tenant_id: str,
        plan_id: str,
        billing_cycle: str = BillingCycle.MONTHLY,
        start_date: Optional[str] = None,
        payment_method: str = "stripe",
        payment_method_id: Optional[str] = None
    ) -> Dict:
        """
        Crear una nueva suscripción.
        
        Args:
            tenant_id: ID del tenant
            plan_id: ID del plan
            billing_cycle: Ciclo de facturación (monthly, yearly)
            start_date: Fecha de inicio (opcional, por defecto hoy)
            payment_method: Método de pago (stripe, pagomovil, zelle, usdt)
            payment_method_id: ID del método de pago (customer_id de Stripe, etc.)
        
        Returns:
            Información de la suscripción creada
        """
        try:
            from .billing_db import create_subscription, init_billing_db
            from utils.tenant_db import update_tenant
            
            init_billing_db()
            subscription_id = f"sub_{datetime.now().strftime('%Y%m%d%H%M%S')}_{tenant_id}"
            
            plan = self.plan_manager.get_plan(plan_id)
            if not plan:
                return {
                    'success': False,
                    'error': f'Plan no encontrado: {plan_id}'
                }
            
            # Calcular fechas
            if not start_date:
                start_date = datetime.now()
            else:
                start_date = datetime.fromisoformat(start_date)
            
            if billing_cycle == BillingCycle.MONTHLY:
                end_date = start_date + timedelta(days=30)
            else:
                end_date = start_date + timedelta(days=365)
            
            subscription_data = {
                'subscription_id': subscription_id,
                'tenant_id': int(tenant_id),
                'plan_id': plan_id,
                'billing_cycle': billing_cycle,
                'status': SubscriptionStatus.ACTIVE,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'payment_method': payment_method,
                'payment_method_id': payment_method_id,
                'amount': plan['price_usd'],
            }
            
            subscription = create_subscription(subscription_data)
            
            if subscription:
                # Actualizar plan del tenant
                update_tenant(int(tenant_id), plan_id=plan_id)
                
                return {
                    'success': True,
                    'subscription': subscription
                }
            else:
                return {
                    'success': False,
                    'error': 'Error al guardar la suscripción en base de datos'
                }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def generate_invoice_for_subscription(
        self,
        subscription_id: str
    ) -> Dict:
        """
        Generar factura para una suscripción.
        
        Args:
            subscription_id: ID de la suscripción
        
        Returns:
            Información de la factura generada
        """
        try:
            # TODO: Obtener suscripción de la base de datos
            # Por ahora, simulamos la obtención
            
            subscription = {
                'subscription_id': subscription_id,
                'tenant_id': '1',
                'plan_id': 'pro',
                'billing_cycle': BillingCycle.MONTHLY,
                'amount': 10.0,
            }
            
            # Obtener información del tenant
            # TODO: Obtener de la base de datos
            tenant_info = {
                'tenant_id': subscription['tenant_id'],
                'name': 'Empresa Demo',
                'email': 'demo@empresa.com'
            }
            
            plan = self.plan_manager.get_plan(subscription['plan_id'])
            
            # Generar ID de factura
            invoice_id = f"inv_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            # Generar PDF
            result = self.invoice_generator.generate_subscription_invoice(
                invoice_id=invoice_id,
                tenant_id=subscription['tenant_id'],
                tenant_name=tenant_info['name'],
                tenant_email=tenant_info['email'],
                plan_name=plan['name'],
                plan_price=subscription['amount'],
                billing_period=subscription['billing_cycle']
            )
            
            if not result['success']:
                return result
            
            # TODO: Guardar factura en base de datos
            
            return {
                'success': True,
                'invoice_id': invoice_id,
                'subscription_id': subscription_id,
                'filepath': result['filepath'],
                'filename': result['filename']
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def cancel_subscription(
        self,
        subscription_id: str,
        cancel_at_period_end: bool = True
    ) -> Dict:
        """
        Cancelar una suscripción.
        
        Args:
            subscription_id: ID de la suscripción
            cancel_at_period_end: Si True, cancela al final del período. Si False, cancela inmediatamente.
        
        Returns:
            Estado de la suscripción actualizada
        """
        try:
            from .billing_db import update_subscription, init_billing_db
            from utils.tenant_db import update_tenant, get_tenant
            
            init_billing_db()
            
            updates = {
                'cancel_at_period_end': 1 if cancel_at_period_end else 0
            }
            
            if not cancel_at_period_end:
                updates['cancelled_at'] = datetime.now().isoformat()
                updates['status'] = SubscriptionStatus.CANCELLED
            
            subscription = update_subscription(subscription_id, updates)
            
            if subscription:
                # Si se cancela inmediatamente, downgradear al plan free
                if not cancel_at_period_end:
                    tenant_id = subscription.get('tenant_id')
                    if tenant_id:
                        update_tenant(tenant_id, plan_id='free')
                
                return {
                    'success': True,
                    'subscription_id': subscription_id,
                    'status': subscription.get('status'),
                    'cancel_at_period_end': cancel_at_period_end,
                    'cancelled_at': updates.get('cancelled_at')
                }
            else:
                return {
                    'success': False,
                    'error': 'Suscripción no encontrada'
                }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_subscription(self, subscription_id: str) -> Dict:
        """
        Obtener información de una suscripción.
        
        Args:
            subscription_id: ID de la suscripción
        
        Returns:
            Información de la suscripción
        """
        try:
            from .billing_db import get_subscription_by_id, init_billing_db
            
            init_billing_db()
            subscription = get_subscription_by_id(subscription_id)
            
            if subscription:
                return {
                    'success': True,
                    'subscription': subscription
                }
            else:
                return {
                    'success': False,
                    'error': 'Suscripción no encontrada'
                }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def list_subscriptions(
        self,
        tenant_id: Optional[str] = None,
        status: Optional[str] = None
    ) -> Dict:
        """
        Listar suscripciones.
        
        Args:
            tenant_id: ID del tenant (opcional, para filtrar)
            status: Estado de la suscripción (opcional, para filtrar)
        
        Returns:
            Lista de suscripciones
        """
        try:
            from .billing_db import get_subscriptions_by_tenant, list_all_subscriptions, init_billing_db
            
            init_billing_db()
            
            if tenant_id:
                subscriptions = get_subscriptions_by_tenant(int(tenant_id), status=status)
            else:
                subscriptions = list_all_subscriptions(status=status)
            
            return {
                'success': True,
                'subscriptions': subscriptions
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def process_renewals(self) -> Dict:
        """
        Procesar renovaciones automáticas de suscripciones.
        Este método debe ser ejecutado periódicamente (ej. diario).
        
        Returns:
            Resumen de renovaciones procesadas
        """
        try:
            # TODO: Implementar lógica de renovación
            # 1. Buscar suscripciones que vencen hoy
            # 2. Para cada suscripción:
            #    a. Intentar cobrar automáticamente (si Stripe)
            #    b. Generar factura
            #    c. Extender el período
            #    d. Si falla el cobro, marcar como past_due
            
            return {
                'success': True,
                'processed': 0,
                'renewed': 0,
                'failed': 0,
                'message': 'No implementado aún - requiere base de datos'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def upgrade_subscription(
        self,
        subscription_id: str,
        new_plan_id: str
    ) -> Dict:
        """
        Actualizar el plan de una suscripción.
        
        Args:
            subscription_id: ID de la suscripción
            new_plan_id: ID del nuevo plan
        
        Returns:
            Suscripción actualizada
        """
        try:
            # TODO: Implementar actualización en base de datos
            
            # Calcular prorrateo
            # Si el nuevo plan es más caro, cobrar la diferencia
            # Si es más barato, aplicar crédito al siguiente período
            
            return {
                'success': True,
                'subscription_id': subscription_id,
                'new_plan_id': new_plan_id,
                'message': 'No implementado aún - requiere base de datos'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }


# Singleton instance
_recurring_billing_handler: Optional[RecurringBillingHandler] = None


def get_recurring_billing_handler() -> RecurringBillingHandler:
    """Get or create the recurring billing handler singleton."""
    global _recurring_billing_handler
    if _recurring_billing_handler is None:
        _recurring_billing_handler = RecurringBillingHandler()
    return _recurring_billing_handler
