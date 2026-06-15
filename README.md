# 证券交易助手 Agent 平台

AI-powered securities trading assistant platform built on the **Claude Agent SDK** (`claude-agent-sdk`) and **AWS Bedrock AgentCore**, featuring investment analysis, stock trading, quantitative backtesting, and scheduled autonomous tasks. The orchestrator delegates to specialized **sub-agents** (`AgentDefinition`) and works tightly with **Skills** (`.claude/skills/*/SKILL.md`); all domain capabilities are exposed as in-process MCP tools.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Frontend (React 18 + Vite)                          │
│  Dashboard │ 投资分析 │ 行情 │ 模拟盘 │ 交易策略 │ 量化 │ AI助手 │ Skills   │
│  扫描 │ 文档知识库 │ 定期任务 │ 设置                                         │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │ HTTPS (/api/*)
┌──────────────────────────────▼──────────────────────────────────────────────┐
│                    Amazon CloudFront (OAC → S3 + ALB)                       │
│  /* → S3 (sec-trading-web-app-prod)                                         │
│  /api/* → ALB (securities-trading-alb) → ECS Fargate                        │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────────────┐
│                    ECS Fargate Backend (FastAPI)                             │
│  Auth (Cognito + JWT) │ Market │ Portfolio │ Strategy │ Quant │ Chat        │
│  Skills │ Scanning │ Documents │ Scheduler │ Analysis │ Settings            │
│                                                                             │
│  Real-time SSE Streaming (text chunks, status updates, keepalive pings)     │
│                                                                             │
│  AI Chat/Analysis/Strategy/Scheduler → invoke_runtime_agent_streaming()     │
└──────┬──────────────┬───────────────────────────────────────────┬───────────┘
       │              │                                           │
┌──────▼──────┐ ┌─────▼────────────┐                    ┌────────▼───────────┐
│ Aurora      │ │ ElastiCache      │                    │ AgentCore Runtime  │
│ PostgreSQL  │ │ Redis (TLS)      │                    │ SecuritiesTrading  │
│ Serverless  │ │ Serverless       │                    │ Agent              │
│ v2          │ │                  │                    │                    │
│ 13 tables   │ │ Quote cache 10s  │                    │ ┌────────────────┐ │
│ Users       │ │ K-line cache 60s │                    │ │ Orchestrator   │ │
│ Stocks      │ │                  │                    │ │ (SDK Sub-agents)│ │
│ Portfolios  │ │                  │                    │ │                │ │
│ Strategies  │ │                  │                    │ │ Sub-Agents:    │ │
│ Orders      │ │                  │                    │ │ • Analyst      │ │
│ Reports     │ │                  │                    │ │ • Trader       │ │
│ Scheduler   │ │                  │                    │ │ • Quant        │ │
│ Documents   │ │                  │                    │ │                │ │
│ Knowledge   │ │                  │                    │ │ Tools:         │ │
└─────────────┘ └──────────────────┘                    │ │ • Browser ✅   │ │
                                                        │ │ • CodeInterp ✅│ │
┌───────────────────────────────────────────┐           │ └────────────────┘ │
│ AgentCore Services                        │           │                    │
│                                           │           │ OTEL Tracing       │
│ Memory (STM + LTM)                        │◄──────────│ Persistent Storage │
│ ├─ SessionSummarizer                      │           └────────────────────┘
│ ├─ InvestmentPreferenceLearner            │                    │
│ └─ TradingKnowledgeEvolution (SCOPE)      │              ┌─────▼─────┐
│                                           │              │ Bedrock   │
│ Registry (9 Skills + external)            │              │ Claude    │
│ ├─ market-data-skill                      │              │ Sonnet    │
│ ├─ analysis-skill                         │              │ 4.6       │
│ ├─ web-fetch-skill                        │              └───────────┘
│ ├─ crawler-skill                          │
│ ├─ trading-skill                          │         ┌─────────────────┐
│ ├─ quant-skill                            │         │ Amazon Cognito  │
│ ├─ notification-skill                     │         │ User Pool       │
│ ├─ browser-crawler-skill                  │         │ (Authentication)│
│ └─ code-interpreter-skill                 │         └─────────────────┘
│                                           │
│ Browser (Public + Web Bot Auth)           │         ┌─────────────────┐
│ Code Interpreter (Public)                 │         │ Amazon SNS      │
│ Observability (OTEL → CloudWatch)         │         │ (Notifications) │
└───────────────────────────────────────────┘         └─────────────────┘
```

## Key Features

### 1. Investment Analysis (投资分析)
- Quick technical analysis: MA, MACD, RSI, Bollinger Bands, KDJ
- AI-powered deep research via AgentCore Runtime with **real-time streaming output**
- Professional financial crawlers (东方财富, 新浪, 财联社)
- Stock research reports from broker analysts
- Web search for latest news and announcements
- 6 analysis templates: stock, sector, market overview, comparison, risk, deep research
- Reports auto-saved to document knowledge base

### 2. Market Data (行情)
- Multi-source realtime quotes: Tencent (default), Sina, Yahoo Finance
- Candlestick K-line charts with MA/Bollinger/Volume indicators
- Buy/Sell 5-level order book
- Market indices: 上证指数, 深圳成指, 创业板指
- Watchlist management with auto-refresh (10s interval)
- Stock search with pinyin autocomplete

### 3. Simulated Trading (模拟盘)
- Paper trading with realistic commission/tax calculation
- Stock search autocomplete with realtime price display
- 5-level order book for price selection
- Position tracking and P&L calculation
- Order history

### 4. Trading Strategy (交易策略)
- Create/edit strategies with technical indicators
- Buy/sell conditions and risk rules
- AI strategy assistant with **real-time streaming**
- Apply strategy to specific stocks for buy/sell analysis
- Strategy templates: MA crossover, RSI, Bollinger, MACD

### 5. Quantitative Trading (量化交易)
- 6 preset templates (幻方量化 style): Dual MA, MACD, Bollinger, RSI, Multi-factor, Turtle
- Custom strategy code editor
- Historical backtesting engine
- Performance metrics: Sharpe, Sortino, Calmar, max drawdown, win rate
- Equity curve visualization
- AI quant assistant with **real-time streaming**

### 6. AI Assistant (AI助手) — Agent Playground
- Chat with AgentCore Runtime agent (Claude Sonnet 4.6)
- **Real-time streaming output** — see agent text as it generates, no tool call noise
- **Skill Control Panel**: toggle 9+ skills on/off
- **Smart Select**: AgentCore Registry semantic search auto-selects relevant skills
- **Agent presets**: Orchestrator, Analyst, Trader, Quant with skill presets
- Conversation stored in AgentCore Memory (STM + LTM)
- SCOPE self-evolution: agent learns from interactions
- Browser and Code Interpreter tools available
- Session history with multi-session management

### 7. Scheduled Tasks (定期任务)
- **Natural language task creation** — AI auto-parses cron expressions
- 6 preset tasks for new users:
  - 每日A股市场分析 (工作日15:00)
  - 每周买卖信号检查 (周一9:00)
  - 每日收盘绩效报告 (工作日16:00)
  - 每周市场周报 (周五15:00)
  - **每日走势预测** (工作日14:30) — 预测自选股和大盘明日走势
  - **每周预测验证与自我改进** (周一9:00) — 验证准确率, 自我改进
- **Edit each task**: name, description, prompt, cron expression, notification email
- **Enable/disable** individual tasks
- **Run immediately** with real-time streaming output
- **SNS email notifications** — auto-subscribe, results sent after execution
- EventBridge cron scheduling

### 8. Authentication (用户认证)
- **Amazon Cognito** integration — secure user authentication
- **Local DB fallback** — works without Cognito for development
- **Self-registration** — new users can register (when Cognito enabled)
- **Per-user data isolation** — each user has independent sessions, watchlists, portfolios, strategies, tasks
- **Shared Registry Skills** — all users access the same AgentCore Registry
- **Auto-seed on first login** — new users get default watchlist (5 stocks), portfolio (¥1M), and 6 scheduled tasks
- JWT token-based API authentication

### 9. Notifications (通知)
- **Amazon SNS** for email notifications (not SES)
- Auto-subscribe email to SNS topic on first use
- Scheduled task results sent via SNS after execution
- Notification email configurable per-user in Settings
- Updating notification email auto-updates all scheduled tasks

### 10. Skills Management
- 9 built-in skills + external imports
- Import from URL (GitHub) or AI-generated
- Auto-publish to AgentCore Registry with approval workflow
- LLM-powered security scanning

### 11. Document Knowledge Base (文档知识库)
- Store analysis reports, strategy documents
- pgvector embeddings for semantic search
- Auto-save agent analysis results

### 12. Settings
- LLM model switching (9 models: Claude 4.x, Nova, Haiku)
- Max tokens configuration (1K-64K slider)
- Notification email (SNS) configuration with test button
- Data source management

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, TypeScript, Tailwind CSS, Recharts, Vite |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Pydantic 2 |
| Agent SDK | Claude Agent SDK (`claude-agent-sdk`), Sub-agents + Skills + in-process MCP tools |
| Runtime | AWS Bedrock AgentCore Runtime (ARM64, VPC) |
| LLM | Bedrock Claude Sonnet 4.6 (default), 9 models available |
| Memory | AgentCore Memory (STM + LTM, SCOPE self-evolution) |
| Registry | AgentCore Registry (9+ skill records, semantic search) |
| Browser | AgentCore Browser (Public, Web Bot Auth) |
| Code Exec | AgentCore Code Interpreter (Public) |
| Observability | AgentCore Observability (OTEL → CloudWatch) |
| Database | Amazon Aurora PostgreSQL Serverless v2 (13 tables) |
| Cache | Amazon ElastiCache Redis Serverless (TLS) |
| Hosting | CloudFront + S3 (frontend), ECS Fargate + ALB (backend) |
| Auth | Amazon Cognito + JWT (per-user isolation) |
| Notifications | Amazon SNS (email subscriptions) |
| Scheduling | EventBridge cron rules |
| Streaming | SSE (Server-Sent Events) with real-time text chunks |

## Real-time Streaming

All agent-powered features use SSE streaming for real-time output:

```
Frontend                    Backend (FastAPI)              AgentCore Runtime
   │                            │                              │
   │── POST /api/chat/ ────────►│                              │
   │                            │── invoke_streaming() ───────►│
   │◄── SSE: {type:"ping"} ────│                              │
   │◄── SSE: {type:"status"} ──│◄── status updates ──────────│
   │◄── SSE: {type:"text"} ────│◄── text chunks ─────────────│
   │◄── SSE: {type:"text"} ────│◄── text chunks ─────────────│
   │◄── SSE: {type:"result"} ──│◄── final result ────────────│
   │                            │                              │
   │  (User sees text appear    │  (No tool call details       │
   │   in real-time)            │   exposed to user)           │
```

Supported pages: AI助手, 投资分析, 交易策略, 量化交易, 定期任务

## Local Development

### Prerequisites
- Python 3.12+, Node.js 18+, Docker (for PostgreSQL/Redis or use docker-compose)
- AWS credentials configured (`aws configure`)
- Bedrock model access enabled (Claude Sonnet 4.6)

### Setup
```bash
# 1. Start databases (option A: docker-compose)
docker-compose up -d

# 1. Start databases (option B: local install)
sudo systemctl start postgresql redis6
sudo -u postgres psql -c "CREATE DATABASE securities_trading OWNER postgres;"

# 2. Backend
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .
cp env/local.env .env    # Local dev (localhost DB/Redis)
# or: cp env/aws.env .env  # Use AWS Aurora/Redis/Cognito
python -m db.seed        # Initialize seed data
python main.py           # http://localhost:8000

# 3. Frontend
cd frontend
npm install
npm run dev              # http://localhost:3000 (proxies /api to :8000)
```

### Default Accounts

| Username | Password | Source | Notes |
|----------|----------|--------|-------|
| demo | demo123456 | Local DB | Works when Cognito disabled |
| admin | Admin@2026! | Cognito | Works when Cognito enabled |
| pingaws | Pingaws@2026! | Cognito | Works when Cognito enabled |

New users can self-register via the login page when Cognito is enabled.

## AWS Deployment

### Infrastructure (deployed in us-east-1)

| Resource | Details |
|----------|---------|
| Aurora PostgreSQL | `securities-trading-aurora` (Serverless v2, VPC-only SG) |
| ElastiCache Redis | `securities-trading-redis` (Serverless, TLS, VPC-only SG) |
| ECS Fargate | `securities-trading` cluster, `backend` service (2 tasks, ARM64) |
| ALB | `securities-trading-alb` → ECS target group (port 8000) |
| ECR | `securities-trading-backend` (Docker image) |
| CloudFront | `dt0u20qd1sod9.cloudfront.net` (OAC→S3 + /api/*→ALB) |
| S3 | `sec-trading-web-app-prod` (private, OAC only) |
| Cognito | `SecuritiesTradingUserPool` (`us-east-1_DpOE0uo8p`) |
| SNS | `securities-trading-notifications` (email subscriptions) |
| AgentCore Runtime | `SecuritiesTradingAgent-Ma2PoA8Zw8` (Public network) |
| AgentCore Memory | `SecuritiesTradingMemory-PhU3ojCYpp` (STM+LTM, 3 strategies) |
| AgentCore Registry | `Eea8hqxihmpeJlYv` (9 skills, all APPROVED) |
| AgentCore Browser | `SecuritiesTradingBrowser-F6aHtUeGkj` (Public + Web Bot Auth) |
| AgentCore Code Interpreter | `SecuritiesTradingCodeInterpreter-wGp9YodWEL` |

### Deploy Commands
```bash
# Frontend → S3 + CloudFront
cd frontend && npm run build
aws s3 sync dist/ s3://sec-trading-web-app-prod/ --delete --region us-east-1
aws cloudfront create-invalidation --distribution-id EFHJYSE515D2O --paths "/*"

# Backend → ECR + ECS Fargate
cd backend
docker build -t securities-trading-backend .
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 632930644527.dkr.ecr.us-east-1.amazonaws.com
docker tag securities-trading-backend:latest 632930644527.dkr.ecr.us-east-1.amazonaws.com/securities-trading-backend:latest
docker push 632930644527.dkr.ecr.us-east-1.amazonaws.com/securities-trading-backend:latest
aws ecs update-service --cluster securities-trading --service backend --force-new-deployment

# AgentCore Runtime
cd backend && source .venv/bin/activate
agentcore launch

# Registry Skills Update
# Login via API, then POST /api/skills/update-registry

# Full infrastructure setup
python infra/deploy_aws.py plan    # Preview
python infra/deploy_aws.py deploy  # Deploy all
python infra/deploy_aws.py status  # Check status
```

### Security Groups
```
ALB SG (sg-alb)         : TCP 80/443 ← 0.0.0.0/0
ECS SG (sg-ecs)         : TCP 8000 ← ALB SG
Aurora SG (sg-aurora)   : TCP 5432 ← VPC CIDR + ECS SG + Runtime SG
Redis SG (sg-redis)     : TCP 6379 ← VPC CIDR + ECS SG + Runtime SG
Runtime SG (sg-runtime) : outbound all
```

## Project Structure
```
├── backend/
│   ├── .claude/skills/                # Claude Agent SDK Skills (progressive disclosure)
│   │   ├── investment-analysis/SKILL.md
│   │   ├── stock-trading/SKILL.md
│   │   ├── quant-trading/SKILL.md
│   │   └── market-data/SKILL.md
│   ├── agents/
│   │   ├── orchestrator_agent.py      # Main agent: claude-agent-sdk query() + AgentCore Runtime entry
│   │   ├── subagents.py               # AgentDefinition sub-agents (analyst / trader / quant)
│   │   ├── sdk_tools.py               # SDK @tool wrappers + in-process MCP server (securities)
│   │   ├── model_loader.py            # Bedrock model catalog + env setup (CLAUDE_CODE_USE_BEDROCK)
│   │   ├── runtime_client.py          # AgentCore Runtime client (local SDK fallback)
│   │   └── skills/                    # Plain business-logic functions (also called by routes)
│   │       ├── market_data_skill.py   # Multi-source quotes, K-line, order book
│   │       ├── analysis_skill.py      # Technical indicators, reports
│   │       ├── web_fetch_skill.py     # Web search (DDG + Bing)
│   │       ├── crawler_skill.py       # Financial crawlers (东方财富/新浪/财联社)
│   │       ├── trading_skill.py       # Simulated trading, signals
│   │       ├── quant_skill.py         # Backtesting engine, 6 templates
│   │       └── notification_skill.py  # SNS email notifications
│   ├── api/
│   │   ├── auth.py                    # Cognito + JWT + auto-seed new users
│   │   ├── schemas.py                 # Pydantic request/response models
│   │   └── routes/
│   │       ├── auth_routes.py         # Login, register, profile, config
│   │       ├── chat_routes.py         # AI chat (SSE streaming)
│   │       ├── market_routes.py       # Quotes, K-line, indices
│   │       ├── portfolio_routes.py    # Simulated trading
│   │       ├── strategy_routes.py     # Trading + quant strategies (SSE streaming)
│   │       ├── analysis_routes.py     # Investment analysis (SSE streaming)
│   │       ├── scheduler_routes.py    # Scheduled tasks (SSE streaming, SNS notify)
│   │       ├── watchlist_routes.py    # Watchlist CRUD
│   │       ├── skill_routes.py        # Skills + Registry management
│   │       ├── document_routes.py     # Document knowledge base
│   │       ├── scanning_routes.py     # LLM security scanning
│   │       └── settings_routes.py     # LLM switch, max tokens, SNS test
│   ├── db/
│   │   ├── database.py                # SQLAlchemy async engine + migrations
│   │   ├── models.py                  # 13 tables (User, Stock, Portfolio, etc.)
│   │   ├── redis_client.py            # Redis cache client
│   │   └── seed.py                    # Seed data (stocks, strategies, scheduler tasks)
│   ├── config/settings.py             # Pydantic settings (env-based)
│   ├── main.py                        # FastAPI app entry
│   ├── Dockerfile                     # ECS Fargate container
│   ├── .bedrock_agentcore.yaml        # AgentCore deployment config
│   └── env/ (local.env, aws.env)
├── frontend/src/
│   ├── services/
│   │   ├── api.ts                     # Axios client with auth interceptor
│   │   └── streaming.ts              # SSE streaming helper
│   ├── store/authStore.ts             # Zustand auth state (Cognito-aware)
│   └── pages/
│       ├── LoginPage.tsx              # Login + Register (Cognito toggle)
│       ├── DashboardPage.tsx          # Indices + watchlist + portfolio
│       ├── AnalysisPage.tsx           # Quick + AI deep analysis (streaming)
│       ├── MarketPage.tsx             # Quotes + K-line + watchlist
│       ├── PortfolioPage.tsx          # Trading with order book
│       ├── StrategyPage.tsx           # Trading strategies (streaming)
│       ├── QuantPage.tsx              # Quant backtesting (streaming)
│       ├── ChatPage.tsx               # Agent Playground + Skill Control (streaming)
│       ├── SchedulerPage.tsx          # Scheduled tasks (edit, toggle, streaming)
│       ├── SkillsPage.tsx             # Skills management
│       ├── DocumentsPage.tsx          # Document knowledge base
│       ├── ScanningPage.tsx           # LLM security scanning
│       └── SettingsPage.tsx           # LLM + SNS notification config
├── infra/deploy_aws.py                # AWS deployment script
├── docker-compose.yml                 # Local dev (PostgreSQL + Redis)
└── README.md
```

## Live URL
- **Frontend**: https://dt0u20qd1sod9.cloudfront.net
- **API Health**: https://dt0u20qd1sod9.cloudfront.net/api/health
- **CloudWatch**: [GenAI Observability Dashboard](https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#gen-ai-observability/agent-core)
