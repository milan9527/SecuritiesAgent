# 证券交易助手 Agent 平台

AI-powered securities trading assistant built on the **Claude Agent SDK** (`claude-agent-sdk`) and **AWS Bedrock AgentCore**. A general-purpose, finance-focused agent (like Claude Code, but for A-shares): it does investment research, trading-signal generation, quantitative strategy design/backtest/auto-execution, writes & runs code, and runs autonomous scheduled tasks. The orchestrator delegates to specialized **sub-agents** (`AgentDefinition`), works tightly with **Skills** (`.claude/skills/*/SKILL.md` on EFS), and exposes all domain capabilities as in-process MCP tools. Every output the agent produces is persisted into the matching business module.

> This repo deploys the **`securities-trading-cc-*`** stack in `us-east-1` (parallel/isolated from any earlier `securities-trading-*` stack).

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         Frontend (React 18 + Vite + TS)                        │
│  总览 │ 投资分析 │ 行情(含自选股4池) │ 模拟盘 │ 量化策略 │ AI助手 │ 工作区     │
│  文档知识库 │ 定期任务 │ Skill/MCP │ 设置                                       │
└──────────────────────────────┬─────────────────────────────────────────────────┘
                               │ HTTPS (/api/*)
┌──────────────────────────────▼─────────────────────────────────────────────────┐
│           Amazon CloudFront (OAC)  d1tzdolf7o9pmw.cloudfront.net                 │
│  /*    → S3 (private, OAC)            /api/* → ALB (Compress=off for SSE)        │
└──────────────────────────────┬─────────────────────────────────────────────────┘
┌──────────────────────────────▼─────────────────────────────────────────────────┐
│                      ECS Fargate Backend (FastAPI, ARM64, ≥2 tasks)             │
│  Auth(Cognito+JWT) │ Market │ Portfolio │ Strategy/Quant │ Chat(SSE) │ Analysis │
│  Watchlist(4 pools) │ Documents+KB │ Scheduler │ Workspace │ Feishu │ Settings  │
│  + token-guarded internal endpoints (agent → module write-back)                 │
└───┬───────────────┬──────────────────────┬──────────────────────┬───────────────┘
    │               │                      │                      │
┌───▼────────┐ ┌────▼──────────┐  ┌────────▼─────────┐   ┌────────▼────────────────┐
│ Aurora     │ │ ElastiCache   │  │ EFS (/mnt/skills)│   │ AgentCore Runtime        │
│ PostgreSQL │ │ Redis (TLS)   │  │ • skills (SKILL) │   │ SecuritiesTradingCcAgent │
│ Serverless │ │ quote 10s     │  │ • sessions       │   │ ┌──────────────────────┐ │
│ v2 (17 tbl)│ │ kline 60s     │  │ • workspace/<uid>│   │ │ Orchestrator         │ │
└────────────┘ │ scheduler lock│  └──────────────────┘   │ │  ├ investment-analyst│ │
               └───────────────┘                         │ │  ├ stock-trader      │ │
┌─────────────────────────────────────────────┐         │ │  ├ quant-trader      │ │
│ AgentCore services                          │         │ │  └ web-browser       │ │
│ • Memory (STM events + LTM: prefs/summary/  │◄────────│ │ skills="all" (EFS)   │ │
│   episodic) — self-iteration                │         │ └──────────────────────┘ │
│ • Web Search (MCP Gateway, SigV4)           │         │ OTEL → Observability     │
│ • Code Interpreter (custom, public egress)  │         └──────────┬───────────────┘
│ • Browser (custom, public egress)           │                    │
│ • Observability (OTEL → X-Ray + CloudWatch) │             ┌──────▼──────┐
└─────────────────────────────────────────────┘             │ Bedrock     │
                                                            │ Claude      │
EventBridge Scheduler ─► Lambda (thin) ─► /api/.../run-task │ Sonnet 4.6  │
  (per-task, tz-aware Asia/Shanghai)                        └─────────────┘
```

## Agents & Tools

**Orchestrator** (`agents/orchestrator_agent.py`) runs via `claude-agent-sdk` `query()`, is the AgentCore Runtime entrypoint (`BedrockAgentCoreApp`), and delegates to four sub-agents (`agents/subagents.py`):

| Sub-agent | Role | Browser | Code Interp. |
|-----------|------|:---:|:---:|
| `investment-analyst` | research / reports (WebSearch + WebFetch only) | ❌ | ❌ |
| `stock-trader` | strategies / signals / simulated orders | ❌ | ❌ |
| `quant-trader` | quant code / backtest (writes & runs code) | ❌ | ✅ |
| `web-browser` | **only** holder of the browser; for must-render/login/interaction pages | ✅ | ❌ |

- **Web search** = AgentCore Web Search (managed MCP Gateway connector, SigV4); page reading = WebFetch; browser is a quarantined fallback.
- **Persistence MCP tools** let the agent write results into modules: `save_trading_strategy`, `save_quant_strategy`, `add_to_watchlist`, `save_analysis_report`, `save_document`, `create_scheduled_task`, `place_simulated_order`, `list_my_strategies` — via token-guarded internal endpoints (the Runtime has no DB creds).
- **Outputs persist** to a per-user EFS workspace `/mnt/skills/workspace/<user_id>/` (code/documents/data/skills), browsable in the 工作区 page.

## Key Features

1. **投资分析** — quick technical analysis (MA/MACD/RSI/Boll/KDJ) + AI deep research (real-time SSE); reports auto-saved to 分析报告 / 知识库.
2. **行情 (Market)** — multi-source realtime quotes (Tencent/Sina/Yahoo), K-line, order book, indices, pinyin search. **自选股已合并到行情页**, 4 pools: 分析股票池 / 实际交易 / 模拟盘 / 量化交易 (`/api/watchlist/pools`).
3. **模拟盘** — paper trading; positions show **live current price & P&L** (refreshed from live quotes on GET, 30s auto-refresh).
4. **量化策略 (merged 交易策略+量化交易)** — 6 preset templates; NL→strategy generation; backtest; **apply to scope** (watchlist/sector/whole-market → per-stock signals); **auto-execute** (per-strategy toggle → EventBridge scheduled task, trading-hours half-hourly).
5. **AI助手** — full Claude-Code-like agent (Sonnet 4.6) with real-time SSE; multi-session history; outputs land in the right modules; long-term memory via AgentCore Memory.
6. **工作区** — browse/preview/download the agent's persisted artifacts (per-user, EFS), grouped by category.
7. **文档知识库** — documents + pgvector semantic search; auto-categorized on add-to-KB.
8. **定期任务** — NL task creation (LLM→cron); **EventBridge Scheduler + Lambda** (per-user, tz-aware **Beijing time**); enable/disable; per-task **notification email toggle**; run-now (SSE, deduped); results emailed via SES.
9. **Skill/MCP** — EFS-based skills (builtin seeded + import from URL/GitHub); enable/disable; external-skill priority.
10. **设置** — global LLM model dropdown + max-tokens (Redis-backed, applied to Runtime); Feishu IM **enable/disable** + config (encrypt_key supported); notification email.
11. **认证** — Cognito + JWT, local fallback; per-user data isolation; auto-seed on first login.
12. **Observability** — all agents emit OTEL traces/spans to AgentCore Observability (X-Ray + CloudWatch GenAI) via ADOT.
13. **飞书 (Feishu) IM** — chat with the agent from Feishu; webhook supports encrypted events; on/off toggle.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, TypeScript, Tailwind, Recharts, react-markdown, Vite |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), Pydantic 2 |
| Agent SDK | Claude Agent SDK (`claude-agent-sdk`); sub-agents + EFS skills + in-process MCP tools |
| Runtime | AWS Bedrock AgentCore Runtime (ARM64, VPC, EFS mount) |
| LLM | Bedrock Claude Sonnet 4.6 (global LLM settings via Redis) |
| Memory | AgentCore Memory (STM events + LTM: preferences/summary/episodic) |
| Web Search | AgentCore Web Search (MCP Gateway connector, SigV4) — $7/1k queries |
| Browser / Code | AgentCore custom Browser + Code Interpreter (public egress) |
| Observability | AgentCore Observability (ADOT / OTEL → X-Ray + CloudWatch) |
| Database | Aurora PostgreSQL Serverless v2 (17 tables, pgvector) |
| Cache/Lock | ElastiCache Redis Serverless (TLS) |
| Storage | EFS (skills + sessions + per-user workspace) |
| Hosting | CloudFront + S3 (frontend), ECS Fargate + ALB (backend) |
| Auth | Amazon Cognito + JWT |
| Scheduling | EventBridge Scheduler + Lambda (tz-aware, per task) |
| Notifications | Amazon SES (HTML email) |
| Streaming | SSE (real-time token streaming, keepalive pings) |

## Local Development

```bash
# 1. Databases
docker-compose up -d                       # PostgreSQL + Redis

# 2. Backend
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .
cp env/local.env .env                      # or env/aws.env for AWS resources
python -m db.seed
python main.py                             # http://localhost:8000
# Local default: SCHEDULER_MODE=apscheduler (in-process); AWS uses eventbridge

# 3. Frontend
cd frontend && npm install && npm run dev  # http://localhost:3000 (proxies /api → :8000)
```

Prereqs: Python 3.12+, Node 18+, Docker, AWS credentials, Bedrock model access (Claude Sonnet 4.6).

### Accounts
`admin` / `milan` (password `Amazon@2019`); local `demo`/`demo123456` when Cognito disabled. Self-registration available when Cognito is enabled.

## AWS Deployment (us-east-1)

| Resource | ID |
|----------|----|
| CloudFront | `d1tzdolf7o9pmw.cloudfront.net` (dist `E3HH2Q94JAJUMM`) |
| ECS | cluster `securities-trading-cc`, service `backend` (ARM64, ≥2 tasks) |
| ALB | `securities-trading-cc-alb` |
| ECR | `securities-trading-cc-backend` |
| Aurora / Redis | `securities-trading-cc-*` (Serverless, VPC-only) |
| EFS | shared access point → `/mnt/skills` (Runtime + ECS) |
| AgentCore Runtime | `SecuritiesTradingCcAgent-hupUVh2j1u` (VPC + EFS) |
| AgentCore Memory | `SecuritiesTradingCcMemory-5JCaSI84kf` |
| Web Search Gateway | `securities-trading-cc-websearch-cmwj8f1pne` (MCP, AWS_IAM) |
| Scheduler | EventBridge Scheduler group `securities-trading-cc` + Lambda `securities-trading-cc-scheduler-trigger` |
| Cognito / SES | user pool + verified senders |

The same Docker image runs two roles via `RUN_MODE` (`entrypoint.sh`): default = FastAPI on ECS (port 8000); `RUN_MODE=agent` = AgentCore Runtime agent server (port 8080, launched via `opentelemetry-instrument`).

```bash
# Frontend → S3 + CloudFront
cd frontend && npm run build
aws s3 sync dist/ s3://securities-trading-cc-web-632930644527-us-east-1 --delete
aws cloudfront create-invalidation --distribution-id E3HH2Q94JAJUMM --paths "/*"

# Backend → ECR + ECS (and bump Runtime, which re-pulls the same image)
cd backend
REPO=632930644527.dkr.ecr.us-east-1.amazonaws.com/securities-trading-cc-backend
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 632930644527.dkr.ecr.us-east-1.amazonaws.com
docker build --platform linux/arm64 -t $REPO:latest . && docker push $REPO:latest
aws ecs update-service --cluster securities-trading-cc --service backend --force-new-deployment

# CDK (infra)
cd infra/cdk && cdk deploy --all
```

## Project Structure
```
backend/
├── agents/
│   ├── orchestrator_agent.py     # query() + BedrockAgentCoreApp entry; per-user workspace; OTEL
│   ├── subagents.py              # 4 sub-agents (analyst/trader/quant/web-browser)
│   ├── sdk_tools.py              # in-process MCP tools (securities) + persistence + web_search routing
│   ├── otel_setup.py             # OTEL tracing bootstrap (ADOT-aware)
│   ├── memory_store.py           # AgentCore Memory record_turn / recall_context
│   ├── model_loader.py           # Bedrock model catalog + global LLM overrides
│   ├── runtime_client.py         # Runtime invoke (local SDK fallback)
│   ├── builtin_skills.py         # builtin SKILL.md constants (seeded to EFS)
│   ├── skill_store.py / skill_importer.py
│   └── skills/                   # pure business fns (also called by routes)
│       ├── market_data_skill.py  analysis_skill.py  web_fetch_skill.py
│       ├── crawler_skill.py  trading_skill.py  quant_skill.py
│       ├── notification_skill.py
│       └── agentcore_websearch_skill.py   # AgentCore Web Search via SigV4 MCP
├── api/
│   ├── auth.py  internal_auth.py # JWT auth + token-guarded internal-endpoint auth
│   └── routes/                   # auth, chat, market, portfolio, strategy, analysis,
│                                 # scheduler, watchlist, skill, document, workspace, feishu, settings
├── services/
│   ├── task_scheduler.py         # APScheduler fallback + _execute_task (dedup lock)
│   └── eventbridge_scheduler.py  # EventBridge Scheduler per-task sync
├── db/ (database.py, models.py [17 tables], redis_client.py, seed.py)
├── config/ (settings.py, timeutil.py [Beijing time])
├── Dockerfile  entrypoint.sh  pyproject.toml
frontend/src/pages/                # Dashboard, Analysis, Market, Portfolio, Quant, Chat,
                                   # Workspace, Documents, Scheduler, Skills, Settings, Login
infra/
├── cdk/                          # CDK stacks (network/data/auth/backend/frontend)
├── lambda/scheduler_trigger.py   # EventBridge → backend trigger
└── enable_runtime_observability.py
```

## Live URL
- **Frontend**: https://d1tzdolf7o9pmw.cloudfront.net
- **API Health**: https://d1tzdolf7o9pmw.cloudfront.net/api/health
- **Observability**: CloudWatch → GenAI Observability (X-Ray traces, service `securities-trading-agent`)
