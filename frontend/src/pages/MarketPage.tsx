import { useState, useEffect, useRef, useCallback } from 'react'
import { ExternalLink, Database, Star, X, BarChart3, RefreshCw, Wallet, Briefcase } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import StockSearch from '../components/StockSearch'
import KlineChart from '../components/KlineChart'
import api from '../services/api'
import toast from 'react-hot-toast'

type PoolKey = 'analysis' | 'trading' | 'simulated' | 'quant'
const POOL_META: Record<PoolKey, { name: string; icon: any }> = {
  analysis: { name: '分析股票池', icon: Star },
  trading: { name: '实际交易股票', icon: Wallet },
  simulated: { name: '模拟盘', icon: Briefcase },
  quant: { name: '量化交易', icon: BarChart3 },
}
const POOL_ORDER: PoolKey[] = ['analysis', 'trading', 'simulated', 'quant']
const pct = (n: number) => `${n >= 0 ? '+' : ''}${(n ?? 0).toFixed(2)}%`

export default function MarketPage() {
  const [source, setSource] = useState('tencent')
  const [sources, setSources] = useState<any[]>([])
  const [selectedStock, setSelectedStock] = useState<any>(null)
  const [showKline, setShowKline] = useState(false)
  const [pools, setPools] = useState<any>({})
  const [activePool, setActivePool] = useState<PoolKey>('analysis')
  const [defaultWlId, setDefaultWlId] = useState('')
  const [quotes, setQuotes] = useState<any[]>([])
  const [loadingQuotes, setLoadingQuotes] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const refreshTimer = useRef<any>(null)
  const navigate = useNavigate()

  useEffect(() => {
    api.get('/api/market/sources').then(r => setSources(r.data.sources || [])).catch(() => {})
    loadPools()
  }, [])

  const poolCodes = useCallback((pk: PoolKey) => {
    return (pools[pk]?.items || []).map((it: any) => it.stock_code).filter(Boolean)
  }, [pools])

  // code → source(manual/ai) 映射 (用于行情表显示人工/AI标签 + 控制是否可手动删除)
  const srcOf = useCallback((pk: PoolKey, rawCode: string) => {
    const it = (pools[pk]?.items || []).find((x: any) => (x.stock_code || '').replace(/^(sh|sz)/, '') === rawCode)
    return it?.source || 'manual'
  }, [pools])

  const loadPools = async () => {
    try {
      const [poolsRes, wlRes] = await Promise.all([
        api.get('/api/watchlist/pools'),
        api.get('/api/watchlist/'),
      ])
      setPools(poolsRes.data.pools || {})
      const def = (wlRes.data.watchlists || []).find((w: any) => w.is_default) || (wlRes.data.watchlists || [])[0]
      setDefaultWlId(def?.id || '')
      return poolsRes.data.pools || {}
    } catch { return {} }
  }

  // Load quotes when active pool is a stock pool
  useEffect(() => {
    if (activePool === 'analysis' || activePool === 'trading') {
      const codes = poolCodes(activePool)
      if (codes.length) loadQuotes(codes)
      else setQuotes([])
    } else {
      setQuotes([])
    }
  }, [activePool, pools, source, poolCodes])

  // Auto-refresh (only for stock pools)
  useEffect(() => {
    if (refreshTimer.current) clearInterval(refreshTimer.current)
    if (autoRefresh && (activePool === 'analysis' || activePool === 'trading')) {
      refreshTimer.current = setInterval(() => {
        const c = poolCodes(activePool)
        if (c.length) loadQuotes(c)
      }, 10000)
    }
    return () => { if (refreshTimer.current) clearInterval(refreshTimer.current) }
  }, [autoRefresh, activePool, pools, source, poolCodes])

  const loadQuotes = async (codes: string[]) => {
    if (!codes.length) return
    setLoadingQuotes(true)
    try {
      const res = await api.get(`/api/market/quotes?codes=${codes.join(',')}&source=${source}`)
      setQuotes(res.data.stocks || [])
    } catch {}
    setLoadingQuotes(false)
  }

  const handleSelectStock = async (stock: { code: string; name: string; market: string; full_code: string }) => {
    try {
      const res = await api.get(`/api/market/quote/${stock.full_code || stock.code}?source=${source}`)
      setSelectedStock({ ...res.data, _search: stock })
      setShowKline(false)
    } catch {}
  }

  // Add to the currently-active stock pool (analysis/trading); sim/quant fall back to analysis
  const handleAddToWatchlist = async () => {
    if (!selectedStock || !defaultWlId) { toast.error('没有自选列表'); return }
    const pool: PoolKey = (activePool === 'analysis' || activePool === 'trading') ? activePool : 'analysis'
    const code = selectedStock._search?.code || selectedStock.code?.replace(/^(sh|sz)/, '')
    const name = selectedStock._search?.name || selectedStock.name
    try {
      await api.post(`/api/watchlist/${defaultWlId}/add`, { stock_code: code, stock_name: name, pool_type: pool })
      toast.success(`${name} 已加入${POOL_META[pool].name}`)
      loadPools()
    } catch (err: any) { toast.error(err.response?.data?.detail || '添加失败') }
  }

  const handleRemove = async (code: string, pool: PoolKey) => {
    if (!defaultWlId) return
    try { await api.delete(`/api/watchlist/${defaultWlId}/remove/${code}?pool_type=${pool}`); toast.success('已移除'); loadPools() } catch {}
  }

  const inPool = (code: string, pool: PoolKey) => poolCodes(pool).includes(code)

  const getStockDetailUrl = (code: string) => {
    const raw = code.replace(/^(sh|sz)/, '')
    const market = code.startsWith('sh') ? 'sh' : 'sz'
    return `https://gu.qq.com/${market}${raw}/gp`
  }

  const isStockPool = activePool === 'analysis' || activePool === 'trading'
  const starPool: PoolKey = isStockPool ? activePool : 'analysis'

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">股票行情</h1>
          <p className="text-gray-500 text-sm mt-1">实时行情 · K线图表 · 自选股 (分析/实际交易/模拟盘/量化)</p>
        </div>
        <div className="flex items-center gap-3">
          <Database className="w-4 h-4 text-gray-500" />
          <select className="input-field w-32 text-xs" value={source} onChange={e => setSource(e.target.value)}>
            {sources.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}
            {!sources.length && <><option value="tencent">腾讯证券</option><option value="sina">新浪财经</option><option value="yahoo">Yahoo</option></>}
          </select>
        </div>
      </div>

      {/* Search */}
      <div className="card">
        <StockSearch onSelect={handleSelectStock} placeholder="搜索股票代码或名称，自动补全..." />
      </div>

      {/* Stock detail */}
      {selectedStock && !selectedStock.error && (
        <div className="card">
          <div className="flex items-start justify-between mb-4">
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-xl font-bold text-white">{selectedStock.name}</h2>
                <button onClick={handleAddToWatchlist}
                  title={`加入${POOL_META[starPool].name}`}
                  className={`p-1 rounded transition-colors ${inPool(selectedStock._search?.code || '', starPool) ? 'text-accent-gold' : 'text-gray-500 hover:text-accent-gold'}`}>
                  <Star className={`w-5 h-5 ${inPool(selectedStock._search?.code || '', starPool) ? 'fill-current' : ''}`} />
                </button>
              </div>
              <p className="text-gray-500 text-sm font-mono">{selectedStock.code} · {selectedStock.source || source}</p>
            </div>
            <div className="text-right">
              <p className={`text-3xl font-bold font-mono ${(selectedStock.change_pct||0) > 0 ? 'stock-up' : (selectedStock.change_pct||0) < 0 ? 'stock-down' : 'text-white'}`}>
                ¥{selectedStock.current_price?.toFixed(2)}
              </p>
              <p className={`text-sm font-mono ${(selectedStock.change_pct||0) > 0 ? 'stock-up' : (selectedStock.change_pct||0) < 0 ? 'stock-down' : 'text-gray-400'}`}>
                {(selectedStock.change_pct||0) > 0 ? '+' : ''}{selectedStock.change_amount?.toFixed(2)} ({(selectedStock.change_pct||0) > 0 ? '+' : ''}{selectedStock.change_pct?.toFixed(2)}%)
              </p>
            </div>
          </div>

          <div className="grid grid-cols-4 md:grid-cols-8 gap-2 mb-4">
            {[
              { l: '今开', v: selectedStock.open?.toFixed(2) }, { l: '昨收', v: selectedStock.prev_close?.toFixed(2) },
              { l: '最高', v: selectedStock.high?.toFixed(2) }, { l: '最低', v: selectedStock.low?.toFixed(2) },
              { l: '成交量', v: `${selectedStock.volume?.toLocaleString()}手` }, { l: '成交额', v: `${selectedStock.amount?.toLocaleString()}万` },
              { l: '市盈率', v: selectedStock.pe_ratio?.toFixed(1) || '-' }, { l: '换手率', v: selectedStock.turnover_rate || '-' },
            ].map(({ l, v }) => (
              <div key={l} className="bg-surface-hover rounded p-2">
                <p className="text-[10px] text-gray-600">{l}</p><p className="text-xs text-gray-300 font-mono mt-0.5">{v}</p>
              </div>
            ))}
          </div>

          <div className="flex items-center justify-between">
            <button onClick={() => setShowKline(!showKline)} className="btn-secondary text-xs flex items-center gap-1">
              <BarChart3 className="w-3 h-3" /> {showKline ? '收起K线图' : '展开K线图表'}
            </button>
            <a href={getStockDetailUrl(selectedStock.code)} target="_blank" rel="noopener noreferrer"
              className="text-primary-400 hover:text-primary-300 text-xs inline-flex items-center gap-1">
              查看详情 <ExternalLink className="w-3 h-3" />
            </a>
          </div>

          {showKline && <div className="mt-3"><KlineChart stockCode={selectedStock.code} source={source === 'tencent' ? 'sina' : source} /></div>}
        </div>
      )}

      {/* 自选股 (4 pools) */}
      <div className="card">
        <div className="flex items-center justify-between mb-3 flex-wrap gap-3">
          <div className="flex flex-wrap gap-2">
            {POOL_ORDER.map((k) => {
              const Icon = POOL_META[k].icon
              const count = (pools[k]?.items || []).length
              return (
                <button key={k} onClick={() => setActivePool(k)}
                  className={`px-3 py-1.5 rounded-lg text-xs flex items-center gap-1.5 border transition-colors ${
                    activePool === k ? 'bg-primary-500/20 text-primary-300 border-primary-500/40'
                                     : 'text-gray-400 border-surface-border hover:text-gray-200'}`}>
                  <Icon className="w-3.5 h-3.5" /> {POOL_META[k].name}
                  <span className="text-[10px] text-gray-500">{count}</span>
                </button>
              )
            })}
          </div>
          {isStockPool && (
            <div className="flex items-center gap-3">
              <button onClick={() => setAutoRefresh(!autoRefresh)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs transition-all ${
                  autoRefresh ? 'bg-green-900/30 text-green-400 border border-green-800/50'
                              : 'bg-surface-hover text-gray-500 border border-surface-border'}`}>
                <RefreshCw className={`w-3 h-3 ${autoRefresh ? 'animate-spin' : ''}`} /> {autoRefresh ? '自动刷新中' : '自动刷新'}
              </button>
              <button onClick={() => { const c = poolCodes(activePool); if (c.length) loadQuotes(c) }}
                className="text-xs text-primary-400 hover:text-primary-300">手动刷新</button>
            </div>
          )}
        </div>

        {/* Stock pools (analysis/trading) — live quotes */}
        {isStockPool && (
          quotes.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-500 text-xs border-b border-surface-border">
                    <th className="text-left py-2 px-2">代码</th><th className="text-left py-2 px-2">名称</th>
                    <th className="text-right py-2 px-2">最新价</th><th className="text-right py-2 px-2">涨跌幅</th>
                    <th className="text-right py-2 px-2">成交量</th><th className="text-right py-2 px-2">成交额</th>
                    <th className="text-center py-2 px-2">详情</th><th className="text-center py-2 px-2">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {quotes.map((q: any, i: number) => {
                    const rawCode = q.code?.replace(/^(sh|sz)/, '') || ''
                    return (
                      <tr key={i} className="border-b border-surface-border/50 hover:bg-surface-hover transition-colors cursor-pointer"
                        onClick={() => { setSelectedStock({ ...q, _search: { code: rawCode, name: q.name, market: q.code?.startsWith('sh') ? 'sh' : 'sz', full_code: q.code } }); setShowKline(false) }}>
                        <td className="py-2.5 px-2 font-mono text-gray-400 text-xs">{rawCode}</td>
                        <td className="py-2.5 px-2 text-white font-medium">
                          {q.name}
                          {srcOf(activePool, rawCode) === 'ai'
                            ? <span className="ml-1.5 text-[9px] px-1 py-0.5 rounded bg-primary-500/20 text-primary-300 align-middle">AI</span>
                            : <span className="ml-1.5 text-[9px] px-1 py-0.5 rounded bg-surface-hover text-gray-500 align-middle">人工</span>}
                        </td>
                        <td className={`py-2.5 px-2 text-right font-mono ${(q.change_pct||0) > 0 ? 'stock-up' : (q.change_pct||0) < 0 ? 'stock-down' : 'text-gray-300'}`}>{q.current_price?.toFixed(2)}</td>
                        <td className={`py-2.5 px-2 text-right font-mono ${(q.change_pct||0) > 0 ? 'stock-up' : (q.change_pct||0) < 0 ? 'stock-down' : 'text-gray-300'}`}>{(q.change_pct||0) > 0 ? '+' : ''}{q.change_pct?.toFixed(2)}%</td>
                        <td className="py-2.5 px-2 text-right text-gray-500 font-mono text-xs">{q.volume?.toLocaleString()}</td>
                        <td className="py-2.5 px-2 text-right text-gray-500 font-mono text-xs">{q.amount?.toLocaleString()}</td>
                        <td className="py-2.5 px-2 text-center" onClick={e => e.stopPropagation()}>
                          <a href={getStockDetailUrl(q.code)} target="_blank" rel="noopener noreferrer" className="text-primary-400 hover:text-primary-300 text-[10px]">详情 <ExternalLink className="w-2.5 h-2.5 inline" /></a>
                        </td>
                        <td className="py-2.5 px-2 text-center" onClick={e => e.stopPropagation()}>
                          <button onClick={() => handleRemove(rawCode, activePool)} className="text-gray-600 hover:text-red-400 transition-colors"><X className="w-3.5 h-3.5" /></button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              {loadingQuotes && <p className="text-center text-xs text-gray-600 py-2 animate-pulse">刷新中...</p>}
            </div>
          ) : poolCodes(activePool).length ? (
            <div className="text-center py-6">
              <button onClick={() => loadQuotes(poolCodes(activePool))} className="btn-primary text-sm">加载{POOL_META[activePool].name}行情</button>
            </div>
          ) : (
            <p className="text-gray-500 text-center py-8 text-sm">{POOL_META[activePool].name}为空，搜索股票后点击 ⭐ 加入</p>
          )
        )}

        {/* 模拟盘 */}
        {activePool === 'simulated' && (
          (() => {
            const p = pools.simulated || { items: [] }
            return (p.items || []).length === 0 ? (
              <p className="text-gray-500 text-center py-8 text-sm">模拟盘暂无持仓 · <button onClick={() => navigate('/portfolio')} className="text-primary-400">去模拟盘</button></p>
            ) : (
              <div className="overflow-x-auto">
                {p.portfolio && (
                  <div className="flex flex-wrap gap-4 px-2 py-2 mb-1 text-xs text-gray-400 border-b border-surface-border">
                    <span>{p.portfolio.name}</span>
                    <span>总资产 ¥{Math.round(p.portfolio.total_value).toLocaleString()}</span>
                    <span>可用 ¥{Math.round(p.portfolio.available_cash).toLocaleString()}</span>
                    <span className={p.portfolio.total_profit_pct >= 0 ? 'stock-up' : 'stock-down'}>收益 {pct(p.portfolio.total_profit_pct)}</span>
                  </div>
                )}
                <table className="w-full text-sm">
                  <thead><tr className="text-gray-500 text-xs border-b border-surface-border">
                    <th className="text-left py-2 px-2">代码</th><th className="text-left py-2 px-2">名称</th>
                    <th className="text-right py-2 px-2">持仓</th><th className="text-right py-2 px-2">成本</th>
                    <th className="text-right py-2 px-2">现价</th><th className="text-right py-2 px-2">盈亏</th>
                  </tr></thead>
                  <tbody>
                    {p.items.map((it: any, i: number) => (
                      <tr key={i} className="border-b border-surface-border/50 hover:bg-surface-hover cursor-pointer" onClick={() => navigate('/portfolio')}>
                        <td className="py-2.5 px-2 font-mono text-gray-400 text-xs">{it.stock_code}</td>
                        <td className="py-2.5 px-2 text-white">{it.stock_name}</td>
                        <td className="py-2.5 px-2 text-right text-gray-300">{it.quantity}</td>
                        <td className="py-2.5 px-2 text-right text-gray-400 font-mono">{(it.avg_cost ?? 0).toFixed(2)}</td>
                        <td className="py-2.5 px-2 text-right text-gray-300 font-mono">{(it.current_price ?? 0).toFixed(2)}</td>
                        <td className={`py-2.5 px-2 text-right font-mono ${it.profit >= 0 ? 'stock-up' : 'stock-down'}`}>{pct(it.profit_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          })()
        )}

        {/* 量化 */}
        {activePool === 'quant' && (
          (() => {
            const p = pools.quant || { items: [] }
            return (p.items || []).length === 0 ? (
              <p className="text-gray-500 text-center py-8 text-sm">暂无量化策略 · <button onClick={() => navigate('/quant')} className="text-primary-400">去量化交易</button></p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="text-gray-500 text-xs border-b border-surface-border">
                    <th className="text-left py-2 px-2">策略</th><th className="text-left py-2 px-2">模板</th>
                    <th className="text-left py-2 px-2">状态</th><th className="text-left py-2 px-2">绩效</th>
                  </tr></thead>
                  <tbody>
                    {p.items.map((s: any) => (
                      <tr key={s.id} className="border-b border-surface-border/50 hover:bg-surface-hover cursor-pointer" onClick={() => navigate('/quant')}>
                        <td className="py-2.5 px-2 text-gray-200">{s.name}</td>
                        <td className="py-2.5 px-2 text-gray-500">{s.template_name || '-'}</td>
                        <td className="py-2.5 px-2"><span className="text-[11px] px-1.5 py-0.5 bg-surface-hover rounded text-gray-400">{s.status}</span></td>
                        <td className="py-2.5 px-2 text-gray-400 text-xs">{s.performance_metrics?.total_return != null ? `收益 ${s.performance_metrics.total_return}` : '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          })()
        )}
      </div>
    </div>
  )
}
