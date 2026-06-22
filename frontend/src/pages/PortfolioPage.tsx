import { useEffect, useState, useRef } from 'react'
import { Briefcase, ArrowUpRight, ArrowDownRight, RefreshCw } from 'lucide-react'
import StockSearch from '../components/StockSearch'
import api from '../services/api'
import toast from 'react-hot-toast'

export default function PortfolioPage() {
  const [portfolios, setPortfolios] = useState<any[]>([])
  const [orderForm, setOrderForm] = useState({ stock_code: '', stock_name: '', side: 'buy', price: '', quantity: '' })
  const [submitting, setSubmitting] = useState(false)
  const [realtimePrice, setRealtimePrice] = useState<any>(null)
  const [orderBook, setOrderBook] = useState<any>(null)
  const [refreshing, setRefreshing] = useState(false)
  const pollTimer = useRef<any>(null)

  useEffect(() => {
    loadPortfolios()
    // 盘中现价/盈亏每30秒自动刷新
    pollTimer.current = setInterval(() => loadPortfolios(true), 30000)
    return () => { if (pollTimer.current) clearInterval(pollTimer.current) }
  }, [])

  const loadPortfolios = async (silent = false) => {
    if (!silent) setRefreshing(true)
    try {
      const res = await api.get('/api/portfolio/')
      setPortfolios(res.data)
    } catch {}
    if (!silent) setRefreshing(false)
  }

  const handleStockSelect = async (stock: { code: string; name: string; market: string; full_code: string }) => {
    setOrderForm(prev => ({ ...prev, stock_code: stock.code, stock_name: stock.name }))
    // Fetch realtime price and order book
    try {
      const [quoteRes, obRes] = await Promise.all([
        api.get(`/api/market/quote/${stock.full_code}`),
        api.get(`/api/market/orderbook/${stock.full_code}`),
      ])
      setRealtimePrice(quoteRes.data)
      setOrderBook(obRes.data)
      // Auto-fill price
      if (quoteRes.data.current_price) {
        setOrderForm(prev => ({ ...prev, price: quoteRes.data.current_price.toFixed(2) }))
      }
    } catch {}
  }

  const handleOrder = async (portfolioId: string) => {
    if (!orderForm.stock_code || !orderForm.price || !orderForm.quantity) {
      toast.error('请填写完整的订单信息'); return
    }
    setSubmitting(true)
    try {
      const res = await api.post(`/api/portfolio/${portfolioId}/order`, {
        stock_code: orderForm.stock_code, stock_name: orderForm.stock_name,
        side: orderForm.side, price: parseFloat(orderForm.price), quantity: parseInt(orderForm.quantity),
      })
      toast.success(res.data.message)
      setOrderForm({ stock_code: '', stock_name: '', side: 'buy', price: '', quantity: '' })
      setRealtimePrice(null)
      setOrderBook(null)
      loadPortfolios()
    } catch (err: any) { toast.error(err.response?.data?.detail || '下单失败') }
    setSubmitting(false)
  }

  const portfolio = portfolios[0]

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Briefcase className="w-6 h-6 text-accent-gold" /> 模拟盘
          <span className="text-xs font-normal text-gray-500">现价/盈亏实时刷新</span>
        </h1>
        <button onClick={() => loadPortfolios()} className="btn-secondary flex items-center gap-2 text-sm">
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} /> 刷新现价
        </button>
      </div>

      {portfolio && (
        <>
          {/* 账户概况 */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            {[
              { label: '总资产', value: `¥${portfolio.total_value?.toLocaleString()}`, color: 'text-white' },
              { label: '可用资金', value: `¥${portfolio.available_cash?.toLocaleString()}`, color: 'text-gray-300' },
              { label: '持仓市值', value: `¥${(portfolio.total_value - portfolio.available_cash)?.toLocaleString()}`, color: 'text-blue-400' },
              { label: '总收益', value: `¥${portfolio.total_profit?.toLocaleString()}`, color: portfolio.total_profit >= 0 ? 'text-accent-red' : 'text-accent-green' },
              { label: '收益率', value: `${portfolio.total_profit_pct?.toFixed(2)}%`, color: portfolio.total_profit_pct >= 0 ? 'text-accent-red' : 'text-accent-green' },
            ].map(({ label, value, color }) => (
              <div key={label} className="card">
                <p className="text-xs text-gray-500">{label}</p>
                <p className={`text-lg font-bold font-mono mt-1 ${color}`}>{value}</p>
              </div>
            ))}
          </div>

          {/* 交易面板 */}
          <div className="card">
            <h2 className="text-lg font-semibold text-white mb-4">模拟交易</h2>

            {/* 股票搜索 */}
            <div className="mb-4">
              <label className="block text-xs text-gray-400 mb-1">搜索股票</label>
              <StockSearch onSelect={handleStockSelect} placeholder="输入股票代码或名称，自动补全..." />
            </div>

            {/* 实时价格 + 盘口 */}
            {realtimePrice && !realtimePrice.error && (
              <div className="mb-4 bg-surface-hover rounded-lg p-3 border border-surface-border/50">
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <span className="text-white font-medium">{realtimePrice.name}</span>
                    <span className="text-gray-500 text-xs font-mono ml-2">{realtimePrice.code}</span>
                  </div>
                  <div className="text-right">
                    <span className={`text-xl font-bold font-mono ${(realtimePrice.change_pct||0) > 0 ? 'stock-up' : (realtimePrice.change_pct||0) < 0 ? 'stock-down' : 'text-white'}`}>
                      ¥{realtimePrice.current_price?.toFixed(2)}
                    </span>
                    <span className={`text-xs font-mono ml-2 ${(realtimePrice.change_pct||0) > 0 ? 'stock-up' : (realtimePrice.change_pct||0) < 0 ? 'stock-down' : 'text-gray-400'}`}>
                      {(realtimePrice.change_pct||0) > 0 ? '+' : ''}{realtimePrice.change_pct?.toFixed(2)}%
                    </span>
                  </div>
                </div>

                {/* 买卖5档 */}
                {orderBook && !orderBook.error && (
                  <div className="grid grid-cols-2 gap-3 text-xs">
                    <div>
                      <p className="text-gray-500 mb-1">卖盘</p>
                      {[...(orderBook.asks || [])].reverse().map((a: any, i: number) => (
                        <div key={i} className="flex justify-between py-0.5 cursor-pointer hover:bg-surface-dark/50 px-1 rounded"
                          onClick={() => setOrderForm(prev => ({ ...prev, price: a.price.toFixed(2), side: 'buy' }))}>
                          <span className="text-accent-green font-mono">卖{5 - i}</span>
                          <span className="text-gray-300 font-mono">{a.price?.toFixed(2)}</span>
                          <span className="text-gray-500 font-mono">{a.volume}</span>
                        </div>
                      ))}
                    </div>
                    <div>
                      <p className="text-gray-500 mb-1">买盘</p>
                      {(orderBook.bids || []).map((b: any, i: number) => (
                        <div key={i} className="flex justify-between py-0.5 cursor-pointer hover:bg-surface-dark/50 px-1 rounded"
                          onClick={() => setOrderForm(prev => ({ ...prev, price: b.price.toFixed(2), side: 'sell' }))}>
                          <span className="text-accent-red font-mono">买{i + 1}</span>
                          <span className="text-gray-300 font-mono">{b.price?.toFixed(2)}</span>
                          <span className="text-gray-500 font-mono">{b.volume}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* 下单表单 */}
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3 items-end">
              <div>
                <label className="block text-xs text-gray-400 mb-1">股票代码</label>
                <input className="input-field font-mono" value={orderForm.stock_code} readOnly placeholder="搜索选择" />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">方向</label>
                <select className="input-field" value={orderForm.side} onChange={e => setOrderForm({ ...orderForm, side: e.target.value })}>
                  <option value="buy">买入</option>
                  <option value="sell">卖出</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">价格</label>
                <input type="number" step="0.01" className="input-field font-mono" value={orderForm.price}
                  onChange={e => setOrderForm({ ...orderForm, price: e.target.value })} placeholder="点击盘口自动填入" />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">数量(股)</label>
                <input type="number" step="100" className="input-field font-mono" value={orderForm.quantity}
                  onChange={e => setOrderForm({ ...orderForm, quantity: e.target.value })} placeholder="100" />
              </div>
              <button onClick={() => handleOrder(portfolio.id)} disabled={submitting}
                className={`${orderForm.side === 'buy' ? 'bg-red-600 hover:bg-red-700' : 'bg-green-600 hover:bg-green-700'} text-white font-medium py-2 rounded-lg transition-colors disabled:opacity-50`}>
                {submitting ? '提交中...' : orderForm.side === 'buy' ? '买入' : '卖出'}
              </button>
            </div>
          </div>

          {/* 持仓列表 */}
          <div className="card">
            <h2 className="text-lg font-semibold text-white mb-4">当前持仓</h2>
            {portfolio.positions?.length > 0 ? (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-500 text-xs border-b border-surface-border">
                    <th className="text-left py-2">股票</th>
                    <th className="text-right py-2">数量</th>
                    <th className="text-right py-2">成本价</th>
                    <th className="text-right py-2">现价</th>
                    <th className="text-right py-2">市值</th>
                    <th className="text-right py-2">盈亏</th>
                    <th className="text-right py-2">盈亏比</th>
                  </tr>
                </thead>
                <tbody>
                  {portfolio.positions.map((pos: any, i: number) => (
                    <tr key={i} className="border-b border-surface-border/50">
                      <td className="py-3">
                        <p className="text-white font-medium">{pos.stock_name}</p>
                        <p className="text-gray-500 text-xs font-mono">{pos.stock_code}</p>
                      </td>
                      <td className="text-right text-gray-300 font-mono">{pos.quantity}</td>
                      <td className="text-right text-gray-300 font-mono">{pos.avg_cost?.toFixed(2)}</td>
                      <td className="text-right text-gray-300 font-mono">{pos.current_price?.toFixed(2)}</td>
                      <td className="text-right text-gray-300 font-mono">¥{pos.market_value?.toLocaleString()}</td>
                      <td className={`text-right font-mono ${(pos.profit||0) >= 0 ? 'stock-up' : 'stock-down'}`}>
                        {(pos.profit||0) >= 0 ? '+' : ''}¥{pos.profit?.toLocaleString()}
                      </td>
                      <td className={`text-right font-mono ${(pos.profit_pct||0) >= 0 ? 'stock-up' : 'stock-down'}`}>
                        {(pos.profit_pct||0) >= 0 ? '+' : ''}{pos.profit_pct?.toFixed(2)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="text-gray-500 text-center py-8">暂无持仓</p>
            )}
          </div>

          {/* 最近订单 */}
          <div className="card">
            <h2 className="text-lg font-semibold text-white mb-4">最近交易</h2>
            {portfolio.recent_orders?.length > 0 ? (
              <div className="space-y-2">
                {portfolio.recent_orders.map((order: any, i: number) => (
                  <div key={i} className="flex items-center justify-between py-2 border-b border-surface-border/50">
                    <div className="flex items-center gap-3">
                      {order.side === 'buy' ? <ArrowUpRight className="w-4 h-4 text-accent-red" /> : <ArrowDownRight className="w-4 h-4 text-accent-green" />}
                      <div>
                        <p className="text-sm text-white">{order.stock_name} <span className="text-gray-500 font-mono text-xs">{order.stock_code}</span></p>
                        <p className="text-xs text-gray-500">{order.created_at?.split('T')[0]}</p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className={`text-sm font-mono ${order.side === 'buy' ? 'text-accent-red' : 'text-accent-green'}`}>
                        {order.side === 'buy' ? '买入' : '卖出'} {order.quantity}股
                      </p>
                      <p className="text-xs text-gray-500 font-mono">¥{order.price?.toFixed(2)}</p>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-gray-500 text-center py-8">暂无交易记录</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
