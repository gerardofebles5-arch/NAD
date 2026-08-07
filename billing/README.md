# Sistema de Billing - PINAD SaaS

Sistema completo de monetización multi-tenant con soporte para pagos con tarjeta (Stripe) y pagos locales venezolanos (PagoMóvil, Zelle, USDT).

## 📋 Tabla de Contenidos

- [Características](#características)
- [Arquitectura](#arquitectura)
- [Configuración](#configuración)
- [Uso de la API](#uso-de-la-api)
- [Flujos de Pago](#flujos-de-pago)
- [Mantenimiento](#mantenimiento)
- [Estructura de Base de Datos](#estructura-de-base-de-datos)

## 🚀 Características

### Planes y Precios
- **Free**: $0/mes - 1 usuario, 100 escaneos/mes
- **Pro**: $10/mes - 5 usuarios, 500 escaneos/mes
- **Enterprise**: $50/mes - 20 usuarios, ilimitado

### Métodos de Pago
- **Stripe**: Pagos con tarjeta (Visa, Mastercard, American Express)
- **PagoMóvil**: Transferencias bancarias venezolanas
- **Zelle**: Pagos por email
- **USDT**: Criptomonedas (TRC20, ERC20, Binance Pay)

### Funcionalidades
- ✅ Checkout seguro con Stripe
- ✅ Portal de cliente para gestionar suscripciones
- ✅ Confirmación manual de pagos locales
- ✅ Generación automática de facturas PDF
- ✅ Analytics en tiempo real (MRR, churn, LTV)
- ✅ Renovación automática de suscripciones
- ✅ Gestión de límites de uso por plan
- ✅ Webhooks de Stripe integrados

## 🏗️ Arquitectura

```
billing/
├── __init__.py                 # Módulo principal
├── plans.py                    # Definición de planes
├── limits.py                   # Verificador de límites
├── stripe_client.py            # Cliente Stripe
├── webhooks.py                 # Manejador de webhooks
├── local_payments.py           # Pagos locales
├── payment_confirmation.py     # Confirmación de pagos
├── invoice_generator.py        # Generador de facturas
├── recurring_billing.py        # Facturación recurrente
├── analytics.py                # Métricas SaaS
├── billing_db.py               # Base de datos
└── subscription_renewal.py     # Renovación automática
```

## ⚙️ Configuración

### 1. Variables de Entorno

Copia `.env.example` a `.env` y configura las siguientes variables:

```bash
# Stripe
STRIPE_API_KEY=sk_test_your_api_key
STRIPE_WEBHOOK_SECRET=whsec_your_webhook_secret
STRIPE_PRICE_PRO=price_your_pro_price_id
STRIPE_PRICE_ENTERPRISE=price_your_enterprise_price_id

# Pagos Locales
PAGOMOVIL_BANK=Banco de Venezuela
PAGOMOVIL_PHONE=04141234567
PAGOMOVIL_CI=12345678

ZELLE_EMAIL=pagos@pinad-saas.com
ZELLE_NAME=PINAD SaaS

USDT_WALLET=0x1234567890abcdef1234567890abcdef12345678
USDT_NETWORK=TRC20
BINANCE_PAY_ID=your_binance_pay_id

# Facturación
INVOICE_COMPANY_NAME=PINAD SaaS C.A.
INVOICE_COMPANY_ADDRESS=Av. Principal, Edificio A, Piso 5
INVOICE_COMPANY_RIF=J-12345678-9
INVOICE_COMPANY_EMAIL=facturacion@pinad-saas.com
```

### 2. Configurar Webhook de Stripe

1. Ve al Dashboard de Stripe → Developers → Webhooks
2. Crea un webhook apuntando a: `https://tu-dominio.com/billing/stripe/webhook`
3. Selecciona los eventos:
   - `checkout.session.completed`
   - `invoice.paid`
   - `invoice.payment_failed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
4. Copia el webhook secret a `STRIPE_WEBHOOK_SECRET`

### 3. Configurar Cron Job

Para el mantenimiento diario de suscripciones:

```bash
# Ejecutar todos los días a las 00:00
0 0 * * * curl -X POST https://tu-dominio.com/billing/maintenance
```

## 📡 Uso de la API

### Obtener Planes Disponibles

```bash
GET /billing/plans
```

**Respuesta:**
```json
{
  "success": true,
  "plans": [
    {
      "id": "free",
      "name": "Plan Gratuito",
      "price_usd": 0,
      "max_users": 1,
      "max_scans_per_month": 100,
      "features": ["Escaneo básico", "Soporte por email"]
    },
    {
      "id": "pro",
      "name": "Plan Profesional",
      "price_usd": 10,
      "max_users": 5,
      "max_scans_per_month": 500,
      "features": ["Todo lo de Free", "Exportación PDF", "API access"]
    }
  ]
}
```

### Iniciar Checkout con Stripe

```bash
POST /billing/stripe/checkout
Content-Type: application/json

{
  "tenant_id": "1",
  "plan_id": "pro",
  "billing_cycle": "monthly",
  "success_url": "https://app.pinad-saas.com/success",
  "cancel_url": "https://app.pinad-saas.com/cancel"
}
```

**Respuesta:**
```json
{
  "success": true,
  "checkout_url": "https://checkout.stripe.com/c/pay/..."
}
```

### Iniciar Pago PagoMóvil

```bash
POST /billing/local/pagomovil
Content-Type: application/json

{
  "tenant_id": "1",
  "amount": 100,
  "phone": "04141234567",
  "reference": "1234",
  "metadata": {
    "plan_id": "pro",
    "billing_cycle": "monthly"
  }
}
```

**Respuesta:**
```json
{
  "success": true,
  "payment": {
    "payment_id": "pm_20240801120000_1",
    "method": "pagomovil",
    "status": "pending",
    "details": {
      "bank": "Banco de Venezuela",
      "phone": "04141234567",
      "ci": "12345678"
    }
  }
}
```

### Enviar Confirmación de Pago

```bash
POST /billing/local/confirm
Content-Type: application/json

{
  "payment_id": "pm_20240801120000_1",
  "proof_image": "data:image/jpeg;base64,...",
  "notes": "Pago realizado el 01/08/2024"
}
```

### Aprobar Pago (Admin)

```bash
POST /billing/local/approve
Content-Type: application/json

{
  "payment_id": "pm_20240801120000_1",
  "admin_id": "1",
  "notes": "Pago verificado en banco"
}
```

### Obtener Analytics

```bash
GET /billing/analytics
```

**Respuesta:**
```json
{
  "success": true,
  "analytics": {
    "mrr": {
      "total_mrr": 500.00,
      "mrr_by_plan": {
        "pro": 200.00,
        "enterprise": 300.00
      }
    },
    "churn": {
      "churn_rate": 5.2,
      "active_at_start": 100,
      "cancelled_in_period": 5
    },
    "arpu": {
      "arpu": 25.00,
      "total_revenue": 500.00,
      "active_users": 20
    },
    "ltv": {
      "ltv": 480.77
    }
  }
}
```

## 💳 Flujos de Pago

### Flujo de Pago con Stripe

```
1. Usuario → POST /billing/stripe/checkout
   ↓
2. Sistema → Crea sesión Stripe con metadata (tenant_id, plan_id)
   ↓
3. Usuario → Completa pago en Stripe Checkout
   ↓
4. Stripe → Webhook checkout.session.completed
   ↓
5. Sistema → Crea suscripción en BD
   ↓
6. Sistema → Activa plan del tenant
   ↓
7. Sistema → Guarda mapeo Stripe customer
```

### Flujo de Pago Local

```
1. Usuario → POST /billing/local/pagomovil
   ↓
2. Sistema → Crea pago en estado "pending"
   ↓
3. Usuario → Realiza transferencia bancaria
   ↓
4. Usuario → POST /billing/local/confirm (con comprobante)
   ↓
5. Admin → POST /billing/local/approve
   ↓
6. Sistema → Actualiza pago a "confirmed"
   ↓
7. Sistema → Crea suscripción en BD
   ↓
8. Sistema → Activa plan del tenant
   ↓
9. Sistema → Genera factura PDF
```

### Flujo de Facturación Automática

```
1. Stripe → Cobra suscripción mensual
   ↓
2. Stripe → Webhook invoice.paid
   ↓
3. Sistema → Extiende fecha de fin de suscripción
   ↓
4. Sistema → Crea factura en BD
   ↓
5. Sistema → Genera factura PDF
   ↓
6. Sistema → Actualiza factura con ruta del PDF
```

## 🔧 Mantenimiento

### Ejecutar Mantenimiento Manual

```bash
POST /billing/maintenance
```

**Tareas ejecutadas:**
- Procesar suscripciones expiradas (downgradear a free)
- Enviar notificaciones de expiración inminente (7 días)
- Verificar suscripciones por vencer

### Automatizar con Cron

```bash
# Agregar a crontab
crontab -e

# Ejecutar todos los días a las 00:00
0 0 * * * curl -X POST https://tu-dominio.com/billing/maintenance
```

## 🗄️ Estructura de Base de Datos

### Tabla: subscriptions
```sql
CREATE TABLE subscriptions (
    id INTEGER PRIMARY KEY,
    subscription_id TEXT UNIQUE,
    tenant_id INTEGER,
    plan_id TEXT,
    billing_cycle TEXT,
    status TEXT,
    start_date TEXT,
    end_date TEXT,
    payment_method TEXT,
    payment_method_id TEXT,
    amount REAL,
    created_at TEXT,
    updated_at TEXT,
    cancelled_at TEXT,
    cancel_at_period_end INTEGER
);
```

### Tabla: invoices
```sql
CREATE TABLE invoices (
    id INTEGER PRIMARY KEY,
    invoice_id TEXT UNIQUE,
    tenant_id INTEGER,
    subscription_id TEXT,
    invoice_number TEXT,
    subtotal REAL,
    tax_amount REAL,
    total REAL,
    currency TEXT,
    status TEXT,
    due_date TEXT,
    paid_date TEXT,
    filepath TEXT,
    filename TEXT,
    notes TEXT,
    created_at TEXT,
    updated_at TEXT
);
```

### Tabla: local_payments
```sql
CREATE TABLE local_payments (
    id INTEGER PRIMARY KEY,
    payment_id TEXT UNIQUE,
    tenant_id INTEGER,
    method TEXT,
    amount REAL,
    currency TEXT,
    status TEXT,
    reference TEXT,
    details TEXT,
    metadata TEXT,
    created_at TEXT,
    updated_at TEXT,
    expires_at TEXT,
    confirmed_at TEXT,
    rejected_at TEXT,
    rejection_reason TEXT
);
```

## 📊 Métricas Disponibles

### MRR (Monthly Recurring Revenue)
Ingreso mensual recurrente de suscripciones activas.

### Churn Rate
Tasa de cancelación de suscripciones en un período.

### ARPU (Average Revenue Per User)
Ingreso promedio por usuario activo.

### LTV (Lifetime Value)
Valor total esperado de un cliente durante su vida útil.

### ARR (Annual Recurring Revenue)
Ingreso anual recurrente (MRR × 12).

## 🔒 Seguridad

- Todas las credenciales de Stripe están en variables de entorno
- Webhooks de Stripe verificados con firma HMAC
- Pagos locales requieren aprobación manual de admin
- Base de datos con threading locks para concurrencia
- Validación de límites de uso por plan

## 📝 Notas Importantes

- Los pagos locales tienen un tiempo de expiración de 24 horas
- Las suscripciones expiradas se downgradearán automáticamente a free
- Las facturas se generan automáticamente para pagos exitosos
- El cron job debe ejecutarse diariamente para mantenimiento
- Los webhooks de Stripe deben estar configurados correctamente

## 🆘 Soporte

Para problemas o preguntas:
- Revisar logs del servidor
- Verificar configuración de variables de entorno
- Confirmar webhook de Stripe está activo
- Verificar cron job está ejecutándose

## 📄 Licencia

Propiedad de PINAD SaaS C.A. Todos los derechos reservados.
