import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || ''
const supabaseKey = import.meta.env.VITE_SUPABASE_KEY || ''

export const supabase = createClient(supabaseUrl, supabaseKey)

export type Database = {
  public: {
    Tables: {
      clientes: {
        Row: {
          id: string
          rif: string
          nombre: string
          creado_en: string
        }
        Insert: {
          id?: string
          rif: string
          nombre: string
          creado_en?: string
        }
        Update: {
          id?: string
          rif?: string
          nombre?: string
          creado_en?: string
        }
      }
      facturas: {
        Row: {
          id: string
          cliente_id: string
          numero_factura: string
          rif_emisor: string
          razon_social: string
          fecha: string
          total: number
          base_imponible: number
          iva: number
          moneda: string
          drive_file_id: string
          drive_file_url: string
          motor_ocr: string
          requiere_revision: boolean
          confidence: number
          creado_en: string
        }
        Insert: {
          id?: string
          cliente_id: string
          numero_factura: string
          rif_emisor: string
          razon_social?: string
          fecha: string
          total: number
          base_imponible?: number
          iva?: number
          moneda?: string
          drive_file_id: string
          drive_file_url: string
          motor_ocr?: string
          requiere_revision?: boolean
          confidence?: number
          creado_en?: string
        }
        Update: {
          id?: string
          cliente_id?: string
          numero_factura?: string
          rif_emisor?: string
          razon_social?: string
          fecha?: string
          total?: number
          base_imponible?: number
          iva?: number
          moneda?: string
          drive_file_id?: string
          drive_file_url?: string
          motor_ocr?: string
          requiere_revision?: boolean
          confidence?: number
          creado_en?: string
        }
      }
      estados_financieros: {
        Row: {
          id: string
          cliente_id: string
          periodo: string
          total_facturado: number
          iva_acumulado: number
          num_facturas: number
          por_moneda: Record<string, number>
          top_proveedores: Record<string, number>
          generado_en: string
        }
        Insert: {
          id?: string
          cliente_id: string
          periodo: string
          total_facturado: number
          iva_acumulado: number
          num_facturas: number
          por_moneda?: Record<string, number>
          top_proveedores?: Record<string, number>
          generado_en?: string
        }
        Update: {
          id?: string
          cliente_id?: string
          periodo?: string
          total_facturado?: number
          iva_acumulado?: number
          num_facturas?: number
          por_moneda?: Record<string, number>
          top_proveedores?: Record<string, number>
          generado_en?: string
        }
      }
    }
  }
}
