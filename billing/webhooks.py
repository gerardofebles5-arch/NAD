"""
Stripe Webhooks Handler for PINAD SaaS
Processes Stripe webhook events (checkout.completed, invoice.paid, etc.)
"""

import os
import hmac
import hashlib
from typing import Dict, Callable, Optional
from datetime import datetime

from .stripe_client import get_stripe_client, is_stripe_configured


class StripeWebhookHandler:
    """Handler for Stripe webhook events."""
    
    def __init__(self):
        self.event_handlers = {
            'checkout.session.completed': self._handle_checkout_completed,
            'invoice.paid': self._handle_invoice_paid,
            'invoice.payment_failed': self._handle_invoice_payment_failed,
            'customer.subscription.created': self._handle_subscription_created,
            'customer.subscription.updated': self._handle_subscription_updated,
            'customer.subscription.deleted': self._handle_subscription_deleted,
        }
    
    def handle_event(self, event: Dict) -> Dict:
        """
        Route a webhook event to the appropriate handler.
        
        Args:
            event: Stripe event object
        
        Returns:
            Handler response
        """
        event_type = event.get('type')
        handler = self.event_handlers.get(event_type)
        
        if not handler:
            return {
                'success': True,
                'message': f'No handler for event type: {event_type}',
                'event_type': event_type
            }
        
        try:
            return handler(event)
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'event_type': event_type
            }
    
    def _handle_checkout_completed(self, event: Dict) -> Dict:
        """
        Handle checkout.session.completed event.
        This is triggered when a customer completes a checkout session.
        """
        try:
            from .billing_db import create_stripe_customer, create_subscription, init_billing_db
            from utils.tenant_db import update_tenant
            
            init_billing_db()
            session = event.get('data', {}).get('object', {})
            customer_id = session.get('customer')
            subscription_id = session.get('subscription')
            metadata = session.get('metadata', {})
            
            # Extract tenant_id from metadata
            tenant_id = metadata.get('tenant_id')
            plan_id = metadata.get('plan_id')
            
            if not tenant_id or not plan_id:
                return {
                    'success': False,
                    'event_type': 'checkout.session.completed',
                    'error': 'Missing tenant_id or plan_id in metadata'
                }
            
            # Guardar mapeo de cliente Stripe
            existing_customer = create_stripe_customer({
                'tenant_id': int(tenant_id),
                'stripe_customer_id': customer_id,
                'email': session.get('customer_details', {}).get('email'),
                'name': session.get('customer_details', {}).get('name')
            })
            
            # Crear suscripción en base de datos
            from .recurring_billing import get_recurring_billing_handler
            billing_handler = get_recurring_billing_handler()
            
            # Obtener información del plan para calcular fechas
            from .plans import PlanManager
            plan_manager = PlanManager()
            plan = plan_manager.get_plan(plan_id)
            
            if plan:
                from datetime import datetime, timedelta
                start_date = datetime.now()
                end_date = start_date + timedelta(days=30)  # Por defecto mensual
                
                subscription_data = {
                    'subscription_id': subscription_id,
                    'tenant_id': int(tenant_id),
                    'plan_id': plan_id,
                    'billing_cycle': 'monthly',
                    'status': 'active',
                    'start_date': start_date.isoformat(),
                    'end_date': end_date.isoformat(),
                    'payment_method': 'stripe',
                    'payment_method_id': customer_id,
                    'amount': plan['price_usd']
                }
                
                create_subscription(subscription_data)
                
                # Actualizar plan del tenant
                update_tenant(int(tenant_id), plan_id=plan_id)
            
            return {
                'success': True,
                'event_type': 'checkout.session.completed',
                'customer_id': customer_id,
                'subscription_id': subscription_id,
                'tenant_id': tenant_id,
                'plan_id': plan_id,
                'message': 'Checkout completed successfully'
            }
        except Exception as e:
            return {
                'success': False,
                'event_type': 'checkout.session.completed',
                'error': str(e)
            }
    
    def _handle_invoice_paid(self, event: Dict) -> Dict:
        """
        Handle invoice.paid event.
        This is triggered when an invoice is successfully paid.
        """
        try:
            from .billing_db import update_subscription, create_invoice, add_invoice_item, init_billing_db, get_subscription_by_id
            from .invoice_generator import InvoiceGenerator
            from datetime import datetime, timedelta
            
            init_billing_db()
            invoice = event.get('data', {}).get('object', {})
            subscription_id = invoice.get('subscription')
            customer_id = invoice.get('customer')
            amount_paid = invoice.get('amount_paid')
            currency = invoice.get('currency')
            
            # Extender el período de suscripción
            if subscription_id:
                subscription = update_subscription(subscription_id, {
                    'end_date': (datetime.now() + timedelta(days=30)).isoformat()
                })
                
                # Generar factura interna
                sub = get_subscription_by_id(subscription_id)
                if sub:
                    tenant_id = sub.get('tenant_id')
                    plan_id = sub.get('plan_id')
                    
                    # Crear factura en base de datos
                    invoice_id = f"inv_{datetime.now().strftime('%Y%m%d%H%M%S')}_{tenant_id}"
                    invoice_number = f"INV-{datetime.now().strftime('%Y%m%d')}-{tenant_id}"
                    
                    invoice_data = {
                        'invoice_id': invoice_id,
                        'tenant_id': tenant_id,
                        'subscription_id': subscription_id,
                        'invoice_number': invoice_number,
                        'subtotal': amount_paid / 100,
                        'tax_amount': 0,
                        'total': amount_paid / 100,
                        'currency': currency.upper(),
                        'status': 'paid',
                        'paid_date': datetime.now().isoformat()
                    }
                    
                    created_invoice = create_invoice(invoice_data)
                    
                    if created_invoice:
                        # Agregar items a la factura
                        from .plans import PlanManager
                        plan_manager = PlanManager()
                        plan = plan_manager.get_plan(plan_id)
                        
                        if plan:
                            add_invoice_item(created_invoice['invoice_id'], {
                                'description': f"Suscripción {plan['name']} - {sub.get('billing_cycle', 'monthly')}",
                                'quantity': 1,
                                'unit_price': amount_paid / 100,
                                'total': amount_paid / 100
                            })
                        
                        # Generar PDF de la factura
                        try:
                            invoice_gen = InvoiceGenerator()
                            pdf_path = invoice_gen.generate_invoice_pdf(
                                invoice_id=invoice_id,
                                tenant_id=tenant_id,
                                subscription_id=subscription_id,
                                amount=amount_paid / 100,
                                currency=currency.upper(),
                                due_date=datetime.now().isoformat(),
                                items=[{
                                    'description': f"Suscripción {plan['name'] if plan else plan_id}",
                                    'quantity': 1,
                                    'unit_price': amount_paid / 100,
                                    'total': amount_paid / 100
                                }]
                            )
                            
                            # Actualizar factura con la ruta del PDF
                            from .billing_db import update_invoice
                            update_invoice(invoice_id, {
                                'filepath': pdf_path,
                                'filename': os.path.basename(pdf_path)
                            })
                        except Exception as pdf_error:
                            print(f"Error generando PDF de factura: {pdf_error}")
            
            # TODO: Enviar email de confirmación
            
            return {
                'success': True,
                'event_type': 'invoice.paid',
                'subscription_id': subscription_id,
                'customer_id': customer_id,
                'amount_paid': amount_paid,
                'currency': currency,
                'message': 'Invoice paid successfully'
            }
        except Exception as e:
            return {
                'success': False,
                'event_type': 'invoice.paid',
                'error': str(e)
            }
    
    def _handle_invoice_payment_failed(self, event: Dict) -> Dict:
        """
        Handle invoice.payment_failed event.
        This is triggered when an invoice payment fails.
        """
        try:
            from .billing_db import update_subscription, init_billing_db
            from utils.tenant_db import update_tenant
            
            init_billing_db()
            invoice = event.get('data', {}).get('object', {})
            subscription_id = invoice.get('subscription')
            customer_id = invoice.get('customer')
            amount_due = invoice.get('amount_due')
            
            # Marcar suscripción como past_due
            if subscription_id:
                subscription = update_subscription(subscription_id, {
                    'status': 'past_due'
                })
                
                # Obtener tenant_id de la suscripción para downgradear
                from .billing_db import get_subscription_by_id
                sub = get_subscription_by_id(subscription_id)
                if sub:
                    tenant_id = sub.get('tenant_id')
                    # Opcional: downgradear a free después de varios intentos fallidos
                    # update_tenant(tenant_id, plan_id='free')
            
            return {
                'success': True,
                'event_type': 'invoice.payment_failed',
                'subscription_id': subscription_id,
                'customer_id': customer_id,
                'amount_due': amount_due,
                'message': 'Invoice payment failed'
            }
        except Exception as e:
            return {
                'success': False,
                'event_type': 'invoice.payment_failed',
                'error': str(e)
            }
    
    def _handle_subscription_created(self, event: Dict) -> Dict:
        """
        Handle customer.subscription.created event.
        This is triggered when a new subscription is created.
        """
        try:
            from .billing_db import create_subscription, init_billing_db
            from datetime import datetime, timedelta
            
            init_billing_db()
            subscription = event.get('data', {}).get('object', {})
            customer_id = subscription.get('customer')
            subscription_id = subscription.get('id')
            status = subscription.get('status')
            
            # Obtener tenant_id del cliente Stripe
            from .billing_db import get_stripe_customer_by_id
            stripe_customer = get_stripe_customer_by_id(customer_id)
            
            if stripe_customer:
                tenant_id = stripe_customer.get('tenant_id')
                
                # Calcular fechas basado en el ciclo de facturación
                start_date = datetime.now()
                billing_cycle = subscription.get('items', {}).get('data', [{}])[0].get('price', {}).get('recurring', {}).get('interval', 'month')
                
                if billing_cycle == 'year':
                    end_date = start_date + timedelta(days=365)
                else:
                    end_date = start_date + timedelta(days=30)
                
                # Determinar plan_id basado en el price
                price_id = subscription.get('items', {}).get('data', [{}])[0].get('price', {}).get('id')
                # Mapeo simple de price_id a plan_id (en producción esto sería más robusto)
                plan_id = 'pro'  # Por defecto
                
                subscription_data = {
                    'subscription_id': subscription_id,
                    'tenant_id': tenant_id,
                    'plan_id': plan_id,
                    'billing_cycle': 'monthly' if billing_cycle == 'month' else 'yearly',
                    'status': status,
                    'start_date': start_date.isoformat(),
                    'end_date': end_date.isoformat(),
                    'payment_method': 'stripe',
                    'payment_method_id': customer_id,
                    'amount': subscription.get('items', {}).get('data', [{}])[0].get('price', {}).get('unit_amount', 0) / 100
                }
                
                create_subscription(subscription_data)
            
            return {
                'success': True,
                'event_type': 'customer.subscription.created',
                'subscription_id': subscription_id,
                'customer_id': customer_id,
                'status': status,
                'message': 'Subscription created successfully'
            }
        except Exception as e:
            return {
                'success': False,
                'event_type': 'customer.subscription.created',
                'error': str(e)
            }
    
    def _handle_subscription_updated(self, event: Dict) -> Dict:
        """
        Handle customer.subscription.updated event.
        This is triggered when a subscription is updated (plan change, etc.).
        """
        try:
            from .billing_db import update_subscription, init_billing_db
            from utils.tenant_db import update_tenant
            
            init_billing_db()
            subscription = event.get('data', {}).get('object', {})
            customer_id = subscription.get('customer')
            subscription_id = subscription.get('id')
            status = subscription.get('status')
            
            previous_attributes = event.get('data', {}).get('previous_attributes', {})
            
            # Actualizar suscripción en base de datos
            updates = {'status': status}
            
            # Si cambió el plan, actualizar el tenant
            if 'items' in previous_attributes:
                # Obtener tenant_id de la suscripción
                from .billing_db import get_subscription_by_id
                sub = get_subscription_by_id(subscription_id)
                if sub:
                    tenant_id = sub.get('tenant_id')
                    
                    # Determinar nuevo plan_id basado en el price
                    price_id = subscription.get('items', {}).get('data', [{}])[0].get('price', {}).get('id')
                    # Mapeo simple (en producción esto sería más robusto)
                    plan_id = 'pro' if 'pro' in price_id.lower() else 'enterprise' if 'enterprise' in price_id.lower() else 'free'
                    
                    update_tenant(tenant_id, plan_id=plan_id)
                    updates['plan_id'] = plan_id
            
            update_subscription(subscription_id, updates)
            
            return {
                'success': True,
                'event_type': 'customer.subscription.updated',
                'subscription_id': subscription_id,
                'customer_id': customer_id,
                'status': status,
                'previous_attributes': previous_attributes,
                'message': 'Subscription updated successfully'
            }
        except Exception as e:
            return {
                'success': False,
                'event_type': 'customer.subscription.updated',
                'error': str(e)
            }
    
    def _handle_subscription_deleted(self, event: Dict) -> Dict:
        """
        Handle customer.subscription.deleted event.
        This is triggered when a subscription is cancelled.
        """
        try:
            from .billing_db import update_subscription, init_billing_db
            from utils.tenant_db import update_tenant
            
            init_billing_db()
            subscription = event.get('data', {}).get('object', {})
            customer_id = subscription.get('customer')
            subscription_id = subscription.get('id')
            
            # Actualizar suscripción como cancelada
            update_subscription(subscription_id, {
                'status': 'cancelled',
                'cancelled_at': datetime.now().isoformat()
            })
            
            # Downgradear tenant a free plan
            from .billing_db import get_subscription_by_id
            sub = get_subscription_by_id(subscription_id)
            if sub:
                tenant_id = sub.get('tenant_id')
                update_tenant(tenant_id, plan_id='free')
            
            return {
                'success': True,
                'event_type': 'customer.subscription.deleted',
                'subscription_id': subscription_id,
                'customer_id': customer_id,
                'message': 'Subscription cancelled successfully'
            }
        except Exception as e:
            return {
                'success': False,
                'event_type': 'customer.subscription.deleted',
                'error': str(e)
            }
    
    def register_handler(self, event_type: str, handler: Callable):
        """
        Register a custom handler for a specific event type.
        
        Args:
            event_type: Stripe event type
            handler: Handler function
        """
        self.event_handlers[event_type] = handler


# Singleton instance
_webhook_handler: Optional[StripeWebhookHandler] = None


def get_webhook_handler() -> StripeWebhookHandler:
    """Get or create the webhook handler singleton."""
    global _webhook_handler
    if _webhook_handler is None:
        _webhook_handler = StripeWebhookHandler()
    return _webhook_handler
