import { useState, useRef, useEffect, useCallback } from 'react'
import { Send, Bot, User, Sparkles, MessageSquarePlus, History, Clock, ChevronLeft, Trash2, Wrench, Brain, Users, ChevronRight, Terminal } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import api from '../services/api'
import toast from 'react-hot-toast'

// 一条 Agent 活动 (工具调用 / 子Agent / 思考), 在助手消息内折叠显示 (Claude Code 风格)
interface Activity {
  id: string
  kind: 'tool' | 'subagent' | 'thinking'
  label: string
  input?: string
  result?: string
  isError?: boolean
  done?: boolean
}
interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  activities?: Activity[]
  thinking?: string
  streaming?: boolean
}

// Agent presets with default skill mappings
const agentPresets: Record<string, { label: string; icon: string; skills: string[] }> = {
  orchestrator: { label: '智能助手', icon: '🤖', skills: ['market-data-skill', 'analysis-skill', 'web-fetch-skill', 'trading-skill', 'quant-skill', 'notification-skill', 'crawler-skill', 'browser-crawler-skill', 'code-interpreter-skill'] },
  analyst: { label: '投资分析', icon: '📊', skills: ['market-data-skill', 'analysis-skill', 'web-fetch-skill', 'crawler-skill', 'browser-crawler-skill', 'code-interpreter-skill'] },
  trader: { label: '股票交易', icon: '💹', skills: ['market-data-skill', 'analysis-skill', 'trading-skill', 'notification-skill'] },
  quant: { label: '量化交易', icon: '📈', skills: ['market-data-skill', 'quant-skill', 'code-interpreter-skill'] },
}

const samplesByFocus: Record<string, string[]> = {
  'market-data-skill': ['查询贵州茅台实时行情', '批量查询宁德时代、比亚迪行情'],
  'analysis-skill': ['分析贵州茅台的技术指标', '评估宁德时代的投资价值'],
  'web-fetch-skill': ['搜索今日A股市场最新动态', '查找新能源行业最新政策'],
  'trading-skill': ['用MACD+KDJ策略分析自选股买卖信号', '模拟买入比亚迪1000股', '创建均线底部聚集交易策略'],
  'quant-skill': ['用双均线策略回测贵州茅台', '列出所有量化策略模板'],
  'crawler-skill': ['爬取东方财富固态电池新闻', '获取中际旭创券商研报'],
  'notification-skill': ['生成今日投资报告'],
  'browser-crawler-skill': ['使用浏览器获取动态网页数据'],
  'code-interpreter-skill': ['执行Python代码分析数据'],
}

// 单条活动行 (可展开看 输入/结果)
function ActivityRow({ a }: { a: Activity }) {
  const [open, setOpen] = useState(false)
  const Icon = a.kind === 'subagent' ? Users : a.kind === 'thinking' ? Brain : (a.label?.includes('代码') ? Terminal : Wrench)
  return (
    <div className="rounded-md border border-surface-border/40 bg-surface-dark/40 overflow-hidden">
      <button onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-2 py-1.5 text-left hover:bg-surface-hover/30 transition-colors">
        <ChevronRight className={`w-3 h-3 text-gray-600 transition-transform ${open ? 'rotate-90' : ''}`} />
        <Icon className={`w-3.5 h-3.5 ${a.isError ? 'text-red-400' : a.done ? 'text-green-400' : 'text-primary-400'} ${!a.done ? 'animate-pulse' : ''}`} />
        <span className="text-[11px] text-gray-300 truncate flex-1">{a.label}</span>
        {!a.done && <span className="text-[9px] text-gray-600">运行中…</span>}
      </button>
      {open && (
        <div className="px-3 pb-2 space-y-1.5 text-[10px] font-mono">
          {a.input && <div><span className="text-gray-600">输入:</span> <span className="text-gray-400 break-all">{a.input}</span></div>}
          {a.result && <div><span className="text-gray-600">结果:</span> <span className={`break-all ${a.isError ? 'text-red-400' : 'text-gray-400'}`}>{a.result}</span></div>}
        </div>
      )}
    </div>
  )
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [agentType, setAgentType] = useState('orchestrator')
  const [sessionId, setSessionId] = useState(() => `chat-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`)
  const [sessions, setSessions] = useState<any[]>([])
  const [showSessions, setShowSessions] = useState(true)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const refreshSessions = useCallback(() => {
    api.get('/api/chat/sessions').then(r => setSessions(r.data.sessions || [])).catch(() => {})
  }, [])

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  useEffect(() => { refreshSessions() }, [refreshSessions])

  const loadSession = async (sid: string) => {
    try {
      const res = await api.get(`/api/chat/history?session_id=${sid}&limit=100`)
      const msgs = (res.data.messages || []).map((m: any) => ({
        role: m.role, content: m.content, timestamp: m.created_at,
      }))
      setMessages(msgs)
      setSessionId(sid)
    } catch {}
  }

  const newSession = () => {
    setSessionId(`chat-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`)
    setMessages([])
  }

  const deleteSession = async (sid: string, e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await api.delete(`/api/chat/history?session_id=${sid}`)
      setSessions(prev => prev.filter(s => s.session_id !== sid))
      if (sessionId === sid) newSession()
    } catch {}
  }

  const handleSend = async () => {
    if (!input.trim() || loading) return
    const userMsg: Message = { role: 'user', content: input, timestamp: new Date().toISOString() }
    // 追加用户消息 + 一条空的流式助手消息 (实时填充)
    setMessages(prev => [...prev, userMsg, {
      role: 'assistant', content: '', timestamp: new Date().toISOString(),
      activities: [], thinking: '', streaming: true,
    }])
    const currentInput = input
    setInput('')
    setLoading(true)

    // 仅更新最后一条 (流式助手) 消息
    const patchLast = (fn: (m: Message) => Message) =>
      setMessages(prev => {
        const next = [...prev]
        for (let i = next.length - 1; i >= 0; i--) {
          if (next[i].role === 'assistant') { next[i] = fn(next[i]); break }
        }
        return next
      })

    try {
      const token = (() => {
        try { const s = localStorage.getItem('auth-storage'); return s ? JSON.parse(s).state?.token : '' } catch { return '' }
      })()
      const baseUrl = import.meta.env.VITE_API_URL || ''
      const response = await fetch(`${baseUrl}/api/chat/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ message: currentInput, session_id: sessionId, agent_type: agentType }),
      })
      if (!response.ok) throw new Error(`Request failed with status ${response.status}`)

      const handleEvent = (e: any) => {
        switch (e.type) {
          case 'text':
            if (e.content) patchLast(m => ({ ...m, content: m.content + e.content }))
            break
          case 'thinking':
            if (e.content) patchLast(m => ({ ...m, thinking: (m.thinking || '') + e.content }))
            break
          case 'tool_use':
            patchLast(m => ({
              ...m,
              activities: [...(m.activities || []), {
                id: e.id || `${Date.now()}-${Math.random()}`,
                kind: e.subagent ? 'subagent' : 'tool',
                label: e.subagent ? `委派子Agent${e.subagent_type ? ' · ' + e.subagent_type : ''}` : (e.label || e.name),
                input: e.input,
              }],
            }))
            break
          case 'tool_result':
            patchLast(m => ({
              ...m,
              activities: (m.activities || []).map(a =>
                a.id === e.tool_use_id ? { ...a, result: e.preview, isError: e.is_error, done: true } : a),
            }))
            break
          case 'result':
            if (e.response) patchLast(m => ({ ...m, content: e.response }))
            break
          case 'done':
            patchLast(m => ({
              ...m,
              content: e.response || m.content,
              streaming: false,
              timestamp: e.timestamp || m.timestamp,
            }))
            break
          case 'error':
            patchLast(m => ({ ...m, content: m.content || `⚠️ ${e.message}`, streaming: false }))
            break
        }
      }

      const contentType = response.headers.get('content-type') || ''
      if (contentType.includes('text/event-stream')) {
        const reader = response.body?.getReader()
        const decoder = new TextDecoder()
        if (reader) {
          let buffer = ''
          while (true) {
            const { done, value } = await reader.read()
            if (done) break
            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split('\n')
            buffer = lines.pop() || ''
            for (const line of lines) {
              if (line.startsWith('data: ')) {
                try { handleEvent(JSON.parse(line.slice(6))) } catch {}
              }
            }
          }
          if (buffer.trim()) {
            for (const line of buffer.split('\n')) {
              if (line.startsWith('data: ')) { try { handleEvent(JSON.parse(line.slice(6))) } catch {} }
            }
          }
        }
      } else {
        const j = await response.json()
        handleEvent({ type: 'done', ...j })
      }
      patchLast(m => ({ ...m, streaming: false }))
      refreshSessions()
    } catch (err: any) {
      patchLast(m => ({ ...m, content: m.content || `⚠️ ${err.message}`, streaming: false }))
    }
    setLoading(false)
  }

  // 按当前 agent 预设给出示例提问
  const activeSamples = (agentPresets[agentType]?.skills || []).flatMap(sk => samplesByFocus[sk] || []).slice(0, 6)

  return (
    <div className="flex h-[calc(100vh-3rem)]">
      {/* Left panel: Session History */}
      <div className={`${showSessions ? 'w-64' : 'w-0'} transition-all duration-200 overflow-hidden border-r border-surface-border bg-surface-dark flex flex-col`}>
        <div className="p-3 border-b border-surface-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <History className="w-4 h-4 text-primary-400" />
            <h2 className="text-sm font-semibold text-white">会话历史</h2>
          </div>
          <button onClick={newSession}
            className="p-1.5 rounded-lg bg-primary-500/20 text-primary-300 hover:bg-primary-500/30 transition-colors"
            title="新建会话">
            <MessageSquarePlus className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {/* Current session indicator */}
          {messages.length > 0 && !sessions.some(s => s.session_id === sessionId) && (
            <div className="p-2.5 rounded-lg bg-primary-500/10 border border-primary-500/30 cursor-default">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
                <p className="text-[11px] text-primary-300 font-medium truncate">当前会话</p>
              </div>
              <p className="text-[10px] text-gray-500 mt-1 truncate ml-4">
                {messages[0]?.content?.slice(0, 40) || '新会话'}
              </p>
            </div>
          )}

          {sessions.length === 0 && messages.length === 0 && (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <Clock className="w-8 h-8 text-gray-700 mb-2" />
              <p className="text-[11px] text-gray-600">暂无历史会话</p>
              <p className="text-[10px] text-gray-700 mt-1">开始对话后自动保存</p>
            </div>
          )}

          {sessions.map(s => {
            const isActive = s.session_id === sessionId
            const timeStr = s.last_at ? new Date(s.last_at).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''
            return (
              <div key={s.session_id}
                onClick={() => loadSession(s.session_id)}
                className={`group p-2.5 rounded-lg border transition-all cursor-pointer ${isActive
                  ? 'bg-primary-500/10 border-primary-500/30'
                  : 'bg-surface-card/50 border-surface-border/30 hover:bg-surface-hover hover:border-surface-border'}`}>
                <div className="flex items-center justify-between">
                  <p className={`text-[11px] font-medium truncate flex-1 ${isActive ? 'text-primary-300' : 'text-gray-300'}`}>
                    {s.preview || '会话'}
                  </p>
                  <button onClick={(e) => deleteSession(s.session_id, e)}
                    className="opacity-0 group-hover:opacity-100 p-0.5 rounded text-gray-600 hover:text-red-400 transition-all"
                    title="删除会话">
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-[9px] text-gray-600">{timeStr}</span>
                  <span className="text-[9px] text-gray-700">· {s.message_count} 条</span>
                </div>
              </div>
            )
          })}
        </div>

        <div className="p-2 border-t border-surface-border">
          <p className="text-[9px] text-gray-700 text-center">
            AgentCore Memory · {sessions.length} 会话
          </p>
        </div>
      </div>

      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-surface-border">
          <div className="flex items-center gap-3">
            {/* Session toggle */}
            <button onClick={() => setShowSessions(!showSessions)}
              className={`p-1.5 rounded-lg transition-colors ${showSessions ? 'bg-primary-500/20 text-primary-300' : 'text-gray-500 hover:text-gray-300'}`}
              title={showSessions ? '隐藏会话历史' : '显示会话历史'}>
              {showSessions ? <ChevronLeft className="w-4 h-4" /> : <History className="w-4 h-4" />}
            </button>
            <Sparkles className="w-5 h-5 text-accent-gold" />
            <div>
              <h1 className="text-lg font-bold text-white">Agent Playground</h1>
              <p className="text-[10px] text-gray-500">
                金融通用 Agent · 写代码/跑程序/编排子Agent · 实时流式 · AgentCore Memory
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {/* Agent type selector */}
            {Object.entries(agentPresets).map(([key, preset]) => (
              <button key={key} onClick={() => setAgentType(key)}
                className={`px-2.5 py-1 rounded-lg text-[11px] ${agentType === key ? 'bg-primary-500/20 text-primary-300 border border-primary-500/30' : 'text-gray-500 border border-surface-border hover:text-gray-300'}`}>
                {preset.icon} {preset.label}
              </button>
            ))}
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <Bot className="w-14 h-14 text-gray-600 mb-4" />
              <h2 className="text-lg text-gray-400 mb-1">金融通用 AI Agent</h2>
              <p className="text-sm text-gray-600 mb-6">能写量化程序、跑回测、编排子Agent、联网研究 · 实时显示思考与工具调用 · 跨会话记忆</p>
              <div className="flex flex-wrap gap-2 justify-center max-w-lg">
                {activeSamples.map(s => (
                  <button key={s} onClick={() => setInput(s)}
                    className="px-3 py-1.5 bg-surface-card border border-surface-border rounded-full text-xs text-gray-400 hover:text-white hover:border-primary-500/50 transition-colors">
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : ''}`}>
              {msg.role === 'assistant' && (
                <div className="w-8 h-8 rounded-lg bg-primary-500/20 flex items-center justify-center flex-shrink-0">
                  <Bot className="w-4 h-4 text-primary-400" />
                </div>
              )}
              <div className={`max-w-[75%] rounded-xl px-4 py-3 ${msg.role === 'user' ? 'bg-primary-500/20 border border-primary-500/30' : 'bg-surface-card border border-surface-border'}`}>
                {msg.role === 'assistant' ? (
                  <div className="space-y-2">
                    {/* 活动轨迹: 工具调用 / 子Agent (Claude Code 风格) */}
                    {msg.activities && msg.activities.length > 0 && (
                      <div className="space-y-1">
                        {msg.activities.map(a => <ActivityRow key={a.id} a={a} />)}
                      </div>
                    )}
                    {/* 思考过程 (折叠) */}
                    {msg.thinking && msg.thinking.trim() && (
                      <details className="rounded-md border border-surface-border/40 bg-surface-dark/40">
                        <summary className="px-2 py-1.5 flex items-center gap-2 cursor-pointer text-[11px] text-gray-400 hover:text-gray-300">
                          <Brain className="w-3.5 h-3.5 text-purple-400" /> 思考过程
                        </summary>
                        <div className="px-3 pb-2 text-[10px] text-gray-500 whitespace-pre-wrap leading-relaxed">{msg.thinking}</div>
                      </details>
                    )}
                    {/* 正文 (逐 token) */}
                    {msg.content ? (
                      <div className="prose prose-invert prose-sm max-w-none
                        prose-headings:text-accent-gold prose-headings:font-semibold
                        prose-strong:text-white
                        prose-p:text-gray-300 prose-p:leading-relaxed
                        prose-table:text-xs prose-table:border-collapse prose-table:w-full
                        prose-thead:bg-surface-hover/50
                        prose-th:px-2 prose-th:py-1.5 prose-th:text-left prose-th:border prose-th:border-surface-border/50 prose-th:text-gray-400 prose-th:font-semibold
                        prose-td:px-2 prose-td:py-1.5 prose-td:border prose-td:border-surface-border/50 prose-td:text-gray-300
                        prose-li:text-gray-300 prose-li:leading-relaxed
                        prose-blockquote:border-l-accent-gold prose-blockquote:bg-accent-gold/5 prose-blockquote:text-gray-400
                        prose-hr:border-surface-border
                        prose-code:text-accent-gold prose-code:bg-surface-hover prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-xs
                        text-sm">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                      </div>
                    ) : msg.streaming && (!msg.activities || msg.activities.length === 0) ? (
                      <p className="text-xs text-gray-500">思考中…</p>
                    ) : null}
                    {msg.streaming && msg.content && <span className="inline-block w-1.5 h-3.5 bg-primary-400 animate-pulse align-middle ml-0.5" />}
                  </div>
                ) : (
                  <p className="text-sm text-gray-200">{msg.content}</p>
                )}
                <div className="flex items-center gap-2 mt-2">
                  <p className="text-[10px] text-gray-600">{new Date(msg.timestamp).toLocaleTimeString()}</p>
                  {msg.role === 'assistant' && msg.content && msg.content.length > 100 && (
                    <button onClick={async () => {
                      try {
                        await api.post('/api/documents/', {
                          title: `AI对话: ${messages.find(m => m.role === 'user')?.content?.slice(0, 40) || '对话记录'}`,
                          category: 'chat', content: msg.content,
                          tags: ['chat', agentType], source: 'agent', add_to_kb: true,
                        })
                        toast.success('已保存到文档知识库')
                      } catch { toast.error('保存失败') }
                    }} className="text-[9px] px-1.5 py-0.5 bg-primary-500/20 text-primary-300 rounded hover:bg-primary-500/30">
                      保存到知识库
                    </button>
                  )}
                </div>
              </div>
              {msg.role === 'user' && (
                <div className="w-8 h-8 rounded-lg bg-accent-gold/20 flex items-center justify-center flex-shrink-0">
                  <User className="w-4 h-4 text-accent-gold" />
                </div>
              )}
            </div>
          ))}

          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="px-4 py-3 border-t border-surface-border">
          <div className="flex gap-3">
            <input type="text" value={input} onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !e.shiftKey && handleSend()}
              className="input-field flex-1" placeholder="输入问题..." disabled={loading} />
            <button onClick={handleSend} disabled={loading || !input.trim()}
              className="btn-primary flex items-center gap-2 disabled:opacity-50">
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
