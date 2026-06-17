import { useState, useEffect } from 'react'
import { FolderOpen, Upload, Search, Database, Trash2, Plus, BookOpen, FileText, Tag } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import api from '../services/api'
import toast from 'react-hot-toast'

const CATEGORIES = [
  { id: '', name: '全部', icon: '📁' },
  { id: 'analysis', name: '投资分析', icon: '📊' },
  { id: 'strategy', name: '交易策略', icon: '🎯' },
  { id: 'quant', name: '量化策略', icon: '📈' },
  { id: 'market', name: '市场研究', icon: '🌐' },
  { id: 'research', name: '深度研报', icon: '📋' },
  { id: 'task', name: '工作任务', icon: '⏰' },
  { id: 'imported', name: '导入文档', icon: '📥' },
  { id: 'general', name: '通用文档', icon: '📄' },
]

export default function DocumentsPage() {
  const [docs, setDocs] = useState<any[]>([])
  const [category, setCategory] = useState('')
  const [viewDoc, setViewDoc] = useState<any>(null)
  const [kbStats, setKbStats] = useState({ documents: 0, chunks: 0 })
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<any[]>([])
  const [searchAnswer, setSearchAnswer] = useState('')
  const [searching, setSearching] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newContent, setNewContent] = useState('')
  const [newCategory, setNewCategory] = useState('general')
  const [addToKb, setAddToKb] = useState(false)
  const [showUrlImport, setShowUrlImport] = useState(false)
  const [importUrl, setImportUrl] = useState('')
  const [importTitle, setImportTitle] = useState('')
  const [importing, setImporting] = useState(false)

  useEffect(() => { loadDocs(); loadKbStats() }, [category])

  const loadDocs = async () => {
    try {
      const res = await api.get(`/api/documents/?category=${category}&limit=100`)
      setDocs(res.data.documents || [])
    } catch {}
  }

  const loadKbStats = async () => {
    try {
      const res = await api.get('/api/documents/kb/stats')
      setKbStats(res.data)
    } catch {}
  }

  const handleView = async (id: string) => {
    try {
      const res = await api.get(`/api/documents/${id}`)
      setViewDoc(res.data)
    } catch { toast.error('加载失败') }
  }

  const handleDelete = async (id: string) => {
    try {
      await api.delete(`/api/documents/${id}`)
      setDocs(prev => prev.filter(d => d.id !== id))
      if (viewDoc?.id === id) setViewDoc(null)
      toast.success('已删除')
      loadKbStats()
    } catch { toast.error('删除失败') }
  }

  const handleAddToKb = async (id: string) => {
    try {
      const res = await api.post(`/api/documents/${id}/add-to-kb`)
      if (res.data.success) {
        toast.success(`已添加到知识库 (${res.data.chunks} 个片段)`)
        loadDocs()
        loadKbStats()
      } else {
        toast.error(res.data.error || '添加失败')
      }
    } catch { toast.error('添加失败') }
  }

  const handleCreate = async () => {
    if (!newTitle.trim()) { toast.error('请输入标题'); return }
    try {
      await api.post('/api/documents/', {
        title: newTitle, category: newCategory, content: newContent,
        tags: [], source: 'user', add_to_kb: addToKb,
      })
      toast.success('文档已创建')
      setShowCreate(false)
      setNewTitle(''); setNewContent(''); setAddToKb(false)
      loadDocs(); loadKbStats()
    } catch { toast.error('创建失败') }
  }

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const form = new FormData()
    form.append('file', file)
    form.append('category', 'imported')
    form.append('add_to_kb', 'true')
    try {
      const res = await api.post('/api/documents/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      toast.success(`已上传: ${res.data.title}`)
      loadDocs(); loadKbStats()
    } catch { toast.error('上传失败') }
    e.target.value = ''
  }

  const handleKbSearch = async () => {
    if (!searchQuery.trim()) return
    setSearching(true)
    setSearchAnswer('')
    setSearchResults([])
    try {
      const res = await api.post('/api/documents/kb/search', { query: searchQuery, limit: 5 })
      setSearchAnswer(res.data.answer || '')
      setSearchResults(res.data.sources || [])
    } catch { toast.error('搜索失败') }
    setSearching(false)
  }

  const handleUrlImport = async () => {
    if (!importUrl.trim()) { toast.error('请输入URL'); return }
    setImporting(true)
    try {
      const res = await api.post('/api/documents/import-url', {
        url: importUrl, title: importTitle, category: 'imported', add_to_kb: true,
      })
      if (res.data.error) {
        toast.error(res.data.error)
      } else {
        toast.success(`已导入: ${res.data.title} (${res.data.chunks} 个知识片段)`)
        setShowUrlImport(false); setImportUrl(''); setImportTitle('')
        loadDocs(); loadKbStats()
      }
    } catch { toast.error('导入失败') }
    setImporting(false)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <FolderOpen className="w-6 h-6 text-accent-gold" /> 文档管理 & 知识库
        </h1>
        <div className="flex items-center gap-3">
          <div className="text-xs text-gray-500 flex items-center gap-2">
            <Database className="w-3 h-3" />
            知识库: {kbStats.documents} 文档 / {kbStats.chunks} 片段
            <button onClick={async () => {
              try {
                toast.loading('重建索引中...')
                const res = await api.post('/api/documents/kb/reindex')
                toast.dismiss()
                toast.success(`已重建: ${res.data.documents} 文档, ${res.data.chunks} 片段`)
                loadKbStats()
              } catch { toast.dismiss(); toast.error('重建失败') }
            }} className="text-[10px] px-1.5 py-0.5 bg-surface-hover text-gray-400 rounded hover:text-white">
              重建索引
            </button>
          </div>
          <button onClick={() => setShowCreate(true)} className="btn-primary flex items-center gap-1 text-sm">
            <Plus className="w-4 h-4" /> 新建
          </button>
          <button onClick={() => setShowUrlImport(true)} className="btn-secondary flex items-center gap-1 text-sm">
            <BookOpen className="w-4 h-4" /> URL导入
          </button>
          <label className="btn-secondary flex items-center gap-1 text-sm cursor-pointer">
            <Upload className="w-4 h-4" /> 文件导入
            <input type="file" className="hidden" accept=".txt,.md,.csv,.json,.html,.pdf" onChange={handleUpload} />
          </label>
        </div>
      </div>

      {/* 知识库搜索 */}
      <div className="card">
        <h2 className="text-sm font-semibold text-gray-400 mb-3 flex items-center gap-2">
          <Search className="w-4 h-4" /> 知识库语义搜索
          <span className="text-[10px] text-gray-600 font-normal">pgvector + Titan Embed</span>
        </h2>
        <div className="flex gap-3">
          <input className="input-field flex-1" value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleKbSearch()} placeholder="输入搜索内容, 语义匹配知识库..." />
          <button onClick={handleKbSearch} disabled={searching} className="btn-primary text-sm">
            {searching ? '搜索中...' : '搜索'}
          </button>
        </div>
        {searchAnswer && (
          <div className="mt-3 space-y-3">
            <div className="bg-surface-hover rounded-lg p-4 border border-accent-gold/20">
              <h4 className="text-xs text-accent-gold font-semibold mb-2">知识库回答</h4>
              <div className="report-container text-sm">
                <ReactMarkdown>{searchAnswer}</ReactMarkdown>
              </div>
            </div>
            {searchResults.length > 0 && (
              <div>
                <h4 className="text-[10px] text-gray-600 mb-1">参考来源</h4>
                <div className="flex flex-wrap gap-2">
                  {searchResults.map((s: any, i: number) => (
                    <span key={i} onClick={() => s.document_id && handleView(s.document_id)}
                      className="text-[10px] px-2 py-1 bg-surface-dark rounded border border-surface-border text-gray-400 cursor-pointer hover:text-primary-300 hover:border-primary-500/30">
                      {s.title || '文档'} ({(s.similarity * 100).toFixed(0)}%)
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
        {!searchAnswer && searchQuery && !searching && (
          <p className="mt-2 text-xs text-gray-600">未找到相关结果</p>
        )}
      </div>

      <div className="flex gap-6">
        {/* 左侧: 分类 + 文档列表 */}
        <div className="w-80 space-y-4">
          {/* 分类 */}
          <div className="card p-3">
            <div className="space-y-1">
              {CATEGORIES.map(c => (
                <button key={c.id} onClick={() => setCategory(c.id)}
                  className={`w-full text-left px-3 py-2 rounded-lg text-xs flex items-center gap-2 ${category === c.id ? 'bg-primary-500/20 text-primary-300' : 'text-gray-400 hover:bg-surface-hover'}`}>
                  <span>{c.icon}</span> {c.name}
                  {c.id === category && <span className="ml-auto text-[10px] text-gray-600">{docs.length}</span>}
                </button>
              ))}
            </div>
          </div>

          {/* 文档列表 */}
          <div className="space-y-1">
            {docs.map(d => (
              <div key={d.id} onClick={() => handleView(d.id)}
                className={`card p-3 cursor-pointer hover:border-primary-500/30 ${viewDoc?.id === d.id ? 'border-primary-500/50' : ''}`}>
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-white truncate">{d.title}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-[10px] text-gray-600">{d.file_type}</span>
                      <span className="text-[10px] text-gray-600">{(d.file_size / 1024).toFixed(1)}KB</span>
                      <span className="text-[10px] text-gray-600">{d.created_at?.split('T')[0]}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-1 ml-2">
                    {d.is_in_knowledge_base ? (
                      <Database className="w-3 h-3 text-accent-gold" />
                    ) : (
                      <button onClick={(e) => { e.stopPropagation(); handleAddToKb(d.id) }}
                        className="text-[10px] px-1.5 py-0.5 bg-primary-500/20 text-primary-300 rounded hover:bg-primary-500/30"
                        title="添加到知识库">+KB</button>
                    )}
                    <button onClick={(e) => { e.stopPropagation(); handleDelete(d.id) }}
                      className="p-0.5 text-gray-600 hover:text-red-400"><Trash2 className="w-3 h-3" /></button>
                  </div>
                </div>
              </div>
            ))}
            {docs.length === 0 && (
              <div className="text-center py-8 text-gray-600 text-sm">暂无文档</div>
            )}
          </div>
        </div>

        {/* 右侧: 文档内容 */}
        <div className="flex-1">
          {viewDoc ? (
            <div className="card">
              <div className="flex items-center justify-between mb-4 pb-3 border-b border-surface-border">
                <div>
                  <h2 className="text-lg text-white font-semibold">{viewDoc.title}</h2>
                  <div className="flex items-center gap-3 mt-1">
                    <span className="text-[10px] text-gray-500">{viewDoc.category}</span>
                    <span className="text-[10px] text-gray-500">{viewDoc.source}</span>
                    <span className="text-[10px] text-gray-500">{viewDoc.created_at?.split('T')[0]}</span>
                    {viewDoc.is_in_knowledge_base && (
                      <span className="text-[10px] px-1.5 py-0.5 bg-accent-gold/20 text-accent-gold rounded">知识库</span>
                    )}
                  </div>
                </div>
                {!viewDoc.is_in_knowledge_base && (
                  <button onClick={() => handleAddToKb(viewDoc.id)} className="btn-secondary text-xs flex items-center gap-1">
                    <Database className="w-3 h-3" /> 添加到知识库
                  </button>
                )}
              </div>
              {(viewDoc.content || '').includes('<div class="report"') ? (
                <div dangerouslySetInnerHTML={{ __html: viewDoc.content }} />
              ) : (
                <div className="report-container">
                  <ReactMarkdown>{viewDoc.content || '(空文档)'}</ReactMarkdown>
                </div>
              )}
            </div>
          ) : (
            <div className="card flex flex-col items-center justify-center py-16 text-center">
              <BookOpen className="w-12 h-12 text-gray-700 mb-3" />
              <p className="text-gray-500 text-sm">选择文档查看内容</p>
              <p className="text-gray-600 text-xs mt-1">或创建/导入新文档</p>
            </div>
          )}
        </div>
      </div>

      {/* 新建文档弹窗 */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowCreate(false)}>
          <div className="bg-surface-card border border-surface-border rounded-xl p-6 w-[600px] max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg text-white font-semibold mb-4">新建文档</h3>
            <div className="space-y-3">
              <input className="input-field" value={newTitle} onChange={e => setNewTitle(e.target.value)} placeholder="文档标题" />
              <select className="input-field" value={newCategory} onChange={e => setNewCategory(e.target.value)}>
                {CATEGORIES.filter(c => c.id).map(c => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
              <textarea className="input-field h-48" value={newContent} onChange={e => setNewContent(e.target.value)}
                placeholder="文档内容 (支持Markdown)" />
              <label className="flex items-center gap-2 text-sm text-gray-400">
                <input type="checkbox" checked={addToKb} onChange={e => setAddToKb(e.target.checked)} />
                同时添加到知识库
              </label>
              <div className="flex gap-3 justify-end">
                <button onClick={() => setShowCreate(false)} className="btn-secondary text-sm">取消</button>
                <button onClick={handleCreate} className="btn-primary text-sm">创建</button>
              </div>
            </div>
          </div>
        </div>
      )}
      {/* URL导入弹窗 */}
      {showUrlImport && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowUrlImport(false)}>
          <div className="bg-surface-card border border-surface-border rounded-xl p-6 w-[500px]" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg text-white font-semibold mb-4">从URL导入文档</h3>
            <div className="space-y-3">
              <input className="input-field" value={importUrl} onChange={e => setImportUrl(e.target.value)}
                placeholder="https://example.com/article" />
              <input className="input-field" value={importTitle} onChange={e => setImportTitle(e.target.value)}
                placeholder="文档标题 (留空自动提取)" />
              <p className="text-[10px] text-gray-500">将自动提取网页文本内容并添加到知识库</p>
              <div className="flex gap-3 justify-end">
                <button onClick={() => setShowUrlImport(false)} className="btn-secondary text-sm">取消</button>
                <button onClick={handleUrlImport} disabled={importing} className="btn-primary text-sm">
                  {importing ? '导入中...' : '导入'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
