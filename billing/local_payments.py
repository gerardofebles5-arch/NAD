"""
Local Payments Handler for PINAD SaaS
Handles Venezuela-specific payment methods: PagoMóvil, Zelle, USDT (Binance Pay).
"""

import os
import json
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from enum import Enum


class LocalPaymentMethod(str, Enum):
    """Local payment methods available."""
    PAGOMOVIL = "pagomovil"
    ZELLE = "zelle"
    USDT = "usdt"


class LocalPaymentStatus(str, Enum):
    """Status of local payments."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EXPIRED = "expired"


class LocalPaymentsHandler:
    """Handler for local payment methods (PagoMóvil, Zelle, USDT)."""
    
    def __init__(self):
        # Configuration for each payment method
        self.config = {
            LocalPaymentMethod.PAGOMOVIL: {
                'bank_name': os.environ.get('PAGOMOVIL_BANK', 'Banco de Venezuela'),
                'phone': os.environ.get('PAGOMOVIL_PHONE', ''),
                'ci': os.environ.get('PAGOMOVIL_CI', ''),
            },
            LocalPaymentMethod.ZELLE: {
                'email': os.environ.get('ZELLE_EMAIL', ''),
                'name': os.environ.get('ZELLE_NAME', 'PINAD SaaS'),
            },
            LocalPaymentMethod.USDT: {
                'wallet_address': os.environ.get('USDT_WALLET', ''),
                'network': os.environ.get('USDT_NETWORK', 'TRC20'),
                'binance_pay_id': os.environ.get('BINANCE_PAY_ID', ''),
            }
        }
    
    def initiate_pagomovil_payment(
        self,
        tenant_id: str,
        amount: float,
        phone: str,
        reference: str,
        metadata: Optional[Dict] = None
    ) -> Dict:
        """
        Iniciar un pago PagoMóvil.
        
        Args:
            tenant_id: ID del tenant
            amount: Monto en VES
            phone: Teléfono del pagador
            reference: Número de referencia del pago
            metadata: Metadatos adicionales
        
        Returns:
            Información del pago iniciado
        """
        try:
            from .billing_db import create_local_payment, init_billing_db
            
            init_billing_db()
            payment_id = f"pm_{datetime.now().strftime('%Y%m%d%H%M%S')}_{tenant_id}"
            
            # Validar formato de referencia (generalmente 4-6 dígitos)
            if not reference.isdigit() or len(reference) < 4:
                return {
                    'success': False,
                    'error': 'La referencia debe ser numérica y tener al menos 4 dígitos'
                }
            
            details = {
                'bank': self.config[LocalPaymentMethod.PAGOMOVIL]['bank_name'],
                'phone': self.config[LocalPaymentMethod.PAGOMOVIL]['phone'],
                'ci': self.config[LocalPaymentMethod.PAGOMOVIL]['ci'],
                'payer_phone': phone,
                'reference': reference,
            }
            
            payment_data = {
                'payment_id': payment_id,
                'tenant_id': int(tenant_id),
                'method': LocalPaymentMethod.PAGOMOVIL,
                'amount': amount,
                'currency': 'VES',
                'status': LocalPaymentStatus.PENDING,
                'reference': reference,
                'details': json.dumps(details),
                'metadata': metadata or {},
                'expires_at': (datetime.now() + timedelta(hours=24)).isoformat(),
            }
            
            payment = create_local_payment(payment_data)
            
            if payment:
                payment['details'] = details
                return {
                    'success': True,
                    'payment': payment
                }
            else:
                return {
                    'success': False,
                    'error': 'Error al guardar el pago en base de datos'
                }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def initiate_zelle_payment(
        self,
        tenant_id: str,
        amount_usd: float,
        payer_email: str,
        confirmation_number: str,
        metadata: Optional[Dict] = None
    ) -> Dict:
        """
        Iniciar un pago Zelle.
        
        Args:
            tenant_id: ID del tenant
            amount_usd: Monto en USD
            payer_email: Email del pagador
            confirmation_number: Número de confirmación de Zelle
            metadata: Metadatos adicionales
        
        Returns:
            Información del pago iniciado
        """
        try:
            from .billing_db import create_local_payment, init_billing_db
            
            init_billing_db()
            payment_id = f"zelle_{datetime.now().strftime('%Y%m%d%H%M%S')}_{tenant_id}"
            
            details = {
                'recipient_email': self.config[LocalPaymentMethod.ZELLE]['email'],
                'recipient_name': self.config[LocalPaymentMethod.ZELLE]['name'],
                'payer_email': payer_email,
                'confirmation_number': confirmation_number,
            }
            
            payment_data = {
                'payment_id': payment_id,
                'tenant_id': int(tenant_id),
                'method': LocalPaymentMethod.ZELLE,
                'amount': amount_usd,
                'currency': 'USD',
                'status': LocalPaymentStatus.PENDING,
                'reference': confirmation_number,
                'details': json.dumps(details),
                'metadata': metadata or {},
                'expires_at': (datetime.now() + timedelta(hours=24)).isoformat(),
            }
            
            payment = create_local_payment(payment_data)
            
            if payment:
                payment['details'] = details
                return {
                    'success': True,
                    'payment': payment
                }
            else:
                return {
                    'success': False,
                    'error': 'Error al guardar el pago en base de datos'
                }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def initiate_usdt_payment(
        self,
        tenant_id: str,
        amount_usdt: float,
        network: str = 'TRC20',
        tx_hash: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> Dict:
        """
        Iniciar un pago USDT (Binance Pay o transferencia directa).
        
        Args:
            tenant_id: ID del tenant
            amount_usdt: Monto en USDT
            network: Red de blockchain (TRC20, ERC20, BEP20)
            tx_hash: Hash de transacción (si ya se realizó)
            metadata: Metadatos adicionales
        
        Returns:
            Información del pago iniciado
        """
        try:
            from .billing_db import create_local_payment, init_billing_db
            
            init_billing_db()
            payment_id = f"usdt_{datetime.now().strftime('%Y%m%d%H%M%S')}_{tenant_id}"
            
            details = {
                'wallet_address': self.config[LocalPaymentMethod.USDT]['wallet_address'],
                'network': network,
                'binance_pay_id': self.config[LocalPaymentMethod.USDT]['binance_pay_id'],
                'tx_hash': tx_hash,
            }
            
            payment_data = {
                'payment_id': payment_id,
                'tenant_id': int(tenant_id),
                'method': LocalPaymentMethod.USDT,
                'amount': amount_usdt,
                'currency': 'USDT',
                'status': LocalPaymentStatus.PENDING,
                'reference': tx_hash,
                'details': json.dumps(details),
                'metadata': metadata or {},
                'expires_at': (datetime.now() + timedelta(hours=24)).isoformat(),
            }
            
            payment = create_local_payment(payment_data)
            
            if payment:
                payment['details'] = details
                return {
                    'success': True,
                    'payment': payment
                }
            else:
                return {
                    'success': False,
                    'error': 'Error al guardar el pago en base de datos'
                }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_payment_info(self, payment_id: str) -> Dict:
        """
        Obtener información de un pago local.
        
        Args:
            payment_id: ID del pago
        
        Returns:
            Información del pago
        """
        try:
            from .billing_db import get_local_payment_by_id, init_billing_db
            
            init_billing_db()
            payment = get_local_payment_by_id(payment_id)
            
            if payment:
                return {
                    'success': True,
                    'payment': payment
                }
            else:
                return {
                    'success': False,
                    'error': 'Pago no encontrado'
                }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def list_pending_payments(self, tenant_id: Optional[str] = None) -> Dict:
        """
        Listar pagos pendientes.
        
        Args:
            tenant_id: ID del tenant (opcional, para filtrar)
        
        Returns:
            Lista de pagos pendientes
        """
        try:
            from .billing_db import get_local_payments_by_tenant, list_all_local_payments, init_billing_db
            
            init_billing_db()
            
            if tenant_id:
                payments = get_local_payments_by_tenant(int(tenant_id), status='pending')
            else:
                payments = list_all_local_payments(status='pending')
            
            return {
                'success': True,
                'payments': payments
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_payment_methods_info(self) -> Dict:
        """
        Obtener información de los métodos de pago disponibles.
        
        Returns:
            Información de configuración de cada método
        """
        return {
            'success': True,
            'methods': {
                LocalPaymentMethod.PAGOMOVIL: {
                    'name': 'PagoMóvil',
                    'currency': 'VES',
                    'bank': self.config[LocalPaymentMethod.PAGOMOVIL]['bank_name'],
                    'phone': self.config[LocalPaymentMethod.PAGOMOVIL]['phone'],
                    'ci': self.config[LocalPaymentMethod.PAGOMOVIL]['ci'],
                    'available': bool(self.config[LocalPaymentMethod.PAGOMOVIL]['phone']),
                },
                LocalPaymentMethod.ZELLE: {
                    'name': 'Zelle',
                    'currency': 'USD',
                    'email': self.config[LocalPaymentMethod.ZELLE]['email'],
                    'name': self.config[LocalPaymentMethod.ZELLE]['name'],
                    'available': bool(self.config[LocalPaymentMethod.ZELLE]['email']),
                },
                LocalPaymentMethod.USDT: {
                    'name': 'USDT (Tether)',
                    'currency': 'USDT',
                    'wallet_address': self.config[LocalPaymentMethod.USDT]['wallet_address'],
                    'network': self.config[LocalPaymentMethod.USDT]['network'],
                    'binance_pay_id': self.config[LocalPaymentMethod.USDT]['binance_pay_id'],
                    'available': bool(self.config[LocalPaymentMethod.USDT]['wallet_address']),
                },
            }
        }


# Singleton instance
_local_payments_handler: Optional[LocalPaymentsHandler] = None


def get_local_payments_handler() -> LocalPaymentsHandler:
    """Get or create the local payments handler singleton."""
    global _local_payments_handler
    if _local_payments_handler is None:
        _local_payments_handler = LocalPaymentsHandler()
    return _local_payments_handler
