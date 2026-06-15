FROM python:3.12-slim

WORKDIR /app

# Install system deps + Node.js (Claude Agent SDK spawns the Claude Code CLI subprocess)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# Claude Code CLI (required at runtime by claude-agent-sdk)
RUN npm install -g @anthropic-ai/claude-code

# uv/uvx — run the official AWS AgentCore MCP server (browser + code interpreter)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    cp /root/.local/bin/uv /usr/local/bin/uv && \
    cp /root/.local/bin/uvx /usr/local/bin/uvx
# 预拉取 MCP server, 避免运行时首次 uvx 拉包延迟
RUN uvx --help >/dev/null 2>&1 || true

# Install Python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir -e . 2>/dev/null || pip install --no-cache-dir \
    claude-agent-sdk bedrock-agentcore opentelemetry-api opentelemetry-sdk \
    fastapi "uvicorn[standard]" httpx "sqlalchemy[asyncio]" asyncpg psycopg2-binary \
    alembic redis pydantic pydantic-settings python-dotenv pandas numpy boto3 \
    "python-jose[cryptography]" "passlib[bcrypt]" "bcrypt<5" python-multipart \
    aiohttp apscheduler jinja2 nest-asyncio playwright markdown pgvector akshare

# Copy app
COPY . .
RUN chmod +x entrypoint.sh

# Route Claude Agent SDK through AWS Bedrock
ENV CLAUDE_CODE_USE_BEDROCK=1 \
    HOME=/home/appuser

# 非 root 用户 (uid/gid 1000):
#  - Claude CLI 拒绝以 root 使用 --dangerously-skip-permissions
#  - 与 EFS access point 的 POSIX user (1000:1000) 匹配, 保证 /mnt/skills 读写
RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g 1000 -m -d /home/appuser appuser && \
    chown -R appuser:appuser /app /home/appuser
USER appuser

# 8000 = FastAPI (ECS); 8080 = AgentCore Runtime (agent)
EXPOSE 8000 8080

ENTRYPOINT ["./entrypoint.sh"]
