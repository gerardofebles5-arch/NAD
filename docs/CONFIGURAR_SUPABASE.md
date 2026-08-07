# Configurar Supabase - NAD Scanner

Este documento guía la configuración de Supabase para NAD Scanner.

## Paso 1: Crear Cuenta Supabase

1. Ir a https://supabase.com/
2. Click en "Start your project"
3. Iniciar sesión con Google (usar `Ktorrealba@negocioaldia.app`)
4. Crear nuevo proyecto:
   - **Name:** `nadscanner-production`
   - **Database Password:** Generar contraseña segura (guardarla)
   - **Region:** Seleccionar región más cercana (ej. South America East)
5. Esperar 2-3 minutos mientras se crea el proyecto

## Paso 2: Obtener Credenciales

1. En el dashboard de Supabase, ir a **Settings** > **API**
2. Copiar los siguientes valores:
   - **Project URL:** `https://your-project.supabase.co`
   - **anon key:** `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...`

## Paso 3: Configurar Variables de Entorno

1. Copiar `.env.example` a `.env`:
```bash
cp .env.example .env
```

2. Editar `.env` y agregar las credenciales de Supabase:
```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key-here
```

## Paso 4: Ejecutar Script SQL

1. En el dashboard de Supabase, ir a **SQL Editor**
2. Click en "New query"
3. Copiar el contenido de `supabase_schema.sql`
4. Pegar en el editor SQL
5. Click en "Run" para ejecutar el script

El script creará:
- 5 tablas: `clientes`, `facturas`, `correcciones_ocr`, `alertas_tasa_cambio`, `estados_financieros`
- Row Level Security (RLS) en todas las tablas
- Índices para optimizar búsquedas
- Funciones y triggers para actualizaciones automáticas

## Paso 5: Verificar Configuración

1. En el dashboard de Supabase, ir a **Table Editor**
2. Verificar que las 5 tablas estén creadas
3. Verificar que las políticas RLS estén activas (icono de candado en cada tabla)

## Paso 6: Probar Conexión

Ejecutar este script Python para verificar la conexión:

```python
from utils.supabase_client import get_supabase_client, is_configured

if is_configured():
    client = get_supabase_client()
    if client:
        print("✅ Conexión Supabase exitosa")
    else:
        print("❌ Error conectando a Supabase")
else:
    print("❌ Supabase no configurado en .env")
```

## Troubleshooting

**Error: "relation does not exist"**
- El script SQL no se ejecutó correctamente
- Revisa el SQL Editor para ver errores de ejecución

**Error: "new row violates row-level security policy"**
- Las políticas RLS están bloqueando las inserciones
- Verifica que las políticas estén configuradas correctamente en el script SQL

**Error: "connection refused"**
- Verifica que SUPABASE_URL y SUPABASE_KEY sean correctos en .env
- Verifica que el proyecto Supabase esté activo (no pausado)
