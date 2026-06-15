import { useEffect, useState } from 'react'
import { Puzzle, Plus, Trash2, Package, Globe, Eye, Sparkles, X, Check, RefreshCw, Upload, Download, ToggleLeft, ToggleRight } from 'lucide-react'
import api from '../services/api'
import toast from 'react-hot-toast'

const statusColors: Record<string, string> = {
  APPROVED: 'bg-green-900/30 text-green-400',
  PENDING_APPROVAL: 'bg-yellow-900/30 text-yellow-400',
  DRAFT: 'bg-blue-900/30 text-blue-400',
  REJECTED: 'bg-red-900/30 text-red-400',
  DEPRECATED: 'bg-gray-800 text-gray-500',
}
const typeColors: Record<string, string> = {
  market: 'bg-green-900/30 text-green-400', analysis: 'bg-blue-900/30 text-blue-400',
  web: 'bg-purple-900/30 text-purple-400', trading: 'bg-red-900/30 text-red-400',
  quant: 'bg-yellow-900/30 text-yellow-400', notification: 'bg-cyan-900/30 text-cyan-400',
  external: 'bg-orange-900/30 text-orange-400',
}

const SKILL_TEMPLATES = [
  { id: 'analysis', name: '分析类Skill', desc: '技术指标/财务分析/估值模型', skeleton: '---\nname: my-analysis-skill\ndescription: >\n  自定义分析skill\nlicense: Apache-2.0\nmetadata:\n  category: analysis\nallowed-tools: my_tool\n---\n\n# My Analysis Skill\n\n## Tools\n### my_tool(stock_code)\n分析股票\n' },
  { id: 'trading', name: '交易类Skill', desc: '交易信号/风控/仓位管理', skeleton: '---\nname: my-trading-skill\ndescription: >\n  自定义交易skill\nlicense: Apache-2.0\nmetadata:\n  category: trading\nallowed-tools: my_tool\n---\n\n# My Trading Skill\n\n## Tools\n### my_tool(params)\n交易工具\n' },
  { id: 'quant', name: '量化类Skill', desc: '回测/因子/策略优化', skeleton: '---\nname: my-quant-skill\ndescription: >\n  自定义量化skill\nlicense: Apache-2.0\nmetadata:\n  category: quant\nallowed-tools: my_tool\n---\n\n# My Quant Skill\n\n## Tools\n### my_tool(params)\n量化工具\n' },
  { id: 'mcp', name: 'MCP Server', desc: 'Model Context Protocol服务', skeleton: '{\n  "name": "my-mcp-server",\n  "command": "uvx",\n  "args": ["my-mcp-package@latest"],\n  "env": {},\n  "disabled": false\n}' },
]

export default function SkillsPage() {
  const [records, setRecords] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [viewRecord, setViewRecord] = useState<any>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [createMode, setCreateMode] = useState<'template' | 'ai'>('template')
  const [createForm, setCreateForm] = useState({ name: '', description: '', content: '' })
  const [selectedTemplate, setSelectedTemplate] = useState('')
  const [aiDesc, setAiDesc] = useState('')
  const [aiLoading, setAiLoading] = useState(false)
  const [importUrl, setImportUrl] = useState('')
  const [importFile, setImportFile] = useState<File | null>(null)
  const [filter, setFilter] = useState('')

  useEffect(() => { loadRecords() }, [])

  const loadRecords = async () => {
    setLoading(true)
    try {
      const res = await api.get('/api/skills/registry')
      setRecords(res.data.records || [])
    } catch {}
    setLoading(false)
  }

  const handleViewRecord = async (recordId: string) => {
    try {
      const res = await api.get(`/api/skills/registry/${recordId}`)
      if (res.data.error) { toast.error(res.data.error); return }
      setViewRecord(res.data)
    } catch { toast.error('加载失败') }
  }

  const handleSelectTemplate = (tpl: any) => {
    setSelectedTemplate(tpl.id)
    setCreateForm({ name: '', description: tpl.desc, content: tpl.skeleton })
    setCreateMode('template')
  }

  const handleAiGenerate = async () => {
    if (!aiDesc) { toast.error('请描述Skill功能'); return }
    setAiLoading(true)
    try {
      const res = await api.post('/api/skills/ai-create', { description: aiDesc })
      if (res.data.error) { toast.error(res.data.error); setAiLoading(false); return }
      setCreateForm({ name: res.data.name, description: aiDesc, content: res.data.content })
      setCreateMode('template')
      toast.success('AI已生成SKILL.md')
    } catch { toast.error('生成失败') }
    setAiLoading(false)
  }

  const handleCreate = async () => {
    if (!createForm.name) { toast.error('请输入名称'); return }
    try {
      const res = await api.post('/api/skills/registry', createForm)
      if (res.data.error) { toast.error(res.data.error); return }
      toast.success(`已发布: ${res.data.name}`)
      setShowCreate(false)
      setCreateForm({ name: '', description: '', content: '' })
      loadRecords()
    } catch { toast.error('创建失败') }
  }

  const handleImportUrl = async () => {
    if (!importUrl) { toast.error('请输入URL'); return }
    try {
      const res = await api.post('/api/skills/import-github', { url: importUrl })
      if (res.data.error) { toast.error(res.data.error); return }
      toast.success(`已导入: ${res.data.name}`)
      setShowImport(false); setImportUrl('')
      loadRecords()
    } catch { toast.error('导入失败') }
  }

  const handleImportFile = async () => {
    if (!importFile) { toast.error('请选择文件'); return }
    try {
      const formData = new FormData()
      formData.append('file', importFile)
      const res = await api.post('/api/skills/import-file', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      if (res.data.error) { toast.error(res.data.error); return }
      toast.success(`已导入: ${res.data.name} (${res.data.content_length} bytes)`)
      setShowImport(false); setImportFile(null)
      loadRecords()
    } catch (err: any) { toast.error(err.response?.data?.detail || '导入失败') }
  }

  const handleDelete = async (recordId: string) => {
    try {
      await api.delete(`/api/skills/registry/${recordId}`)
      toast.success('已删除'); loadRecords()
      if (viewRecord?.record_id === recordId) setViewRecord(null)
    } catch { toast.error('删除失败') }
  }

  const handleApprove = async (recordId: string) => {
    try {
      await api.put(`/api/skills/registry/${recordId}/status?status=APPROVED`)
      toast.success('已批准'); loadRecords()
    } catch { toast.error('操作失败') }
  }

  const handleToggleEnabled = async (recordId: string, enabled: boolean) => {
    try {
      await api.post(`/api/skills/registry/${recordId}/enabled?enabled=${enabled}`)
      toast.success(enabled ? '已启用' : '已禁用'); loadRecords()
    } catch { toast.error('操作失败') }
  }

  const filtered = filter ? records.filter(r => r.status === filter || r.skill_type === filter) : records

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Puzzle className="w-6 h-6 text-accent-gold" /> Skill / MCP 管理
        </h1>
        <div className="flex gap-2">
          <button onClick={loadRecords} className="btn-secondary text-sm p-2"><RefreshCw className="w-4 h-4" /></button>
          <button onClick={() => { setShowImport(true); setShowCreate(false) }} className="btn-secondary flex items-center gap-1 text-sm">
            <Download className="w-4 h-4" /> 导入
          </button>
          <button onClick={() => { setShowCreate(true); setShowImport(false) }} className="btn-primary flex items-center gap-1 text-sm">
            <Plus className="w-4 h-4" /> 新建
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        {[
          { key: '', label: `全部 (${records.length})` },
          { key: 'APPROVED', label: `已批准 (${records.filter(r => r.status === 'APPROVED').length})` },
          { key: 'PENDING_APPROVAL', label: '待审批' },
          { key: 'DRAFT', label: '草稿' },
        ].map(f => (
          <button key={f.key} onClick={() => setFilter(f.key)}
            className={`px-3 py-1.5 rounded-lg text-xs ${filter === f.key ? 'bg-primary-500/20 text-primary-300 border border-primary-500/30' : 'bg-surface-hover text-gray-400 border border-surface-border'}`}>
            {f.label}
          </button>
        ))}
      </div>

      {/* 导入 */}
      {showImport && (
        <div className="card space-y-4">
          <h2 className="text-sm font-semibold text-white flex items-center gap-2"><Download className="w-4 h-4" /> 导入外部 Skill / MCP</h2>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-3">
              <p className="text-xs text-gray-400">从URL导入 (GitHub / 网络地址)</p>
              <input className="input-field" value={importUrl} onChange={e => setImportUrl(e.target.value)}
                placeholder="https://github.com/user/repo/tree/main/skills/my-skill" />
              <button onClick={handleImportUrl} disabled={!importUrl} className="btn-primary text-sm w-full disabled:opacity-50">导入URL</button>
            </div>
            <div className="space-y-3">
              <p className="text-xs text-gray-400">上传文件 (SKILL.md / ZIP / JSON)</p>
              <input type="file" accept=".md,.zip,.json,.yaml,.yml,.txt" onChange={e => setImportFile(e.target.files?.[0] || null)}
                className="input-field text-xs file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:bg-primary-500/20 file:text-primary-300 file:text-xs" />
              <p className="text-[10px] text-gray-600">ZIP文件会自动查找其中的SKILL.md或README.md</p>
              <button onClick={handleImportFile} disabled={!importFile} className="btn-primary text-sm w-full disabled:opacity-50">上传导入</button>
            </div>
          </div>
          <button onClick={() => setShowImport(false)} className="btn-secondary text-sm">取消</button>
        </div>
      )}

      {/* 新建 (模板 + AI合并) */}
      {showCreate && (
        <div className="card space-y-4">
          <h2 className="text-sm font-semibold text-white">新建 Skill / MCP</h2>

          {/* 模式切换 */}
          <div className="flex gap-2">
            <button onClick={() => setCreateMode('template')}
              className={`px-3 py-1.5 rounded-lg text-xs ${createMode === 'template' ? 'bg-primary-500/20 text-primary-300 border border-primary-500/30' : 'bg-surface-hover text-gray-400 border border-surface-border'}`}>
              选择模板
            </button>
            <button onClick={() => setCreateMode('ai')}
              className={`px-3 py-1.5 rounded-lg text-xs flex items-center gap-1 ${createMode === 'ai' ? 'bg-accent-gold/20 text-accent-gold border border-accent-gold/30' : 'bg-surface-hover text-gray-400 border border-surface-border'}`}>
              <Sparkles className="w-3 h-3" /> AI生成
            </button>
          </div>

          {/* AI模式 */}
          {createMode === 'ai' && (
            <div className="space-y-3">
              <textarea className="input-field h-20" value={aiDesc} onChange={e => setAiDesc(e.target.value)}
                placeholder="用自然语言描述Skill功能, 如: 创建一个计算股票夏普比率的工具, 输入股票代码和时间范围" />
              <button onClick={handleAiGenerate} disabled={aiLoading} className="btn-primary text-sm flex items-center gap-1">
                <Sparkles className="w-3 h-3" /> {aiLoading ? 'AI生成中...' : 'AI生成SKILL.md'}
              </button>
            </div>
          )}

          {/* 模板选择 */}
          {createMode === 'template' && !createForm.content && (
            <div className="grid grid-cols-4 gap-3">
              {SKILL_TEMPLATES.map(tpl => (
                <button key={tpl.id} onClick={() => handleSelectTemplate(tpl)}
                  className={`text-left p-3 rounded-lg border transition-all ${selectedTemplate === tpl.id ? 'bg-primary-500/20 border-primary-500/50' : 'bg-surface-hover border-surface-border hover:border-primary-500/30'}`}>
                  <p className="text-xs text-white font-medium">{tpl.name}</p>
                  <p className="text-[10px] text-gray-500 mt-1">{tpl.desc}</p>
                </button>
              ))}
            </div>
          )}

          {/* 编辑表单 (模板选择后或AI生成后显示) */}
          {createForm.content && (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <input className="input-field" value={createForm.name} onChange={e => setCreateForm({ ...createForm, name: e.target.value })} placeholder="skill-name (小写+连字符)" />
                <input className="input-field" value={createForm.description} onChange={e => setCreateForm({ ...createForm, description: e.target.value })} placeholder="描述" />
              </div>
              <textarea className="input-field h-56 font-mono text-xs" value={createForm.content} onChange={e => setCreateForm({ ...createForm, content: e.target.value })} />
              <div className="flex gap-3">
                <button onClick={handleCreate} className="btn-primary text-sm">发布到Registry</button>
                <button onClick={() => { setCreateForm({ name: '', description: '', content: '' }); setSelectedTemplate('') }} className="btn-secondary text-sm">重选模板</button>
                <button onClick={() => setShowCreate(false)} className="btn-secondary text-sm">取消</button>
              </div>
            </div>
          )}

          {!createForm.content && createMode !== 'ai' && (
            <button onClick={() => setShowCreate(false)} className="btn-secondary text-sm">取消</button>
          )}
        </div>
      )}

      {/* Records Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {filtered.map(r => {
          const enabled = r.enabled !== false
          return (
          <div key={r.record_id} className={`card transition-opacity ${enabled ? '' : 'opacity-50'}`}>
            <div className="flex items-start justify-between mb-2">
              <div className="flex items-center gap-2">
                {r.is_builtin ? <Package className="w-4 h-4 text-blue-400" /> : <Globe className="w-4 h-4 text-orange-400" />}
                <div>
                  <h3 className="text-white font-semibold text-sm">{r.display_name || r.name}</h3>
                  <p className="text-[10px] text-gray-500 font-mono">{r.name} v{r.version}</p>
                </div>
              </div>
              <div className="flex items-center gap-1">
                <span className={`text-[10px] px-1.5 py-0.5 rounded ${enabled ? 'bg-green-900/30 text-green-400' : 'bg-gray-800 text-gray-500'}`}>
                  {enabled ? '启用' : '禁用'}
                </span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded ${typeColors[r.skill_type] || 'bg-gray-800 text-gray-500'}`}>{r.skill_type}</span>
              </div>
            </div>
            <p className="text-xs text-gray-400 mb-2">{r.description?.slice(0, 120)}</p>
            <div className="flex items-center gap-2 pt-2 border-t border-surface-border/30">
              <button onClick={() => handleViewRecord(r.record_id)} className="text-[10px] text-primary-400 hover:text-primary-300 flex items-center gap-1">
                <Eye className="w-3 h-3" /> 查看
              </button>
              <button onClick={() => handleToggleEnabled(r.record_id, !enabled)}
                className={`text-[10px] flex items-center gap-1 ${enabled ? 'text-green-400 hover:text-green-300' : 'text-gray-500 hover:text-gray-300'}`}>
                {enabled ? <ToggleRight className="w-3.5 h-3.5" /> : <ToggleLeft className="w-3.5 h-3.5" />}
                {enabled ? '禁用' : '启用'}
              </button>
              {!r.is_builtin && (
                <button onClick={() => handleDelete(r.record_id)} className="text-[10px] text-gray-500 hover:text-red-400 flex items-center gap-1 ml-auto">
                  <Trash2 className="w-3 h-3" /> 删除
                </button>
              )}
            </div>
          </div>
          )
        })}
      </div>
      {loading && <div className="text-center py-8 text-gray-500">加载中...</div>}
      {!loading && filtered.length === 0 && <div className="text-center py-8 text-gray-600">暂无记录</div>}

      {/* View Record Modal */}
      {viewRecord && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setViewRecord(null)}>
          <div className="bg-surface-card border border-surface-border rounded-xl w-[750px] max-h-[85vh] overflow-hidden" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-surface-border">
              <div>
                <h3 className="text-sm text-white font-semibold">{viewRecord.name}</h3>
                <span className={`text-[9px] px-1.5 py-0.5 rounded ${statusColors[viewRecord.status] || ''}`}>{viewRecord.status}</span>
              </div>
              <button onClick={() => setViewRecord(null)} className="text-gray-500 hover:text-white"><X className="w-4 h-4" /></button>
            </div>
            {viewRecord.content && (
              <pre className="px-5 py-4 text-xs text-gray-300 font-mono overflow-auto max-h-[60vh] bg-surface-dark/50 whitespace-pre-wrap">{viewRecord.content}</pre>
            )}
            {viewRecord.raw && !viewRecord.content && (
              <pre className="px-5 py-4 text-[10px] text-gray-500 font-mono overflow-auto max-h-[60vh] bg-surface-dark">{viewRecord.raw}</pre>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
