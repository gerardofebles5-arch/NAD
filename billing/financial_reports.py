"""
Financial Reports Module for PINAD SaaS
Generates exportable financial reports.
"""

import os
import csv
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from io import StringIO


class FinancialReportGenerator:
    """Generates financial reports in various formats."""
    
    def __init__(self):
        pass
    
    def generate_revenue_report(
        self,
        start_date: str,
        end_date: str,
        format: str = 'csv'
    ) -> str:
        """
        Generate revenue report.
        
        Args:
            start_date: Start date (ISO format)
            end_date: End date (ISO format)
            format: Output format (csv, excel)
        
        Returns:
            File path or CSV content
        """
        from .billing_db import init_billing_db
        from .billing_db import _connect
        import threading
        
        _lock = threading.RLock()
        DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'output', 'nadscanner.db')
        
        @contextmanager
        def _connect():
            with _lock:
                import sqlite3
                conn = sqlite3.connect(DB_PATH, timeout=10)
                conn.row_factory = sqlite3.Row
                try:
                    yield conn
                    conn.commit()
                finally:
                    conn.close()
        
        init_billing_db()
        
        with _connect() as conn:
            # Get payments in date range
            rows = conn.execute(
                """SELECT * FROM local_payments 
                   WHERE created_at >= ? AND created_at <= ? AND status = 'completed'
                   ORDER BY created_at""",
                (start_date, end_date)
            ).fetchall()
            
            if format == 'csv':
                output = StringIO()
                writer = csv.writer(output)
                
                # Header
                writer.writerow([
                    'Payment ID', 'Tenant ID', 'Method', 'Amount', 'Currency',
                    'Status', 'Created At'
                ])
                
                # Data
                for row in rows:
                    writer.writerow([
                        row['payment_id'],
                        row['tenant_id'],
                        row['method'],
                        row['amount'],
                        row['currency'],
                        row['status'],
                        row['created_at']
                    ])
                
                return output.getvalue()
        
        return ""
    
    def generate_subscription_report(
        self,
        start_date: str,
        end_date: str,
        format: str = 'csv'
    ) -> str:
        """Generate subscription report."""
        from .billing_db import init_billing_db, _connect
        import threading
        
        _lock = threading.RLock()
        DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'output', 'nadscanner.db')
        
        @contextmanager
        def _connect():
            with _lock:
                import sqlite3
                conn = sqlite3.connect(DB_PATH, timeout=10)
                conn.row_factory = sqlite3.Row
                try:
                    yield conn
                    conn.commit()
                finally:
                    conn.close()
        
        init_billing_db()
        
        with _connect() as conn:
            rows = conn.execute(
                """SELECT * FROM subscriptions 
                   WHERE created_at >= ? AND created_at <= ?
                   ORDER BY created_at""",
                (start_date, end_date)
            ).fetchall()
            
            if format == 'csv':
                output = StringIO()
                writer = csv.writer(output)
                
                writer.writerow([
                    'Subscription ID', 'Tenant ID', 'Plan ID', 'Status',
                    'Amount', 'Start Date', 'End Date', 'Created At'
                ])
                
                for row in rows:
                    writer.writerow([
                        row['subscription_id'],
                        row['tenant_id'],
                        row['plan_id'],
                        row['status'],
                        row['amount'],
                        row['start_date'],
                        row['end_date'],
                        row['created_at']
                    ])
                
                return output.getvalue()
        
        return ""
    
    def generate_invoice_report(
        self,
        start_date: str,
        end_date: str,
        format: str = 'csv'
    ) -> str:
        """Generate invoice report."""
        from .billing_db import init_billing_db, _connect
        import threading
        
        _lock = threading.RLock()
        DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'output', 'nadscanner.db')
        
        @contextmanager
        def _connect():
            with _lock:
                import sqlite3
                conn = sqlite3.connect(DB_PATH, timeout=10)
                conn.row_factory = sqlite3.Row
                try:
                    yield conn
                    conn.commit()
                finally:
                    conn.close()
        
        init_billing_db()
        
        with _connect() as conn:
            rows = conn.execute(
                """SELECT * FROM billing_invoices 
                   WHERE created_at >= ? AND created_at <= ?
                   ORDER BY created_at""",
                (start_date, end_date)
            ).fetchall()
            
            if format == 'csv':
                output = StringIO()
                writer = csv.writer(output)
                
                writer.writerow([
                    'Invoice ID', 'Invoice Number', 'Tenant ID', 'Total',
                    'Currency', 'Status', 'Created At'
                ])
                
                for row in rows:
                    writer.writerow([
                        row['invoice_id'],
                        row['invoice_number'],
                        row['tenant_id'],
                        row['total'],
                        row['currency'],
                        row['status'],
                        row['created_at']
                    ])
                
                return output.getvalue()
        
        return ""
    
    def generate_comprehensive_report(
        self,
        start_date: str,
        end_date: str,
        format: str = 'csv'
    ) -> Dict[str, str]:
        """Generate comprehensive financial report."""
        return {
            'revenue': self.generate_revenue_report(start_date, end_date, format),
            'subscriptions': self.generate_subscription_report(start_date, end_date, format),
            'invoices': self.generate_invoice_report(start_date, end_date, format)
        }
