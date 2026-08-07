import { useState, useEffect } from 'react'
import { supabase } from '../lib/supabase'
import { getMonthlySummary, getTopProviders } from '../lib/api'
import { BarChart3, TrendingUp, FileText, DollarSign } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, LineChart, Line } from 'recharts'

const COLORS = ['#2563eb', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6']

export default function Dashboard() {
  const [summary, setSummary] = useState<any>(null)
  const [topProviders, setTopProviders] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [year, setYear] = useState(new Date().getFullYear())
  const [month, setMonth] = useState(new Date().getMonth() + 1)

  useEffect(() => {
    fetchData()
  }, [year, month])

  const fetchData = async () => {
    try {
      // Por defecto, usar cliente_id de ejemplo
      const clienteId = 'default'
      
      const [summaryRes, providersRes] = await Promise.all([
        getMonthlySummary(clienteId, year, month),
        getTopProviders(clienteId, 10)
      ])

      setSummary(summaryRes.summary)
      setTopProviders(providersRes.providers)
    } catch (error) {
      console.error('Error fetching data:', error)
      // Datos de ejemplo si falla la conexión
      setSummary({
        periodo: `${year}-${month.toString().padStart(2, '0')}`,
        total_facturado: 125000,
        iva_acumulado: 18750,
        num_facturas: 45,
        por_moneda: { 'VES': 80000, 'USD': 45000 },
        top_proveedores: {}
      })
      setTopProviders([
        { nombre: 'Proveedor A C.A.', total: 35000, num_facturas: 15 },
        { nombre: 'Proveedor B C.A.', total: 28000, num_facturas: 12 },
        { nombre: 'Proveedor C C.A.', total: 22000, num_facturas: 10 },
      ])
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-500">Cargando...</div>
      </div>
    )
  }

  const currencyData = Object.entries(summary?.por_moneda || {}).map(([name, value]) => ({
    name,
    value
  }))

  const providerData = topProviders.map((p, i) => ({
    name: p.nombre,
    total: p.total,
    fill: COLORS[i % COLORS.length]
  }))

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold text-gray-900">Dashboard Financiero</h2>
        <div className="flex space-x-2">
          <select
            value={year}
            onChange={(e) => setYear(Number(e.target.value))}
            className="px-3 py-2 border border-gray-300 rounded-md"
          >
            <option value={2025}>2025</option>
            <option value={2026}>2026</option>
          </select>
          <select
            value={month}
            onChange={(e) => setMonth(Number(e.target.value))}
            className="px-3 py-2 border border-gray-300 rounded-md"
          >
            {Array.from({ length: 12 }, (_, i) => (
              <option key={i + 1} value={i + 1}>
                {new Date(2026, i).toLocaleString('es', { month: 'long' })}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center">
            <div className="p-3 bg-blue-100 rounded-lg">
              <DollarSign className="w-6 h-6 text-blue-600" />
            </div>
            <div className="ml-4">
              <p className="text-sm font-medium text-gray-600">Total Facturado</p>
              <p className="text-2xl font-bold text-gray-900">
                ${(summary?.total_facturado || 0).toLocaleString()}
              </p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center">
            <div className="p-3 bg-green-100 rounded-lg">
              <TrendingUp className="w-6 h-6 text-green-600" />
            </div>
            <div className="ml-4">
              <p className="text-sm font-medium text-gray-600">IVA Acumulado</p>
              <p className="text-2xl font-bold text-gray-900">
                ${(summary?.iva_acumulado || 0).toLocaleString()}
              </p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center">
            <div className="p-3 bg-purple-100 rounded-lg">
              <FileText className="w-6 h-6 text-purple-600" />
            </div>
            <div className="ml-4">
              <p className="text-sm font-medium text-gray-600">Facturas</p>
              <p className="text-2xl font-bold text-gray-900">{summary?.num_facturas || 0}</p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center">
            <div className="p-3 bg-orange-100 rounded-lg">
              <BarChart3 className="w-6 h-6 text-orange-600" />
            </div>
            <div className="ml-4">
              <p className="text-sm font-medium text-gray-600">Proveedores</p>
              <p className="text-2xl font-bold text-gray-900">{topProviders.length}</p>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Desglose por Moneda</h3>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={currencyData}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                outerRadius={80}
                fill="#8884d8"
                dataKey="value"
              >
                {currencyData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Top Proveedores</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={providerData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="total" fill="#2563eb" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Detalle de Proveedores</h3>
        <div className="space-y-3">
          {topProviders.map((proveedor, index) => (
            <div key={index} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
              <div className="flex items-center">
                <div className="w-3 h-3 rounded-full mr-3" style={{ backgroundColor: COLORS[index % COLORS.length] }} />
                <span className="font-medium text-gray-900">{proveedor.nombre}</span>
              </div>
              <div className="text-right">
                <span className="text-gray-900 font-medium">${proveedor.total.toLocaleString()}</span>
                <span className="text-gray-500 text-sm ml-2">({proveedor.num_facturas} facturas)</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
