"""
Billing Analytics for PINAD SaaS
Calculates MRR, churn, LTV, and other SaaS metrics.
"""

from typing import Dict, Optional, List
from datetime import datetime, timedelta
from decimal import Decimal


class BillingAnalytics:
    """Calculates SaaS billing metrics."""
    
    def __init__(self):
        pass
    
    def calculate_mrr(
        self,
        subscriptions: Optional[List[Dict]] = None,
        as_of_date: Optional[str] = None
    ) -> Dict:
        """
        Calcular Monthly Recurring Revenue (MRR).
        
        Args:
            subscriptions: Lista de suscripciones activas (opcional, si None se obtiene de BD)
            as_of_date: Fecha de cálculo (opcional, por defecto hoy)
        
        Returns:
            MRR desglosado por plan y total
        """
        try:
            from .billing_db import list_all_subscriptions, init_billing_db
            
            init_billing_db()
            
            if subscriptions is None:
                subscriptions = list_all_subscriptions(status='active')
        except:
            subscriptions = subscriptions or []
        
        if not as_of_date:
            as_of_date = datetime.now()
        else:
            as_of_date = datetime.fromisoformat(as_of_date)
        
        mrr_by_plan = {}
        total_mrr = 0.0
        
        for sub in subscriptions:
            # Solo contar suscripciones activas
            if sub.get('status') != 'active':
                continue
            
            # Verificar si la suscripción está activa en la fecha
            start_date = datetime.fromisoformat(sub['start_date'])
            end_date = datetime.fromisoformat(sub.get('end_date', '2099-12-31'))
            
            if not (start_date <= as_of_date <= end_date):
                continue
            
            plan_id = sub['plan_id']
            amount = sub.get('amount', 0)
            
            # Ajustar según ciclo de facturación
            billing_cycle = sub.get('billing_cycle', 'monthly')
            if billing_cycle == 'yearly':
                monthly_amount = amount / 12
            else:
                monthly_amount = amount
            
            mrr_by_plan[plan_id] = mrr_by_plan.get(plan_id, 0) + monthly_amount
            total_mrr += monthly_amount
        
        return {
            'total_mrr': round(total_mrr, 2),
            'mrr_by_plan': {k: round(v, 2) for k, v in mrr_by_plan.items()},
            'as_of_date': as_of_date.isoformat(),
            'active_subscriptions': len(subscriptions)
        }
    
    def calculate_arr(
        self,
        subscriptions: List[Dict],
        as_of_date: Optional[str] = None
    ) -> Dict:
        """
        Calcular Annual Recurring Revenue (ARR).
        
        Args:
            subscriptions: Lista de suscripciones activas
            as_of_date: Fecha de cálculo (opcional, por defecto hoy)
        
        Returns:
            ARR desglosado por plan y total
        """
        mrr_result = self.calculate_mrr(subscriptions, as_of_date)
        total_arr = mrr_result['total_mrr'] * 12
        
        return {
            'total_arr': round(total_arr, 2),
            'arr_by_plan': {k: round(v * 12, 2) for k, v in mrr_result['mrr_by_plan'].items()},
            'as_of_date': mrr_result['as_of_date'],
            'active_subscriptions': mrr_result['active_subscriptions']
        }
    
    def calculate_churn_rate(
        self,
        subscriptions: Optional[List[Dict]] = None,
        period_days: int = 30
    ) -> Dict:
        """
        Calcular tasa de cancelación (churn rate).
        
        Args:
            subscriptions: Lista de todas las suscripciones (opcional, si None se obtiene de BD)
            period_days: Período en días para calcular churn
        
        Returns:
            Tasa de churn porcentual
        """
        try:
            from .billing_db import list_all_subscriptions, init_billing_db
            
            init_billing_db()
            
            if subscriptions is None:
                subscriptions = list_all_subscriptions()
        except:
            subscriptions = subscriptions or []
        
        now = datetime.now()
        period_start = now - timedelta(days=period_days)
        
        # Contar suscripciones activas al inicio del período
        active_at_start = 0
        cancelled_in_period = 0
        
        for sub in subscriptions:
            start_date = datetime.fromisoformat(sub['start_date'])
            
            # Suscripciones activas al inicio del período
            if start_date <= period_start:
                if sub.get('status') == 'active':
                    active_at_start += 1
            
            # Suscripciones canceladas en el período
            if sub.get('status') == 'cancelled':
                cancelled_date = datetime.fromisoformat(sub.get('cancelled_at', sub.get('updated_at', now.isoformat())))
                if period_start <= cancelled_date <= now:
                    cancelled_in_period += 1
        
        if active_at_start == 0:
            churn_rate = 0.0
        else:
            churn_rate = (cancelled_in_period / active_at_start) * 100
        
        return {
            'churn_rate': round(churn_rate, 2),
            'active_at_start': active_at_start,
            'cancelled_in_period': cancelled_in_period,
            'period_days': period_days,
            'period_start': period_start.isoformat(),
            'period_end': now.isoformat()
        }
    
    def calculate_ltv(
        self,
        subscriptions: List[Dict],
        arpu: float,
        churn_rate: float
    ) -> Dict:
        """
        Calcular Lifetime Value (LTV) de un cliente.
        
        Args:
            subscriptions: Lista de suscripciones (para cálculo de lifespan)
            arpu: Average Revenue Per User (mensual)
            churn_rate: Tasa de churn mensual (porcentaje)
        
        Returns:
            LTV estimado
        """
        if churn_rate == 0:
            # Si no hay churn, usar un lifespan estimado de 36 meses
            lifespan_months = 36
        else:
            # LTV = ARPU / Churn Rate
            churn_rate_decimal = churn_rate / 100
            lifespan_months = 1 / churn_rate_decimal if churn_rate_decimal > 0 else 36
        
        ltv = arpu * lifespan_months
        
        return {
            'ltv': round(ltv, 2),
            'arpu': round(arpu, 2),
            'churn_rate': round(churn_rate, 2),
            'lifespan_months': round(lifespan_months, 2)
        }
    
    def calculate_arpu(
        self,
        subscriptions: List[Dict],
        active_users: int
    ) -> Dict:
        """
        Calcular Average Revenue Per User (ARPU).
        
        Args:
            subscriptions: Lista de suscripciones activas
            active_users: Número de usuarios activos
        
        Returns:
            ARPU mensual
        """
        if active_users == 0:
            return {
                'arpu': 0.0,
                'total_revenue': 0.0,
                'active_users': 0
            }
        
        total_revenue = 0.0
        for sub in subscriptions:
            if sub.get('status') == 'active':
                billing_cycle = sub.get('billing_cycle', 'monthly')
                amount = sub.get('amount', 0)
                
                if billing_cycle == 'yearly':
                    monthly_amount = amount / 12
                else:
                    monthly_amount = amount
                
                total_revenue += monthly_amount
        
        arpu = total_revenue / active_users
        
        return {
            'arpu': round(arpu, 2),
            'total_revenue': round(total_revenue, 2),
            'active_users': active_users
        }
    
    def get_revenue_by_payment_method(
        self,
        payments: Optional[List[Dict]] = None,
        period_days: int = 30
    ) -> Dict:
        """
        Obtener ingresos por método de pago.
        
        Args:
            payments: Lista de pagos (opcional, si None se obtiene de BD)
            period_days: Período en días
        
        Returns:
            Ingresos desglosados por método de pago
        """
        try:
            from .billing_db import list_all_local_payments, init_billing_db
            
            init_billing_db()
            
            if payments is None:
                payments = list_all_local_payments(status='confirmed')
        except:
            payments = payments or []
        
        now = datetime.now()
        period_start = now - timedelta(days=period_days)
        
        revenue_by_method = {}
        total_revenue = 0.0
        
        for payment in payments:
            payment_date = datetime.fromisoformat(payment.get('created_at', now.isoformat()))
            
            if period_start <= payment_date <= now:
                method = payment.get('method', 'unknown')
                amount = payment.get('amount', 0)
                
                revenue_by_method[method] = revenue_by_method.get(method, 0) + amount
                total_revenue += amount
        
        return {
            'total_revenue': round(total_revenue, 2),
            'revenue_by_method': {k: round(v, 2) for k, v in revenue_by_method.items()},
            'period_days': period_days,
            'period_start': period_start.isoformat(),
            'period_end': now.isoformat()
        }
    
    def get_subscription_growth(
        self,
        subscriptions: Optional[List[Dict]] = None,
        period_days: int = 30
    ) -> Dict:
        """
        Obtener crecimiento de suscripciones.
        
        Args:
            subscriptions: Lista de suscripciones (opcional, si None se obtiene de BD)
            period_days: Período en días
        
        Returns:
            Métricas de crecimiento
        """
        try:
            from .billing_db import list_all_subscriptions, init_billing_db
            
            init_billing_db()
            
            if subscriptions is None:
                subscriptions = list_all_subscriptions()
        except:
            subscriptions = subscriptions or []
        
        now = datetime.now()
        period_start = now - timedelta(days=period_days)
        
        new_subscriptions = 0
        cancelled_subscriptions = 0
        upgraded_subscriptions = 0
        downgraded_subscriptions = 0
        
        for sub in subscriptions:
            created_date = datetime.fromisoformat(sub['created_at'])
            
            # Nuevas suscripciones en el período
            if period_start <= created_date <= now:
                new_subscriptions += 1
            
            # Cancelaciones en el período
            if sub.get('status') == 'cancelled':
                cancelled_date = datetime.fromisoformat(sub.get('cancelled_at', sub.get('updated_at', now.isoformat())))
                if period_start <= cancelled_date <= now:
                    cancelled_subscriptions += 1
            
            # Upgrades/Downgrades (requiere tracking de cambios de plan)
            # TODO: Implementar cuando se tenga tracking de cambios
        
        net_growth = new_subscriptions - cancelled_subscriptions
        
        return {
            'new_subscriptions': new_subscriptions,
            'cancelled_subscriptions': cancelled_subscriptions,
            'net_growth': net_growth,
            'upgraded_subscriptions': upgraded_subscriptions,
            'downgraded_subscriptions': downgraded_subscriptions,
            'period_days': period_days,
            'period_start': period_start.isoformat(),
            'period_end': now.isoformat()
        }
    
    def get_comprehensive_analytics(
        self,
        subscriptions: Optional[List[Dict]] = None,
        payments: Optional[List[Dict]] = None,
        active_users: Optional[int] = None
    ) -> Dict:
        """
        Obtener analytics completos de billing.
        
        Args:
            subscriptions: Lista de suscripciones (opcional, si None se obtiene de BD)
            payments: Lista de pagos (opcional, si None se obtiene de BD)
            active_users: Número de usuarios activos (opcional, si None se calcula)
        
        Returns:
            Dashboard completo de métricas
        """
        try:
            from .billing_db import list_all_subscriptions, list_all_local_payments, init_billing_db
            from utils.tenant_db import list_tenants
            
            init_billing_db()
            
            if subscriptions is None:
                subscriptions = list_all_subscriptions()
            
            if payments is None:
                payments = list_all_local_payments(status='confirmed')
            
            if active_users is None:
                tenants = list_tenants()
                active_users = sum(t.get('user_count', 0) for t in tenants)
        except:
            subscriptions = subscriptions or []
            payments = payments or []
            active_users = active_users or 0
        
        # Calcular MRR y ARR
        mrr = self.calculate_mrr(subscriptions)
        arr = self.calculate_arr(subscriptions)
        
        # Calcular churn
        churn = self.calculate_churn_rate(subscriptions)
        
        # Calcular ARPU
        arpu = self.calculate_arpu(subscriptions, active_users)
        
        # Calcular LTV
        ltv = self.calculate_ltv(subscriptions, arpu['arpu'], churn['churn_rate'])
        
        # Ingresos por método de pago
        revenue_by_method = self.get_revenue_by_payment_method(payments)
        
        # Crecimiento de suscripciones
        growth = self.get_subscription_growth(subscriptions)
        
        return {
            'mrr': mrr,
            'arr': arr,
            'churn': churn,
            'arpu': arpu,
            'ltv': ltv,
            'revenue_by_method': revenue_by_method,
            'growth': growth,
            'generated_at': datetime.now().isoformat()
        }


# Singleton instance
_billing_analytics: Optional[BillingAnalytics] = None


def get_billing_analytics() -> BillingAnalytics:
    """Get or create the billing analytics singleton."""
    global _billing_analytics
    if _billing_analytics is None:
        _billing_analytics = BillingAnalytics()
    return _billing_analytics
