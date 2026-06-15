"""pytest 配置 - 离线测试 (不调用 AWS/Bedrock)"""
import os
import sys

# 确保 backend 在 import path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 离线: 不让任何测试真的去打 Bedrock
os.environ.setdefault("AWS_REGION", "us-east-1")
