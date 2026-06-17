import { useState, useEffect, useCallback } from 'react'
import { FolderOutput, FileCode, FileText, File, Download, Trash2, RefreshCw, FolderOpen } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import api from '../services/api'
import toast from 'react-hot-toast'

interface WsFile { path: string; size: number; modified_at: number; ext: string; category: string }

const CAT_ICON: Record<string, string> = { code: '💻', documents: '📄', data: '🗃️', skills: '🧩', general: '📁' }
const CAT_ORDER = ['code', 'documents', 'data', 'skills', 'general']

const TEXT_EXTS = ['.py', '.md', '.txt', '.json', '.csv', '.yaml', '.yml', '.html', '.js', '.ts', '.sh', '.ipynb', '.log', '.sql', '.toml', '.ini', '.tsv']
const CODE_EXTS = ['.py', '.js', '.ts', '.sh', '.sql', '.json', '.yaml', '.yml', '.toml', '.ini', '.html', '.csv', '.tsv', '.log']

function fmtSize(n: number) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
function fmtTime(ts: number) {
  return new Date(ts * 1000).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
function iconFor(ext: string) {
  if (CODE_EXTS.includes(ext)) return FileCode
  if (ext === '.md' || ext === '.txt') return FileText
  return File
}

export default function WorkspacePage() {
  const [files, setFiles] = useState<WsFile[]>([])
  const [catNames, setCatNames] = useState<Record<string, string>>({})
  const [activeCat, setActiveCat] = useState<string>('')   // '' = 全部
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<WsFile | null>(null)
  const [content, setContent] = useState('')
  const [contentLoading, setContentLoading] = useState(false)

  const baseUrl = import.meta.env.VITE_API_URL || ''
  const token = (() => {
    try { const s = localStorage.getItem('auth-storage'); return s ? JSON.parse(s).state?.token : '' } catch { return '' }
  })()

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.get('/api/workspace/files')
      setFiles(res.data.files || [])
      setCatNames(res.data.categories || {})
    } catch (err: any) {
      toast.error(err.response?.data?.error || '加载失败')
    }
    setLoading(false)
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const openFile = async (f: WsFile) => {
    setSelected(f)
    if (!TEXT_EXTS.includes(f.ext)) { setContent(''); return }
    setContentLoading(true)
    try {
      const res = await api.get(`/api/workspace/file?path=${encodeURIComponent(f.path)}`, { responseType: 'text', transformResponse: [(d) => d] })
      setContent(typeof res.data === 'string' ? res.data : JSON.stringify(res.data, null, 2))
    } catch (err: any) {
      setContent(`⚠️ ${err.response?.data?.error || '读取失败'}`)
    }
    setContentLoading(false)
  }

  const download = async (f: WsFile) => {
    try {
      const resp = await fetch(`${baseUrl}/api/workspace/file?path=${encodeURIComponent(f.path)}&download=true`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!resp.ok) throw new Error('下载失败')
      const blob = await resp.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = f.path.split('/').pop() || 'file'
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(url)
    } catch (err: any) {
      toast.error(err.message || '下载失败')
    }
  }

  const remove = async (f: WsFile, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm(`删除 ${f.path}？此操作不可恢复。`)) return
    try {
      await api.delete(`/api/workspace/file?path=${encodeURIComponent(f.path)}`)
      toast.success('已删除')
      if (selected?.path === f.path) { setSelected(null); setContent('') }
      refresh()
    } catch (err: any) {
      toast.error(err.response?.data?.error || '删除失败')
    }
  }

  const isMarkdown = selected?.ext === '.md'
  const isText = selected && TEXT_EXTS.includes(selected.ext)

  // 按类别分组 (受 activeCat 过滤); 维持 CAT_ORDER 顺序
  const shown = activeCat ? files.filter(f => f.category === activeCat) : files
  const counts: Record<string, number> = {}
  files.forEach(f => { counts[f.category] = (counts[f.category] || 0) + 1 })
  const presentCats = CAT_ORDER.filter(c => counts[c] > 0)
  const grouped: { cat: string; items: WsFile[] }[] = presentCats
    .map(c => ({ cat: c, items: shown.filter(f => f.category === c) }))
    .filter(g => g.items.length > 0)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <FolderOutput className="w-6 h-6 text-accent-gold" /> 工作区
          <span className="text-xs font-normal text-gray-500">Agent 产出物 · 持久保存于 EFS</span>
        </h1>
        <button onClick={refresh} className="btn-secondary flex items-center gap-2 text-sm">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> 刷新
        </button>
      </div>

      <div className="grid grid-cols-12 gap-4" style={{ height: 'calc(100vh - 10rem)' }}>
        {/* File list (按类别分组) */}
        <div className="col-span-4 card overflow-y-auto p-0">
          {/* 类别筛选 */}
          <div className="px-3 py-2.5 border-b border-surface-border sticky top-0 bg-surface-card z-10 flex flex-wrap gap-1.5">
            <button onClick={() => setActiveCat('')}
              className={`px-2 py-1 rounded-md text-[11px] ${activeCat === '' ? 'bg-primary-500/20 text-primary-300 border border-primary-500/30' : 'text-gray-500 border border-surface-border hover:text-gray-300'}`}>
              全部 {files.length}
            </button>
            {presentCats.map(c => (
              <button key={c} onClick={() => setActiveCat(c)}
                className={`px-2 py-1 rounded-md text-[11px] ${activeCat === c ? 'bg-primary-500/20 text-primary-300 border border-primary-500/30' : 'text-gray-500 border border-surface-border hover:text-gray-300'}`}>
                {CAT_ICON[c] || '📁'} {catNames[c] || c} {counts[c]}
              </button>
            ))}
          </div>

          {files.length === 0 && !loading && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <FolderOpen className="w-10 h-10 text-gray-700 mb-2" />
              <p className="text-sm text-gray-600">暂无产出物</p>
              <p className="text-xs text-gray-700 mt-1">AI 助手生成的代码/报告会保存在这里</p>
            </div>
          )}

          {grouped.map(({ cat, items }) => (
            <div key={cat}>
              <div className="px-4 py-1.5 bg-surface-dark/60 border-b border-surface-border/40 sticky top-[41px] z-[5]">
                <p className="text-[11px] font-medium text-gray-400">
                  {CAT_ICON[cat] || '📁'} {catNames[cat] || cat} · {items.length}
                </p>
              </div>
              <div className="divide-y divide-surface-border/40">
                {items.map((f) => {
                  const Icon = iconFor(f.ext)
                  const active = selected?.path === f.path
                  return (
                    <div key={f.path} onClick={() => openFile(f)}
                      className={`group px-4 py-3 cursor-pointer transition-colors ${active ? 'bg-primary-500/10' : 'hover:bg-surface-hover/40'}`}>
                      <div className="flex items-center gap-2">
                        <Icon className={`w-4 h-4 flex-shrink-0 ${active ? 'text-primary-300' : 'text-gray-500'}`} />
                        <span className={`text-sm truncate flex-1 ${active ? 'text-primary-200' : 'text-gray-300'}`}>{f.path}</span>
                        <button onClick={(e) => { e.stopPropagation(); download(f) }}
                          className="opacity-0 group-hover:opacity-100 p-1 text-gray-500 hover:text-accent-gold transition-all" title="下载">
                          <Download className="w-3.5 h-3.5" />
                        </button>
                        <button onClick={(e) => remove(f, e)}
                          className="opacity-0 group-hover:opacity-100 p-1 text-gray-500 hover:text-red-400 transition-all" title="删除">
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                      <div className="flex items-center gap-2 mt-1 ml-6">
                        <span className="text-[10px] text-gray-600">{fmtSize(f.size)}</span>
                        <span className="text-[10px] text-gray-700">· {fmtTime(f.modified_at)}</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
        </div>

        {/* Preview */}
        <div className="col-span-8 card overflow-y-auto">
          {!selected ? (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <FileCode className="w-12 h-12 text-gray-700 mb-3" />
              <p className="text-sm text-gray-600">选择左侧文件预览</p>
            </div>
          ) : (
            <div>
              <div className="flex items-center justify-between mb-4 pb-3 border-b border-surface-border">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-white truncate">{selected.path}</p>
                  <p className="text-[11px] text-gray-500 mt-0.5">{fmtSize(selected.size)} · {fmtTime(selected.modified_at)}</p>
                </div>
                <button onClick={() => download(selected)} className="btn-secondary flex items-center gap-2 text-sm flex-shrink-0">
                  <Download className="w-4 h-4" /> 下载
                </button>
              </div>

              {contentLoading ? (
                <p className="text-sm text-gray-500">加载中…</p>
              ) : !isText ? (
                <div className="flex flex-col items-center justify-center py-16 text-center">
                  <File className="w-10 h-10 text-gray-700 mb-2" />
                  <p className="text-sm text-gray-500">该文件类型不支持预览，请下载查看</p>
                </div>
              ) : isMarkdown ? (
                <div className="prose prose-invert prose-sm max-w-none
                  prose-headings:text-accent-gold prose-strong:text-white prose-p:text-gray-300
                  prose-table:text-xs prose-th:border prose-th:border-surface-border/50 prose-th:px-2 prose-th:py-1.5 prose-th:text-gray-400
                  prose-td:border prose-td:border-surface-border/50 prose-td:px-2 prose-td:py-1.5 prose-td:text-gray-300
                  prose-li:text-gray-300 prose-code:text-accent-gold prose-code:bg-surface-hover prose-code:px-1 prose-code:rounded
                  prose-blockquote:border-l-accent-gold prose-blockquote:text-gray-400">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
                </div>
              ) : (
                <pre className="text-xs text-gray-300 font-mono whitespace-pre-wrap break-words bg-surface-dark rounded-lg p-4 overflow-x-auto">
                  {content}
                </pre>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
