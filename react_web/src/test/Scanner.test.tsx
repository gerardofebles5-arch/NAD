import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import Scanner from '../pages/Scanner'

// Mock the API function
vi.mock('../lib/api', () => ({
  processInvoice: vi.fn(() => Promise.resolve({
    success: true,
    ocr_data: {
      numero_factura: 'F001-000001',
      rif_emisor: 'J-12345678-9',
      razon_social: 'Proveedor A C.A.',
      fecha: '2026-08-04',
      total: 1500.00,
      base_imponible: 1250.00,
      iva: 250.00,
      moneda: 'VES'
    },
    ocr_confidence: 0.95,
    stats: { time_seconds: 2.5 }
  }))
}))

describe('Scanner', () => {
  it('renders scanner title', () => {
    render(
      <BrowserRouter>
        <Scanner />
      </BrowserRouter>
    )

    expect(screen.getByText('Escanear Factura')).toBeInTheDocument()
  })

  it('renders capture instructions', () => {
    render(
      <BrowserRouter>
        <Scanner />
      </BrowserRouter>
    )

    expect(screen.getByText(/Selecciona 5 fotos de la factura/)).toBeInTheDocument()
  })

  it('renders select images button', () => {
    render(
      <BrowserRouter>
        <Scanner />
      </BrowserRouter>
    )

    expect(screen.getByText('Seleccionar Imágenes')).toBeInTheDocument()
  })

  it('renders process button initially disabled', () => {
    render(
      <BrowserRouter>
        <Scanner />
      </BrowserRouter>
    )

    const processButton = screen.getByText('Procesar Factura')
    expect(processButton).toBeDisabled()
  })

  it('shows error when less than 5 files selected', () => {
    render(
      <BrowserRouter>
        <Scanner />
      </BrowserRouter>
    )

    // Usar querySelector en lugar de getByRole ya que el input está oculto
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['test'], 'test.jpg', { type: 'image/jpeg' })
    
    // Simular cambio de archivos
    Object.defineProperty(fileInput, 'files', {
      value: [file],
      writable: false
    })
    
    fireEvent.change(fileInput)
    
    expect(screen.getByText('Debes seleccionar exactamente 5 imágenes')).toBeInTheDocument()
  })
})
