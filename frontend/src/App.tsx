import { Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import { useAuthStore } from './store/authStore'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import MarketPage from './pages/MarketPage'
import PortfolioPage from './pages/PortfolioPage'
import StrategyPage from './pages/StrategyPage'
import QuantPage from './pages/QuantPage'
import ChatPage from './pages/ChatPage'
import SkillsPage from './pages/SkillsPage'
import AnalysisPage from './pages/AnalysisPage'
import SettingsPage from './pages/SettingsPage'
import DocumentsPage from './pages/DocumentsPage'
import SchedulerPage from './pages/SchedulerPage'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <>
      <Toaster
        position="top-right"
        toastOptions={{
          style: { background: '#1a2332', color: '#e5e7eb', border: '1px solid #2d3f52' },
        }}
      />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/*"
          element={
            <ProtectedRoute>
              <Layout>
                <Routes>
                  <Route path="/" element={<DashboardPage />} />
                  <Route path="/analysis" element={<AnalysisPage />} />
                  <Route path="/market" element={<MarketPage />} />
                  <Route path="/portfolio" element={<PortfolioPage />} />
                  <Route path="/strategy" element={<StrategyPage />} />
                  <Route path="/quant" element={<QuantPage />} />
                  <Route path="/chat" element={<ChatPage />} />
                  <Route path="/skills" element={<SkillsPage />} />
                  <Route path="/documents" element={<DocumentsPage />} />
                  <Route path="/scheduler" element={<SchedulerPage />} />
                  <Route path="/settings" element={<SettingsPage />} />
                </Routes>
              </Layout>
            </ProtectedRoute>
          }
        />
      </Routes>
    </>
  )
}
