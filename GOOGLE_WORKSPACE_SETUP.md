# Google Workspace + Google Sites Setup Guide

## Arquitectura Recomendada

```
Google Sites (Frontend)
    ↓ HTTP requests
Google Cloud Functions (Backend Python)
    ↓
Google Drive (Almacenamiento de facturas/PDFs)
    ↓
Google Workspace Standard (Dominio + Gestión de usuarios)
```

## Paso 1: Configurar Google Cloud Console

### 1.1 Crear Proyecto
1. Ir a [Google Cloud Console](https://console.cloud.google.com/)
2. Crear nuevo proyecto: `nadscanner-production`
3. Anotar Project ID

### 1.2 Habilitar APIs Necesarias
```bash
gcloud services enable \
  drive.googleapis.com \
  cloudfunctions.googleapis.com \
  clouldresourcemanager.googleapis.com \
  appengine.googleapis.com \
  iam.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com
```

### 1.3 Configurar Google Drive API
1. Ir a APIs & Services > Credentials
2. Crear OAuth 2.0 Client ID
3. Tipo: Web application
4. Authorized redirect URIs:
   - `https://negocioaldia.app/callback`
   - `https://sites.google.com/callback`

### 1.4 Crear Service Account
1. APIs & Services > Credentials
2. Create Service Account
3. Nombre: `nadscanner-service`
4. Roles: `Editor` en Google Drive
5. Descargar JSON credentials

## Paso 2: Configurar Google Workspace Standard

### 2.1 Configurar Dominio Personalizado
1. Google Admin Console > Domains
2. Agregar dominio: `negocioaldia.app`
3. Verificar propiedad (DNS TXT record)
4. Configurar DNS records

### 2.2 Configurar Google Sites
1. Google Sites > Crear nuevo sitio
2. Usar dominio personalizado
3. Configurar como público o restringido por dominio

## Paso 3: Migrar Backend a Cloud Functions

### 3.1 Estructura de Carpetas
```
cloud-functions/
├── main.py (entry point)
├── requirements.txt
├── billing/ (módulos de billing)
├── ocr/ (módulos de OCR)
├── core/ (módulos core)
├── utils/ (utilidades)
└── drive/ (integración Drive)
```

### 3.2 main.py para Cloud Functions
```python
import os
from flask import escape
import functions_framework

@functions_framework.http
def process_invoice(request):
    """Cloud Function para procesar facturas"""
    # Lógica de procesamiento
    return {"status": "success"}
```

### 3.3 Deploy Commands
```bash
gcloud functions deploy process_invoice \
  --runtime python39 \
  --trigger-http \
  --allow-unauthenticated \
  --memory 2GB \
  --timeout 540s \
  --env-vars-file .env.yaml
```

## Paso 4: Integrar Google Drive

### 4.1 Configurar Service Account
1. Compartir carpeta de Drive con service account
2. Dar permisos de Editor
3. Usar credentials JSON en Cloud Functions

### 4.2 Almacenamiento de Facturas
- Carpeta: `/NADScanner/Facturas/[tenant_id]/`
- PDFs generados automáticamente
- Backup automático

## Paso 5: Crear Frontend en Google Sites

### 5.1 Opción A: Google Apps Script (Simple)
- Crear Apps Script incrustado en Sites
- Llamar a Cloud Functions via `UrlFetchApp`
- Limitado en funcionalidad

### 5.2 Opción B: HTML/JS en Sites (Recomendado)
- Usar "Embed Code" en Google Sites
- Mismo frontend actual adaptado
- Llamadas HTTP a Cloud Functions

## Paso 6: Configurar Autenticación

### 6.1 Google OAuth 2.0
1. Usar Google Identity Services
2. Integrar con Google Workspace users
3. SSO automático para usuarios del dominio

### 6.2 Configurar en Google Sites
```javascript
// Google Identity Services
gapi.load('auth2', function() {
  gapi.auth2.init({
    client_id: 'TU_CLIENT_ID',
    scope: 'profile email'
  });
});
```

## Paso 7: Variables de Entorno

### .env.yaml para Cloud Functions
```yaml
STRIPE_SECRET_KEY: sk_live_...
STRIPE_WEBHOOK_SECRET: whsec_...
GOOGLE_DRIVE_CREDENTIALS: |
GOOGLE_CLOUD_PROJECT: nadscanner-production
DATABASE_URL: ...
SMTP_SERVER: smtp.gmail.com
SMTP_USERNAME: ...
SMTP_PASSWORD: ...
```

## Paso 8: Testing y Deploy

### 8.1 Testing Local
```bash
functions-framework --target process_invoice --debug
```

### 8.2 Deploy a Producción
```bash
gcloud functions deploy process_invoice --region us-central1
```

### 8.3 Monitoreo
- Google Cloud Logging
- Google Cloud Monitoring
- Error Reporting

## Costos Estimados (Google Workspace Standard)

- Google Workspace Standard: $6/user/mes
- Cloud Functions: ~ based on usage
- Google Drive: Incluido en Workspace
- Google Sites: Gratis

## Limitaciones a Considerar

1. **Google Sites**: No ejecuta código Python directamente
2. **Cloud Functions**: Timeout max 540s (9 minutos)
3. **OCR**: Requiere más memoria (2GB recomendado)
4. **Storage**: Google Drive tiene límites de espacio

## Alternativa: Google App Engine

Si Cloud Functions es muy limitado:
- Usar App Engine Standard/Flexible
- Más control sobre el entorno
- Escalado automático
- Costos más altos

## Próximos Pasos

1. ¿Tienes acceso a Google Cloud Console?
2. ¿El dominio ya está configurado en Google Workspace?
3. ¿Prefieres Cloud Functions o App Engine?
