import { useState, useEffect, useCallback } from 'react'
import { Star, Plus, Trash2, RefreshCw, TrendingUp, Wallet, BarChart3, Briefcase } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import api from '../services/api'
import toast from 'react-hot-toast'

type PoolKey = 'analysis' | 'trading' | 'simulated' | 'quant'

const POOL_META: Record<PoolKey, { name: string; icon: any; desc: string }> = {
  analysis: { name: '分析股票池', icon: Star, desc: '用于研究/关注的股票（默认自选股）' },
  trading: { name: '实际交易股票', icon: Wallet, desc: '真实持有/计划交易的股票（默认自选股）' },
  simulated: { name: '模拟盘', icon: Briefcase, desc: '模拟盘持仓' },
  quant: { name: '量化交易', icon: BarChart3, desc: '量化策略' },
}
const ORDER: PoolKey[] = ['analysis', 'trading', 'simulated', 'quant']

function pct(n: number) { return `${n >= 0 ? '+' : ''}${(n ?? 0).toFixed(2)}%` }

export default function WatchlistPage() {
  const [pools, setPools] = useState<any>({})
  const [active, setActive] = useState<PoolKey>('analysis')
  const [loading, setLoading] = useState(false)
  const [defaultWlId, setDefaultWlId] = useState('')
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ stock_code: '', stock_name: '', added_reason: '' })
  const navigate = useNavigate()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [poolsRes, wlRes] = await Promise.all([
        api.get('/api/watchlist/pools'),
        api.get('/api/watchlist/'),
      ])
      setPools(poolsRes.data.pools || {})
      const def = (wlRes.data.watchlists || []).find((w: any) => w.is_default) || (wlRes.data.watchlists || [])[0]
      setDefaultWlId(def?.id || '')
    } catch (err: any) {
      toast.error(err.response?.data?.detail || '加载失败')
    }
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  const addStock = async () => {
    if (!form.stock_code.trim() || !defaultWlId) return
    setAdding(true)
    try {
      await api.post(`/api/watchlist/${defaultWlId}/add`, { ...form, pool_type: active })
      toast.success('已加入')
      setForm({ stock_code: '', stock_name: '', added_reason: '' })
      load()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || '添加失败')
    }
    setAdding(false)
  }

  const removeStock = async (code: string) => {
    if (!defaultWlId) return
    try {
      await api.delete(`/api/watchlist/${defaultWlId}/remove/${code}?pool_type=${active}`)
      toast.success('已移除')
      load()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || '移除失败')
    }
  }

  const cur = pools[active] || { items: [] }
  const isWatchlistPool = active === 'analysis' || active === 'trading'

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Star className="w-6 h-6 text-accent-gold" /> 自选股
        </h1>
        <button onClick={load} className="btn-secondary flex items-center gap-2 text-sm">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> 刷新
        </button>
      </div>

      {/* Pool tabs */}
      <div className="flex flex-wrap gap-2">
        {ORDER.map((k) => {
          const Icon = POOL_META[k].icon
          const count = (pools[k]?.items || []).length
          return (
            <button key={k} onClick={() => setActive(k)}
              className={`px-3 py-2 rounded-lg text-sm flex items-center gap-2 border transition-colors ${
                active === k ? 'bg-primary-500/20 text-primary-300 border-primary-500/40'
                             : 'text-gray-400 border-surface-border hover:text-gray-200 hover:border-surface-hover'}`}>
              <Icon className="w-4 h-4" /> {POOL_META[k].name}
              <span className="text-[11px] text-gray-500">{count}</span>
            </button>
          )
        })}
      </div>
      <p className="text-xs text-gray-500">{POOL_META[active].desc}</p>

      {/* Add form — only for watchlist pools */}
      {isWatchlistPool && (
        <div className="card flex flex-wrap items-end gap-3">
          <div>
            <label className="block text-[11px] text-gray-500 mb-1">股票代码</label>
            <input className="input-field w-32" placeholder="600519" value={form.stock_code}
              onChange={(e) => setForm({ ...form, stock_code: e.target.value })} />
          </div>
          <div>
            <label className="block text-[11px] text-gray-500 mb-1">名称</label>
            <input className="input-field w-32" placeholder="贵州茅台" value={form.stock_name}
              onChange={(e) => setForm({ ...form, stock_name: e.target.value })} />
          </div>
          <div className="flex-1 min-w-[160px]">
            <label className="block text-[11px] text-gray-500 mb-1">理由</label>
            <input className="input-field w-full" placeholder="加入理由（可选）" value={form.added_reason}
              onChange={(e) => setForm({ ...form, added_reason: e.target.value })} />
          </div>
          <button onClick={addStock} disabled={adding || !form.stock_code.trim()}
            className="btn-primary flex items-center gap-2 disabled:opacity-50">
            <Plus className="w-4 h-4" /> 加入{POOL_META[active].name}
          </button>
        </div>
      )}

      {/* Pool content */}
      <div className="card overflow-x-auto">
        {(cur.items || []).length === 0 ? (
          <div className="py-12 text-center text-gray-600 text-sm">该池暂无内容</div>
        ) : active === 'quant' ? (
          <table className="w-full text-sm">
            <thead><tr className="text-gray-500 text-xs border-b border-surface-border">
              <th className="text-left px-3 py-2">策略</th><th className="text-left px-3 py-2">模板</th>
              <th className="text-left px-3 py-2">状态</th><th className="text-left px-3 py-2">绩效</th>
            </tr></thead>
            <tbody>
              {cur.items.map((s: any) => (
                <tr key={s.id} className="border-b border-surface-border/30 hover:bg-surface-hover/30 cursor-pointer"
                  onClick={() => navigate('/quant')}>
                  <td className="px-3 py-2 text-gray-200">{s.name}</td>
                  <td className="px-3 py-2 text-gray-500">{s.template_name || '-'}</td>
                  <td className="px-3 py-2"><span className="text-[11px] px-1.5 py-0.5 bg-surface-hover rounded text-gray-400">{s.status}</span></td>
                  <td className="px-3 py-2 text-gray-400 text-xs">{s.performance_metrics?.total_return != null ? `收益 ${s.performance_metrics.total_return}` : '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : active === 'simulated' ? (
          <>
            {cur.portfolio && (
              <div className="flex flex-wrap gap-4 px-3 py-2 mb-2 text-xs text-gray-400 border-b border-surface-border">
                <span>{cur.portfolio.name}</span>
                <span>总资产 ¥{Math.round(cur.portfolio.total_value).toLocaleString()}</span>
                <span>可用 ¥{Math.round(cur.portfolio.available_cash).toLocaleString()}</span>
                <span className={cur.portfolio.total_profit_pct >= 0 ? 'text-accent-red' : 'text-accent-green'}>收益 {pct(cur.portfolio.total_profit_pct)}</span>
              </div>
            )}
            <table className="w-full text-sm">
              <thead><tr className="text-gray-500 text-xs border-b border-surface-border">
                <th className="text-left px-3 py-2">代码</th><th className="text-left px-3 py-2">名称</th>
                <th className="text-right px-3 py-2">持仓</th><th className="text-right px-3 py-2">成本</th>
                <th className="text-right px-3 py-2">现价</th><th className="text-right px-3 py-2">盈亏</th>
              </tr></thead>
              <tbody>
                {cur.items.map((p: any, i: number) => (
                  <tr key={i} className="border-b border-surface-border/30 hover:bg-surface-hover/30 cursor-pointer" onClick={() => navigate('/portfolio')}>
                    <td className="px-3 py-2 text-gray-300 font-mono">{p.stock_code}</td>
                    <td className="px-3 py-2 text-gray-200">{p.stock_name}</td>
                    <td className="px-3 py-2 text-right text-gray-300">{p.quantity}</td>
                    <td className="px-3 py-2 text-right text-gray-400">{(p.avg_cost ?? 0).toFixed(2)}</td>
                    <td className="px-3 py-2 text-right text-gray-300">{(p.current_price ?? 0).toFixed(2)}</td>
                    <td className={`px-3 py-2 text-right ${p.profit >= 0 ? 'text-accent-red' : 'text-accent-green'}`}>{pct(p.profit_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <table className="w-full text-sm">
            <thead><tr className="text-gray-500 text-xs border-b border-surface-border">
              <th className="text-left px-3 py-2">代码</th><th className="text-left px-3 py-2">名称</th>
              <th className="text-left px-3 py-2">理由</th><th className="text-right px-3 py-2">目标价</th>
              <th className="text-right px-3 py-2">止损</th><th className="px-3 py-2"></th>
            </tr></thead>
            <tbody>
              {cur.items.map((it: any) => (
                <tr key={it.id} className="group border-b border-surface-border/30 hover:bg-surface-hover/30">
                  <td className="px-3 py-2 text-gray-300 font-mono">{it.stock_code}</td>
                  <td className="px-3 py-2 text-gray-200">{it.stock_name}</td>
                  <td className="px-3 py-2 text-gray-500 text-xs max-w-[280px] truncate">{it.added_reason || '-'}</td>
                  <td className="px-3 py-2 text-right text-gray-400">{it.target_price ?? '-'}</td>
                  <td className="px-3 py-2 text-right text-gray-400">{it.stop_loss_price ?? '-'}</td>
                  <td className="px-3 py-2 text-right">
                    <button onClick={() => removeStock(it.stock_code)}
                      className="opacity-0 group-hover:opacity-100 p-1 text-gray-500 hover:text-red-400 transition-all">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
