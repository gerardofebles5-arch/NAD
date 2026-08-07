"""
Script de prueba para el sistema de Billing de PINAD SaaS
Verifica que todas las funcionalidades del sistema funcionen correctamente.
"""

import os
import sys
from datetime import datetime, timedelta

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from billing import (
    PlanManager,
    PlanLimits,
    init_billing_db,
    create_subscription,
    list_all_subscriptions,
    create_invoice,
    list_all_invoices,
    create_local_payment,
    list_all_local_payments,
    BillingAnalytics,
    get_subscription_renewal
)
from utils.tenant_db import init_tenant_db, create_tenant, list_tenants


def test_plans():
    """Prueba el sistema de planes."""
    print("\n=== Test: Sistema de Planes ===")
    
    plan_manager = PlanManager()
    plans = plan_manager.get_all_plans()
    
    print(f"✓ Planes disponibles: {len(plans)}")
    for plan_id, plan in plans.items():
        print(f"  - {plan['name']}: ${plan['price_usd']}/mes")
    
    # Verificar límites
    limits = PlanLimits()
    pro_limits = limits.get_tenant_limits('1', 'pro')
    print(f"✓ Límites del plan Pro: {pro_limits}")
    
    return True


def test_database():
    """Prueba la base de datos de billing."""
    print("\n=== Test: Base de Datos ===")
    
    init_billing_db()
    print("✓ Base de datos inicializada")
    
    subscriptions = list_all_subscriptions()
    print(f"✓ Suscripciones en BD: {len(subscriptions)}")
    
    invoices = list_all_invoices()
    print(f"✓ Facturas en BD: {len(invoices)}")
    
    payments = list_all_local_payments()
    print(f"✓ Pagos locales en BD: {len(payments)}")
    
    return True


def test_subscription_creation():
    """Prueba la creación de suscripciones."""
    print("\n=== Test: Creación de Suscripción ===")
    
    init_tenant_db()
    
    # Crear tenant de prueba único
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    test_tenant = create_tenant(
        name=f'Test Tenant {timestamp}',
        email=f'test{timestamp}@example.com',
        plan_id='free'
    )
    print(f"✓ Tenant de prueba creado: {test_tenant['id']}")
    
    # Crear suscripción de prueba
    subscription_id = f"sub_test_{timestamp}"
    subscription_data = {
        'subscription_id': subscription_id,
        'tenant_id': int(test_tenant['id']),
        'plan_id': 'pro',
        'billing_cycle': 'monthly',
        'status': 'active',
        'start_date': datetime.now().isoformat(),
        'end_date': (datetime.now() + timedelta(days=30)).isoformat(),
        'payment_method': 'test',
        'payment_method_id': 'test_method',
        'amount': 10.0
    }
    
    subscription = create_subscription(subscription_data)
    if subscription:
        print(f"✓ Suscripción creada: {subscription_id}")
        print(f"  - Tenant ID: {subscription['tenant_id']}")
        print(f"  - Plan: {subscription['plan_id']}")
        print(f"  - Estado: {subscription['status']}")
    else:
        print(f"✗ Error creando suscripción")
        return False
    
    return True


def test_invoice_creation():
    """Prueba la creación de facturas."""
    print("\n=== Test: Creación de Factura ===")
    
    init_tenant_db()
    init_billing_db()
    
    # Crear tenant de prueba único
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    test_tenant = create_tenant(
        name=f'Test Tenant Invoice {timestamp}',
        email=f'invoice{timestamp}@example.com',
        plan_id='free'
    )
    
    # Crear factura de prueba
    invoice_id = f"inv_test_{timestamp}"
    invoice_data = {
        'invoice_id': invoice_id,
        'tenant_id': int(test_tenant['id']),
        'subscription_id': 'sub_test',
        'invoice_number': f"TEST-{timestamp}",
        'subtotal': 10.0,
        'tax_amount': 0,
        'total': 10.0,
        'currency': 'USD',
        'status': 'pending',
        'notes': 'Factura de prueba'
    }
    
    invoice = create_invoice(invoice_data)
    if invoice:
        print(f"✓ Factura creada: {invoice_id}")
        print(f"  - Número: {invoice['invoice_number']}")
        print(f"  - Total: ${invoice['total']} {invoice['currency']}")
        print(f"  - Estado: {invoice['status']}")
    else:
        print(f"✗ Error creando factura")
        return False
    
    return True


def test_local_payment():
    """Prueba la creación de pagos locales."""
    print("\n=== Test: Pago Local ===")
    
    init_tenant_db()
    init_billing_db()
    
    # Crear tenant de prueba único
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    test_tenant = create_tenant(
        name=f'Test Tenant Payment {timestamp}',
        email=f'payment{timestamp}@example.com',
        plan_id='free'
    )
    
    # Crear pago local de prueba
    payment_id = f"pm_test_{timestamp}"
    payment_data = {
        'payment_id': payment_id,
        'tenant_id': int(test_tenant['id']),
        'method': 'pagomovil',
        'amount': 100.0,
        'currency': 'VES',
        'status': 'pending',
        'reference': '1234',
        'details': '{"bank": "Banco de Venezuela", "phone": "04141234567"}',
        'metadata': {'plan_id': 'pro'},
        'expires_at': (datetime.now() + timedelta(hours=24)).isoformat()
    }
    
    payment = create_local_payment(payment_data)
    if payment:
        print(f"✓ Pago local creado: {payment_id}")
        print(f"  - Método: {payment['method']}")
        print(f"  - Monto: {payment['amount']} {payment['currency']}")
        print(f"  - Estado: {payment['status']}")
    else:
        print(f"✗ Error creando pago local")
        return False
    
    return True


def test_analytics():
    """Prueba el sistema de analytics."""
    print("\n=== Test: Analytics ===")
    
    init_billing_db()
    
    analytics = get_billing_analytics()
    
    # Calcular MRR
    mrr = analytics.calculate_mrr()
    print(f"✓ MRR calculado: ${mrr['total_mrr']}")
    print(f"  - Suscripciones activas: {mrr['active_subscriptions']}")
    
    # Calcular churn
    churn = analytics.calculate_churn_rate()
    print(f"✓ Churn rate: {churn['churn_rate']}%")
    print(f"  - Cancelados en período: {churn['cancelled_in_period']}")
    
    # Calcular ARPU
    subscriptions = list_all_subscriptions()
    arpu = analytics.calculate_arpu(subscriptions, 1)
    print(f"✓ ARPU: ${arpu['arpu']}")
    print(f"  - Usuarios activos: {arpu['active_users']}")
    
    # Analytics completos
    comprehensive = analytics.get_comprehensive_analytics()
    print(f"✓ Analytics completos generados")
    print(f"  - MRR: ${comprehensive['mrr']['total_mrr']}")
    print(f"  - Churn: {comprehensive['churn']['churn_rate']}%")
    print(f"  - LTV: ${comprehensive['ltv']['ltv']}")
    
    return True


def test_subscription_renewal():
    """Prueba el sistema de renovación de suscripciones."""
    print("\n=== Test: Renovación de Suscripciones ===")
    
    init_billing_db()
    
    renewal = get_subscription_renewal()
    
    # Verificar suscripciones por expirar en 7 días
    expiring = renewal.check_expiring_subscriptions(days_before=7)
    print(f"✓ Suscripciones expirando en 7 días: {len(expiring)}")
    
    # Verificar suscripciones expiradas
    expired = renewal.check_expired_subscriptions()
    print(f"✓ Suscripciones ya expiradas: {len(expired)}")
    
    # Ejecutar mantenimiento
    maintenance = renewal.run_daily_maintenance()
    print(f"✓ Mantenimiento ejecutado:")
    print(f"  - Expiradas procesadas: {maintenance['expired_processed']['processed']}")
    print(f"  - Notificaciones enviadas: {maintenance['notifications_sent']['sent']}")
    
    return True


def run_all_tests():
    """Ejecuta todas las pruebas."""
    print("=" * 60)
    print("SISTEMA DE BILLING - PRUEBAS INTEGRACIÓN")
    print("=" * 60)
    
    tests = [
        ("Base de Datos", test_database),
        ("Sistema de Planes", test_plans),
        ("Creación de Suscripción", test_subscription_creation),
        ("Creación de Factura", test_invoice_creation),
        ("Pago Local", test_local_payment),
        ("Analytics", test_analytics),
        ("Renovación de Suscripciones", test_subscription_renewal),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"✗ Error en {name}: {e}")
            results.append((name, False))
    
    # Resumen
    print("\n" + "=" * 60)
    print("RESUMEN DE PRUEBAS")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASÓ" if result else "✗ FALLÓ"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} pruebas pasaron")
    
    if passed == total:
        print("\n🎉 Todas las pruebas pasaron exitosamente!")
    else:
        print(f"\n⚠️  {total - passed} prueba(s) fallaron")
    
    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
