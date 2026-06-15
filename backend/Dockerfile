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

# Install Python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir -e . 2>/dev/null || pip install --no-cache-dir \
    claude-agent-sdk bedrock-agentcore \
    fastapi "uvicorn[standard]" httpx "sqlalchemy[asyncio]" asyncpg psycopg2-binary \
    alembic redis pydantic pydantic-settings python-dotenv pandas numpy boto3 \
    "python-jose[cryptography]" "passlib[bcrypt]" "bcrypt<5" python-multipart \
    aiohttp apscheduler jinja2 nest-asyncio playwright markdown pgvector

# Copy app
COPY . .

# Route Claude Agent SDK through AWS Bedrock
ENV CLAUDE_CODE_USE_BEDROCK=1

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
