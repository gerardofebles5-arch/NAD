"""
Billing Module for PINAD SaaS
"""

from .plans import PlanManager
from .limits import LimitsChecker as PlanLimits
from .stripe_client import get_stripe_client, is_stripe_configured
from .webhooks import StripeWebhookHandler
from .local_payments import LocalPaymentsHandler as LocalPaymentHandler
from .payment_confirmation import PaymentConfirmationHandler
from .invoice_generator import InvoiceGenerator
from .recurring_billing import RecurringBillingHandler as RecurringBilling
from .analytics import BillingAnalytics
from .billing_db import (
    init_billing_db,
    create_subscription,
    get_subscription_by_id,
    get_subscriptions_by_tenant,
    update_subscription,
    list_all_subscriptions,
    create_invoice,
    get_invoice_by_id,
    get_invoices_by_tenant,
    update_invoice,
    list_all_invoices,
    add_invoice_item,
    get_invoice_items,
    create_local_payment,
    get_local_payment_by_id,
    get_local_payments_by_tenant,
    update_local_payment,
    list_all_local_payments,
    create_payment_confirmation,
    get_payment_confirmation_by_id,
    get_pending_confirmations,
    update_payment_confirmation,
    create_stripe_customer,
    get_stripe_customer_by_tenant,
    update_stripe_customer
)
from .subscription_renewal import get_subscription_renewal

__all__ = [
    'PlanManager',
    'PlanLimits',
    'get_stripe_client',
    'is_stripe_configured',
    'StripeWebhookHandler',
    'LocalPaymentHandler',
    'PaymentConfirmationHandler',
    'InvoiceGenerator',
    'get_recurring_billing_handler',
    'get_billing_analytics',
    'get_subscription_renewal',
    'init_billing_db',
    'create_subscription',
    'get_subscription_by_id',
    'get_subscriptions_by_tenant',
    'update_subscription',
    'list_all_subscriptions',
    'create_invoice',
    'get_invoice_by_id',
    'get_invoices_by_tenant',
    'update_invoice',
    'list_all_invoices',
    'add_invoice_item',
    'get_invoice_items',
    'create_local_payment',
    'get_local_payment_by_id',
    'get_local_payments_by_tenant',
    'update_local_payment',
    'list_all_local_payments',
    'create_payment_confirmation',
    'get_payment_confirmation_by_id',
    'get_pending_confirmations',
    'update_payment_confirmation',
    'create_stripe_customer',
    'get_stripe_customer_by_tenant',
    'get_stripe_customer_by_id',
    'update_stripe_customer'
]
