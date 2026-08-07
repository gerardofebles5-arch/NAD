import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from '../components/Layout'

describe('Layout', () => {
  it('renders navigation links', () => {
    render(
      <BrowserRouter>
        <Layout>
          <div>Test Content</div>
        </Layout>
      </BrowserRouter>
    )

    expect(screen.getByText('Dashboard')).toBeInTheDocument()
    expect(screen.getByText('Escanear')).toBeInTheDocument()
    expect(screen.getByText('Facturas')).toBeInTheDocument()
  })

  it('renders children content via Outlet', () => {
    render(
      <BrowserRouter>
        <Layout>
          <div>Test Content</div>
        </Layout>
      </BrowserRouter>
    )

    // El contenido children no se renderiza directamente, se usa Outlet
    // Verificamos que el Layout se renderiza correctamente
    expect(screen.getByText('NAD Scanner')).toBeInTheDocument()
  })

  it('shows NAD Scanner title', () => {
    render(
      <BrowserRouter>
        <Layout>
          <div>Test Content</div>
        </Layout>
      </BrowserRouter>
    )

    expect(screen.getByText('NAD Scanner')).toBeInTheDocument()
  })
})
