"""
Payment Confirmation Handler for PINAD SaaS
Handles manual confirmation of local payments (PagoMóvil, Zelle, USDT).
"""

import os
import json
from typing import Dict, Optional, List
from datetime import datetime
from enum import Enum

from .local_payments import LocalPaymentMethod, LocalPaymentStatus


class ConfirmationStatus(str, Enum):
    """Status of payment confirmation."""
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class PaymentConfirmationHandler:
    """Handler for manual payment confirmation."""
    
    def __init__(self):
        pass
    
    def submit_confirmation(
        self,
        payment_id: str,
        proof_image: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict:
        """
        Enviar confirmación de pago para revisión manual.
        
        Args:
            payment_id: ID del pago
            proof_image: Base64 de la imagen de comprobante (opcional)
            notes: Notas adicionales
        
        Returns:
            Estado de la confirmación
        """
        try:
            from .billing_db import create_payment_confirmation, init_billing_db
            
            init_billing_db()
            confirmation_id = f"conf_{datetime.now().strftime('%Y%m%d%H%M%S')}_{payment_id}"
            
            confirmation_data = {
                'confirmation_id': confirmation_id,
                'payment_id': payment_id,
                'status': ConfirmationStatus.PENDING_REVIEW,
                'proof_image': proof_image,
                'notes': notes,
                'submitted_at': datetime.now().isoformat(),
            }
            
            confirmation = create_payment_confirmation(confirmation_data)
            
            if confirmation:
                return {
                    'success': True,
                    'confirmation': confirmation
                }
            else:
                return {
                    'success': False,
                    'error': 'Error al guardar la confirmación en base de datos'
                }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def approve_payment(
        self,
        payment_id: str,
        admin_id: str,
        notes: Optional[str] = None
    ) -> Dict:
        """
        Aprobar un pago manualmente.
        
        Args:
            payment_id: ID del pago
            admin_id: ID del admin que aprueba
            notes: Notas de aprobación
        
        Returns:
            Estado del pago actualizado
        """
        try:
            from .billing_db import (
                update_local_payment, update_payment_confirmation,
                get_local_payment_by_id, init_billing_db, create_subscription,
                create_invoice, add_invoice_item, update_invoice
            )
            from utils.tenant_db import update_tenant
            from .invoice_generator import InvoiceGenerator
            from datetime import datetime, timedelta
            
            init_billing_db()
            
            # Actualizar estado del pago
            payment = update_local_payment(payment_id, {
                'status': LocalPaymentStatus.CONFIRMED,
                'confirmed_at': datetime.now().isoformat()
            })
            
            if not payment:
                return {
                    'success': False,
                    'error': 'Pago no encontrado'
                }
            
            # Actualizar plan del tenant si el pago está asociado a una suscripción
            metadata = payment.get('metadata', {})
            plan_id = metadata.get('plan_id')
            tenant_id = payment.get('tenant_id')
            
            if plan_id and tenant_id:
                update_tenant(tenant_id, plan_id=plan_id)
                
                # Crear suscripción para el pago local
                subscription_id = f"sub_{datetime.now().strftime('%Y%m%d%H%M%S')}_{tenant_id}"
                
                # Calcular fechas basado en el ciclo
                billing_cycle = metadata.get('billing_cycle', 'monthly')
                start_date = datetime.now()
                if billing_cycle == 'yearly':
                    end_date = start_date + timedelta(days=365)
                else:
                    end_date = start_date + timedelta(days=30)
                
                subscription_data = {
                    'subscription_id': subscription_id,
                    'tenant_id': tenant_id,
                    'plan_id': plan_id,
                    'billing_cycle': billing_cycle,
                    'status': 'active',
                    'start_date': start_date.isoformat(),
                    'end_date': end_date.isoformat(),
                    'payment_method': payment.get('method'),
                    'payment_method_id': payment_id,
                    'amount': payment.get('amount')
                }
                
                create_subscription(subscription_data)
                
                # Generar factura para el pago local
                invoice_id = f"inv_{datetime.now().strftime('%Y%m%d%H%M%S')}_{tenant_id}"
                invoice_number = f"INV-{datetime.now().strftime('%Y%m%d')}-{tenant_id}"
                
                invoice_data = {
                    'invoice_id': invoice_id,
                    'tenant_id': tenant_id,
                    'subscription_id': subscription_id,
                    'invoice_number': invoice_number,
                    'subtotal': payment.get('amount'),
                    'tax_amount': 0,
                    'total': payment.get('amount'),
                    'currency': payment.get('currency', 'USD'),
                    'status': 'paid',
                    'paid_date': datetime.now().isoformat(),
                    'notes': f"Pago local {payment.get('method')} - {payment.get('reference')}"
                }
                
                created_invoice = create_invoice(invoice_data)
                
                if created_invoice:
                    # Agregar items a la factura
                    from .plans import PlanManager
                    plan_manager = PlanManager()
                    plan = plan_manager.get_plan(plan_id)
                    
                    if plan:
                        add_invoice_item(created_invoice['invoice_id'], {
                            'description': f"Suscripción {plan['name']} - {billing_cycle}",
                            'quantity': 1,
                            'unit_price': payment.get('amount'),
                            'total': payment.get('amount')
                        })
                    
                    # Generar PDF de la factura
                    try:
                        invoice_gen = InvoiceGenerator()
                        pdf_path = invoice_gen.generate_invoice_pdf(
                            invoice_id=invoice_id,
                            tenant_id=tenant_id,
                            subscription_id=subscription_id,
                            amount=payment.get('amount'),
                            currency=payment.get('currency', 'USD'),
                            due_date=datetime.now().isoformat(),
                            items=[{
                                'description': f"Suscripción {plan['name'] if plan else plan_id}",
                                'quantity': 1,
                                'unit_price': payment.get('amount'),
                                'total': payment.get('amount')
                            }],
                            notes=f"Pago local vía {payment.get('method')} - Ref: {payment.get('reference')}"
                        )
                        
                        # Actualizar factura con la ruta del PDF
                        update_invoice(invoice_id, {
                            'filepath': pdf_path,
                            'filename': os.path.basename(pdf_path)
                        })
                    except Exception as pdf_error:
                        print(f"Error generando PDF de factura: {pdf_error}")
            
            return {
                'success': True,
                'payment_id': payment_id,
                'status': LocalPaymentStatus.CONFIRMED,
                'approved_by': admin_id,
                'approved_at': datetime.now().isoformat(),
                'notes': notes,
                'message': 'Pago aprobado exitosamente'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def reject_payment(
        self,
        payment_id: str,
        admin_id: str,
        reason: str
    ) -> Dict:
        """
        Rechazar un pago manualmente.
        
        Args:
            payment_id: ID del pago
            admin_id: ID del admin que rechaza
            reason: Razón del rechazo
        
        Returns:
            Estado del pago actualizado
        """
        try:
            from .billing_db import update_local_payment, init_billing_db
            
            init_billing_db()
            
            payment = update_local_payment(payment_id, {
                'status': LocalPaymentStatus.REJECTED,
                'rejected_at': datetime.now().isoformat(),
                'rejection_reason': reason
            })
            
            if not payment:
                return {
                    'success': False,
                    'error': 'Pago no encontrado'
                }
            
            return {
                'success': True,
                'payment_id': payment_id,
                'status': LocalPaymentStatus.REJECTED,
                'rejected_by': admin_id,
                'rejected_at': datetime.now().isoformat(),
                'reason': reason,
                'message': 'Pago rechazado'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_pending_confirmations(self) -> Dict:
        """
        Obtener lista de confirmaciones pendientes de revisión.
        
        Returns:
            Lista de confirmaciones pendientes
        """
        try:
            from .billing_db import get_pending_confirmations, init_billing_db
            
            init_billing_db()
            confirmations = get_pending_confirmations()
            
            return {
                'success': True,
                'confirmations': confirmations
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_payment_history(
        self,
        tenant_id: Optional[str] = None,
        limit: int = 50
    ) -> Dict:
        """
        Obtener historial de pagos.
        
        Args:
            tenant_id: ID del tenant (opcional, para filtrar)
            limit: Límite de resultados
        
        Returns:
            Historial de pagos
        """
        # TODO: Implementar consulta a base de datos
        return {
            'success': False,
            'error': 'No implementado aún - requiere base de datos'
        }


# Singleton instance
_confirmation_handler: Optional[PaymentConfirmationHandler] = None


def get_confirmation_handler() -> PaymentConfirmationHandler:
    """Get or create the confirmation handler singleton."""
    global _confirmation_handler
    if _confirmation_handler is None:
        _confirmation_handler = PaymentConfirmationHandler()
    return _confirmation_handler
