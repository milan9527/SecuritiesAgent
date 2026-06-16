#!/usr/bin/env python3
"""
证券交易助手 Agent 平台 - CDK App Entry Point

Usage:
  cd infra/cdk
  pip install -r requirements.txt
  cdk synth                          # Preview CloudFormation template
  cdk deploy --all                   # Deploy all stacks
  cdk deploy --all -c region=us-west-2  # Deploy to specific region
  cdk destroy --all                  # Destroy all resources
"""
import os
import aws_cdk as cdk
from stacks.network_stack import NetworkStack
from stacks.data_stack import DataStack
from stacks.auth_stack import AuthStack
from stacks.backend_stack import BackendStack
from stacks.frontend_stack import FrontendStack

app = cdk.App()

# Configuration
region = app.node.try_get_context("region") or os.environ.get("CDK_DEFAULT_REGION", "us-east-1")
account = os.environ.get("CDK_DEFAULT_ACCOUNT", "")

env = cdk.Environment(account=account, region=region) if account else cdk.Environment(region=region)
# 项目前缀可经 -c project=... 覆盖。默认 securities-trading-cc, 与现有生产 (securities-trading) 并行隔离。
project = app.node.try_get_context("project") or "securities-trading-cc"

# Stack 1: VPC & Security Groups
network = NetworkStack(app, f"{project}-network", env=env, project=project)

# Stack 2: Aurora PostgreSQL + ElastiCache Redis
data = DataStack(app, f"{project}-data", env=env, project=project, vpc=network.vpc,
                 db_sg=network.db_sg, redis_sg=network.redis_sg, efs_sg=network.efs_sg)

# Stack 3: Cognito User Pool + SNS Topic
auth = AuthStack(app, f"{project}-auth", env=env, project=project)

# Stack 4: ECR + ECS Fargate + ALB (Backend API)
backend = BackendStack(app, f"{project}-backend", env=env, project=project,
                       vpc=network.vpc, ecs_sg=network.ecs_sg, alb_sg=network.alb_sg,
                       db_cluster=data.db_cluster, redis_cache=data.redis_cache,
                       user_pool=auth.user_pool, user_pool_client=auth.user_pool_client,
                       sns_topic=auth.sns_topic,
                       skills_fs=data.skills_fs, skills_ap=data.skills_ap,
                       efs_sg=network.efs_sg,
                       agentcore_runtime_arn=app.node.try_get_context("runtime_arn") or "",
                       agentcore_browser_id=app.node.try_get_context("browser_id") or "",
                       agentcore_ci_id=app.node.try_get_context("ci_id") or "",
                       agentcore_memory_id=app.node.try_get_context("memory_id") or "")

# Stack 5: S3 + CloudFront (Frontend)
frontend = FrontendStack(app, f"{project}-frontend", env=env, project=project,
                         backend_alb=backend.alb)

app.synth()
