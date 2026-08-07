"""
Email Notifications Module for PINAD SaaS
Sends email notifications for billing events.
"""

import os
import json
from datetime import datetime
from typing import Dict, Optional, Any
from enum import Enum


class EmailType(str, Enum):
    """Types of email notifications."""
    PAYMENT_SUCCESS = "payment_success"
    PAYMENT_FAILED = "payment_failed"
    SUBSCRIPTION_RENEWED = "subscription_renewed"
    SUBSCRIPTION_EXPIRING = "subscription_expiring"
    SUBSCRIPTION_CANCELLED = "subscription_cancelled"
    INVOICE_AVAILABLE = "invoice_available"
    TRIAL_ENDING = "trial_ending"
    PLAN_CHANGED = "plan_changed"
    REFUND_PROCESSED = "refund_processed"


class EmailNotificationService:
    """Service for sending billing-related email notifications."""
    
    def __init__(self):
        self.smtp_server = os.getenv('SMTP_SERVER')
        self.smtp_port = int(os.getenv('SMTP_PORT', 587))
        self.smtp_username = os.getenv('SMTP_USERNAME')
        self.smtp_password = os.getenv('SMTP_PASSWORD')
        self.from_email = os.getenv('FROM_EMAIL', 'noreply@pinad.com')
        self.from_name = os.getenv('FROM_NAME', 'PINAD SaaS')
    
    def is_configured(self) -> bool:
        """Check if email service is configured."""
        return all([
            self.smtp_server,
            self.smtp_username,
            self.smtp_password
        ])
    
    def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None
    ) -> bool:
        """
        Send an email.
        
        Args:
            to_email: Recipient email
            subject: Email subject
            html_content: HTML content
            text_content: Plain text content (optional)
        
        Returns:
            True if sent successfully
        """
        if not self.is_configured():
            print(f"Email service not configured. Would send to: {to_email}")
            print(f"Subject: {subject}")
            return False
        
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{self.from_name} <{self.from_email}>"
            msg['To'] = to_email
            
            if text_content:
                msg.attach(MIMEText(text_content, 'plain'))
            
            msg.attach(MIMEText(html_content, 'html'))
            
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)
            
            return True
        except Exception as e:
            print(f"Error sending email: {e}")
            return False
    
    def send_payment_success(
        self,
        tenant_email: str,
        tenant_name: str,
        amount: float,
        currency: str,
        payment_method: str,
        invoice_number: Optional[str] = None
    ) -> bool:
        """Send payment success notification."""
        subject = f"Payment Successful - ${amount} {currency}"
        
        html_content = f"""
        <html>
        <body>
            <h2>Payment Successful</h2>
            <p>Dear {tenant_name},</p>
            <p>Your payment of <strong>${amount} {currency}</strong> has been successfully processed.</p>
            <p><strong>Payment Method:</strong> {payment_method}</p>
            {f"<p><strong>Invoice:</strong> {invoice_number}</p>" if invoice_number else ""}
            <p>Thank you for your payment!</p>
            <p>Best regards,<br>PINAD Team</p>
        </body>
        </html>
        """
        
        return self.send_email(tenant_email, subject, html_content)
    
    def send_payment_failed(
        self,
        tenant_email: str,
        tenant_name: str,
        amount: float,
        currency: str,
        error_message: str
    ) -> bool:
        """Send payment failed notification."""
        subject = f"Payment Failed - ${amount} {currency}"
        
        html_content = f"""
        <html>
        <body>
            <h2>Payment Failed</h2>
            <p>Dear {tenant_name},</p>
            <p>Your payment of <strong>${amount} {currency}</strong> could not be processed.</p>
            <p><strong>Error:</strong> {error_message}</p>
            <p>Please update your payment information and try again.</p>
            <p>Best regards,<br>PINAD Team</p>
        </body>
        </html>
        """
        
        return self.send_email(tenant_email, subject, html_content)
    
    def send_subscription_expiring(
        self,
        tenant_email: str,
        tenant_name: str,
        days_remaining: int,
        plan_name: str
    ) -> bool:
        """Send subscription expiring notification."""
        subject = f"Subscription Expiring in {days_remaining} Days"
        
        html_content = f"""
        <html>
        <body>
            <h2>Subscription Expiring Soon</h2>
            <p>Dear {tenant_name},</p>
            <p>Your <strong>{plan_name}</strong> subscription will expire in <strong>{days_remaining} days</strong>.</p>
            <p>To avoid service interruption, please renew your subscription.</p>
            <p><a href="#">Renew Now</a></p>
            <p>Best regards,<br>PINAD Team</p>
        </body>
        </html>
        """
        
        return self.send_email(tenant_email, subject, html_content)
    
    def send_invoice_available(
        self,
        tenant_email: str,
        tenant_name: str,
        invoice_number: str,
        amount: float,
        currency: str,
        due_date: str
    ) -> bool:
        """Send invoice available notification."""
        subject = f"Invoice Available - {invoice_number}"
        
        html_content = f"""
        <html>
        <body>
            <h2>New Invoice Available</h2>
            <p>Dear {tenant_name},</p>
            <p>Your invoice <strong>{invoice_number}</strong> for <strong>${amount} {currency}</strong> is now available.</p>
            <p><strong>Due Date:</strong> {due_date}</p>
            <p><a href="#">View Invoice</a></p>
            <p>Best regards,<br>PINAD Team</p>
        </body>
        </html>
        """
        
        return self.send_email(tenant_email, subject, html_content)
    
    def send_plan_changed(
        self,
        tenant_email: str,
        tenant_name: str,
        old_plan: str,
        new_plan: str,
        effective_date: str
    ) -> bool:
        """Send plan change notification."""
        subject = f"Plan Changed - {old_plan} to {new_plan}"
        
        html_content = f"""
        <html>
        <body>
            <h2>Plan Changed</h2>
            <p>Dear {tenant_name},</p>
            <p>Your plan has been changed from <strong>{old_plan}</strong> to <strong>{new_plan}</strong>.</p>
            <p><strong>Effective Date:</strong> {effective_date}</p>
            <p>Thank you for being a valued customer!</p>
            <p>Best regards,<br>PINAD Team</p>
        </body>
        </html>
        """
        
        return self.send_email(tenant_email, subject, html_content)
    
    def send_refund_processed(
        self,
        tenant_email: str,
        tenant_name: str,
        refund_amount: float,
        currency: str,
        refund_id: str
    ) -> bool:
        """Send refund processed notification."""
        subject = f"Refund Processed - {refund_id}"
        
        html_content = f"""
        <html>
        <body>
            <h2>Refund Processed</h2>
            <p>Dear {tenant_name},</p>
            <p>Your refund of <strong>${refund_amount} {currency}</strong> has been processed.</p>
            <p><strong>Refund ID:</strong> {refund_id}</p>
            <p>Please allow 5-10 business days for the refund to appear in your account.</p>
            <p>Best regards,<br>PINAD Team</p>
        </body>
        </html>
        """
        
        return self.send_email(tenant_email, subject, html_content)


# Singleton instance
_email_service = None


def get_email_service() -> EmailNotificationService:
    """Get the email notification service singleton."""
    global _email_service
    if _email_service is None:
        _email_service = EmailNotificationService()
    return _email_service
