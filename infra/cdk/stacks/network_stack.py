"""
Network Stack - VPC, Subnets, Security Groups
"""
from aws_cdk import (
    Stack, CfnOutput,
    aws_ec2 as ec2,
)
from constructs import Construct


class NetworkStack(Stack):
    def __init__(self, scope: Construct, id: str, project: str, **kwargs):
        super().__init__(scope, id, **kwargs)

        # VPC with public + private subnets
        self.vpc = ec2.Vpc(self, "Vpc",
            vpc_name=f"{project}-vpc",
            max_azs=3,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="Public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24),
                ec2.SubnetConfiguration(name="Private", subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS, cidr_mask=24),
                ec2.SubnetConfiguration(name="Isolated", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=24),
            ],
        )

        # ALB Security Group (public HTTP/HTTPS)
        self.alb_sg = ec2.SecurityGroup(self, "AlbSg",
            vpc=self.vpc, security_group_name=f"{project}-alb-sg",
            description="ALB - public HTTP/HTTPS",
            allow_all_outbound=True,
        )
        self.alb_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80), "HTTP")
        self.alb_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), "HTTPS")

        # ECS Security Group (from ALB only)
        self.ecs_sg = ec2.SecurityGroup(self, "EcsSg",
            vpc=self.vpc, security_group_name=f"{project}-ecs-sg",
            description="ECS Fargate tasks",
            allow_all_outbound=True,
        )
        self.ecs_sg.add_ingress_rule(self.alb_sg, ec2.Port.tcp(8000), "From ALB")

        # Aurora Security Group (from ECS + VPC)
        self.db_sg = ec2.SecurityGroup(self, "DbSg",
            vpc=self.vpc, security_group_name=f"{project}-aurora-sg",
            description="Aurora PostgreSQL - VPC internal",
            allow_all_outbound=False,
        )
        self.db_sg.add_ingress_rule(self.ecs_sg, ec2.Port.tcp(5432), "From ECS")
        self.db_sg.add_ingress_rule(ec2.Peer.ipv4(self.vpc.vpc_cidr_block), ec2.Port.tcp(5432), "From VPC")

        # Redis Security Group (from ECS + VPC)
        self.redis_sg = ec2.SecurityGroup(self, "RedisSg",
            vpc=self.vpc, security_group_name=f"{project}-redis-sg",
            description="ElastiCache Redis - VPC internal",
            allow_all_outbound=False,
        )
        self.redis_sg.add_ingress_rule(self.ecs_sg, ec2.Port.tcp(6379), "From ECS")
        self.redis_sg.add_ingress_rule(ec2.Peer.ipv4(self.vpc.vpc_cidr_block), ec2.Port.tcp(6379), "From VPC")

        # AgentCore Runtime Security Group (VPC-mode Runtime ENIs; needs EFS mount)
        self.runtime_sg = ec2.SecurityGroup(self, "RuntimeSg",
            vpc=self.vpc, security_group_name=f"{project}-runtime-sg",
            description="AgentCore Runtime - VPC mode (EFS skills mount)",
            allow_all_outbound=True,
        )

        # EFS Security Group (NFS 2049 from Runtime + ECS)
        self.efs_sg = ec2.SecurityGroup(self, "EfsSg",
            vpc=self.vpc, security_group_name=f"{project}-efs-sg",
            description="EFS skills - NFS 2049 from Runtime/ECS",
            allow_all_outbound=True,
        )
        self.efs_sg.add_ingress_rule(self.runtime_sg, ec2.Port.tcp(2049), "NFS from Runtime")
        self.efs_sg.add_ingress_rule(self.ecs_sg, ec2.Port.tcp(2049), "NFS from ECS")

        # Outputs
        CfnOutput(self, "VpcId", value=self.vpc.vpc_id)
        CfnOutput(self, "AlbSgId", value=self.alb_sg.security_group_id)
        CfnOutput(self, "EcsSgId", value=self.ecs_sg.security_group_id)
        CfnOutput(self, "RuntimeSgId", value=self.runtime_sg.security_group_id)
        CfnOutput(self, "EfsSgId", value=self.efs_sg.security_group_id)
        CfnOutput(self, "PrivateSubnetIds",
                  value=",".join(s.subnet_id for s in self.vpc.private_subnets))
