"""
Backend Stack - ECR + ECS Fargate + ALB
"""
from aws_cdk import (
    Stack, Duration, RemovalPolicy, CfnOutput,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecr as ecr,
    aws_iam as iam,
    aws_logs as logs,
    aws_elasticloadbalancingv2 as elbv2,
    aws_rds as rds,
    aws_elasticache as elasticache,
    aws_cognito as cognito,
    aws_sns as sns,
    aws_efs as efs,
)
from constructs import Construct


class BackendStack(Stack):
    def __init__(self, scope: Construct, id: str, project: str,
                 vpc: ec2.Vpc, ecs_sg: ec2.SecurityGroup, alb_sg: ec2.SecurityGroup,
                 db_cluster: rds.DatabaseCluster,
                 redis_cache: elasticache.CfnServerlessCache,
                 user_pool: cognito.UserPool,
                 user_pool_client: cognito.UserPoolClient,
                 sns_topic: sns.Topic,
                 skills_fs: efs.FileSystem = None,
                 skills_ap: efs.AccessPoint = None,
                 efs_sg: ec2.SecurityGroup = None,
                 agentcore_runtime_arn: str = "",
                 agentcore_browser_id: str = "",
                 agentcore_ci_id: str = "",
                 agentcore_memory_id: str = "",
                 agentcore_websearch_gateway_url: str = "",
                 scheduler_mode: str = "apscheduler",
                 scheduler_invoke_token: str = "",
                 scheduler_role_arn: str = "",
                 scheduler_lambda_arn: str = "",
                 scheduler_group: str = "",
                 **kwargs):
        super().__init__(scope, id, **kwargs)

        # ── ECR Repository ──
        self.ecr_repo = ecr.Repository(self, "EcrRepo",
            repository_name=f"{project}-backend",
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[ecr.LifecycleRule(max_image_count=10)],
        )

        # ── ECS Cluster ──
        cluster = ecs.Cluster(self, "EcsCluster",
            cluster_name=project,
            vpc=vpc,
            container_insights_v2=ecs.ContainerInsights.ENABLED,
        )

        # ── Task Role (permissions for the running container) ──
        task_role = iam.Role(self, "TaskRole",
            role_name=f"{project}-ecs-task-role",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )
        # Bedrock (LLM + AgentCore)
        task_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("AmazonBedrockFullAccess"))
        # AgentCore Runtime/Browser/CodeInterpreter/Registry invoke (NOT covered by AmazonBedrockFullAccess)
        task_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "bedrock-agentcore:InvokeAgentRuntime", "bedrock-agentcore:InvokeAgentRuntimeForUser",
                "bedrock-agentcore:InvokeCodeInterpreter", "bedrock-agentcore:InvokeBrowser",
                "bedrock-agentcore:StartCodeInterpreterSession", "bedrock-agentcore:StartBrowserSession",
                "bedrock-agentcore:GetCodeInterpreterSession", "bedrock-agentcore:GetBrowserSession",
                "bedrock-agentcore:StopCodeInterpreterSession", "bedrock-agentcore:StopBrowserSession",
                "bedrock-agentcore:ListBrowserSessions",
                "bedrock-agentcore:CreateEvent", "bedrock-agentcore:ListEvents",
                "bedrock-agentcore:RetrieveMemoryRecords",
                "bedrock-agentcore:SearchRegistryRecords", "bedrock-agentcore:GetRegistryRecord",
            ],
            resources=["*"],
        ))
        # SES (HTML email notifications)
        task_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSESFullAccess"))
        # SNS (fallback notifications)
        sns_topic.grant_publish(task_role)
        # Cognito (user management)
        task_role.add_to_policy(iam.PolicyStatement(
            actions=["cognito-idp:*"],
            resources=[user_pool.user_pool_arn],
        ))
        # Secrets Manager (Aurora credentials)
        db_cluster.secret.grant_read(task_role)
        # EventBridge (legacy rules) + EventBridge Scheduler (定期任务: 每任务一个 schedule)
        task_role.add_to_policy(iam.PolicyStatement(
            actions=["events:PutRule", "events:DeleteRule", "events:PutTargets", "events:RemoveTargets",
                     "scheduler:CreateSchedule", "scheduler:UpdateSchedule", "scheduler:DeleteSchedule",
                     "scheduler:GetSchedule", "scheduler:ListSchedules",
                     "scheduler:CreateScheduleGroup", "scheduler:GetScheduleGroup"],
            resources=["*"],
        ))
        # 允许把 scheduler-invoke-role 传给 EventBridge Scheduler (创建 schedule 时)
        task_role.add_to_policy(iam.PolicyStatement(
            actions=["iam:PassRole"],
            resources=[f"arn:aws:iam::{self.account}:role/{project}-scheduler-invoke-role"],
            conditions={"StringEquals": {"iam:PassedToService": "scheduler.amazonaws.com"}},
        ))
        # CloudWatch Logs
        task_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchLogsFullAccess"))
        # EFS (shared skills dir — backend writes imported skills the Runtime agent reads)
        if skills_fs is not None:
            task_role.add_to_policy(iam.PolicyStatement(
                actions=["elasticfilesystem:ClientMount", "elasticfilesystem:ClientWrite",
                         "elasticfilesystem:DescribeMountTargets"],
                resources=[skills_fs.file_system_arn],
            ))

        # ── Task Definition ──
        task_def = ecs.FargateTaskDefinition(self, "TaskDef",
            family=f"{project}-backend",
            cpu=1024,       # 1 vCPU
            memory_limit_mib=2048,  # 2 GB
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.ARM64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
            task_role=task_role,
        )

        # ── EFS volume (shared skills dir, same access point as AgentCore Runtime) ──
        skills_mount_path = "/mnt/skills"
        skills_enabled = skills_fs is not None and skills_ap is not None
        if skills_enabled:
            task_def.add_volume(
                name="skills",
                efs_volume_configuration=ecs.EfsVolumeConfiguration(
                    file_system_id=skills_fs.file_system_id,
                    transit_encryption="ENABLED",
                    authorization_config=ecs.AuthorizationConfig(
                        access_point_id=skills_ap.access_point_id,
                        iam="ENABLED",
                    ),
                ),
            )

        # Log group
        log_group = logs.LogGroup(self, "LogGroup",
            log_group_name=f"/ecs/{project}-backend",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Container
        container = task_def.add_container("Backend",
            container_name="backend",
            image=ecs.ContainerImage.from_ecr_repository(self.ecr_repo, tag="latest"),
            logging=ecs.LogDrivers.aws_logs(stream_prefix="ecs", log_group=log_group),
            environment={
                "ENV": "aws",
                "DEBUG": "false",
                "AWS_REGION": self.region,
                "HOST": "0.0.0.0",
                "PORT": "8000",
                "POSTGRES_HOST": db_cluster.cluster_endpoint.hostname,
                "POSTGRES_PORT": str(db_cluster.cluster_endpoint.port),
                "POSTGRES_DB": "securities_trading",
                "REDIS_HOST": redis_cache.attr_endpoint_address if hasattr(redis_cache, 'attr_endpoint_address') else "",
                "REDIS_PORT": "6379",
                "COGNITO_USER_POOL_ID": user_pool.user_pool_id,
                "COGNITO_CLIENT_ID": user_pool_client.user_pool_client_id,
                "COGNITO_REGION": self.region,
                "SNS_TOPIC_ARN": sns_topic.topic_arn,
                "CORS_ORIGINS": '["*"]',
                "LLM_MODEL_ID": "us.anthropic.claude-sonnet-4-6",
                "LLM_MAX_TOKENS": "16384",
                "LLM_TEMPERATURE": "0.3",
                # AgentCore: backend 通过 Runtime 调用 Agent (空则回退进程内 SDK orchestrator)
                "AGENTCORE_AGENT_ARN": agentcore_runtime_arn,
                "AGENTCORE_BROWSER_ID": agentcore_browser_id,
                "AGENTCORE_CODE_INTERPRETER_ID": agentcore_ci_id,
                "AGENTCORE_MEMORY_ID": agentcore_memory_id,  # 长期记忆 (偏好/摘要/情节)
                "AGENTCORE_WEBSEARCH_GATEWAY_URL": agentcore_websearch_gateway_url,  # AgentCore Web Search 网关
                # 定期任务调度 (EventBridge Scheduler + Lambda)
                "SCHEDULER_MODE": scheduler_mode,
                "SCHEDULER_INVOKE_TOKEN": scheduler_invoke_token,
                "SCHEDULER_ROLE_ARN": scheduler_role_arn,
                "SCHEDULER_LAMBDA_ARN": scheduler_lambda_arn,
                "SCHEDULER_GROUP": scheduler_group or project,
                # 共享 skill 目录 (EFS, 与 Runtime 同一 access point): 导入的 skill 落此处, agent 自动读取
                **({"AGENTCORE_SKILLS_ROOT": skills_mount_path} if skills_enabled else {}),
            },
            secrets={
                "POSTGRES_USER": ecs.Secret.from_secrets_manager(db_cluster.secret, "username"),
                "POSTGRES_PASSWORD": ecs.Secret.from_secrets_manager(db_cluster.secret, "password"),
            },
            health_check=ecs.HealthCheck(
                command=["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"],
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                retries=3,
                start_period=Duration.seconds(60),
            ),
        )
        container.add_port_mappings(ecs.PortMapping(container_port=8000, protocol=ecs.Protocol.TCP))
        if skills_enabled:
            container.add_mount_points(ecs.MountPoint(
                source_volume="skills",
                container_path=skills_mount_path,
                read_only=False,
            ))

        # ── ALB ──
        self.alb = elbv2.ApplicationLoadBalancer(self, "Alb",
            load_balancer_name=f"{project}-alb",
            vpc=vpc,
            internet_facing=True,
            security_group=alb_sg,
        )

        # ── ECS Service ──
        service = ecs.FargateService(self, "Service",
            service_name="backend",
            cluster=cluster,
            task_definition=task_def,
            desired_count=2,
            security_groups=[ecs_sg],
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            assign_public_ip=False,
            health_check_grace_period=Duration.seconds(120),
            min_healthy_percent=50,
            max_healthy_percent=200,
        )

        # ALB Target Group + Listener
        listener = self.alb.add_listener("HttpListener", port=80)
        target_group = listener.add_targets("EcsTargets",
            port=8000,
            targets=[service],
            health_check=elbv2.HealthCheck(
                path="/health",
                interval=Duration.seconds(30),
                # 放宽: 重型 agent 任务运行时 task 较忙, 给更长超时/更多失败次数,
                # 避免健康检查误杀正在跑长任务的 task。
                timeout=Duration.seconds(10),
                healthy_threshold_count=2,
                unhealthy_threshold_count=5,
            ),
            deregistration_delay=Duration.seconds(30),
        )

        # Auto-scaling
        # min 2: 重型 agent 任务 (定期任务/长对话) 会长时间占满单个 task,
        # 保持 ≥2 个 task 才能一边跑重任务一边正常响应 API/健康检查。
        scaling = service.auto_scale_task_count(min_capacity=2, max_capacity=4)
        scaling.scale_on_cpu_utilization("CpuScaling",
            target_utilization_percent=70,
            scale_in_cooldown=Duration.seconds(60),
            scale_out_cooldown=Duration.seconds(60),
        )

        # Outputs
        CfnOutput(self, "AlbDnsName", value=self.alb.load_balancer_dns_name)
        CfnOutput(self, "AlbArn", value=self.alb.load_balancer_arn)
        CfnOutput(self, "EcrRepoUri", value=self.ecr_repo.repository_uri)
        CfnOutput(self, "EcsClusterName", value=cluster.cluster_name)
        CfnOutput(self, "EcsServiceName", value=service.service_name)
