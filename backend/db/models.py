"""
数据库模型 - Database Models
证券交易助手平台核心数据模型
"""
import uuid
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime, Text, JSON,
    ForeignKey, Enum, UniqueConstraint, Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from db.database import Base


# ═══════════════════════════════════════════════════════
# 枚举类型
# ═══════════════════════════════════════════════════════

class MarketType(str, PyEnum):
    SH = "sh"   # 上海证券交易所
    SZ = "sz"   # 深圳证券交易所


class OrderSide(str, PyEnum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, PyEnum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class SignalType(str, PyEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class StrategyStatus(str, PyEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class BacktestStatus(str, PyEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ═══════════════════════════════════════════════════════
# 用户模型
# ═══════════════════════════════════════════════════════

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100), default="")
    is_active = Column(Boolean, default=True)
    risk_preference = Column(String(20), default="moderate")  # conservative, moderate, aggressive
    notification_email = Column(Boolean, default=True)
    notification_sms = Column(Boolean, default=False)
    notification_push = Column(Boolean, default=True)
    notification_email_address = Column(String(255), default="")  # SNS notification target
    phone = Column(String(20), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    watchlists = relationship("Watchlist", back_populates="user", cascade="all, delete-orphan")
    portfolios = relationship("Portfolio", back_populates="user", cascade="all, delete-orphan")
    strategies = relationship("TradingStrategy", back_populates="user", cascade="all, delete-orphan")
    quant_strategies = relationship("QuantStrategy", back_populates="user", cascade="all, delete-orphan")
    custom_skills = relationship("CustomSkill", back_populates="user", cascade="all, delete-orphan")


# ═══════════════════════════════════════════════════════
# 股票基础数据
# ═══════════════════════════════════════════════════════

class Stock(Base):
    __tablename__ = "stocks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(10), unique=True, nullable=False, index=True)  # e.g., "600519"
    name = Column(String(50), nullable=False)
    market = Column(Enum(MarketType), nullable=False)
    industry = Column(String(50), default="")
    sector = Column(String(50), default="")
    list_date = Column(DateTime, nullable=True)
    total_shares = Column(Float, default=0)       # 总股本(万股)
    circulating_shares = Column(Float, default=0)  # 流通股本(万股)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_stocks_market_code", "market", "code"),
    )


# ═══════════════════════════════════════════════════════
# 自选股 / 股票池
# ═══════════════════════════════════════════════════════

class Watchlist(Base):
    __tablename__ = "watchlists"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False, default="默认股票池")
    description = Column(Text, default="")
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="watchlists")
    items = relationship("WatchlistItem", back_populates="watchlist", cascade="all, delete-orphan")


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    watchlist_id = Column(UUID(as_uuid=True), ForeignKey("watchlists.id"), nullable=False)
    stock_code = Column(String(10), nullable=False)
    stock_name = Column(String(50), default="")
    # 股票池类型: analysis=分析股票池, trading=实际交易股票。
    # (模拟盘/量化为独立模块, 不在此表; 自选股页统一展示这4类)
    pool_type = Column(String(20), default="analysis", nullable=False)
    # 来源: manual=人工添加(Agent 不得改动), ai=Agent 自行管理。Agent 只能增删改 source=ai 的项。
    source = Column(String(10), default="manual", nullable=False)
    added_reason = Column(Text, default="")  # 加入原因/投资分析摘要
    target_price = Column(Float, nullable=True)
    stop_loss_price = Column(Float, nullable=True)
    added_at = Column(DateTime, default=datetime.utcnow)

    watchlist = relationship("Watchlist", back_populates="items")

    __table_args__ = (
        # 同一股票可同时在分析/交易池, 也可同时存在人工与AI来源, 故 pool_type+source 都纳入唯一约束
        UniqueConstraint("watchlist_id", "stock_code", "pool_type", "source", name="uq_watchlist_stock_pool_src"),
    )


# ═══════════════════════════════════════════════════════
# 模拟盘 / 投资组合
# ═══════════════════════════════════════════════════════

class Portfolio(Base):
    __tablename__ = "portfolios"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False, default="模拟盘")
    initial_capital = Column(Float, default=1000000.0)  # 初始资金100万
    available_cash = Column(Float, default=1000000.0)
    total_value = Column(Float, default=1000000.0)      # 总市值
    total_profit = Column(Float, default=0.0)
    total_profit_pct = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="portfolios")
    positions = relationship("Position", back_populates="portfolio", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="portfolio", cascade="all, delete-orphan")


class Position(Base):
    __tablename__ = "positions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    portfolio_id = Column(UUID(as_uuid=True), ForeignKey("portfolios.id"), nullable=False)
    stock_code = Column(String(10), nullable=False)
    stock_name = Column(String(50), default="")
    quantity = Column(Integer, default=0)
    avg_cost = Column(Float, default=0.0)
    current_price = Column(Float, default=0.0)
    market_value = Column(Float, default=0.0)
    profit = Column(Float, default=0.0)
    profit_pct = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    portfolio = relationship("Portfolio", back_populates="positions")

    __table_args__ = (
        UniqueConstraint("portfolio_id", "stock_code", name="uq_portfolio_stock"),
    )


class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    portfolio_id = Column(UUID(as_uuid=True), ForeignKey("portfolios.id"), nullable=False)
    stock_code = Column(String(10), nullable=False)
    stock_name = Column(String(50), default="")
    side = Column(Enum(OrderSide), nullable=False)
    price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)
    filled_quantity = Column(Integer, default=0)
    filled_price = Column(Float, default=0.0)
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING)
    strategy_id = Column(UUID(as_uuid=True), nullable=True)  # 关联策略
    signal_reason = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    portfolio = relationship("Portfolio", back_populates="orders")


# ═══════════════════════════════════════════════════════
# 交易策略
# ═══════════════════════════════════════════════════════

class TradingStrategy(Base):
    __tablename__ = "trading_strategies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, default="")
    strategy_type = Column(String(50), default="technical")  # technical, fundamental, mixed
    parameters = Column(JSON, default=dict)  # 策略参数
    indicators = Column(JSON, default=list)  # 使用的技术指标
    buy_conditions = Column(JSON, default=list)
    sell_conditions = Column(JSON, default=list)
    risk_rules = Column(JSON, default=dict)  # 风控规则
    status = Column(Enum(StrategyStatus), default=StrategyStatus.DRAFT)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="strategies")
    signals = relationship("TradingSignal", back_populates="strategy", cascade="all, delete-orphan")


class TradingSignal(Base):
    __tablename__ = "trading_signals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_id = Column(UUID(as_uuid=True), ForeignKey("trading_strategies.id"), nullable=False)
    stock_code = Column(String(10), nullable=False)
    stock_name = Column(String(50), default="")
    signal_type = Column(Enum(SignalType), nullable=False)
    price = Column(Float, nullable=False)
    target_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    confidence = Column(Float, default=0.0)  # 0-1
    reason = Column(Text, default="")
    is_notified = Column(Boolean, default=False)
    is_executed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    strategy = relationship("TradingStrategy", back_populates="signals")


# ═══════════════════════════════════════════════════════
# 量化策略
# ═══════════════════════════════════════════════════════

class QuantStrategy(Base):
    __tablename__ = "quant_strategies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, default="")
    template_name = Column(String(50), default="")  # 预置模板名称
    code = Column(Text, default="")  # 策略代码
    parameters = Column(JSON, default=dict)
    status = Column(Enum(StrategyStatus), default=StrategyStatus.DRAFT)
    performance_metrics = Column(JSON, default=dict)  # 最新回测指标
    # 应用范围: watchlist(自选股池) | sector(板块) | market(全A股)
    apply_scope = Column(String(20), default="watchlist")
    # 范围目标: watchlist→池类型(analysis/trading/...); sector→板块名/代码; market→留空
    apply_target = Column(String(100), default="")
    # 自动执行: 开启后挂定时任务, 按 apply_scope 定期回测+信号(+可选模拟下单)
    auto_execute = Column(Boolean, default=False)
    # 关联的定时任务 id (自动执行时创建/更新)
    scheduled_task_id = Column(String(64), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="quant_strategies")
    backtests = relationship("Backtest", back_populates="strategy", cascade="all, delete-orphan")


class Backtest(Base):
    __tablename__ = "backtests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_id = Column(UUID(as_uuid=True), ForeignKey("quant_strategies.id"), nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    initial_capital = Column(Float, default=1000000.0)
    final_value = Column(Float, default=0.0)
    total_return = Column(Float, default=0.0)
    annual_return = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    sharpe_ratio = Column(Float, default=0.0)
    win_rate = Column(Float, default=0.0)
    total_trades = Column(Integer, default=0)
    trade_log = Column(JSON, default=list)
    equity_curve = Column(JSON, default=list)
    status = Column(Enum(BacktestStatus), default=BacktestStatus.PENDING)
    error_message = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    strategy = relationship("QuantStrategy", back_populates="backtests")


# ═══════════════════════════════════════════════════════
# 投资报告
# ═══════════════════════════════════════════════════════

class InvestmentReport(Base):
    __tablename__ = "investment_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    title = Column(String(200), nullable=False)
    report_type = Column(String(50), default="comprehensive")  # comprehensive, stock, sector, market
    content = Column(Text, default="")
    summary = Column(Text, default="")
    stock_codes = Column(JSON, default=list)  # 涉及的股票代码
    recommendations = Column(JSON, default=list)  # 投资建议
    data_sources = Column(JSON, default=list)  # 数据来源
    created_at = Column(DateTime, default=datetime.utcnow)


# ═══════════════════════════════════════════════════════
# 自定义Skill
# ═══════════════════════════════════════════════════════

class CustomSkill(Base):
    __tablename__ = "custom_skills"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, default="")
    skill_type = Column(String(50), default="analysis")  # analysis, trading, quant, notification
    code = Column(Text, default="")  # Skill代码
    parameters_schema = Column(JSON, default=dict)
    is_published = Column(Boolean, default=False)  # 是否发布到Registry
    registry_record_id = Column(String(100), default="")
    version = Column(String(20), default="1.0.0")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="custom_skills")


# ═══════════════════════════════════════════════════════
# 会话历史
# ═══════════════════════════════════════════════════════

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    session_id = Column(String(100), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user / assistant
    content = Column(Text, default="")
    agent_type = Column(String(50), default="orchestrator")
    created_at = Column(DateTime, default=datetime.utcnow)


# ═══════════════════════════════════════════════════════
# 文档管理 & 知识库
# ═══════════════════════════════════════════════════════

class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title = Column(String(300), nullable=False)
    category = Column(String(50), default="general")  # analysis, strategy, quant, market, research, imported
    content = Column(Text, default="")
    file_path = Column(String(500), default="")  # AgentCore Runtime Session Storage path
    file_type = Column(String(20), default="md")  # md, html, pdf, txt
    file_size = Column(Integer, default=0)
    tags = Column(JSON, default=list)
    source = Column(String(50), default="system")  # system, user, agent, imported
    session_id = Column(String(100), default="")  # AgentCore Runtime session for storage access
    is_in_knowledge_base = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_documents_user_category", "user_id", "category"),
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    chunk_index = Column(Integer, default=0)
    content = Column(Text, nullable=False)
    chunk_meta = Column("metadata", JSON, default=dict)  # title, category, tags, source
    embedding_model = Column(String(100), default="amazon.titan-embed-text-v2:0")
    created_at = Column(DateTime, default=datetime.utcnow)

    # Note: embedding vector column added via raw SQL (pgvector)
    # ALTER TABLE knowledge_chunks ADD COLUMN embedding vector(1024);

    __table_args__ = (
        Index("ix_knowledge_chunks_user", "user_id"),
        Index("ix_knowledge_chunks_document", "document_id"),
    )


# ═══════════════════════════════════════════════════════
# 定期任务
# ═══════════════════════════════════════════════════════

class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")  # Natural language description
    prompt = Column(Text, nullable=False)  # Agent prompt to execute
    cron_expression = Column(String(100), default="")  # EventBridge cron: cron(0 7 ? * MON-FRI *)
    timezone = Column(String(50), default="Asia/Shanghai")
    is_active = Column(Boolean, default=True)
    agent_type = Column(String(50), default="orchestrator")
    notification_email = Column(String(255), default="")  # Send result to email
    notify_enabled = Column(Boolean, default=True)  # 通知邮箱开关 (关闭则保留地址但不发信)
    aws_rule_name = Column(String(200), default="")  # EventBridge rule name
    aws_rule_arn = Column(String(500), default="")
    last_run_at = Column(DateTime, nullable=True)
    last_result = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
