# 部署记录 — securities-trading-cc (并行新环境)

与现有生产 (`securities-trading`) 完全隔离的全新一套环境, 区域 us-east-1, 账号 632930644527。
通过 CDK (`project=securities-trading-cc`) + boto3 (AgentCore) 部署。

## 访问入口
- 前端 (CloudFront, OAC, S3 禁止 public access): https://d1tzdolf7o9pmw.cloudfront.net
- API: 经 CloudFront `/api/*` → ALB → ECS
- ALB: securities-trading-cc-alb-1243409214.us-east-1.elb.amazonaws.com

## 资源 ID
| 资源 | 标识 |
|------|------|
| VPC | vpc-066df4769eaf3fa9f |
| Aurora PostgreSQL v2 | securities-trading-cc-aurora.cluster-c7b8fns5un9o.us-east-1.rds.amazonaws.com |
| Aurora 凭证 (Secrets) | securities-trading-cc/aurora-credentials-UqI240 |
| Redis Serverless | securities-trading-cc-redis-0uiite.serverless.use1.cache.amazonaws.com |
| EFS (skills) | fs-022341283bb29952e |
| EFS Access Point | fsap-056c4a9dac04b3e6c (mount /mnt/skills, POSIX 1000:1000) |
| Cognito User Pool | us-east-1_ilJF1JJub |
| Cognito Client | 5b3ls2l27ndflbf5lc9fhhuumm |
| SNS Topic | securities-trading-cc-notifications |
| ECR | 632930644527.dkr.ecr.us-east-1.amazonaws.com/securities-trading-cc-backend |
| ECS Cluster / Service | securities-trading-cc / backend |
| CloudFront Dist | E3HH2Q94JAJUMM |
| S3 (web) | securities-trading-cc-web-632930644527-us-east-1 (BlockPublicAccess=ALL) |
| AgentCore Runtime | SecuritiesTradingCcAgent-hupUVh2j1u (VPC mode, EFS /mnt/skills) |
| AgentCore Browser | SecuritiesTradingCcBrowser-WHsc01o4UM |
| AgentCore CodeInterpreter | SecuritiesTradingCcCodeInterpreter-hbgGFem27Y |
| Runtime IAM Role | securities-trading-cc-runtime-role |

## Skill via EFS
AgentCore Runtime 以 VPC 模式挂载 EFS access point 到 `/mnt/skills`。
容器 (env `AGENTCORE_SKILLS_ROOT=/mnt/skills`) 首次启动把内置 4 个 skill seed 到 EFS,
之后用户运行时导入/AI生成的 skill 落在 EFS, 跨 session/agent 共享、持久、可读写。

## 同一镜像两种角色 (entrypoint.sh)
- ECS (默认): `uvicorn main:app` (FastAPI, 8000)
- AgentCore Runtime (`RUN_MODE=agent`): `python -m agents.orchestrator_agent` (BedrockAgentCoreApp, 8080)
镜像以非 root (uid 1000) 运行: Claude CLI 拒绝 root + `--dangerously-skip-permissions`;
uid 1000 同时匹配 EFS access point POSIX user。

## 部署命令
```bash
# 基础设施 (CDK)
cd infra/cdk && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export CDK_DEFAULT_ACCOUNT=632930644527 CDK_DEFAULT_REGION=us-east-1
npx cdk deploy securities-trading-cc-network securities-trading-cc-data securities-trading-cc-auth --require-approval never
# 镜像
cd ../../backend && docker build -t securities-trading-cc-backend:latest .
aws ecr get-login-password --region us-east-1 | docker login -u AWS --password-stdin 632930644527.dkr.ecr.us-east-1.amazonaws.com
docker tag securities-trading-cc-backend:latest 632930644527.dkr.ecr.us-east-1.amazonaws.com/securities-trading-cc-backend:latest
docker push 632930644527.dkr.ecr.us-east-1.amazonaws.com/securities-trading-cc-backend:latest
# 后端 (带 AgentCore IDs)
cd ../infra/cdk && npx cdk deploy securities-trading-cc-backend --require-approval never \
  -c runtime_arn=arn:aws:bedrock-agentcore:us-east-1:632930644527:runtime/SecuritiesTradingCcAgent-hupUVh2j1u \
  -c browser_id=SecuritiesTradingCcBrowser-WHsc01o4UM -c ci_id=SecuritiesTradingCcCodeInterpreter-hbgGFem27Y
# 前端
cd ../../frontend && npm run build
aws s3 sync dist/ s3://securities-trading-cc-web-632930644527-us-east-1/ --delete --region us-east-1
aws cloudfront create-invalidation --distribution-id E3HH2Q94JAJUMM --paths "/*"
```
