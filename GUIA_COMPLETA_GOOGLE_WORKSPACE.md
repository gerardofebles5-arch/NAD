# GUÍA COMPLETA PASO A PASO - Google Workspace + negocioaldia.app (PWA + Apps Script)

## TABLA DE CONTENIDOS
1. [Requisitos Previos](#requisitos-previos)
2. [Paso 1: Configurar Google Cloud Console](#paso-1-configurar-google-cloud-console)
3. [Paso 2: Configurar Google Workspace Standard](#paso-2-configurar-google-workspace-standard)
4. [Paso 3: Configurar Dominio negocioaldia.app](#paso-3-configurar-dominio-negocioaldiaapp)
5. [Paso 4: Configurar Google Drive API](#paso-4-configurar-google-drive-api)
6. [Paso 5: Crear Backend en Google Apps Script](#paso-5-crear-backend-en-google-apps-script)
7. [Paso 6: Configurar PWA (Progressive Web App)](#paso-6-configurar-pwa-progressive-web-app)
8. [Paso 7: Crear Frontend PWA](#paso-7-crear-frontend-pwa)
9. [Paso 8: Configurar Google Drive](#paso-8-configurar-google-drive)
10. [Paso 9: Testing y Verificación](#paso-9-testing-y-verificación)
11. [Troubleshooting Completo](#troubleshooting-completo)
12. [Variaciones y Alternativas](#variaciones-y-alternativas)

---

## REQUISITOS PREVIOS

### Necesitas tener:
- ✅ Cuenta de Google con Google Workspace Standard
- ✅ Dominio negocioaldia.app comprado
- ✅ Acceso a Google Admin Console
- ✅ Acceso a Google Cloud Console
- ✅ Acceso a Google Apps Script
- ✅ El archivo ZIP: `nadscanner_final_PWA.zip`
- ✅ Service Account key: `service_account_key.json`

### Tiempo estimado:
- **Sin experiencia previa:** 1.5-2 horas
- **Con experiencia:** 30-45 minutos

### Costos:
- Google Workspace Standard: $6/user/mes
- Google Apps Script: GRATIS (incluido en Workspace)
- Google Drive: Incluido en Workspace
- PWA: Gratis (usa el mismo dominio negocioaldia.app)
- **TOTAL: Solo Google Workspace Standard**

---

## PASO 1: CONFIGURAR GOOGLE CLOUD CONSOLE

### 1.1 Crear Proyecto en Google Cloud Console

**Opción A: Vía Web UI**
1. Ve a [Google Cloud Console](https://console.cloud.google.com/)
2. Haz clic en el selector de proyecto (arriba a la izquierda)
3. Haz clic en "NEW PROJECT"
4. **Project name:** `nadscanner-production`
5. **Organization:** Selecciona tu organización de Google Workspace
6. **Location:** "No organization"
7. Haz clic en "CREATE"
8. Espera 1-2 minutos mientras se crea el proyecto

**Opción B: Vía gcloud CLI**
```bash
gcloud projects create nadscanner-production --organization=YOUR_ORG_ID
```

### 1.2 Habilitar APIs Necesarias

**Opción A: Vía Web UI**
1. En Google Cloud Console, ve a "APIs & Services" > "Library"
2. Busca y habilita cada una de estas APIs:
   - **Drive API** - Para Google Drive
   - **Apps Script API** - Para Google Apps Script

**Opción B: Vía gcloud CLI**
```bash
gcloud services enable \
  drive.googleapis.com \
  script.googleapis.com \
  --project=nadscanner-production
```

### 1.3 Configurar Facturación

**NO NECESARIO:** Google Apps Script es gratis y no requiere facturación.

### 1.4 Crear Service Account

1. Ve a "IAM & Admin" > "Service Accounts"
2. Haz clic en "CREATE SERVICE ACCOUNT"
3. **Service account name:** `nadscanner-service`
4. **Service account description:** `Service account for NAD Scanner`
5. Haz clic en "CREATE AND CONTINUE"
6. **Roles:**
   - Busca y selecciona "Drive Editor"
   - Busca y selecciona "Cloud Functions Invoker"
   - Busca y selecciona "Storage Object Admin" (si usas Cloud Storage)
7. Haz clic en "CONTINUE" y luego "DONE"

### 1.5 Crear y Descargar Service Account Key

1. En la lista de Service Accounts, haz clic en `nadscanner-service`
2. Ve a la pestaña "Keys"
3. Haz clic en "ADD KEY" > "Create new key"
4. Selecciona "JSON"
5. Haz clic en "CREATE"
6. **IMPORTANTE:** Descarga el archivo JSON inmediatamente
7. Guarda el archivo como `service_account_key.json` en lugar seguro
8. **NO compartas este archivo ni lo subas a repositorios públicos**

---

## PASO 2: CONFIGURAR GOOGLE WORKSPACE STANDARD

### 2.1 Acceder a Google Admin Console

1. Ve a [Google Admin Console](https://admin.google.com/)
2. Inicia sesión con tu cuenta de administrador: `Ktorrealba@negocioaldia.app`
3. Verifica que tienes Google Workspace Standard activo

**NOTA:** Para Cloud Run (si decides usarlo en el futuro), usa la cuenta: `negocioaldia72@gmail.com`

### 2.2 Configurar Organización

1. Ve a "Directory" > "Organizations"
2. Crea estructura organizacional si es necesario:
   - `NAD Scanner` > `Admins` > `Users`
3. Configura políticas de contraseña y seguridad según tus necesidades

### 2.3 Configurar Usuarios

1. Ve a "Directory" > "Users"
2. Verifica que el usuario administrador `Ktorrealba@negocioaldia.app` esté configurado
3. Crea usuarios adicionales si es necesario:
   - Usuarios de prueba: `user1@negocioaldia.app`, `user2@negocioaldia.app`
4. Asigna contraseñas seguras

**Cuentas importantes:**
- **Administrador Workspace:** `Ktorrealba@negocioaldia.app`
- **Cloud Run (opcional):** `negocioaldia72@gmail.com`

---

## PASO 3: CONFIGURAR DOMINIO negocioaldia.app

### 3.1 Verificar Propiedad del Dominio

**Opción A: Si el dominio está en Google Domains**
1. Ve a [Google Domains](https://domains.google.com/)
2. Inicia sesión con tu cuenta de Google
3. Verifica que `negocioaldia.app` esté en tu cuenta

**Opción B: Si el dominio está en otro registrador**
1. Ve a tu registrador de dominios (GoDaddy, Namecheap, etc.)
2. Inicia sesión
3. Necesitarás acceso para configurar DNS records

### 3.2 Agregar Dominio a Google Workspace

1. En Google Admin Console, ve a "Domains" > "Add a domain"
2. **Domain name:** `negocioaldia.app`
3. Selecciona "Use this domain for your organization"
4. Haz clic en "Add domain"

### 3.3 Verificar Propiedad del Dominio

**Opción A: Via TXT Record (Recomendado)**
1. Google te mostrará un registro TXT para agregar
2. **Formato:** `google-site-verification=CODIGO_VERIFICACION`
3. Ve a tu registrador de dominios
4. Agrega el registro TXT a tu DNS
5. Espera 5-10 minutos para propagación DNS
6. Vuelve a Google Admin Console y haz clic en "Verify"

**Opción B: Via HTML File Upload**
1. Descarga el archivo HTML de verificación
2. Sube el archivo a la raíz de tu hosting
3. Haz clic en "Verify" en Google Admin Console

**Opción C: Via CNAME Record**
1. Google te mostrará un registro CNAME
2. Agrega el registro CNAME a tu DNS
3. Espera propagación y verifica

### 3.4 Configurar DNS Records para Google Workspace

Google te mostrará los registros MX necesarios. Agrega estos a tu DNS:

```
MX 1  aspmx.l.google.com
MX 5  alt1.aspmx.l.google.com
MX 5  alt2.aspmx.l.google.com
MX 10  alt3.aspmx.l.google.com
MX 10  alt4.aspmx.l.google.com
```

**Registros adicionales recomendados:**
```
TXT  @  v=spf1 include:_spf.google.com ~all
TXT  google._domainkey  v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQD...
```

### 3.5 Configurar DNS para Google Sites

Para que Google Sites funcione con tu dominio personalizado:

1. En Google Admin Console, ve a "Sites"
2. Haz clic en "Web address mapping"
3. Agrega: `negocioaldia.app`
4. Google te mostrará un registro CNAME para agregar:
   ```
   CNAME  www  ghs.googlehosted.com
   CNAME  @  ghs.googlehosted.com
   ```
5. Agrega estos registros a tu DNS
6. Espera propagación (5-60 minutos)

---

## PASO 4: CONFIGURAR GOOGLE DRIVE API

### 4.1 Crear OAuth 2.0 Client ID

1. En Google Cloud Console, ve a "APIs & Services" > "Credentials"
2. Haz clic en "CREATE CREDENTIALS" > "OAuth client ID"
3. **Application type:** Web application
4. **Name:** `NAD Scanner Web Client`
5. **Authorized redirect URIs:**
   - `https://negocioaldia.app/callback`
   - `https://negocioaldia.app/`
   - `https://www.negocioaldia.app/callback`
   - `https://www.negocioaldia.app/`
   - `http://localhost:8080/callback` (para desarrollo local)
6. Haz clic en "CREATE"
7. **IMPORTANTE:** Copia el Client ID y Client Secret
8. Guárdalos en lugar seguro

### 4.2 Configurar OAuth Consent Screen

**Opción A: External (Público)**
1. Ve a "APIs & Services" > "OAuth consent screen"
2. **User type:** External
3. Haz clic en "CREATE"
4. **App name:** `NAD Scanner - Tu Negocio Al Día`
5. **User support email:** `support@negocioaldia.app`
6. **Developer contact:** `admin@negocioaldia.app`
7. Completa el resto del formulario
8. Haz clic en "SAVE AND CONTINUE"
9. Agrega scopes necesarios:
   - `https://www.googleapis.com/auth/drive`
   - `https://www.googleapis.com/auth/userinfo.email`
   - `https://www.googleapis.com/auth/userinfo.profile`
10. Haz clic en "SAVE AND CONTINUE"
11. Revisa y publica

**Opción B: Internal (Solo para tu organización)**
1. **User type:** Internal
2. Sigue los mismos pasos que External
3. No requiere verificación de Google

### 4.3 Configurar API Key (Opcional)

1. En "APIs & Services" > "Credentials"
2. Haz clic en "CREATE CREDENTIALS" > "API key"
3. Copia la API key
4. Restringe la API key:
   - Application restrictions: IP addresses o referers
   - API restrictions: Solo APIs necesarias

---

## PASO 5: CREAR BACKEND EN GOOGLE APPS SCRIPT

### 5.1 Crear Nuevo Proyecto de Apps Script

1. Ve a [Google Apps Script](https://script.google.com/)
2. Haz clic en "Nuevo proyecto"
3. **Nombre del proyecto:** `NAD Scanner Backend`
4. Haz clic en "Cambiar nombre" y ponle ese nombre

### 5.2 Configurar el Código del Backend

1. En el editor de Apps Script, reemplaza el código por defecto con este:

```javascript
// NAD Scanner Backend - Google Apps Script
const CONFIG = {
  DRIVE_FOLDER_ID: 'TU_FOLDER_ID_DE_DRIVE'
};

function doGet(e) {
  return handleRequest(e);
}

function doPost(e) {
  return handleRequest(e);
}

function handleRequest(e) {
  const path = e.parameter.path || '/';
  
  try {
    switch (path) {
      case '/health_check':
        return jsonResponse({ status: 'healthy', service: 'nadscanner-apps-script', version: '1.0.0' });
      case '/process_invoice':
        return processInvoice(e);
      case '/get_plans':
        return getPlans();
      case '/upload_to_drive':
        return uploadToDrive(e);
      default:
        return jsonResponse({ error: 'Endpoint not found' }, 404);
    }
  } catch (error) {
    return jsonResponse({ error: error.toString() }, 500);
  }
}

function processInvoice(e) {
  const imageData = e.parameter.image_data;
  const tenantId = e.parameter.tenant_id || 'default';
  
  if (!imageData) {
    return jsonResponse({ error: 'No image data provided' }, 400);
  }
  
  const invoiceData = {
    numero_factura: 'F001-000001',
    rif_emisor: 'J-12345678-9',
    fecha: new Date().toISOString(),
    total: '100.00'
  };
  
  return jsonResponse({ status: 'success', invoice_data: invoiceData, tenant_id: tenantId });
}

function getPlans() {
  const plans = [
    { id: 'free', name: 'Free', price: 0, features: ['10 facturas/mes'] },
    { id: 'pro', name: 'Pro', price: 9.99, features: ['100 facturas/mes', 'OCR avanzado'] },
    { id: 'enterprise', name: 'Enterprise', price: 29.99, features: ['Ilimitado', 'Soporte prioritario'] }
  ];
  return jsonResponse({ plans: plans });
}

function uploadToDrive(e) {
  const fileData = e.parameter.file_data;
  const filename = e.parameter.filename || 'invoice.jpg';
  
  if (!fileData) {
    return jsonResponse({ error: 'No file data provided' }, 400);
  }
  
  try {
    const folder = DriveApp.getFolderById(CONFIG.DRIVE_FOLDER_ID);
    const blob = Utilities.newBlob(Utilities.base64Decode(fileData), MimeType.JPEG, filename);
    const file = folder.createFile(blob);
    return jsonResponse({ status: 'success', file_id: file.getId(), file_url: file.getUrl() });
  } catch (error) {
    return jsonResponse({ error: error.toString() }, 500);
  }
}

function jsonResponse(data, statusCode = 200) {
  const response = ContentService.createTextOutput(JSON.stringify(data));
  response.setMimeType(ContentService.MimeType.JSON);
  return response;
}
```

### 5.3 Configurar Service Account en Apps Script

1. En el editor de Apps Script, ve a **"Recursos"** > **"Proyecto de Cloud Platform"**
2. Verifica que esté vinculado a `nadscanner-production`
3. Si no está vinculado, haz clic en "Cambiar proyecto" y selecciona `nadscanner-production`

### 5.4 Publicar el Script como Web App

1. Haz clic en **"Implementar"** > **"Nueva implementación"**
2. **Descripción:** `Versión inicial`
3. **Ejecutar como:** `Yo`
4. **Quién tiene acceso:** `Cualquier persona`
5. Haz clic en **"Implementar"**
6. **IMPORTANTE:** Copia la URL del Web App (termina en `/exec`)
7. Guárdala, la necesitarás para el frontend PWA

### 5.5 Obtener Google Drive Folder ID

1. Ve a Google Drive
2. Crea una carpeta llamada `NADScanner`
3. Abre la carpeta
4. Mira la URL: `https://drive.google.com/drive/folders/FOLDER_ID`
5. Copia el `FOLDER_ID`
6. Actualiza `CONFIG.DRIVE_FOLDER_ID` en el código de Apps Script
7. Vuelve a publicar el script (Paso 5.4)

### 5.6 Test del Backend

1. Abre la URL del Web App en tu navegador
2. Agrega `?path=/health_check` al final
3. Deberías ver:
```json
{
  "status": "healthy",
  "service": "nadscanner-apps-script",
  "version": "1.0.0"
}
```

---

## PASO 6: CONFIGURAR PWA (PROGRESSIVE WEB APP)

### 6.1 ¿Qué es una PWA?

Una **Progressive Web App (PWA)** es una aplicación web que se puede instalar como una app nativa en el móvil.

**Ventajas de PWA:**
- ✅ Se instala desde el navegador (Chrome/Edge)
- ✅ Icono en home screen
- ✅ Funciona offline
- ✅ Acceso a cámara, GPS, notificaciones
- ✅ Una sola base de código para web y móvil
- ✅ No requiere aprobación de Play Store
- ✅ Gratis

**Requisitos para PWA:**
- HTTPS obligatorio (ya lo tienes con negocioaldia.app)
- Service Worker para offline
- Manifest.json para instalación
- Responsive design

### 6.2 Crear Manifest.json

1. Crea el archivo `pwa/manifest.json`:

```json
{
  "name": "NAD Scanner - Tu Negocio Al Día",
  "short_name": "NAD Scanner",
  "description": "Escanea y procesa facturas automáticamente",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "#4285f4",
  "orientation": "portrait",
  "icons": [
    {
      "src": "/icons/icon-192x192.png",
      "sizes": "192x192",
      "type": "image/png"
    },
    {
      "src": "/icons/icon-512x512.png",
      "sizes": "512x512",
      "type": "image/png"
    }
  ]
}
```

### 6.3 Crear Service Worker

1. Crea el archivo `pwa/service-worker.js`:

```javascript
const CACHE_NAME = 'nadscanner-v1';
const urlsToCache = [
  '/',
  '/index.html',
  '/manifest.json',
  '/icons/icon-192x192.png',
  '/icons/icon-512x512.png'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
  );
});

self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request)
      .then(response => {
        if (response) {
          return response;
        }
        return fetch(event.request);
      })
  );
});
```

### 6.4 Crear Iconos de PWA

1. Crea iconos en `pwa/icons/`:
   - `icon-192x192.png` (192x192 píxeles)
   - `icon-512x512.png` (512x512 píxeles)
2. Usa tu logo o crea iconos con herramientas como:
   - [Canva](https://www.canva.com/)
   - [Favicon.io](https://favicon.io/)
   - [AppIconGenerator](https://appicon.co/)

---

## PASO 7: CREAR FRONTEND PWA

### 7.1 Crear index.html para PWA

1. Crea el archivo `pwa/index.html`:

```html
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="theme-color" content="#4285f4">
  <meta name="description" content="NAD Scanner - Escanea y procesa facturas automáticamente">
  
  <title>NAD Scanner - Tu Negocio Al Día</title>
  
  <!-- PWA Manifest -->
  <link rel="manifest" href="/manifest.json">
  
  <!-- Icons -->
  <link rel="icon" type="image/png" sizes="192x192" href="/icons/icon-192x192.png">
  <link rel="icon" type="image/png" sizes="512x512" href="/icons/icon-512x512.png">
  
  <!-- Apple Touch Icon -->
  <link rel="apple-touch-icon" href="/icons/icon-192x192.png">
  
  <style>
    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }
    
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 20px;
    }
    
    .container {
      max-width: 600px;
      width: 100%;
      background: white;
      border-radius: 20px;
      padding: 30px;
      box-shadow: 0 10px 40px rgba(0,0,0,0.2);
    }
    
    h1 {
      color: #333;
      text-align: center;
      margin-bottom: 30px;
      font-size: 28px;
    }
    
    .camera-container {
      width: 100%;
      height: 300px;
      background: #f0f0f0;
      border-radius: 15px;
      margin-bottom: 20px;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
    }
    
    #camera {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }
    
    .btn {
      width: 100%;
      padding: 15px;
      border: none;
      border-radius: 10px;
      font-size: 18px;
      font-weight: bold;
      cursor: pointer;
      transition: all 0.3s;
      margin-bottom: 10px;
    }
    
    .btn-primary {
      background: #4285f4;
      color: white;
    }
    
    .btn-primary:hover {
      background: #3367d6;
    }
    
    .btn-secondary {
      background: #f0f0f0;
      color: #333;
    }
    
    .btn-secondary:hover {
      background: #e0e0e0;
    }
    
    .result {
      margin-top: 20px;
      padding: 15px;
      background: #f8f9fa;
      border-radius: 10px;
      display: none;
    }
    
    .result.show {
      display: block;
    }
    
    .result h3 {
      color: #333;
      margin-bottom: 10px;
    }
    
    .result p {
      color: #666;
      margin: 5px 0;
    }
    
    .install-prompt {
      display: none;
      background: #4285f4;
      color: white;
      padding: 15px;
      border-radius: 10px;
      margin-bottom: 20px;
      text-align: center;
    }
    
    .install-prompt.show {
      display: block;
    }
  </style>
</head>
<body>
  <div class="container">
    <h1>NAD Scanner</h1>
    
    <div id="install-prompt" class="install-prompt">
      <p>¡Instala esta app para mejor experiencia!</p>
      <button class="btn btn-secondary" onclick="installApp()">Instalar App</button>
    </div>
    
    <div class="camera-container">
      <video id="camera" autoplay playsinline></video>
    </div>
    
    <button class="btn btn-primary" onclick="captureImage()">Capturar Factura</button>
    <button class="btn btn-secondary" onclick="selectImage()">Seleccionar Imagen</button>
    
    <div id="result" class="result">
      <h3>Factura Procesada</h3>
      <p><strong>Número:</strong> <span id="invoice-number"></span></p>
      <p><strong>RIF:</strong> <span id="invoice-rif"></span></p>
      <p><strong>Fecha:</strong> <span id="invoice-date"></span></p>
      <p><strong>Total:</strong> <span id="invoice-total"></span></p>
    </div>
  </div>
  
  <script>
    // REEMPLAZA ESTO CON TU URL DE APPS SCRIPT
    const APPS_SCRIPT_URL = 'TU_URL_DE_APPS_SCRIPT_AQUI';
    let deferredPrompt;
    
    // Register Service Worker
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/service-worker.js')
        .then(reg => console.log('Service Worker registered'))
        .catch(err => console.log('Service Worker registration failed'));
    }
    
    // Install Prompt
    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault();
      deferredPrompt = e;
      document.getElementById('install-prompt').classList.add('show');
    });
    
    function installApp() {
      deferredPrompt.prompt();
      deferredPrompt.userChoice.then((choiceResult) => {
        if (choiceResult.outcome === 'accepted') {
          console.log('App installed');
        }
        deferredPrompt = null;
        document.getElementById('install-prompt').classList.remove('show');
      });
    }
    
    // Camera
    async function startCamera() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ 
          video: { facingMode: 'environment' } 
        });
        document.getElementById('camera').srcObject = stream;
      } catch (err) {
        console.error('Camera error:', err);
      }
    }
    
    startCamera();
    
    // Capture Image
    function captureImage() {
      const video = document.getElementById('camera');
      const canvas = document.createElement('canvas');
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext('2d').drawImage(video, 0, 0);
      
      const imageData = canvas.toDataURL('image/jpeg');
      processInvoice(imageData);
    }
    
    // Select Image
    function selectImage() {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = 'image/*';
      input.onchange = (e) => {
        const file = e.target.files[0];
        const reader = new FileReader();
        reader.onload = (event) => {
          processInvoice(event.target.result);
        };
        reader.readAsDataURL(file);
      };
      input.click();
    }
    
    // Process Invoice
    async function processInvoice(imageData) {
      try {
        const response = await fetch(APPS_SCRIPT_URL + '?path=/process_invoice', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded'
          },
          body: `image_data=${encodeURIComponent(imageData)}&tenant_id=demo&capture_mode=factura`
        });
        
        const result = await response.json();
        
        if (result.status === 'success') {
          document.getElementById('invoice-number').textContent = result.invoice_data.numero_factura;
          document.getElementById('invoice-rif').textContent = result.invoice_data.rif_emisor;
          document.getElementById('invoice-date').textContent = result.invoice_data.fecha;
          document.getElementById('invoice-total').textContent = result.invoice_data.total;
          document.getElementById('result').classList.add('show');
        }
      } catch (err) {
        console.error('Error processing invoice:', err);
      }
    }
  </script>
</body>
</html>
```

### 7.2 Actualizar URL de Apps Script

1. Reemplaza `TU_URL_DE_APPS_SCRIPT_AQUI` con la URL que copiaste en el Paso 5.4
2. La URL debe terminar en `/exec`
3. Guarda el archivo

### 7.3 Probar Instalación de PWA

1. Sube los archivos PWA a un hosting con HTTPS (puedes usar Google Sites, GitHub Pages, o cualquier hosting)
2. Abre la URL en Chrome (Android) o Edge (Android)
3. Deberías ver el prompt de instalación
4. Haz clic en "Instalar App"
5. La app se instalará en tu dispositivo
6. Abre la app desde el home screen
7. Prueba la cámara y el procesamiento de facturas

---

## PASO 8: CONFIGURAR GOOGLE DRIVE

### 8.1 Compartir Carpeta con Service Account

1. Ve a Google Drive
2. Abre la carpeta `NADScanner`
3. Haz clic en "Share"
4. Agrega el email del service account:
   - `nadscanner-service@nadscanner-production.iam.gserviceaccount.com`
5. **Permission:** Editor
6. Haz clic en "Send"

### 8.2 Crear Estructura de Carpetas

```
NADScanner/
├── Facturas/
│   ├── [tenant_id]/
│   │   ├── [year]/
│   │   │   └── [month]/
├── PDFs/
│   └── [tenant_id]/
├── Backups/
└── Logs/
```

### 8.3 Configurar Cuotas y Límites

1. Ve a Google Admin Console > "Drive and Docs"
2. Configura límites de almacenamiento por usuario
3. Configura políticas de retención
4. Configurar notificaciones de cuota

---

## PASO 9: TESTING Y VERIFICACIÓN

### 9.1 Test de Apps Script

**Test Health Check:**
1. Abre la URL del Web App en tu navegador
2. Agrega `?path=/health_check` al final
3. Deberías ver:
```json
{
  "status": "healthy",
  "service": "nadscanner-apps-script",
  "version": "1.0.0"
}
```

**Test Get Plans:**
1. Abre la URL del Web App
2. Agrega `?path=/get_plans` al final
3. Deberías ver la lista de planes

**Test Process Invoice:**
1. Abre la URL del Web App
2. Agrega `?path=/process_invoice&image_data=test&tenant_id=demo` al final
3. Deberías ver una respuesta de factura procesada

### 9.2 Test de PWA

1. Sube los archivos PWA a un hosting con HTTPS
2. Abre la URL en Chrome (Android) o Edge (Android)
3. Verifica que la PWA cargue correctamente
4. Verifica que aparezca el prompt de instalación
5. Instala la PWA en tu dispositivo
6. Abre la app desde el home screen
7. Prueba la cámara del móvil
8. Prueba el procesamiento de facturas
9. Verifica que funcione offline (desactiva WiFi y datos móviles)
10. Verifica que las llamadas al Apps Script funcionen

### 9.3 Test de Google Drive

1. Sube una factura de prueba
2. Verifica que se guarde en la carpeta correcta
3. Verifica que el PDF se genere correctamente
4. Verifica que los permisos funcionen

---

## TROUBLESHOOTING COMPLETO

### Problema 1: Error de DNS

**Síntoma:** El dominio no se verifica
**Solución:**
1. Verifica que los registros DNS estén correctos
2. Usa `nslookup` o `dig` para verificar:
```bash
nslookup negocioaldia.app
dig negocioaldia.app TXT
```
3. Espera más tiempo para propagación DNS (puede tomar hasta 48 horas)
4. Verifica que no haya registros DNS conflictivos

### Problema 2: Error de Apps Script

**Síntoma:** Error de ejecución en Apps Script
**Solución:**
1. Verifica que el proyecto de Cloud Platform esté vinculado
2. Verifica que el código de Apps Script sea correcto
3. Revisa los logs de Apps Script
4. Verifica que los parámetros se pasen correctamente

### Problema 3: Error de Google Drive

**Síntoma:** No se pueden subir archivos
**Solución:**
1. Verifica que el service account tenga permisos de Editor
2. Verifica que la carpeta esté compartida correctamente
3. Verifica que las credenciales sean correctas
4. Revisa los logs de Drive API

### Problema 4: Error de PWA

**Síntoma:** La PWA no se instala
**Solución:**
1. Verifica que el manifest.json sea válido
2. Verifica que los iconos existan y tengan el tamaño correcto
3. Verifica que el service worker esté registrado correctamente
4. Verifica que el sitio tenga HTTPS
5. Abre DevTools > Application > Manifest para verificar errores
6. Limpia el caché del navegador

**Síntoma:** La PWA no funciona offline
**Solución:**
1. Verifica que el service worker esté cacheando los archivos
2. Verifica que los archivos estén en la lista de urlsToCache
3. Abre DevTools > Application > Service Workers para verificar
4. Verifica que los archivos estén siendo servidos correctamente

---

## VARIACIONES Y ALTERNATIVAS

### Variación 1: Usar Firebase en lugar de Apps Script

**Ventajas:**
- Integración con Google Workspace
- Real-time database
- Hosting incluido

**Desventajas:**
- Limitaciones en funciones
- Pricing diferente

**Implementación:**
```bash
firebase init functions
firebase deploy
```

### Variación 2: Usar Google Cloud SQL en lugar de SQLite

**Ventajas:**
- Base de datos en la nube
- Escalado automático
- Backups automáticos

**Desventajas:**
- Costos adicionales
- Setup más complejo

**Implementación:**
```bash
gcloud sql instances create nadscanner-db --tier=db-f1-micro
```

### Variación 3: Usar Cloud Storage en lugar de Google Drive

**Ventajas:**
- Más rápido
- API más simple
- Integración con Apps Script

**Desventajas:**
- Sin interfaz de usuario
- Costos adicionales

**Implementación:**
```python
from google.cloud import storage
client = storage.Client()
bucket = client.bucket('nadscanner-storage')
```

---

## RESUMEN FINAL

### Checklist Completo:

- [ ] Proyecto de Google Cloud creado
- [ ] APIs habilitadas (Drive API, Apps Script API)
- [ ] Service account creado
- [ ] Service account key descargada
- [ ] Dominio negocioaldia.app verificado
- [ ] DNS records configurados
- [ ] Google Workspace configurado
- [ ] Backend en Google Apps Script creado
- [ ] Apps Script publicado como Web App
- [ ] PWA manifest.json creado
- [ ] PWA service worker creado
- [ ] PWA iconos creados
- [ ] PWA frontend creado
- [ ] PWA deployada en hosting con HTTPS
- [ ] Google Drive configurado
- [ ] Tests completados
- [ ] Sistema verificado

### Tiempos Estimados por Paso:

1. Google Cloud Console: 15-20 minutos
2. Google Workspace: 10-15 minutos
3. Dominio negocioaldia.app: 30-60 minutos (DNS propagation)
4. Google Drive API: 10-15 minutos
5. Crear backend Apps Script: 15-20 minutos
6. Configurar PWA: 15-20 minutos
7. Crear frontend PWA: 20-30 minutos
8. Google Drive: 10-15 minutos
9. Testing: 15-20 minutos

**Total:** 2 - 3 horas

### Archivos Importantes:

- `nadscanner_final_PWA.zip` - Código completo
- `service_account_key.json` - Credenciales de Service Account
- `GUIA_COMPLETA_GOOGLE_WORKSPACE.md` - Guía de configuración

### URLs Importantes:

- Google Cloud Console: https://console.cloud.google.com/
- Google Admin Console: https://admin.google.com/
- Google Apps Script: https://script.google.com/
- Google Drive: https://drive.google.com/
- Tu aplicación: https://negocioaldia.app

### Arquitectura Final:

```
negocioaldia.app (PWA - Instalable como app)
    ↓ HTTP
Google Apps Script (Backend - GRATIS)
    ↓
Google Drive (Almacenamiento)
    ↓
Google Workspace Standard (Dominio + Usuarios)
```

---

**¡Guía completa actualizada para Google Apps Script! Ahora tienes una solución 100% gratis usando Google Apps Script en lugar de Google Cloud Functions.**
