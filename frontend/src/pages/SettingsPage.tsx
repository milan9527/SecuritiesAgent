import { useEffect, useState } from 'react'
import { Settings, Cpu, Database, Check, Sliders } from 'lucide-react'
import api from '../services/api'
import toast from 'react-hot-toast'

const TOKEN_PRESETS = [
  { label: '4K', value: 4096 },
  { label: '8K', value: 8192 },
  { label: '16K', value: 16384 },
  { label: '32K', value: 32768 },
  { label: '64K', value: 65536 },
]

export default function SettingsPage() {
  const [models, setModels] = useState<any[]>([])
  const [activeModel, setActiveModel] = useState('')
  const [maxTokens, setMaxTokens] = useState(16384)
  const [sources, setSources] = useState<any[]>([])
  const [switching, setSwitching] = useState(false)
  const [notifyEmail, setNotifyEmail] = useState('')
  const [userEmail, setUserEmail] = useState('')
  const [sesStatus, setSesStatus] = useState<{ verified: boolean; status: string }>({ verified: false, status: '' })

  useEffect(() => { loadSettings() }, [])

  const loadSesStatus = async () => {
    try { const r = await api.get('/api/settings/ses-status'); setSesStatus(r.data) } catch {}
  }

  const loadSettings = async () => {
    try {
      const [modelsRes, sourcesRes, userRes] = await Promise.all([
        api.get('/api/settings/models'),
        api.get('/api/settings/data-sources'),
        api.get('/api/auth/me'),
      ])
      setModels(modelsRes.data.models || [])
      setActiveModel(modelsRes.data.active || '')
      setMaxTokens(modelsRes.data.max_tokens || 16384)
      setSources(sourcesRes.data.sources || [])
      setUserEmail(userRes.data.email || '')
      setNotifyEmail(userRes.data.notification_email_address || userRes.data.email || '')
      loadSesStatus()
    } catch {}
  }

  const handleSwitchModel = async (key: string) => {
    setSwitching(true)
    try {
      await api.post('/api/settings/models/switch', { model_key: key })
      setActiveModel(key)
      toast.success(`已切换到 ${models.find(m => m.key === key)?.name || key}`)
      loadSettings()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || '切换失败')
    }
    setSwitching(false)
  }

  const handleUpdateMaxTokens = async (value: number) => {
    setMaxTokens(value)
    try {
      await api.post('/api/settings/models/max-tokens', { max_tokens: value })
      toast.success(`Max Tokens 已更新为 ${value.toLocaleString()}`)
    } catch (err: any) {
      toast.error(err.response?.data?.detail || '更新失败')
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white flex items-center gap-2">
        <Settings className="w-6 h-6 text-accent-gold" />
        系统设置
      </h1>

      {/* Max Tokens 配置 */}
      <div className="card">
        <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
          <Sliders className="w-5 h-5 text-yellow-400" />
          Max Tokens
        </h2>
        <p className="text-xs text-gray-500 mb-4">
          控制LLM单次响应的最大token数。更大的值允许更详细的分析报告，但会增加延迟和成本。
          分析任务建议 16K+，简单对话 4K-8K 即可。
        </p>
        <div className="space-y-3">
          {/* 快捷预设 */}
          <div className="flex gap-2">
            {TOKEN_PRESETS.map(p => (
              <button
                key={p.value}
                onClick={() => handleUpdateMaxTokens(p.value)}
                className={`px-4 py-2 rounded-lg text-sm font-mono transition-all ${
                  maxTokens === p.value
                    ? 'bg-accent-gold/20 text-accent-gold border border-accent-gold/50'
                    : 'bg-surface-hover text-gray-400 border border-surface-border hover:border-accent-gold/30'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
          {/* 滑块 */}
          <div className="flex items-center gap-4">
            <input
              type="range"
              min={1024}
              max={65536}
              step={1024}
              value={maxTokens}
              onChange={e => setMaxTokens(parseInt(e.target.value))}
              onMouseUp={() => handleUpdateMaxTokens(maxTokens)}
              onTouchEnd={() => handleUpdateMaxTokens(maxTokens)}
              className="flex-1 h-2 bg-surface-hover rounded-lg appearance-none cursor-pointer accent-accent-gold"
            />
            <span className="text-sm font-mono text-accent-gold w-20 text-right">{maxTokens.toLocaleString()}</span>
          </div>
          <p className="text-[10px] text-gray-600">范围: 1,024 - 65,536 tokens</p>
        </div>
      </div>

      {/* LLM模型切换 */}
      <div className="card">
        <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
          <Cpu className="w-5 h-5 text-blue-400" />
          LLM 模型
        </h2>
        <p className="text-xs text-gray-500 mb-4">选择 Agent 及全平台 LLM 调用使用的模型，设置全局生效（所有后端实例与 Agent Runtime）。</p>
        <div className="max-w-xl">
          <label className="block text-xs text-gray-500 mb-1.5">当前模型</label>
          <div className="relative">
            <select
              value={activeModel}
              disabled={switching}
              onChange={(e) => handleSwitchModel(e.target.value)}
              className="input-field appearance-none pr-9 cursor-pointer disabled:opacity-60"
            >
              {models.map((m: any) => (
                <option key={m.key} value={m.key} className="bg-surface-dark text-gray-100">
                  {m.name} · {m.provider} (CTX {m.context_window} / OUT {m.max_output})
                </option>
              ))}
            </select>
            <Cpu className="w-4 h-4 text-gray-500 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
          </div>
          {(() => {
            const cur = models.find((m: any) => m.key === activeModel)
            return cur ? (
              <div className="mt-3 p-3 rounded-lg bg-surface-hover border border-surface-border">
                <div className="flex items-center gap-2">
                  <Check className="w-3.5 h-3.5 text-green-400" />
                  <span className="text-sm font-medium text-white">{cur.name}</span>
                  <span className="text-[10px] px-1.5 py-0.5 bg-surface-dark rounded text-gray-500">{cur.provider}</span>
                </div>
                <p className="text-[11px] text-gray-500 mt-1.5">{cur.description}</p>
                <p className="text-[9px] text-gray-700 font-mono mt-1">{cur.id}</p>
              </div>
            ) : null
          })()}
        </div>
      </div>

      {/* 通知邮箱设置 */}
      <div className="card">
        <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
          <Settings className="w-5 h-5 text-accent-gold" />
          通知邮箱 (SES)
        </h2>
        <p className="text-xs text-gray-500 mb-3">定期任务执行结果将以HTML格式邮件发送到此邮箱。首次使用需要验证邮箱。</p>

        {/* SES verification status */}
        <div className={`flex items-center gap-2 px-3 py-2 rounded-lg mb-4 text-xs ${
          sesStatus.verified
            ? 'bg-green-900/20 border border-green-800/30 text-green-400'
            : sesStatus.status === 'Pending'
            ? 'bg-yellow-900/20 border border-yellow-800/30 text-yellow-400'
            : 'bg-gray-800/50 border border-surface-border text-gray-500'
        }`}>
          <span className={`w-2 h-2 rounded-full ${sesStatus.verified ? 'bg-green-400' : sesStatus.status === 'Pending' ? 'bg-yellow-400 animate-pulse' : 'bg-gray-600'}`} />
          {sesStatus.verified
            ? `✅ ${notifyEmail} 已验证，可以接收HTML邮件`
            : sesStatus.status === 'Pending'
            ? `⏳ ${notifyEmail} 验证待确认，请查收邮件并点击确认链接`
            : '未验证 — 请输入邮箱并点击"验证邮箱"'}
        </div>

        <div className="flex gap-3 items-end">
          <div className="flex-1">
            <label className="text-xs text-gray-400 mb-1 block">通知邮箱地址</label>
            <input className="input-field" value={notifyEmail} onChange={e => setNotifyEmail(e.target.value)} placeholder="your@email.com" />
          </div>
          <button onClick={async () => {
            try {
              await api.put('/api/auth/profile', { notification_email_address: notifyEmail })
              setUserEmail(notifyEmail)
              toast.success('通知邮箱已更新')
              loadSesStatus()
            } catch (err: any) { toast.error(err.response?.data?.detail || err.response?.data?.error || '更新失败') }
          }} className="btn-primary text-sm">保存</button>
          <button onClick={async () => {
            if (!notifyEmail) { toast.error('请先输入邮箱'); return }
            try {
              toast.loading('处理中...')
              const res = await api.post('/api/settings/test-email', { to_email: notifyEmail })
              toast.dismiss()
              if (res.data.status === 'sent') {
                toast.success(res.data.message)
              } else if (res.data.status === 'verification_sent') {
                toast.success(res.data.message, { duration: 10000 })
                setSesStatus({ verified: false, status: 'Pending' })
              } else if (res.data.status === 'pending') {
                toast.success(res.data.message, { duration: 8000 })
              } else {
                toast.error(res.data.message || '操作失败')
              }
              loadSesStatus()
            } catch (err: any) { toast.dismiss(); toast.error(err.response?.data?.detail || '操作失败') }
          }} className={`text-sm ${sesStatus.verified ? 'btn-secondary' : 'bg-accent-gold/20 text-accent-gold border border-accent-gold/30 px-3 py-1.5 rounded-lg hover:bg-accent-gold/30'}`}>
            {sesStatus.verified ? '发送测试邮件' : '验证邮箱'}
          </button>
        </div>

        <div className="mt-3 text-[10px] text-gray-600 space-y-1">
          <p>使用流程: ① 输入邮箱 → ② 点击"验证邮箱" → ③ 查收AWS验证邮件并点击确认 → ④ 发送测试邮件</p>
          <p>当前配置: AWS SES (us-east-1) · {sesStatus.verified ? 'HTML邮件已就绪' : '待验证'}</p>
        </div>
      </div>

      {/* 行情数据源 */}
      <div className="card">
        <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
          <Database className="w-5 h-5 text-green-400" />
          行情数据源
        </h2>
        <p className="text-xs text-gray-500 mb-4">可用的行情数据接口，在行情页面和分析页面可选择使用</p>
        <div className="space-y-2">
          {sources.map((s: any) => (
            <div key={s.id} className="flex items-center justify-between bg-surface-hover rounded-lg p-3 border border-surface-border/50">
              <div>
                <p className="text-sm text-white font-medium">{s.name}</p>
                <p className="text-xs text-gray-500">{s.description}</p>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-gray-600 font-mono">{s.type}</span>
                <span className={`w-2 h-2 rounded-full ${s.status === 'active' ? 'bg-green-500' : 'bg-gray-600'}`} />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 飞书渠道配置 */}
      <FeishuConfig />
    </div>
  )
}

function FeishuConfig() {
  const [config, setConfig] = useState<any>(null)
  const [form, setForm] = useState({ app_id: '', app_secret: '', verification_token: '' })
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.get('/api/feishu/config').then(r => setConfig(r.data)).catch(() => {})
  }, [])

  const handleSave = async () => {
    setSaving(true)
    try {
      await api.post('/api/feishu/config', form)
      toast.success('飞书配置已保存')
      api.get('/api/feishu/config').then(r => setConfig(r.data))
    } catch (err: any) {
      toast.error(err.response?.data?.detail || '保存失败')
    }
    setSaving(false)
  }

  return (
    <div className="card">
      <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none"><path d="M3 12.5L12 3l9 9.5-4.5 4.5L12 12.5 7.5 17 3 12.5z" fill="#3370FF"/></svg>
        飞书机器人
      </h2>
      <p className="text-xs text-gray-500 mb-4">连接飞书，通过飞书消息与AI助手对话</p>

      {/* Status */}
      <div className={`flex items-center gap-2 px-3 py-2 rounded-lg mb-4 text-xs ${
        config?.configured
          ? 'bg-green-900/20 border border-green-800/30 text-green-400'
          : 'bg-gray-800/50 border border-surface-border text-gray-500'
      }`}>
        <span className={`w-2 h-2 rounded-full ${config?.configured ? 'bg-green-400' : 'bg-gray-600'}`} />
        {config?.configured ? `已配置 (App: ${config.app_id})` : '未配置'}
      </div>

      {/* Config form */}
      <div className="space-y-3">
        <div>
          <label className="text-xs text-gray-400 mb-1 block">App ID</label>
          <input className="input-field text-sm" value={form.app_id} onChange={e => setForm({...form, app_id: e.target.value})}
            placeholder="cli_xxxxxxxxxx" />
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1 block">App Secret</label>
          <input className="input-field text-sm" type="password" value={form.app_secret} onChange={e => setForm({...form, app_secret: e.target.value})}
            placeholder="飞书应用密钥" />
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1 block">Verification Token</label>
          <input className="input-field text-sm" value={form.verification_token} onChange={e => setForm({...form, verification_token: e.target.value})}
            placeholder="事件订阅验证Token" />
        </div>
        <button onClick={handleSave} disabled={saving || !form.app_id} className="btn-primary text-sm disabled:opacity-50">
          {saving ? '保存中...' : '保存配置'}
        </button>
      </div>

      {/* Instructions */}
      <div className="mt-4 pt-4 border-t border-surface-border space-y-2">
        <p className="text-[10px] text-gray-500 font-semibold">配置步骤:</p>
        <ol className="text-[10px] text-gray-600 space-y-1 list-decimal list-inside">
          <li>在<a href="https://open.feishu.cn/app" target="_blank" rel="noopener" className="text-primary-400 hover:underline">飞书开放平台</a>创建应用</li>
          <li>启用"机器人"能力</li>
          <li>配置事件订阅URL: <code className="bg-surface-hover px-1 rounded text-accent-gold">{window.location.origin}/api/feishu/webhook</code></li>
          <li>订阅事件: <code className="bg-surface-hover px-1 rounded">im.message.receive_v1</code></li>
          <li>在上方填入 App ID、App Secret、Verification Token</li>
        </ol>
      </div>
    </div>
  )
}
