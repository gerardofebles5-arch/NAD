"""
Motor Financiero - Agregados y Reportes
=======================================
Calcula agregados mensuales, agrupa por moneda, top proveedores.
"""
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from utils.supabase_client import get_supabase_client


class FinancialEngine:
    """Motor para cálculos financieros y agregados."""
    
    def __init__(self):
        self.supabase = get_supabase_client()
    
    def get_monthly_summary(self, cliente_id: str, year: int, month: int) -> Dict:
        """
        Obtiene resumen mensual de facturas.
        
        Args:
            cliente_id: ID del cliente en Supabase
            year: Año (ej. 2026)
            month: Mes (1-12)
        
        Returns:
            Diccionario con agregados del mes
        """
        if not self.supabase:
            return {'error': 'Supabase no configurado'}
        
        # Formatear periodo
        periodo = f"{year}-{month:02d}"
        
        # Obtener estado financiero del periodo
        result = self.supabase.table('estados_financieros').select('*').eq('cliente_id', cliente_id).eq('periodo', periodo).execute()
        
        if not result.data:
            return {
                'periodo': periodo,
                'total_facturado': 0,
                'iva_acumulado': 0,
                'num_facturas': 0,
                'por_moneda': {},
                'top_proveedores': {}
            }
        
        estado = result.data[0]
        
        return {
            'periodo': estado['periodo'],
            'total_facturado': float(estado['total_facturado']),
            'iva_acumulado': float(estado['iva_acumulado']),
            'num_facturas': estado['num_facturas'],
            'por_moneda': estado.get('por_moneda', {}),
            'top_proveedores': estado.get('top_proveedores', {}),
            'generado_en': estado['generado_en']
        }
    
    def get_invoices_by_period(self, cliente_id: str, year: int, month: int) -> List[Dict]:
        """
        Obtiene todas las facturas de un periodo.
        
        Args:
            cliente_id: ID del cliente en Supabase
            year: Año
            month: Mes
        
        Returns:
            Lista de facturas del periodo
        """
        if not self.supabase:
            return []
        
        # Calcular rango de fechas
        start_date = f"{year}-{month:02d}-01"
        if month == 12:
            end_date = f"{year+1}-01-01"
        else:
            end_date = f"{year}-{month+1:02d}-01"
        
        # Consultar facturas
        result = self.supabase.table('facturas').select('*').eq('cliente_id', cliente_id).gte('fecha', start_date).lt('fecha', end_date).execute()
        
        return result.data if result.data else []
    
    def get_top_providers(self, cliente_id: str, limit: int = 10) -> List[Dict]:
        """
        Obtiene top proveedores por monto total.
        
        Args:
            cliente_id: ID del cliente en Supabase
            limit: Número de proveedores a retornar
        
        Returns:
            Lista de proveedores ordenados por monto
        """
        if not self.supabase:
            return []
        
        # Obtener todas las facturas del cliente
        result = self.supabase.table('facturas').select('rif_emisor', 'razon_social', 'total').eq('cliente_id', cliente_id).execute()
        
        if not result.data:
            return []
        
        # Agrupar por proveedor
        providers = {}
        for factura in result.data:
            rif = factura['rif_emisor']
            nombre = factura['razon_social'] or rif
            total = float(factura['total']) or 0
            
            if rif not in providers:
                providers[rif] = {
                    'rif': rif,
                    'nombre': nombre,
                    'total': 0,
                    'num_facturas': 0
                }
            
            providers[rif]['total'] += total
            providers[rif]['num_facturas'] += 1
        
        # Ordenar por monto total
        sorted_providers = sorted(providers.values(), key=lambda x: x['total'], reverse=True)
        
        return sorted_providers[:limit]
    
    def get_currency_breakdown(self, cliente_id: str, year: int, month: int) -> Dict[str, float]:
        """
        Obtiene desglose por moneda de un periodo.
        
        Args:
            cliente_id: ID del cliente en Supabase
            year: Año
            month: Mes
        
        Returns:
            Diccionario {moneda: total}
        """
        if not self.supabase:
            return {}
        
        # Obtener estado financiero del periodo
        periodo = f"{year}-{month:02d}"
        result = self.supabase.table('estados_financieros').select('por_moneda').eq('cliente_id', cliente_id).eq('periodo', periodo).execute()
        
        if not result.data:
            return {}
        
        return result.data[0].get('por_moneda', {})
    
    def get_iva_summary(self, cliente_id: str, year: int, month: int) -> Dict:
        """
        Obtiene resumen de IVA de un periodo.
        
        Args:
            cliente_id: ID del cliente en Supabase
            year: Año
            month: Mes
        
        Returns:
            Diccionario con resumen de IVA
        """
        if not self.supabase:
            return {}
        
        # Obtener estado financiero del periodo
        periodo = f"{year}-{month:02d}"
        result = self.supabase.table('estados_financieros').select('iva_acumulado', 'total_facturado').eq('cliente_id', cliente_id).eq('periodo', periodo).execute()
        
        if not result.data:
            return {
                'iva_acumulado': 0,
                'total_facturado': 0,
                'porcentaje_iva': 0
            }
        
        estado = result.data[0]
        total = float(estado['total_facturado']) or 0
        iva = float(estado['iva_acumulado']) or 0
        
        return {
            'iva_acumulado': iva,
            'total_facturado': total,
            'porcentaje_iva': (iva / total * 100) if total > 0 else 0
        }
    
    def get_yearly_summary(self, cliente_id: str, year: int) -> Dict:
        """
        Obtiene resumen anual.
        
        Args:
            cliente_id: ID del cliente en Supabase
            year: Año
        
        Returns:
            Diccionario con agregados anuales
        """
        if not self.supabase:
            return {'error': 'Supabase no configurado'}
        
        # Obtener estados financieros de todos los meses del año
        periodos = [f"{year}-{month:02d}" for month in range(1, 13)]
        result = self.supabase.table('estados_financieros').select('*').eq('cliente_id', cliente_id).in_('periodo', periodos).execute()
        
        if not result.data:
            return {
                'year': year,
                'total_facturado': 0,
                'iva_acumulado': 0,
                'num_facturas': 0,
                'mensual': {}
            }
        
        # Agregar datos mensuales
        total_facturado = 0
        iva_acumulado = 0
        num_facturas = 0
        mensual = {}
        
        for estado in result.data:
            periodo = estado['periodo']
            mensual[periodo] = {
                'total_facturado': float(estado['total_facturado']),
                'iva_acumulado': float(estado['iva_acumulado']),
                'num_facturas': estado['num_facturas']
            }
            
            total_facturado += float(estado['total_facturado'])
            iva_acumulado += float(estado['iva_acumulado'])
            num_facturas += estado['num_facturas']
        
        return {
            'year': year,
            'total_facturado': total_facturado,
            'iva_acumulado': iva_acumulado,
            'num_facturas': num_facturas,
            'mensual': mensual
        }


def get_financial_engine() -> FinancialEngine:
    """Retorna instancia del motor financiero."""
    return FinancialEngine()
