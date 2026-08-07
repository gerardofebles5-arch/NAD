import { useState, useRef } from 'react'
import { Camera, Upload, AlertCircle, X } from 'lucide-react'
import { processInvoice } from '../lib/api'

export default function Scanner() {
  const [capturing, setCapturing] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    if (files.length === 5) {
      setSelectedFiles(files)
      setError(null)
    } else {
      setError('Debes seleccionar exactamente 5 imágenes')
    }
  }

  const handleCapture = async () => {
    if (selectedFiles.length !== 5) {
      setError('Debes seleccionar exactamente 5 imágenes')
      return
    }

    setCapturing(true)
    setError(null)
    
    try {
      const response = await processInvoice(selectedFiles)
      
      if (response.success) {
        setResult(response)
      } else {
        setError('Error al procesar la factura')
      }
    } catch (err) {
      console.error('Error processing invoice:', err)
      setError('Error al conectar con el servidor de procesamiento')
    } finally {
      setCapturing(false)
    }
  }

  const removeFile = (index: number) => {
    setSelectedFiles(prev => prev.filter((_, i) => i !== index))
  }

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-gray-900">Escanear Factura</h2>

      {!result ? (
        <div className="bg-white rounded-lg shadow p-8">
          <div className="text-center">
            <div className="mx-auto flex items-center justify-center h-48 w-48 rounded-full bg-blue-100 mb-6">
              <Camera className="h-24 w-24 text-blue-600" />
            </div>
            <h3 className="text-lg font-medium text-gray-900 mb-2">
              Capturar Factura
            </h3>
            <p className="text-gray-600 mb-6">
              Selecciona 5 fotos de la factura para obtener el mejor resultado OCR
            </p>
            
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              onChange={handleFileSelect}
              className="hidden"
            />
            
            <button
              onClick={() => fileInputRef.current?.click()}
              className="inline-flex items-center px-6 py-3 border border-gray-300 text-base font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 mb-4"
            >
              Seleccionar Imágenes
            </button>

            {selectedFiles.length > 0 && (
              <div className="mb-4">
                <p className="text-sm text-gray-600 mb-2">
                  {selectedFiles.length}/5 imágenes seleccionadas
                </p>
                <div className="flex flex-wrap gap-2 justify-center">
                  {selectedFiles.map((file, index) => (
                    <div key={index} className="relative inline-block">
                      <div className="w-16 h-16 bg-gray-200 rounded-lg flex items-center justify-center overflow-hidden">
                        <img
                          src={URL.createObjectURL(file)}
                          alt={`Shot ${index}`}
                          className="w-full h-full object-cover"
                        />
                      </div>
                      <button
                        onClick={() => removeFile(index)}
                        className="absolute -top-2 -right-2 bg-red-500 text-white rounded-full p-1"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <button
              onClick={handleCapture}
              disabled={capturing || selectedFiles.length !== 5}
              className="inline-flex items-center px-6 py-3 border border-transparent text-base font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {capturing ? 'Procesando...' : 'Procesar Factura'}
            </button>

            {error && (
              <div className="mt-4 flex items-center justify-center text-red-600">
                <AlertCircle className="w-5 h-5 mr-2" />
                {error}
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center mb-4">
            <div className="p-2 bg-green-100 rounded-lg">
              <Upload className="w-5 h-5 text-green-600" />
            </div>
            <h3 className="ml-3 text-lg font-medium text-gray-900">
              Resultado OCR
            </h3>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Número de Factura
              </label>
              <p className="text-gray-900">{result.ocr_data.numero_factura}</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                RIF Emisor
              </label>
              <p className="text-gray-900">{result.ocr_data.rif_emisor}</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Razón Social
              </label>
              <p className="text-gray-900">{result.ocr_data.razon_social}</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Fecha
              </label>
              <p className="text-gray-900">{result.ocr_data.fecha}</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Base Imponible
              </label>
              <p className="text-gray-900">${result.ocr_data.base_imponible?.toFixed(2) || '0.00'}</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                IVA
              </label>
              <p className="text-gray-900">${result.ocr_data.iva?.toFixed(2) || '0.00'}</p>
            </div>
            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Total
              </label>
              <p className="text-2xl font-bold text-gray-900">
                ${result.ocr_data.total?.toFixed(2) || '0.00'}
              </p>
            </div>
          </div>

          <div className="mt-4 p-4 bg-gray-50 rounded-lg">
            <p className="text-sm text-gray-600">
              <strong>Confianza OCR:</strong> {(result.ocr_confidence * 100).toFixed(1)}%
            </p>
            <p className="text-sm text-gray-600">
              <strong>Tiempo de procesamiento:</strong> {result.stats.time_seconds.toFixed(2)}s
            </p>
            {result.supabase_factura_id && (
              <p className="text-sm text-green-600">
                <strong>✓ Guardado en Supabase:</strong> {result.supabase_factura_id}
              </p>
            )}
          </div>

          <div className="mt-6 flex space-x-3">
            <button
              onClick={() => {
                setResult(null)
                setSelectedFiles([])
                setError(null)
              }}
              className="px-4 py-2 border border-gray-300 rounded-md text-gray-700 hover:bg-gray-50"
            >
              Nueva Captura
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
