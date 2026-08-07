# NAD Scanner - Frontend React

Frontend React con Vite para la aplicación NAD Scanner de escaneo de facturas con OCR y análisis financiero.

## Tecnologías

- **React 18** - Framework UI
- **Vite 8** - Build tool y dev server
- **Tailwind CSS** - Estilos
- **Recharts** - Gráficos financieros
- **React Router DOM** - Navegación
- **Lucide React** - Iconos
- **Supabase JS** - Cliente de base de datos
- **vite-plugin-pwa** - Configuración PWA

## Estructura del Proyecto

```
react_web/
├── src/
│   ├── components/
│   │   └── Layout.tsx          # Layout principal con navegación
│   ├── lib/
│   │   ├── api.ts              # Servicio API para conectar con backend Flask
│   │   └── supabase.ts         # Cliente Supabase con tipos TypeScript
│   ├── pages/
│   │   ├── Dashboard.tsx       # Dashboard financiero con gráficos
│   │   ├── Scanner.tsx         # Escáner de facturas
│   │   └── Invoices.tsx        # Lista de facturas
│   ├── App.tsx                 # Componente principal con router
│   └── index.css               # Estilos globales con Tailwind
├── public/                     # Archivos estáticos
├── vite.config.js              # Configuración de Vite y PWA
├── tailwind.config.js          # Configuración de Tailwind
└── postcss.config.js           # Configuración de PostCSS
```

## Instalación

```bash
cd react_web
npm install
```

## Variables de Entorno

Crear archivo `.env` basado en `.env.example`:

```env
VITE_API_BASE_URL=http://localhost:5000
VITE_SUPABASE_URL=your_supabase_project_url
VITE_SUPABASE_KEY=your_supabase_anon_key
```

## Desarrollo

```bash
npm run dev
```

El servidor de desarrollo se iniciará en `http://localhost:5173/`

## Build para Producción

```bash
npm run build
```

Los archivos compilados estarán en `dist/`

## PWA

La aplicación está configurada como PWA (Progressive Web App) con:
- Manifest para instalación
- Service worker para cache
- Actualización automática

## Páginas

### Dashboard
- Métricas financieras (total facturado, IVA acumulado, número de facturas)
- Gráfico de desglose por moneda (PieChart)
- Gráfico de top proveedores (BarChart)
- Filtros por año y mes
- Conectado con API del motor financiero

### Scanner
- Selección de 5 imágenes de factura
- Procesamiento OCR vía backend Flask
- Visualización de resultados con confianza y tiempo de procesamiento
- Integración automática con Supabase

### Invoices
- Lista de facturas desde Supabase
- Búsqueda por número, RIF o razón social
- Enlace a archivos en Google Drive
- Ordenamiento por fecha de creación

## API

El frontend se conecta con:

1. **Backend Flask** (`http://localhost:5000`)
   - `POST /process` - Procesamiento OCR de facturas
   - `GET /api/financial/monthly` - Resumen mensual
   - `GET /api/financial/top-providers` - Top proveedores
   - `GET /api/financial/currency-breakdown` - Desglose por moneda
   - `GET /api/financial/yearly` - Resumen anual

2. **Supabase**
   - Tabla `facturas` - Datos de facturas
   - Tabla `clientes` - Información de clientes
   - Tabla `estados_financieros` - Agregados financieros

## Dependencias

```json
{
  "dependencies": {
    "@supabase/supabase-js": "^2.x",
    "lucide-react": "^0.x",
    "react": "^18.x",
    "react-dom": "^18.x",
    "react-router-dom": "^6.x",
    "recharts": "^2.x"
  },
  "devDependencies": {
    "@tailwindcss/postcss": "^4.x",
    "autoprefixer": "^10.x",
    "tailwindcss": "^4.x",
    "vite": "^8.x",
    "vite-plugin-pwa": "^0.x"
  }
}
```

## Notas

- La aplicación usa datos de ejemplo cuando no hay conexión con el backend o Supabase
- Los gráficos de Recharts son responsivos y se adaptan al tamaño de pantalla
- El PWA permite instalación en dispositivos móviles
- Tailwind CSS v4 usa el nuevo plugin PostCSS

