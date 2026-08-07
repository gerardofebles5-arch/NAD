# Deployment en Render.com

Este documento describe cómo desplegar el backend de NAD Scanner en Render.com.

## Requisitos Previos

- Cuenta en [Render.com](https://render.com)
- Cuenta en [GitHub](https://github.com)
- Repositorio de GitHub con el código del proyecto

## Pasos de Deployment

### 1. Preparar el Repositorio

```bash
# Agregar archivos al git
git add .
git commit -m "Prepare for Render deployment"

# Push a GitHub
git push origin main
```

### 2. Crear Servicio Web en Render

1. Ir a [Render.com](https://dashboard.render.com)
2. Hacer clic en "New +" → "Web Service"
3. Conectar el repositorio de GitHub
4. Configurar:

**Nombre:** `nad-scanner-backend`

**Runtime:** Python 3

**Build Command:**
```bash
apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-spa && pip install -r requirements.txt
```

**Start Command:**
```bash
python web_server.py
```

### 3. Configurar Variables de Entorno

En Render Dashboard → Environment Variables, agregar:

```
SUPABASE_URL=tu_supabase_url
SUPABASE_ANON_KEY=tu_supabase_anon_key
GOOGLE_DRIVE_CREDENTIALS=contenido_de_credentials_json
TESSERACT_CMD=/usr/bin/tesseract
```

**Importante:** Para `GOOGLE_DRIVE_CREDENTIALS`, copiar el contenido de `credentials.json` y pegarlo como string JSON.

### 4. Configurar Google Drive para Producción

El backend usa credenciales Desktop app. Para producción:

1. Usar las credenciales Desktop actuales (`credentials.json`)
2. O crear nuevas credenciales Desktop app en Google Cloud Console
3. Convertir el JSON a string y agregar como variable de entorno

### 5. Deploy

Render automáticamente detectará cambios en GitHub y redeployará.

## Archivos de Configuración

- `render.yaml` - Configuración de servicio Render
- `requirements.txt` - Dependencias Python (optimizado para Tesseract)
- `.render-build.sh` - Script de build para instalar Tesseract
- `.gitignore` - Archivos excluidos del git (incluye .env y credentials)

## Limitaciones del Plan Gratuito

- 512MB RAM
- 0.1 CPU
- 750 hours/mes
- Sin disco persistente (los archivos se pierden al redeploy)

## Solución de Problemas

### Tesseract no encontrado

Si aparece error "Tesseract not found", verificar que el build command incluya:
```bash
apt-get install -y tesseract-ocr tesseract-ocr-spa
```

### Error de memoria

El plan gratuito tiene 512MB. Si hay errores de memoria:
- Considerar optimizar el procesamiento de imágenes
- O actualizar a un plan de pago

### Variables de entorno

Las variables de entorno se configuran en:
Render Dashboard → Service → Environment Variables

## Monitoreo

Render proporciona:
- Logs en tiempo real
- Métricas de uso
- Alertas de errores
- Health checks automáticos

## URL del Servicio

Una vez deployado, Render asignará una URL como:
```
https://nad-scanner-backend.onrender.com
```

Esta URL se debe usar en el frontend React para las llamadas API.
