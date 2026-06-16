"""
Frontend Stack - S3 + CloudFront
Routes /* to S3 (SPA), /api/* to ALB (backend)
"""
from aws_cdk import (
    Stack, RemovalPolicy, CfnOutput, Duration,
    aws_s3 as s3,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_elasticloadbalancingv2 as elbv2,
)
from constructs import Construct


class FrontendStack(Stack):
    def __init__(self, scope: Construct, id: str, project: str,
                 backend_alb: elbv2.ApplicationLoadBalancer, **kwargs):
        super().__init__(scope, id, **kwargs)

        # ── S3 Bucket (private, OAC only) ──
        self.bucket = s3.Bucket(self, "WebBucket",
            bucket_name=f"{project}-web-{self.account}-{self.region}",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # ── CloudFront Distribution ──
        # S3 origin (OAC)
        s3_origin = origins.S3BucketOrigin.with_origin_access_control(self.bucket)

        # ALB origin (for /api/*)
        alb_origin = origins.HttpOrigin(
            backend_alb.load_balancer_dns_name,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
            http_port=80,
            connection_timeout=Duration.seconds(10),
            read_timeout=Duration.seconds(60),
        )

        self.distribution = cloudfront.Distribution(self, "Distribution",
            comment=f"{project} - Securities Trading Assistant",
            default_behavior=cloudfront.BehaviorOptions(
                origin=s3_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            additional_behaviors={
                "/api/*": cloudfront.BehaviorOptions(
                    origin=alb_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
                    # 关闭压缩: 开启 Compress 会让 CloudFront 缓冲整个响应再压缩,
                    # 导致 SSE 流式失效 (keepalive ping 不流出 → 60s origin 超时 → 504)。
                    compress=False,
                ),
            },
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
            ],
        )

        # Outputs
        CfnOutput(self, "BucketName", value=self.bucket.bucket_name)
        CfnOutput(self, "DistributionId", value=self.distribution.distribution_id)
        CfnOutput(self, "DistributionDomain", value=self.distribution.distribution_domain_name)
        CfnOutput(self, "WebUrl", value=f"https://{self.distribution.distribution_domain_name}")
