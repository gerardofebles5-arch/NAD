"""
Stripe Client for PINAD SaaS
Handles Stripe Checkout sessions, customer management, and subscriptions.
"""

import os
import json
from typing import Dict, Optional, List
from datetime import datetime

try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    STRIPE_AVAILABLE = False


class StripeClient:
    """Client for Stripe API operations."""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Stripe client.
        
        Args:
            api_key: Stripe API key. If None, reads from STRIPE_API_KEY env var.
        """
        if not STRIPE_AVAILABLE:
            raise ImportError("stripe package not installed. Run: pip install stripe>=7.0.0")
        
        self.api_key = api_key or os.environ.get('STRIPE_API_KEY')
        if not self.api_key:
            raise ValueError("Stripe API key not provided. Set STRIPE_API_KEY environment variable.")
        
        stripe.api_key = self.api_key
        
        # Stripe price IDs for our plans (to be configured in Stripe Dashboard)
        self.price_ids = {
            'free': os.environ.get('STRIPE_PRICE_FREE', ''),
            'pro': os.environ.get('STRIPE_PRICE_PRO', ''),
            'enterprise': os.environ.get('STRIPE_PRICE_ENTERPRISE', ''),
        }
    
    def create_customer(self, email: str, name: str, metadata: Optional[Dict] = None) -> Dict:
        """
        Create a Stripe customer.
        
        Args:
            email: Customer email
            name: Customer name
            metadata: Additional metadata (e.g., tenant_id)
        
        Returns:
            Stripe customer object
        """
        try:
            customer = stripe.Customer.create(
                email=email,
                name=name,
                metadata=metadata or {}
            )
            return {
                'success': True,
                'customer': customer
            }
        except stripe.error.StripeError as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_customer(self, customer_id: str) -> Dict:
        """Retrieve a Stripe customer by ID."""
        try:
            customer = stripe.Customer.retrieve(customer_id)
            return {
                'success': True,
                'customer': customer
            }
        except stripe.error.StripeError as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def create_checkout_session(
        self,
        customer_id: str,
        plan_id: str,
        success_url: str,
        cancel_url: str,
        metadata: Optional[Dict] = None
    ) -> Dict:
        """
        Create a Stripe Checkout session for subscription.
        
        Args:
            customer_id: Stripe customer ID
            plan_id: Plan ID (free, pro, enterprise)
            success_url: URL to redirect after successful payment
            cancel_url: URL to redirect if payment is cancelled
            metadata: Additional metadata
        
        Returns:
            Checkout session URL
        """
        try:
            price_id = self.price_ids.get(plan_id)
            if not price_id:
                return {
                    'success': False,
                    'error': f'Price ID not configured for plan: {plan_id}'
                }
            
            session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=['card'],
                line_items=[{
                    'price': price_id,
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=success_url,
                cancel_url=cancel_url,
                metadata=metadata or {},
                allow_promotion_codes=True,
            )
            
            return {
                'success': True,
                'session_id': session.id,
                'session_url': session.url
            }
        except stripe.error.StripeError as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def create_one_time_checkout_session(
        self,
        customer_id: str,
        amount: int,
        success_url: str,
        cancel_url: str,
        currency: str = 'usd',
        metadata: Optional[Dict] = None
    ) -> Dict:
        """
        Create a one-time payment checkout session.
        
        Args:
            customer_id: Stripe customer ID
            amount: Amount in cents
            currency: Currency code (default: usd)
            success_url: URL to redirect after successful payment
            cancel_url: URL to redirect if payment is cancelled
            metadata: Additional metadata
        
        Returns:
            Checkout session URL
        """
        try:
            session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': currency,
                        'product_data': {
                            'name': 'PINAD SaaS Subscription',
                        },
                        'unit_amount': amount,
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=success_url,
                cancel_url=cancel_url,
                metadata=metadata or {},
            )
            
            return {
                'success': True,
                'session_id': session.id,
                'session_url': session.url
            }
        except stripe.error.StripeError as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def create_customer_portal_session(
        self,
        customer_id: str,
        return_url: str
    ) -> Dict:
        """
        Create a Stripe Customer Portal session for managing subscriptions.
        
        Args:
            customer_id: Stripe customer ID
            return_url: URL to redirect after portal session
        
        Returns:
            Portal session URL
        """
        try:
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )
            
            return {
                'success': True,
                'portal_url': session.url
            }
        except stripe.error.StripeError as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_subscription(self, subscription_id: str) -> Dict:
        """Retrieve a subscription by ID."""
        try:
            subscription = stripe.Subscription.retrieve(subscription_id)
            return {
                'success': True,
                'subscription': subscription
            }
        except stripe.error.StripeError as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def cancel_subscription(self, subscription_id: str, at_period_end: bool = True) -> Dict:
        """
        Cancel a subscription.
        
        Args:
            subscription_id: Stripe subscription ID
            at_period_end: If True, cancel at period end. If False, cancel immediately.
        
        Returns:
            Updated subscription object
        """
        try:
            subscription = stripe.Subscription.modify(
                subscription_id,
                cancel_at_period_end=at_period_end
            )
            return {
                'success': True,
                'subscription': subscription
            }
        except stripe.error.StripeError as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def update_subscription(
        self,
        subscription_id: str,
        new_price_id: str
    ) -> Dict:
        """
        Update a subscription to a new price (plan change).
        
        Args:
            subscription_id: Stripe subscription ID
            new_price_id: New Stripe price ID
        
        Returns:
            Updated subscription object
        """
        try:
            subscription = stripe.Subscription.retrieve(subscription_id)
            
            # Get the subscription item
            subscription_item = subscription['items']['data'][0]
            
            updated_subscription = stripe.Subscription.modify(
                subscription_id,
                items=[{
                    'id': subscription_item.id,
                    'price': new_price_id,
                }]
            )
            
            return {
                'success': True,
                'subscription': updated_subscription
            }
        except stripe.error.StripeError as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def list_customer_subscriptions(self, customer_id: str) -> Dict:
        """List all subscriptions for a customer."""
        try:
            subscriptions = stripe.Subscription.list(
                customer=customer_id,
                status='all',
                limit=10
            )
            return {
                'success': True,
                'subscriptions': subscriptions['data']
            }
        except stripe.error.StripeError as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def construct_webhook_event(self, payload: str, sig_header: str, webhook_secret: str) -> Dict:
        """
        Construct a webhook event from payload and signature.
        
        Args:
            payload: Raw request body
            sig_header: Stripe-Signature header
            webhook_secret: Stripe webhook secret
        
        Returns:
            Event object or error
        """
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
            return {
                'success': True,
                'event': event
            }
        except ValueError as e:
            # Invalid payload
            return {
                'success': False,
                'error': f'Invalid payload: {str(e)}'
            }
        except stripe.error.SignatureVerificationError as e:
            # Invalid signature
            return {
                'success': False,
                'error': f'Invalid signature: {str(e)}'
            }


# Singleton instance (initialized when needed)
_stripe_client: Optional[StripeClient] = None


def get_stripe_client() -> Optional[StripeClient]:
    """Get or create the Stripe client singleton."""
    global _stripe_client
    if _stripe_client is None:
        try:
            _stripe_client = StripeClient()
        except (ImportError, ValueError):
            # Stripe not configured
            _stripe_client = None
    return _stripe_client


def is_stripe_configured() -> bool:
    """Check if Stripe is properly configured."""
    return STRIPE_AVAILABLE and os.environ.get('STRIPE_API_KEY') is not None
