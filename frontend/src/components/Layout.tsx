import { NavLink, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import {
  LayoutDashboard, TrendingUp, Briefcase,
  BarChart3, MessageSquare, Puzzle, LogOut, Bot,
  FileSearch, Settings, FolderOpen, Clock, FolderOutput,
} from 'lucide-react'

const navItems = [
  { to: '/', icon: LayoutDashboard, label: '总览' },
  { to: '/analysis', icon: FileSearch, label: '投资分析' },
  { to: '/market', icon: TrendingUp, label: '行情' },
  { to: '/portfolio', icon: Briefcase, label: '模拟盘' },
  { to: '/quant', icon: BarChart3, label: '量化策略' },
  { to: '/chat', icon: MessageSquare, label: 'AI助手' },
  { to: '/workspace', icon: FolderOutput, label: '工作区' },
  { to: '/documents', icon: FolderOpen, label: '文档知识库' },
  { to: '/scheduler', icon: Clock, label: '定期任务' },
  { to: '/skills', icon: Puzzle, label: 'Skill/MCP' },
  { to: '/settings', icon: Settings, label: '设置' },
]

export default function Layout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {/* 侧边栏 */}
      <aside className="w-60 bg-surface-card border-r border-surface-border flex flex-col">
        {/* Logo */}
        <div className="p-5 border-b border-surface-border">
          <div className="flex items-center gap-2">
            <Bot className="w-7 h-7 text-accent-gold" />
            <div>
              <h1 className="text-sm font-bold text-white">证券交易助手</h1>
              <p className="text-[10px] text-gray-500">Agent Platform</p>
            </div>
          </div>
        </div>

        {/* 导航 */}
        <nav className="flex-1 py-3 px-3 space-y-1 overflow-y-auto">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                  isActive
                    ? 'bg-primary-500/20 text-primary-300 border border-primary-500/30'
                    : 'text-gray-400 hover:bg-surface-hover hover:text-gray-200'
                }`
              }
            >
              <Icon className="w-4 h-4" />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* 用户信息 */}
        <div className="p-3 border-t border-surface-border">
          <div className="flex items-center justify-between">
            <div className="text-xs">
              <p className="text-gray-300 font-medium">{user?.full_name || user?.username}</p>
              <p className="text-gray-500">{user?.risk_preference === 'moderate' ? '稳健型' : user?.risk_preference === 'aggressive' ? '激进型' : '保守型'}</p>
            </div>
            <button onClick={handleLogout} className="p-1.5 text-gray-500 hover:text-gray-300 transition-colors">
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* 主内容 */}
      <main className="flex-1 overflow-y-auto bg-surface-dark">
        <div className="p-6">{children}</div>
      </main>
    </div>
  )
}
