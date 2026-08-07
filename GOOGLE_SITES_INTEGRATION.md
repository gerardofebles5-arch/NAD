# Google Sites Integration Guide

## Opción A: Usar Google Apps Script (Simple)

### 1. Crear Apps Script en Google Sites
1. Abre tu Google Site
2. Ve a Insert > Apps Script
3. Crea un nuevo script

### 2. Código Apps Script (backend_proxy.gs)
```javascript
// Backend Proxy para Google Sites
// Llama a Google Cloud Functions

const CLOUD_FUNCTION_URL = 'https://REGION-PROJECT.cloudfunctions.net/nadscanner-api';
const APP_DOMAIN = 'https://negocioaldia.app';

function processInvoice(imageData, tenantId) {
  const payload = {
    image_data: imageData,
    tenant_id: tenantId,
    capture_mode: 'factura'
  };
  
  const options = {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };
  
  try {
    const response = UrlFetchApp.fetch(CLOUD_FUNCTION_URL + '/process_invoice', options);
    return JSON.parse(response.getContentText());
  } catch (e) {
    return { error: e.toString() };
  }
}

function getPlans() {
  try {
    const response = UrlFetchApp.fetch(CLOUD_FUNCTION_URL + '/get_plans');
    return JSON.parse(response.getContentText());
  } catch (e) {
    return { error: e.toString() };
  }
}

function uploadToDrive(fileData, filename) {
  const payload = {
    file_data: fileData,
    filename: filename
  };
  
  const options = {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };
  
  try {
    const response = UrlFetchApp.fetch(CLOUD_FUNCTION_URL + '/upload_to_drive', options);
    return JSON.parse(response.getContentText());
  } catch (e) {
    return { error: e.toString() };
  }
}
```

### 3. Crear Frontend en Google Sites
1. Insert > Embed Code
2. Pegar el HTML/JS adaptado del frontend actual

## Opción B: HTML/JS Embed (Recomendado)

### 1. Adaptar frontend actual para Google Sites
```html
<!DOCTYPE html>
<html>
<head>
  <title>NAD Scanner - Google Sites</title>
  <style>
    /* Estilos adaptados para Google Sites */
    .container {
      max-width: 100%;
      margin: 0 auto;
      padding: 20px;
    }
  </style>
</head>
<body>
  <div id="app">
    <h1>NAD Scanner</h1>
    <div id="camera-container"></div>
    <button onclick="processInvoice()">Procesar Factura</button>
  </div>

  <script>
    const CLOUD_FUNCTION_URL = 'https://REGION-PROJECT.cloudfunctions.net/nadscanner-api';
    const APP_DOMAIN = 'https://negocioaldia.app';
    
    async function processInvoice() {
      const imageData = captureImage(); // Tu función de captura
      
      const response = await fetch(CLOUD_FUNCTION_URL + '/process_invoice', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          image_data: imageData,
          tenant_id: 'YOUR_TENANT_ID',
          capture_mode: 'factura'
        })
      });
      
      const result = await response.json();
      console.log('Invoice processed:', result);
    }
    
    function captureImage() {
      // Implementación de captura de imagen
      return 'base64_image_data';
    }
  </script>
</body>
</html>
```

### 2. Insertar en Google Sites
1. Google Sites > Insert > Embed > Embed Code
2. Pegar el HTML completo
3. Ajustar altura según necesidad

## Opción C: Google Sites + Google Apps Script + Cloud Functions (Híbrida)

### 1. Crear estructura en Google Sites
- Página principal con Apps Script
- Páginas secundarias con HTML embed
- Navegación entre páginas

### 2. Configurar autenticación
```javascript
// Google OAuth 2.0
function onGoogleSignIn(googleUser) {
  const profile = googleUser.getBasicProfile();
  console.log('ID: ' + profile.getId());
  console.log('Name: ' + profile.getName());
  console.log('Email: ' + profile.getEmail());
  
  // Enviar token al backend
  sendTokenToBackend(googleUser.getAuthResponse().id_token);
}
```

## Configuración de Dominio Personalizado

### 1. En Google Admin Console
1. Admin Console > Domains
2. Agregar dominio personalizado
3. Verificar propiedad (DNS TXT)

### 2. Configurar Google Sites
1. Sites > Publicar
2. Usar dominio personalizado
3. Configurar DNS CNAME

### 3. Configurar Cloud Functions
```bash
gcloud functions deploy nadscanner-api \
  --trigger-http \
  --allow-unauthenticated \
  --region us-central1
```

## Integración con Google Drive

### 1. Compartir carpeta con Service Account
1. Crear carpeta en Google Drive: `/NADScanner`
2. Compartir con service account email
3. Dar permisos de Editor

### 2. Configurar en Cloud Functions
```python
# En cloud_functions/main.py
from google.oauth2 import service_account
from googleapiclient.discovery import build

def get_drive_service():
    credentials = service_account.Credentials.from_service_account_info(
        json.loads(os.environ['GOOGLE_DRIVE_CREDENTIALS'])
    )
    return build('drive', 'v3', credentials=credentials)
```

## Testing

### 1. Test local
```bash
cd cloud_functions
functions-framework --target main --debug
```

### 2. Test en Cloud Functions
```bash
curl https://REGION-PROJECT.cloudfunctions.net/nadscanner-api/health_check
```

### 3. Test desde Google Sites
1. Abrir Google Site
2. Usar las funciones del frontend
3. Verificar que las llamadas a Cloud Functions funcionan

## Troubleshooting

### Problema: CORS errors
**Solución:** Agregar CORS headers en Cloud Functions

### Problema: Timeout
**Solución:** Aumentar timeout a 540s máximo

### Problema: Memory limit
**Solución:** Aumentar memoria a 2GB o 4GB

### Problema: Authentication
**Solución:** Configurar OAuth 2.0 correctamente
