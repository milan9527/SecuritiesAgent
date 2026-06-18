import { useEffect, useState } from 'react'
import { Clock, Plus, Play, Trash2, Pause, CheckCircle, X, Sparkles, Edit3, Save, Mail } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import api from '../services/api'
import toast from 'react-hot-toast'

const TASK_EXAMPLES = [
  '每个工作日北京时间15点, 全面分析A股市场, 包括指数和个股、热点板块, 结合指标分析短期和中期趋势',
  '每周一早上9点, 检查自选股池中所有股票的买卖信号, 发送邮件通知',
  '每天收盘后16点, 生成今日投资组合绩效报告',
  '每周五下午3点, 搜索本周A股市场重大新闻和政策变化, 生成周报',
  '每个工作日14:30, 预测自选股和大盘明日走势, 标记预测结果供后续验证',
  '每周一9:00, 验证上周预测结果, 分析预测准确率, 总结经验教训并自我改进',
]

export default function SchedulerPage() {
  const [tasks, setTasks] = useState<any[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [desc, setDesc] = useState('')
  const [email, setEmail] = useState('')
  const [creating, setCreating] = useState(false)
  const [runResult, setRunResult] = useState<any>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState({ name: '', description: '', prompt: '', cron_expression: '', notification_email: '', notify_enabled: true })

  useEffect(() => { loadTasks(); loadUserEmail() }, [])

  const loadTasks = async () => {
    try { const r = await api.get('/api/scheduler/'); setTasks(r.data.tasks || []) } catch {}
  }

  const loadUserEmail = async () => {
    try {
      const r = await api.get('/api/auth/me')
      setEmail(r.data.notification_email_address || r.data.email || '')
    } catch {}
  }

  const handleCreate = async () => {
    if (!desc.trim()) { toast.error('请描述任务'); return }
    setCreating(true)
    try {
      const res = await api.post('/api/scheduler/', { description: desc, notification_email: email })
      if (res.data.error) { toast.error(res.data.error); return }
      toast.success(`任务已创建: ${res.data.name} (${res.data.cron_expression})`)
      setShowCreate(false); setDesc(''); loadTasks()
    } catch { toast.error('创建失败') }
    setCreating(false)
  }

  const handleDelete = async (id: string) => {
    try { await api.delete(`/api/scheduler/${id}`); toast.success('已删除'); loadTasks() } catch {}
  }

  const handleToggle = async (task: any) => {
    try {
      await api.put(`/api/scheduler/${task.id}`, { is_active: !task.is_active })
      toast.success(task.is_active ? '已暂停' : '已启用'); loadTasks()
    } catch {}
  }

  const startEdit = (t: any) => {
    setEditingId(t.id)
    setEditForm({
      name: t.name || '',
      description: t.description || '',
      prompt: t.prompt || '',
      cron_expression: t.cron_expression || '',
      notification_email: t.notification_email || '',
      notify_enabled: t.notify_enabled !== false,
    })
  }

  const handleSaveEdit = async () => {
    if (!editingId) return
    try {
      await api.put(`/api/scheduler/${editingId}`, editForm)
      toast.success('任务已更新')
      setEditingId(null)
      loadTasks()
    } catch { toast.error('更新失败') }
  }

  const handleRunNow = async (id: string) => {
    setRunResult({ id, loading: true, result: '' })
    try {
      const token = (() => { try { return JSON.parse(localStorage.getItem('auth-storage') || '{}').state?.token || '' } catch { return '' } })()
      const resp = await fetch(`${import.meta.env.VITE_API_URL || ''}/api/scheduler/${id}/run`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      })
      const contentType = resp.headers.get('content-type') || ''
      if (contentType.includes('text/event-stream')) {
        const reader = resp.body?.getReader(); const decoder = new TextDecoder(); let buf = '', result: any = null, streamText = ''
        if (reader) {
          while (true) {
            const { done, value } = await reader.read(); if (done) break
            buf += decoder.decode(value, { stream: true }); const lines = buf.split('\n'); buf = lines.pop() || ''
            for (const l of lines) {
              if (l.startsWith('data: ')) {
                try {
                  const p = JSON.parse(l.slice(6))
                  if (p.type === 'result') result = p
                  else if (p.type === 'text') { streamText += p.content; setRunResult({ id, loading: true, result: streamText }) }
                  else if (p.type === 'status') { setRunResult({ id, loading: true, result: streamText ? streamText + `\n\n_${p.content}_` : `_${p.content}_` }) }
                } catch {}
              }
            }
          }
        }
        setRunResult({ id, loading: false, result: result?.result || streamText || 'No response' })
      } else {
        const data = await resp.json()
        setRunResult({ id, loading: false, result: data.result || data.error || '' })
      }
      loadTasks()
    } catch (e: any) { setRunResult({ id, loading: false, result: `Error: ${e.message}` }) }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Clock className="w-6 h-6 text-accent-gold" /> 定期任务
        </h1>
        <button onClick={() => setShowCreate(true)} className="btn-primary flex items-center gap-1 text-sm">
          <Plus className="w-4 h-4" /> 新建任务
        </button>
      </div>

      {/* 创建任务 */}
      {showCreate && (
        <div className="card space-y-4">
          <h2 className="text-sm font-semibold text-white flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-accent-gold" /> 用自然语言创建定期任务
          </h2>
          <textarea className="input-field h-24" value={desc} onChange={e => setDesc(e.target.value)}
            placeholder="描述任务, 如: 每个工作日北京时间15点, 全面分析A股市场..." />
          <input className="input-field" value={email} onChange={e => setEmail(e.target.value)}
            placeholder="通知邮箱 (默认使用设置中的邮箱)" />
          <div className="flex flex-wrap gap-2">
            {TASK_EXAMPLES.map(ex => (
              <button key={ex} onClick={() => setDesc(ex)}
                className="text-[10px] px-2 py-1 bg-surface-hover rounded text-gray-500 hover:text-white text-left">{ex.slice(0, 40)}...</button>
            ))}
          </div>
          <div className="flex gap-3">
            <button onClick={handleCreate} disabled={creating} className="btn-primary text-sm">
              {creating ? 'AI解析中...' : '创建任务 (AI自动解析cron)'}
            </button>
            <button onClick={() => setShowCreate(false)} className="btn-secondary text-sm">取消</button>
          </div>
          <p className="text-[10px] text-gray-600">AI会自动将自然语言转为EventBridge cron表达式, 并生成Agent提示词</p>
        </div>
      )}

      {/* 任务列表 */}
      <div className="space-y-4">
        {tasks.map(t => (
          <div key={t.id} className={`card ${!t.is_active ? 'opacity-60' : ''}`}>
            {/* 编辑模式 */}
            {editingId === t.id ? (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-accent-gold flex items-center gap-2">
                    <Edit3 className="w-4 h-4" /> 编辑任务
                  </h3>
                  <button onClick={() => setEditingId(null)} className="text-gray-500 hover:text-white"><X className="w-4 h-4" /></button>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[10px] text-gray-500 mb-1 block">任务名称</label>
                    <input className="input-field text-sm" value={editForm.name}
                      onChange={e => setEditForm({ ...editForm, name: e.target.value })} />
                  </div>
                  <div>
                    <label className="text-[10px] text-gray-500 mb-1 block">Cron 表达式</label>
                    <input className="input-field text-sm font-mono" value={editForm.cron_expression}
                      onChange={e => setEditForm({ ...editForm, cron_expression: e.target.value })} />
                  </div>
                </div>
                <div>
                  <label className="text-[10px] text-gray-500 mb-1 block">任务描述</label>
                  <input className="input-field text-sm" value={editForm.description}
                    onChange={e => setEditForm({ ...editForm, description: e.target.value })} />
                </div>
                <div>
                  <label className="text-[10px] text-gray-500 mb-1 block">Agent 提示词</label>
                  <textarea className="input-field text-sm h-24" value={editForm.prompt}
                    onChange={e => setEditForm({ ...editForm, prompt: e.target.value })} />
                </div>
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-[10px] text-gray-500 flex items-center gap-1"><Mail className="w-3 h-3" /> 通知邮箱</label>
                    <label className="flex items-center gap-1.5 cursor-pointer text-[10px] text-gray-400">
                      <input type="checkbox" checked={editForm.notify_enabled}
                        onChange={e => setEditForm({ ...editForm, notify_enabled: e.target.checked })} />
                      {editForm.notify_enabled ? '邮件通知已启用' : '邮件通知已禁用'}
                    </label>
                  </div>
                  <input className="input-field text-sm disabled:opacity-50" value={editForm.notification_email}
                    disabled={!editForm.notify_enabled}
                    onChange={e => setEditForm({ ...editForm, notification_email: e.target.value })}
                    placeholder="留空则不发送通知" />
                  <p className="text-[10px] text-gray-600 mt-1">禁用后保留地址但不发送结果邮件</p>
                </div>
                <div className="flex gap-3">
                  <button onClick={handleSaveEdit} className="btn-primary text-sm flex items-center gap-1">
                    <Save className="w-3 h-3" /> 保存
                  </button>
                  <button onClick={() => setEditingId(null)} className="btn-secondary text-sm">取消</button>
                </div>
              </div>
            ) : (
              /* 显示模式 */
              <>
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <h3 className="text-white font-semibold text-sm flex items-center gap-2">
                      {t.is_active ? <CheckCircle className="w-4 h-4 text-green-400" /> : <Pause className="w-4 h-4 text-gray-500" />}
                      {t.name}
                    </h3>
                    <p className="text-xs text-gray-500 mt-1">{t.description}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`text-[10px] px-2 py-0.5 rounded font-mono ${t.is_active ? 'bg-green-900/30 text-green-400' : 'bg-gray-800 text-gray-500'}`}>
                      {t.cron_expression}
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-4 gap-3 text-xs mb-3">
                  <div className="bg-surface-hover rounded p-2">
                    <p className="text-gray-600">Agent提示词</p>
                    <p className="text-gray-400 mt-1 line-clamp-2">{t.prompt?.slice(0, 80)}</p>
                  </div>
                  <div className="bg-surface-hover rounded p-2">
                    <p className="text-gray-600">下次执行</p>
                    <p className="text-gray-400 mt-1">{t.next_run_at ? new Date(t.next_run_at).toLocaleString('zh-CN') : (t.is_active ? '计算中...' : '已暂停')}</p>
                  </div>
                  <div className="bg-surface-hover rounded p-2">
                    <p className="text-gray-600">上次执行</p>
                    <p className="text-gray-400 mt-1">{t.last_run_at ? new Date(t.last_run_at).toLocaleString('zh-CN') : '未执行'}</p>
                  </div>
                  <div className="bg-surface-hover rounded p-2">
                    <p className="text-gray-600">通知邮箱</p>
                    <p className="text-gray-400 mt-1">
                      {t.notification_email || '未设置'}
                      {t.notification_email && (
                        <span className={`ml-1.5 text-[10px] px-1 py-0.5 rounded ${t.notify_enabled !== false ? 'bg-green-900/30 text-green-400' : 'bg-gray-800 text-gray-500'}`}>
                          {t.notify_enabled !== false ? '已启用' : '已禁用'}
                        </span>
                      )}
                    </p>
                  </div>
                </div>

                {t.last_result && (
                  <div className="bg-surface-hover rounded p-2 mb-3 text-xs text-gray-400 max-h-20 overflow-hidden">
                    {t.last_result}
                  </div>
                )}

                <div className="flex gap-2 pt-2 border-t border-surface-border/30">
                  <button onClick={() => handleRunNow(t.id)} className="text-[10px] text-primary-400 hover:text-primary-300 flex items-center gap-1">
                    <Play className="w-3 h-3" /> 立即执行
                  </button>
                  <button onClick={() => startEdit(t)} className="text-[10px] text-accent-gold hover:text-yellow-300 flex items-center gap-1">
                    <Edit3 className="w-3 h-3" /> 编辑
                  </button>
                  <button onClick={() => handleToggle(t)} className="text-[10px] text-gray-400 hover:text-white flex items-center gap-1">
                    {t.is_active ? <><Pause className="w-3 h-3" /> 暂停</> : <><CheckCircle className="w-3 h-3" /> 启用</>}
                  </button>
                  <button onClick={() => handleDelete(t.id)} className="text-[10px] text-gray-500 hover:text-red-400 flex items-center gap-1 ml-auto">
                    <Trash2 className="w-3 h-3" /> 删除
                  </button>
                </div>

                {/* Run result */}
                {runResult?.id === t.id && (
                  <div className="mt-3 p-3 bg-surface-hover rounded-lg border border-surface-border/50">
                    {runResult.loading ? (
                      runResult.result ? (
                        <div className="report-container text-xs"><ReactMarkdown>{runResult.result}</ReactMarkdown></div>
                      ) : (
                        <p className="text-xs text-gray-500 flex items-center gap-2">
                          <span className="inline-flex gap-1">
                            <span className="w-1.5 h-1.5 bg-primary-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                            <span className="w-1.5 h-1.5 bg-primary-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                            <span className="w-1.5 h-1.5 bg-primary-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                          </span>
                          Agent 执行中...
                        </p>
                      )
                    ) : (
                      <div className="report-container text-xs"><ReactMarkdown>{runResult.result}</ReactMarkdown></div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        ))}
      </div>

      {tasks.length === 0 && !showCreate && (
        <div className="text-center py-12 text-gray-500">
          <Clock className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p>暂无定期任务</p>
          <p className="text-xs text-gray-600 mt-1">用自然语言创建, AI自动解析调度时间</p>
        </div>
      )}
    </div>
  )
}
