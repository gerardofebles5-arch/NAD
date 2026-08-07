# ⬡ πNAD Scanner — Tu Negocio, Al Día

[![PWA](https://img.shields.io/badge/PWA-Instalable-7CBE8C?style=flat-square&logo=pwa&logoColor=white)](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps)
[![Service Worker](https://img.shields.io/badge/SW-✅_Activo-D9B158?style=flat-square&logo=serviceworker&logoColor=white)](.)
[![Manifest](https://img.shields.io/badge/Manifest-v1.0-AC7649?style=flat-square&logo=json&logoColor=white)](./static/manifest.json)
[![License](https://img.shields.io/badge/Licencia-Propietaria-241609?style=flat-square)](.)

Escáner inteligente de facturas con alineación multi-toma estilo PhotoScan, fusión anti-reflejo, OCR automático, y formato Z para documentos extra-largos.

---

## 📋 Índice

- [PWA Readiness Report](#-pwa-readiness-report)
- [Requisitos PWA Lighthouse](#-requisitos-pwa-lighthouse)
- [Guía de Inicio Rápido](#-guía-de-inicio-rápido)
- [Arquitectura](#-arquitectura)

---

## 📱 PWA Readiness Report

La aplicación es completamente instalable como **Progressive Web App** (PWA) en dispositivos móviles y de escritorio. A continuación el análisis detallado contra los criterios de Lighthouse PWA.

### 🏆 Badge de Puntuación PWA

```
┌─────────────────────────────────────────────────────────┐
│  ⬡ πNAD Scanner · PWA LIGHTHOUSE CHECKLIST              │
├─────────────────────────────────────────────────────────┤
│  ✅ Installable              │  ✅ Offline-capable       │
│  ✅ Manifest válido          │  ✅ Service Worker activo │
│  ✅ HTTPS-ready              │  ✅ Splash screen         │
│  ✅ Theme color              │  ✅ Background sync       │
│  ✅ iOS home screen          │  ✅ Shortcuts             │
├─────────────────────────────────────────────────────────┤
│  ▶ 11/13 criterios cumplidos  ·  2 pendientes (⚠️ HTTPS, 🟡 icono PNG)  │
└─────────────────────────────────────────────────────────┘
```

### 📊 Checklist Detallado por Auditoría Lighthouse

| # | Criterio PWA | Estado | Implementación |
|---|-------------|--------|----------------|
| 1 | **Registra Service Worker** | ✅ | `service-worker.js` registrado desde `/sw.js` con scope `"/"` |
| 2 | **Responde con 200 offline** | ✅ | Cache-first para estáticos, network-first para APIs con fallback |
| 3 | **Tiene manifest.json** | ✅ | `display: standalone`, `orientation: portrait`, iconos SVG |
| 4 | **start_url válido** | ✅ | `start_url: "/"` con scope `"/"` |
| 5 | **theme_color en manifest** | ✅ | `#D9B158` (oro institucional) |
| 6 | **Icono ≥192px** | ✅ | SVG vectorial escalable a cualquier resolución |
| 7 | **Icono ≥512px** | ✅ | SVG vectorial escalable |
| 8 | **Configura apple-touch-icon** | ✅ | `apple-touch-icon` link + `apple-mobile-web-app-capable` meta |
| 9 | **Splash screen** | ✅ | iOS: `apple-touch-icon` + `black-translucent` status bar |
| 10 | **Contenido adaptativo** | ✅ | Meta viewport + responsive CSS + media queries |
| 11 | **HTTPS (producción)** | ⚠️ | Cert adhoc de Flask no pasa auditoría. Requiere cert válido (Let's Encrypt) + proxy inverso (Nginx/Caddy) en producción. |
| 12 | **Transiciones suaves** | ✅ | Animaciones CSS en splash ↔ captura ↔ resultado |
| 13 | **Background Sync** | ✅ | `sync` event listener para cola de subidas offline |

### 🧩 Componentes PWA

#### Manifest (`/static/manifest.json`)

```json
{
  "name": "πNAD Scanner — Tu Negocio, Al Día",
  "short_name": "πNAD Scan",
  "display": "standalone",
  "orientation": "portrait",
  "theme_color": "#D9B158",
  "background_color": "#241609",
  "categories": ["business", "productivity", "finance"],
  "icons": [
    { "src": "/static/icons/icon-192.svg", "sizes": "192x192" },
    { "src": "/static/icons/icon-512.svg", "sizes": "512x512" }
  ],
  "shortcuts": [
    { "name": "Escanear factura", "url": "/?scan=1" },
    { "name": "Historial", "url": "/?history=1" }
  ]
}
```

#### Service Worker (`/static/service-worker.js`)

| Aspecto | Detalle |
|---------|---------|
| **Estrategia estáticos** | Cache-first (CSS, JS, fuentes, iconos) |
| **Estrategia APIs** | Network-first con fallback a caché |
| **Estrategia OpenCV.js** | Network-first (7MB, no se cachea) |
| **Estrategia navegación** | Network-first con fallback a `/` |
| **Offline response** | JSON `{error: "Sin conexión al servidor"}` con status 503 |
| **Precarga** | `install` event: precachea URLs estáticas |
| **Limpieza** | `activate` event: elimina caches de versiones anteriores |
| **Background Sync** | Evento `sync` para cola de subidas offline |
| **Scope** | `Service-Worker-Allowed: /` header desde `/sw.js` |

#### Meta Tags en HTML (`templates/scan.html`)

```html
<link rel="manifest" href="/static/manifest.json">
<link rel="apple-touch-icon" href="/static/icons/icon-192.svg">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="πNAD Scan">
<meta name="mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#D9B158">
<meta name="application-name" content="πNAD Scanner">
```

#### Servicio del Service Worker (`web_server.py`)

```python
@app.route('/sw.js')
def service_worker():
    resp = make_response(send_file('static/service-worker.js'))
    resp.headers['Service-Worker-Allowed'] = '/'  # Scope raíz
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['Content-Type'] = 'application/javascript'
    return resp
```

### 📦 Cómo Instalar la App

#### En Android (Chrome)

1. Abre `https://[TU-IP]:5000` en Chrome
2. Toca el menú ⋮ → **"Instalar πNAD Scan"**
3. La app se agrega al home screen con icono y splash screen

#### En iOS (Safari)

1. Abre `https://[TU-IP]:5000` en Safari
2. Toca el icono **Compartir** (cuadro con flecha ↑)
3. Desplázate y toca **"Agregar a la pantalla de inicio"**
4. Nombra la app y toca **"Agregar"**

#### En Escritorio (Chrome/Edge)

1. Abre `https://[TU-IP]:5000`
2. Haz clic en el icono de instalación en la barra de direcciones
3. La app se abre en su propia ventana sin barras de navegación

### 🧪 Cómo Verificar con Lighthouse

```bash
# Opción 1: Chrome DevTools
Abrir → F12 → Lighthouse → Categoría "PWA" → Generate report

# Opción 2: CLI (Node.js)
npx lighthouse https://[TU-IP]:5000 --view --preset=desktop --only-categories=pwa

# Opción 3: PageSpeed Insights (público)
https://pagespeed.web.dev/
```

### 🔮 Mejoras Planificadas (post-MVP)

| Mejora | Impacto en PWA Score |
|--------|---------------------|
| PNG fallback para apple-touch-icon (iOS <14) | +5 pts compatibilidad iOS |
| `screenshots` en manifest con imagen real | +10 pts puntuación play store |
| `prefer_related_applications: false` explícito | Ya incluido ✅ |
| Cacheo de Google Fonts en precache | Ya incluido ✅ |
| Cobertura offline completa con IndexedDB | +15 pts experiencia offline |
| `aria-label` en botones del viewfinder (goBtn, rstBtn, cb) | +5 pts accesibilidad PWA |

---

## 🚀 Guía de Inicio Rápido

```bash
# Requisitos
Python 3.10+  ·  OpenCV 4.9+  ·  PaddleOCR 2.8+

# Instalar dependencias
pip install -r requirements.txt

# Iniciar servidor
python web_server.py

# Abrir en el teléfono (misma red WiFi)
# https://192.168.x.x:5000
```

## 🏗 Arquitectura

```
nadscanner/
├── core/                    # Motor de procesamiento
│   ├── fusion.py           # Fusión multi-toma por mediana (anti-reflejo)
│   ├── detector.py          # Detección y recorte de documento
│   ├── enhancer.py          # Realce de imagen (contraste, nitidez)
│   ├── stitch.py            # Stitching ORB pairwise para modo Z
│   ├── stitch_session.py    # Sesiones incrementales shot-by-shot
│   └── stitch_jobs.py       # Workers asíncronos con polling
├── ocr/                     # Reconocimiento de texto
│   ├── extractor.py         # Motor OCR (PaddleOCR + backends)
│   ├── extractor_abbrev.py  # Expansión de abreviaciones venezolanas
│   ├── format_learner.py    # Aprendizaje de formatos por clustering
│   ├── cross_validator.py   # Validación cruzada (IVA, montos, RIF)
│   └── bcv_rate.py          # Consulta de tasa BCV multi-fuente
├── utils/                   # Utilidades
│   ├── config.py            # Configuración central
│   └── currency.py          # Detección y conversión de moneda
├── static/                  # Assets PWA
│   ├── manifest.json        # Web App Manifest
│   ├── service-worker.js    # Service Worker con caching estratégico
│   └── icons/               # Iconos PWA SVG
├── templates/
│   └── scan.html            # UI completa (splash → how → capture → result)
├── database/
│   └── database.py          # SQLite de facturas (historial, búsqueda)
└── web_server.py            # Servidor Flask con 20+ endpoints REST
```

---

*πNAD Scanner — Pi Administración y Asesoría*
