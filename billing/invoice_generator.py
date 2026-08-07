"""
Invoice Generator for PINAD SaaS
Generates invoices for subscriptions and one-time payments.
"""

import os
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from decimal import Decimal

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


class InvoiceGenerator:
    """Generates PDF invoices for SaaS subscriptions."""
    
    def __init__(self):
        self.company_info = {
            'name': os.environ.get('INVOICE_COMPANY_NAME', 'PINAD SaaS'),
            'address': os.environ.get('INVOICE_COMPANY_ADDRESS', ''),
            'rif': os.environ.get('INVOICE_COMPANY_RIF', ''),
            'email': os.environ.get('INVOICE_COMPANY_EMAIL', ''),
            'phone': os.environ.get('INVOICE_COMPANY_PHONE', ''),
        }
    
    def generate_invoice(
        self,
        invoice_id: str,
        tenant_id: str,
        tenant_name: str,
        tenant_email: str,
        items: List[Dict],
        subtotal: float,
        tax_amount: float,
        total: float,
        currency: str = 'USD',
        due_date: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict:
        """
        Generar una factura PDF.
        
        Args:
            invoice_id: ID de la factura
            tenant_id: ID del tenant
            tenant_name: Nombre del tenant
            tenant_email: Email del tenant
            items: Lista de items [{description, quantity, price, total}]
            subtotal: Subtotal
            tax_amount: Monto de impuesto
            total: Total
            currency: Moneda (USD, VES, etc.)
            due_date: Fecha de vencimiento (opcional)
            notes: Notas adicionales
        
        Returns:
            Ruta del archivo PDF generado
        """
        if not REPORTLAB_AVAILABLE:
            return {
                'success': False,
                'error': 'ReportLab no está instalado. Run: pip install reportlab'
            }
        
        try:
            # Crear nombre de archivo
            filename = f"invoice_{invoice_id}_{tenant_id}.pdf"
            output_dir = os.path.join(os.environ.get('TEMP_DIR', 'temp'), 'invoices')
            os.makedirs(output_dir, exist_ok=True)
            filepath = os.path.join(output_dir, filename)
            
            # Crear documento PDF
            doc = SimpleDocTemplate(
                filepath,
                pagesize=letter,
                rightMargin=72,
                leftMargin=72,
                topMargin=72,
                bottomMargin=18
            )
            
            # Estilos
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=24,
                textColor=colors.HexColor('#1a1a1a'),
                spaceAfter=30,
            )
            heading_style = ParagraphStyle(
                'CustomHeading',
                parent=styles['Heading2'],
                fontSize=14,
                textColor=colors.HexColor('#333333'),
                spaceAfter=12,
            )
            normal_style = styles['Normal']
            
            # Contenido del documento
            story = []
            
            # Título
            story.append(Paragraph(f"FACTURA #{invoice_id}", title_style))
            story.append(Spacer(1, 0.2 * inch))
            
            # Información de la empresa
            company_text = f"""
            <b>{self.company_info['name']}</b><br/>
            {self.company_info['address']}<br/>
            RIF: {self.company_info['rif']}<br/>
            Email: {self.company_info['email']}<br/>
            Tel: {self.company_info['phone']}
            """
            story.append(Paragraph(company_text, normal_style))
            story.append(Spacer(1, 0.3 * inch))
            
            # Información del cliente
            client_text = f"""
            <b>Facturar a:</b><br/>
            {tenant_name}<br/>
            Email: {tenant_email}<br/>
            Tenant ID: {tenant_id}
            """
            story.append(Paragraph(client_text, normal_style))
            story.append(Spacer(1, 0.3 * inch))
            
            # Fecha y vencimiento
            issue_date = datetime.now().strftime('%d/%m/%Y')
            due_date_str = due_date if due_date else (datetime.now() + timedelta(days=30)).strftime('%d/%m/%Y')
            
            date_text = f"""
            <b>Fecha de emisión:</b> {issue_date}<br/>
            <b>Fecha de vencimiento:</b> {due_date_str}
            """
            story.append(Paragraph(date_text, normal_style))
            story.append(Spacer(1, 0.3 * inch))
            
            # Tabla de items
            table_data = [['Descripción', 'Cantidad', 'Precio Unitario', 'Total']]
            for item in items:
                table_data.append([
                    item['description'],
                    str(item['quantity']),
                    f"{currency} {item['price']:.2f}",
                    f"{currency} {item['total']:.2f}"
                ])
            
            table = Table(table_data, colWidths=[3*inch, 1*inch, 1.5*inch, 1.5*inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4a90e2')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ]))
            story.append(table)
            story.append(Spacer(1, 0.3 * inch))
            
            # Totales
            totals_data = [
                ['', '', 'Subtotal:', f"{currency} {subtotal:.2f}"],
                ['', '', 'IVA (16%):', f"{currency} {tax_amount:.2f}"],
                ['', '', '<b>TOTAL:</b>', f"<b>{currency} {total:.2f}</b>"],
            ]
            
            totals_table = Table(totals_data, colWidths=[3*inch, 1*inch, 1.5*inch, 1.5*inch])
            totals_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
                ('FONTNAME', (2, 2), (-1, 2), 'Helvetica-Bold'),
                ('FONTSIZE', (2, 2), (-1, 2), 14),
                ('TEXTCOLOR', (2, 2), (-1, 2), colors.HexColor('#4a90e2')),
            ]))
            story.append(totals_table)
            
            # Notas
            if notes:
                story.append(Spacer(1, 0.5 * inch))
                story.append(Paragraph("<b>Notas:</b>", heading_style))
                story.append(Paragraph(notes, normal_style))
            
            # Generar PDF
            doc.build(story)
            
            return {
                'success': True,
                'filepath': filepath,
                'filename': filename
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def generate_subscription_invoice(
        self,
        invoice_id: str,
        tenant_id: str,
        tenant_name: str,
        tenant_email: str,
        plan_name: str,
        plan_price: float,
        billing_period: str = 'monthly',
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict:
        """
        Generar factura de suscripción.
        
        Args:
            invoice_id: ID de la factura
            tenant_id: ID del tenant
            tenant_name: Nombre del tenant
            tenant_email: Email del tenant
            plan_name: Nombre del plan
            plan_price: Precio del plan
            billing_period: Período de facturación (monthly, yearly)
            start_date: Fecha de inicio del período
            end_date: Fecha de fin del período
        
        Returns:
            Ruta del archivo PDF generado
        """
        # Calcular IVA (16% en Venezuela)
        tax_rate = 0.16
        tax_amount = plan_price * tax_rate
        total = plan_price + tax_amount
        
        # Crear items
        items = [{
            'description': f"Suscripción {plan_name} - {billing_period}",
            'quantity': 1,
            'price': plan_price,
            'total': plan_price
        }]
        
        # Fechas
        if not start_date:
            start_date = datetime.now().strftime('%d/%m/%Y')
        if not end_date:
            if billing_period == 'monthly':
                end_date = (datetime.now() + timedelta(days=30)).strftime('%d/%m/%Y')
            else:
                end_date = (datetime.now() + timedelta(days=365)).strftime('%d/%m/%Y')
        
        notes = f"Período de facturación: {start_date} - {end_date}"
        
        return self.generate_invoice(
            invoice_id=invoice_id,
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            tenant_email=tenant_email,
            items=items,
            subtotal=plan_price,
            tax_amount=tax_amount,
            total=total,
            currency='USD',
            notes=notes
        )


# Singleton instance
_invoice_generator: Optional[InvoiceGenerator] = None


def get_invoice_generator() -> InvoiceGenerator:
    """Get or create the invoice generator singleton."""
    global _invoice_generator
    if _invoice_generator is None:
        _invoice_generator = InvoiceGenerator()
    return _invoice_generator
