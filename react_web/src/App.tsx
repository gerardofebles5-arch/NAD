import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Scanner from './pages/Scanner'
import Invoices from './pages/Invoices'
import Layout from './components/Layout'

function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/scanner" element={<Scanner />} />
          <Route path="/invoices" element={<Invoices />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}

export default App
