import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { Bot, TrendingUp, Shield, Zap, UserPlus, LogIn } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [mode, setMode] = useState<'login' | 'register'>('login')
  // 默认按已启用 Cognito 渲染, 消除首屏 config 未返回时的界面闪烁;
  // /api/auth/config 返回后会以真实值覆盖。
  const [authConfig, setAuthConfig] = useState<{ cognito_enabled: boolean; allow_registration: boolean }>({
    cognito_enabled: true,
    allow_registration: true,
  })
  const login = useAuthStore((s) => s.login)
  const navigate = useNavigate()

  useEffect(() => {
    api.get('/api/auth/config').then(r => setAuthConfig(r.data)).catch(() => {})
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username.trim() || !password.trim()) { toast.error('请输入用户名和密码'); return }
    setLoading(true)
    try {
      if (mode === 'register') {
        if (!email.trim()) { toast.error('请输入邮箱'); setLoading(false); return }
        const res = await api.post('/api/auth/register', { username, password, email })
        const { access_token } = res.data
        useAuthStore.setState({ token: access_token, isAuthenticated: true })
        api.defaults.headers.common['Authorization'] = `Bearer ${access_token}`
        await useAuthStore.getState().fetchUser()
        toast.success('注册成功')
        navigate('/')
      } else {
        await login(username, password)
        toast.success('登录成功')
        navigate('/')
      }
    } catch (err: any) {
      const detail = err.response?.data?.detail || err.response?.data?.error
      if (mode === 'register') {
        toast.error(detail || '注册失败')
      } else {
        toast.error(detail || '登录失败，请检查用户名和密码')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex">
      {/* Left brand area */}
      <div className="hidden lg:flex lg:w-1/2 bg-gradient-to-br from-primary-900 via-primary-800 to-surface-dark items-center justify-center p-12">
        <div className="max-w-md">
          <div className="flex items-center gap-3 mb-8">
            <Bot className="w-12 h-12 text-accent-gold" />
            <div>
              <h1 className="text-3xl font-bold text-white">证券交易助手</h1>
              <p className="text-primary-300 text-sm">Securities Trading Assistant</p>
            </div>
          </div>
          <p className="text-gray-300 text-lg mb-10 leading-relaxed">
            智能证券交易平台，AI驱动的投资分析、交易策略和量化回测。
          </p>
          <div className="space-y-4">
            {[
              { icon: TrendingUp, title: '投资分析', desc: '基本面+技术面全方位分析，AI生成投资报告' },
              { icon: Shield, title: '智能交易', desc: '实时监控买卖信号，模拟盘交易验证' },
              { icon: Zap, title: '量化回测', desc: '预置量化模板，自定义策略，历史回测验证' },
            ].map(({ icon: Icon, title, desc }) => (
              <div key={title} className="flex items-start gap-3">
                <div className="p-2 bg-primary-500/20 rounded-lg">
                  <Icon className="w-5 h-5 text-accent-gold" />
                </div>
                <div>
                  <h3 className="text-white font-medium text-sm">{title}</h3>
                  <p className="text-gray-400 text-xs">{desc}</p>
                </div>
              </div>
            ))}
          </div>

          {authConfig.cognito_enabled && (
            <div className="mt-8 pt-6 border-t border-primary-700/50">
              <div className="flex items-center gap-2 text-xs text-primary-300">
                <Shield className="w-4 h-4" />
                <span>Amazon Cognito 安全认证</span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Right login/register form */}
      <div className="flex-1 flex items-center justify-center p-8 bg-surface-dark">
        <div className="w-full max-w-sm">
          <div className="lg:hidden flex items-center gap-2 mb-8 justify-center">
            <Bot className="w-8 h-8 text-accent-gold" />
            <h1 className="text-xl font-bold text-white">证券交易助手</h1>
          </div>

          {/* Mode toggle */}
          {authConfig.allow_registration && (
            <div className="flex mb-6 bg-surface-card rounded-lg p-1 border border-surface-border">
              <button
                onClick={() => setMode('login')}
                className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-md text-sm transition-all ${
                  mode === 'login'
                    ? 'bg-primary-500/20 text-primary-300 border border-primary-500/30'
                    : 'text-gray-500 hover:text-gray-300'
                }`}
              >
                <LogIn className="w-4 h-4" /> 登录
              </button>
              <button
                onClick={() => setMode('register')}
                className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-md text-sm transition-all ${
                  mode === 'register'
                    ? 'bg-accent-gold/20 text-accent-gold border border-accent-gold/30'
                    : 'text-gray-500 hover:text-gray-300'
                }`}
              >
                <UserPlus className="w-4 h-4" /> 注册
              </button>
            </div>
          )}

          <h2 className="text-2xl font-bold text-white mb-2">
            {mode === 'register' ? '创建账户' : '登录'}
          </h2>
          <p className="text-gray-500 text-sm mb-6">
            {mode === 'register'
              ? '注册新账户，自动创建股票池和定期任务'
              : '登录您的账户开始使用'}
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1.5">用户名</label>
              <input type="text" value={username} onChange={(e) => setUsername(e.target.value)}
                className="input-field" placeholder="输入用户名" required autoComplete="username" />
            </div>

            {mode === 'register' && (
              <div>
                <label className="block text-xs text-gray-400 mb-1.5">邮箱</label>
                <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                  className="input-field" placeholder="输入邮箱" required autoComplete="email" />
              </div>
            )}

            <div>
              <label className="block text-xs text-gray-400 mb-1.5">密码</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                className="input-field" placeholder={mode === 'register' ? '至少8位，含大小写字母和数字' : '输入密码'}
                required autoComplete={mode === 'register' ? 'new-password' : 'current-password'} />
            </div>

            <button type="submit" disabled={loading}
              className={`w-full py-2.5 rounded-lg font-medium text-sm disabled:opacity-50 transition-all ${
                mode === 'register'
                  ? 'bg-accent-gold/20 text-accent-gold border border-accent-gold/30 hover:bg-accent-gold/30'
                  : 'btn-primary'
              }`}>
              {loading
                ? (mode === 'register' ? '注册中...' : '登录中...')
                : (mode === 'register' ? '注册' : '登录')}
            </button>
          </form>

          {mode === 'register' && (
            <p className="text-center text-[10px] text-gray-600 mt-4">
              注册后自动创建默认股票池、模拟盘和定期任务
            </p>
          )}

          {!authConfig.allow_registration && (
            <p className="text-center text-xs text-gray-600 mt-6">
              账户由管理员创建和管理
            </p>
          )}

          {authConfig.cognito_enabled && (
            <div className="mt-6 pt-4 border-t border-surface-border text-center">
              <p className="text-[10px] text-gray-600 flex items-center justify-center gap-1">
                <Shield className="w-3 h-3" /> Amazon Cognito 安全认证
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
