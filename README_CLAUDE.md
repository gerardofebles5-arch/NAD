# NAD Scanner - Versión Completa para Claude

## 📋 Resumen del Proyecto

NAD Scanner es un sistema de captura, procesamiento y subida automática de facturas que utiliza:
- **PhotoScan** para captura múltiple
- **ORB** para alineación por características
- **Fusión anti-glare** (mediana)
- **CamScanner** para detección de documento
- **CLAHE + umbral** para realce
- **OCR** para extracción de datos
- **Google Drive** para almacenamiento

## 🏗️ Arquitectura Actual

### Opción 1: Local (Para pruebas inmediatas)
```
PWA (Frontend) → Servidor Local (Python/Flask) → Google Drive
```

### Opción 2: Google Workspace (Para producción)
```
PWA (Frontend) → Google Apps Script (Backend - GRATIS) → Google Drive
```

## 📁 Estructura del Proyecto

```
nadscanner_final/
├── main.py                      # Aplicación principal CLI
├── web_server.py                # Servidor web Flask
├── iniciar_pwa_local.bat        # Script para iniciar servidor local
├── iniciar_servidor.bat         # Script original
├── requirements.txt             # Dependencias Python
├── service_account_key.json     # Credenciales Google Drive
├── GUIA_COMPLETA_GOOGLE_WORKSPACE.md  # Guía completa para Google Apps Script
├── README_CLAUDE.md             # Este archivo
├── static/
│   └── pwa/                     # Archivos PWA
│       ├── manifest.json        # Configuración PWA
│       ├── service-worker.js    # Service worker para offline
│       ├── index.html           # Frontend PWA
│       └── icons/               # Iconos PWA
│           ├── icon-192x192.png
│           └── icon-512x512.png
├── core/                        # Módulos de procesamiento
├── ocr/                         # Módulos OCR
├── drive/                       # Módulos Google Drive
├── auth/                        # Módulos de autenticación
├── billing/                     # Módulos de facturación
├── templates/                   # Plantillas HTML
└── utils/                       # Utilidades
```

## 🚀 Cómo Usar

### Opción 1: Servidor Local (Pruebas Inmediatas)

1. **Requisitos:**
   - Python 3.8+
   - Dependencias en `requirements.txt`
   - Google Drive configurado (service account key)

2. **Iniciar servidor:**
   ```bash
   # Windows
   iniciar_pwa_local.bat

   # O manualmente
   python web_server.py
   ```

3. **Acceder desde el teléfono:**
   - Conectar PC y teléfono a la misma red WiFi
   - Abrir navegador: `https://[IP-DEL-PC]:5000/pwa`
   - Aceptar advertencia de seguridad (certificado autofirmado)

4. **Probar:**
   - Capturar factura con cámara
   - Seleccionar imagen de galería
   - Ver resultados de OCR

### Opción 2: Google Apps Script (Producción)

Sigue la guía completa en `GUIA_COMPLETA_GOOGLE_WORKSPACE.md`

## 🔑 Configuración Google Drive

**Service Account:**
- Email: `nadscanner-service@nadscanner-production.iam.gserviceaccount.com`
- Key: `service_account_key.json`
- Proyecto: `nadscanner-production`

**Cuentas importantes:**
- **Administrador Workspace:** `Ktorrealba@negocioaldia.app`
- **Cloud Run (opcional):** `negocioaldia72@gmail.com`

## 📦 Archivos Importantes

- `service_account_key.json` - Credenciales de Service Account (NO COMPARTIR)
- `GUIA_COMPLETA_GOOGLE_WORKSPACE.md` - Guía completa para Google Apps Script
- `nadscanner_final_AppsScript.zip` - Versión anterior empaquetada
- `requirements.txt` - Dependencias Python

## 🔧 Dependencias Principales

```
flask
flask-socketio
opencv-python
numpy
pytesseract
google-api-python-client
google-auth-httplib2
google-auth-oauthlib
pillow
cryptography
```

## 📱 PWA Features

- **Instalable:** Se puede instalar como app nativa
- **Offline:** Service worker para caché
- **Cámara:** Acceso a cámara del dispositivo
- **Responsive:** Optimizado para móviles
- **HTTPS:** Requerido para acceso a cámara

## 🌐 URLs de Acceso

**Local:**
- Servidor: `https://127.0.0.1:5000`
- PWA: `https://127.0.0.1:5000/pwa`
- Red: `https://192.168.101.4:5000/pwa`

**Google Workspace:**
- Google Admin Console: https://admin.google.com/
- Google Cloud Console: https://console.cloud.google.com/
- Google Apps Script: https://script.google.com/
- Dominio: https://negocioaldia.app

## 📝 Notas para Claude

1. **Arquitectura actual:** El proyecto tiene dos arquitecturas:
   - Local: Servidor Python/Flask para pruebas inmediatas
   - Google Apps Script: Para producción sin costos de facturación

2. **Google Cloud Billing:** NO se puede habilitar facturación, por eso se cambió a Google Apps Script

3. **PWA:** Ya está configurada con manifest.json, service-worker.js e iconos

4. **Google Drive:** Service account creado y configurado

5. **Guía completa:** `GUIA_COMPLETA_GOOGLE_WORKSPACE.md` tiene todos los pasos para Google Apps Script

6. **Servidor local:** Ya está funcionando y probado en `https://192.168.101.4:5000`

## 🎯 Próximos Pasos Sugeridos

1. Probar la PWA localmente en el teléfono
2. Si funciona bien, seguir con la guía de Google Apps Script
3. Configurar el dominio `negocioaldia.app` en Google Workspace
4. Desplegar el backend en Google Apps Script
5. Conectar la PWA al backend de Apps Script

## 📞 Soporte

Para cualquier pregunta, consultar:
- `GUIA_COMPLETA_GOOGLE_WORKSPACE.md` - Guía paso a paso
- `README.md` - Documentación original del proyecto

---

**Versión:** 1.3.0  
**Fecha:** Agosto 2026  
**Estado:** Funcionando localmente, listo para Google Apps Script
