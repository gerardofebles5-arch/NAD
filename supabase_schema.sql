-- ══════════════════════════════════════════════════════════════
--  Supabase Schema - NAD Scanner
-- ══════════════════════════════════════════════════════════════
-- Ejecutar este script en el SQL Editor de Supabase Dashboard
-- https://supabase.com/dashboard/project/YOUR_PROJECT/sql/new

-- ══════════════════════════════════════════════════════════════
--  Tabla: clientes
-- ══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS clientes (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    nombre TEXT NOT NULL,
    rif TEXT UNIQUE NOT NULL,
    email TEXT,
    telefono TEXT,
    plan TEXT DEFAULT 'free',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════
--  Tabla: facturas
-- ══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS facturas (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    cliente_id UUID REFERENCES clientes(id) ON DELETE CASCADE,
    numero_factura TEXT NOT NULL,
    numero_control TEXT,
    fecha DATE NOT NULL,
    rif_emisor TEXT NOT NULL,
    razon_social TEXT,
    direccion TEXT,
    telefono TEXT,
    base_imponible NUMERIC,
    iva NUMERIC,
    total NUMERIC NOT NULL,
    moneda TEXT DEFAULT 'BS',
    tasa_cambio NUMERIC,
    condicion_pago TEXT,
    ocr_confidence NUMERIC,
    motor_ocr TEXT DEFAULT 'paddleocr_vl',
    requiere_revision BOOLEAN DEFAULT FALSE,
    drive_file_id TEXT,
    raw_text TEXT,
    validation_errors JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════
--  Tabla: correcciones_ocr
-- ══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS correcciones_ocr (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    factura_id UUID REFERENCES facturas(id) ON DELETE CASCADE,
    campo TEXT NOT NULL,
    valor_incorrecto TEXT,
    valor_correcto TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════
--  Tabla: alertas_tasa_cambio
-- ══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS alertas_tasa_cambio (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    factura_id UUID REFERENCES facturas(id) ON DELETE CASCADE,
    moneda TEXT NOT NULL,
    tasa_detectada NUMERIC NOT NULL,
    tasa_referencia NUMERIC NOT NULL,
    nivel TEXT NOT NULL, -- 'advertencia' | 'critico'
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════
--  Tabla: estados_financieros
-- ══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS estados_financieros (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    cliente_id UUID REFERENCES clientes(id) ON DELETE CASCADE,
    periodo TEXT NOT NULL, -- '2026-08'
    total_facturado NUMERIC DEFAULT 0,
    iva_acumulado NUMERIC DEFAULT 0,
    num_facturas INTEGER DEFAULT 0,
    por_moneda JSONB DEFAULT '{}',
    top_proveedores JSONB DEFAULT '{}',
    generado_en TIMESTAMPTZ DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════
--  Row Level Security (RLS)
-- ══════════════════════════════════════════════════════════════

-- Habilitar RLS en todas las tablas
ALTER TABLE clientes ENABLE ROW LEVEL SECURITY;
ALTER TABLE facturas ENABLE ROW LEVEL SECURITY;
ALTER TABLE correcciones_ocr ENABLE ROW LEVEL SECURITY;
ALTER TABLE alertas_tasa_cambio ENABLE ROW LEVEL SECURITY;
ALTER TABLE estados_financieros ENABLE ROW LEVEL SECURITY;

-- Políticas para clientes
CREATE POLICY "Usuarios pueden ver sus propios clientes"
ON clientes FOR SELECT
USING (auth.uid()::text = id::text);

CREATE POLICY "Usuarios pueden insertar sus propios clientes"
ON clientes FOR INSERT
WITH CHECK (auth.uid()::text = id::text);

CREATE POLICY "Usuarios pueden actualizar sus propios clientes"
ON clientes FOR UPDATE
USING (auth.uid()::text = id::text);

-- Políticas para facturas
CREATE POLICY "Usuarios pueden ver sus propias facturas"
ON facturas FOR SELECT
USING (cliente_id IN (
    SELECT id FROM clientes WHERE auth.uid()::text = id::text
));

CREATE POLICY "Usuarios pueden insertar sus propias facturas"
ON facturas FOR INSERT
WITH CHECK (cliente_id IN (
    SELECT id FROM clientes WHERE auth.uid()::text = id::text
));

CREATE POLICY "Usuarios pueden actualizar sus propias facturas"
ON facturas FOR UPDATE
USING (cliente_id IN (
    SELECT id FROM clientes WHERE auth.uid()::text = id::text
));

-- Políticas para correcciones_ocr
CREATE POLICY "Usuarios pueden ver correcciones de sus facturas"
ON correcciones_ocr FOR SELECT
USING (factura_id IN (
    SELECT id FROM facturas WHERE cliente_id IN (
        SELECT id FROM clientes WHERE auth.uid()::text = id::text
    )
));

CREATE POLICY "Usuarios pueden insertar correcciones en sus facturas"
ON correcciones_ocr FOR INSERT
WITH CHECK (factura_id IN (
    SELECT id FROM facturas WHERE cliente_id IN (
        SELECT id FROM clientes WHERE auth.uid()::text = id::text
    )
));

-- Políticas para alertas_tasa_cambio
CREATE POLICY "Usuarios pueden ver alertas de sus facturas"
ON alertas_tasa_cambio FOR SELECT
USING (factura_id IN (
    SELECT id FROM facturas WHERE cliente_id IN (
        SELECT id FROM clientes WHERE auth.uid()::text = id::text
    )
));

CREATE POLICY "Usuarios pueden insertar alertas en sus facturas"
ON alertas_tasa_cambio FOR INSERT
WITH CHECK (factura_id IN (
    SELECT id FROM facturas WHERE cliente_id IN (
        SELECT id FROM clientes WHERE auth.uid()::text = id::text
    )
));

-- Políticas para estados_financieros
CREATE POLICY "Usuarios pueden ver sus estados financieros"
ON estados_financieros FOR SELECT
USING (cliente_id IN (
    SELECT id FROM clientes WHERE auth.uid()::text = id::text
));

CREATE POLICY "Usuarios pueden insertar sus estados financieros"
ON estados_financieros FOR INSERT
WITH CHECK (cliente_id IN (
    SELECT id FROM clientes WHERE auth.uid()::text = id::text
));

CREATE POLICY "Usuarios pueden actualizar sus estados financieros"
ON estados_financieros FOR UPDATE
USING (cliente_id IN (
    SELECT id FROM clientes WHERE auth.uid()::text = id::text
));

-- ══════════════════════════════════════════════════════════════
--  Índices para optimizar búsquedas
-- ══════════════════════════════════════════════════════════════

CREATE INDEX IF NOT EXISTS idx_facturas_cliente ON facturas(cliente_id);
CREATE INDEX IF NOT EXISTS idx_facturas_fecha ON facturas(fecha);
CREATE INDEX IF NOT EXISTS idx_facturas_rif ON facturas(rif_emisor);
CREATE INDEX IF NOT EXISTS idx_facturas_requiere_revision ON facturas(requiere_revision);
CREATE INDEX IF NOT EXISTS idx_facturas_motor_ocr ON facturas(motor_ocr);

CREATE INDEX IF NOT EXISTS idx_estados_financieros_cliente ON estados_financieros(cliente_id);
CREATE INDEX IF NOT EXISTS idx_estados_financieros_periodo ON estados_financieros(periodo);

CREATE INDEX IF NOT EXISTS idx_correcciones_factura ON correcciones_ocr(factura_id);
CREATE INDEX IF NOT EXISTS idx_alertas_factura ON alertas_tasa_cambio(factura_id);

-- ══════════════════════════════════════════════════════════════
--  Funciones útiles
-- ══════════════════════════════════════════════════════════════

-- Función para upsert estado financiero
CREATE OR REPLACE FUNCTION upsert_estado_financiero(
    p_cliente_id UUID,
    p_periodo TEXT,
    p_total_facturado NUMERIC,
    p_iva_acumulado NUMERIC,
    p_num_facturas INTEGER,
    p_por_moneda JSONB,
    p_top_proveedores JSONB
)
RETURNS VOID AS $$
BEGIN
    INSERT INTO estados_financieros (
        cliente_id, periodo, total_facturado, iva_acumulado,
        num_facturas, por_moneda, top_proveedores
    )
    VALUES (
        p_cliente_id, p_periodo, p_total_facturado, p_iva_acumulado,
        p_num_facturas, p_por_moneda, p_top_proveedores
    )
    ON CONFLICT (cliente_id, periodo)
    DO UPDATE SET
        total_facturado = EXCLUDED.total_facturado + p_total_facturado,
        iva_acumulado = EXCLUDED.iva_acumulado + p_iva_acumulado,
        num_facturas = EXCLUDED.num_facturas + p_num_facturas,
        por_moneda = EXCLUDED.por_moneda || p_por_moneda,
        top_proveedores = EXCLUDED.top_proveedores || p_top_proveedores,
        generado_en = NOW();
END;
$$ LANGUAGE plpgsql;

-- ══════════════════════════════════════════════════════════════
--  Triggers para actualizaciones automáticas
-- ══════════════════════════════════════════════════════════════

-- Trigger para actualizar estado financiero al insertar factura
CREATE OR REPLACE FUNCTION actualizar_estado_financiero_trigger()
RETURNS TRIGGER AS $$
DECLARE
    v_periodo TEXT;
BEGIN
    -- Calcular periodo (YYYY-MM)
    v_periodo := TO_CHAR(NEW.fecha, 'YYYY-MM');
    
    -- Llamar función upsert
    PERFORM upsert_estado_financiero(
        NEW.cliente_id,
        v_periodo,
        COALESCE(NEW.total, 0),
        COALESCE(NEW.iva, 0),
        1,
        jsonb_build_object(NEW.moneda, COALESCE(NEW.total, 0)),
        jsonb_build_object(COALESCE(NEW.razon_social, NEW.rif_emisor), COALESCE(NEW.total, 0))
    );
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Crear trigger
DROP TRIGGER IF EXISTS trigger_actualizar_estado_financiero ON facturas;
CREATE TRIGGER trigger_actualizar_estado_financiero
    AFTER INSERT ON facturas
    FOR EACH ROW
    EXECUTE FUNCTION actualizar_estado_financiero_trigger();
