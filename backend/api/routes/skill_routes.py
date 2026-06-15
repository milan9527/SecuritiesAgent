"""
Skill管理路由 - 直接管理AgentCore Registry记录
所有skill数据来自Registry, 本地只缓存builtin skill定义
"""
from __future__ import annotations

import os
import json as _json
import time
import traceback
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from db.models import User, CustomSkill
from api.auth import get_current_user
from api.schemas import CustomSkillCreate, CustomSkillResponse
from config.settings import get_settings

router = APIRouter(prefix="/api/skills", tags=["Skills管理"])
_settings = get_settings()

REGISTRY_ID = _settings.AGENTCORE_REGISTRY_ID
AWS_REGION = _settings.AWS_REGION


def _get_ctrl_client():
    import boto3
    return boto3.client("bedrock-agentcore-control", region_name=AWS_REGION)


def _get_dp_client():
    import boto3
    return boto3.client("bedrock-agentcore", region_name=AWS_REGION)


def _publish_to_registry_optional(name: str, content: str, desc: str) -> dict:
    """配置了 Registry 才发布 (增强, 非必需)。Agent 读 skill 走 EFS, 不依赖 Registry。"""
    if not REGISTRY_ID:
        return {"published": False, "reason": "registry_not_configured"}
    try:
        ctrl = _get_ctrl_client()
        body = content if len(content.encode("utf-8")) <= 60000 else content[:50000]
        r = ctrl.create_registry_record(
            registryId=REGISTRY_ID, name=name[:100], descriptorType="AGENT_SKILLS",
            descriptors={"agentSkills": {"skillMd": {"inlineContent": body}}},
            recordVersion="1.0.0", description=desc[:200],
        )
        rid = r["recordArn"].split("/")[-1]
        try:
            ctrl.submit_registry_record_for_approval(registryId=REGISTRY_ID, recordId=rid)
        except Exception:
            pass
        return {"published": True, "record_id": rid}
    except Exception as e:
        return {"published": False, "reason": str(e)[:150]}


# ═══════════════════════════════════════════════════════
# Builtin skill -> Registry name mapping
# ═══════════════════════════════════════════════════════
BUILTIN_SKILLS = {
    "market-data-skill": {"name": "行情数据技能", "type": "market", "file": "agents/skills/market_data_skill.py"},
    "analysis-skill": {"name": "投资分析技能", "type": "analysis", "file": "agents/skills/analysis_skill.py"},
    "web-fetch-skill": {"name": "Web信息获取技能", "type": "web", "file": "agents/skills/web_fetch_skill.py"},
    "trading-skill": {"name": "交易技能", "type": "trading", "file": "agents/skills/trading_skill.py"},
    "quant-skill": {"name": "量化交易技能", "type": "quant", "file": "agents/skills/quant_skill.py"},
    "notification-skill": {"name": "通知技能", "type": "notification", "file": "agents/skills/notification_skill.py"},
    "crawler-skill": {"name": "专业财经爬虫技能", "type": "web", "file": "agents/skills/crawler_skill.py"},
    "browser-crawler-skill": {"name": "浏览器爬虫技能", "type": "web", "file": ""},
    "code-interpreter-skill": {"name": "代码执行技能", "type": "quant", "file": ""},
}


# ═══════════════════════════════════════════════════════
# Registry Records (核心API)
# ═══════════════════════════════════════════════════════

def _efs_records() -> list[dict]:
    """把 EFS .claude/skills 下的 skill 表示成 registry-record 形状, 供前端列表展示。"""
    from agents.skill_store import list_skills
    recs = []
    for s in list_skills():
        recs.append({
            "record_id": s["name"], "name": s["name"], "display_name": s["name"],
            "status": "INSTALLED", "version": "1.0.0", "description": s["description"],
            "type": "AGENT_SKILLS", "skill_type": "builtin" if s["builtin"] else "external",
            "is_builtin": s["builtin"], "source": "efs", "created_at": "", "updated_at": "",
        })
    recs.sort(key=lambda x: (0 if x["is_builtin"] else 1, x["name"]))
    return recs


@router.get("/registry")
async def list_registry_records(current_user: User = Depends(get_current_user)):
    """列出 skill 记录。Registry 未配置时回退到 EFS .claude/skills (agent 实际读取处)。"""
    if not REGISTRY_ID:
        return {"records": _efs_records(), "source": "efs"}
    try:
        client = _get_ctrl_client()
        resp = client.list_registry_records(registryId=REGISTRY_ID, maxResults=50)
        # Deduplicate by name, keep APPROVED over others
        by_name = {}
        for r in resp.get("registryRecords", []):
            name = r.get("name", "")
            existing = by_name.get(name)
            if not existing or (r.get("status") == "APPROVED" and existing.get("status") != "APPROVED"):
                by_name[name] = r

        records = []
        for name, r in by_name.items():
            builtin = BUILTIN_SKILLS.get(name, {})
            records.append({
                "record_id": r.get("recordId", ""),
                "name": name,
                "display_name": builtin.get("name", name),
                "status": r.get("status", ""),
                "version": r.get("recordVersion", ""),
                "description": r.get("description", ""),
                "type": r.get("descriptorType", ""),
                "skill_type": builtin.get("type", "external"),
                "is_builtin": name in BUILTIN_SKILLS,
                "created_at": str(r.get("createdAt", "")),
                "updated_at": str(r.get("updatedAt", "")),
            })
        # Sort: builtin first, then by name
        records.sort(key=lambda x: (0 if x["is_builtin"] else 1, x["name"]))
        return {"records": records, "registry_id": REGISTRY_ID}
    except Exception as e:
        return {"records": [], "error": str(e)[:200]}


@router.get("/registry/{record_id}")
async def get_registry_record(record_id: str, current_user: User = Depends(get_current_user)):
    """获取Registry记录详情(含完整内容)"""
    if not REGISTRY_ID:
        return {"error": "Registry未配置"}
    try:
        client = _get_ctrl_client()
        r = client.get_registry_record(registryId=REGISTRY_ID, recordId=record_id)
        record = r.get("registryRecord", r)

        # Extract skill content
        content = ""
        descriptors = record.get("descriptors", {})
        agent_skills = descriptors.get("agentSkills", {})
        skill_md = agent_skills.get("skillMd", {})
        content = skill_md.get("inlineContent", "")

        return {
            "record_id": record.get("recordId", record_id),
            "name": record.get("name", ""),
            "status": record.get("status", ""),
            "version": record.get("recordVersion", ""),
            "description": record.get("description", ""),
            "type": record.get("descriptorType", ""),
            "content": content,
            "raw": _json.dumps(descriptors, default=str, indent=2)[:5000],
        }
    except Exception as e:
        return {"error": str(e)[:200]}


class CreateRecordRequest(BaseModel):
    name: str
    description: str = ""
    content: str = ""  # SKILL.md content
    version: str = "1.0.0"


@router.post("/registry")
async def create_registry_record(request: CreateRecordRequest, current_user: User = Depends(get_current_user)):
    """创建/发布一个 Skill —— 写入 EFS .claude/skills (agent 自动读取), Registry 可选。"""
    if not request.name:
        return {"error": "请输入名称"}
    try:
        from agents.skill_store import write_skill
        content = request.content or f"# {request.name}\n\n{request.description}\n"
        info = write_skill(request.name, content, request.description)
        registry_status = _publish_to_registry_optional(info["name"], content, request.description)
        return {
            "record_id": info["name"], "name": info["name"], "status": "INSTALLED",
            "path": info["path"], "registry": registry_status,
            "message": f"Skill '{info['name']}' 已发布, agent 下次调用即可自动使用",
        }
    except Exception as e:
        return {"error": str(e)[:200]}


@router.put("/registry/{record_id}/status")
async def update_record_status(record_id: str, status: str = "APPROVED", current_user: User = Depends(get_current_user)):
    """更新状态。EFS skill 一旦安装即生效, 无审批流程, 直接返回成功。"""
    if REGISTRY_ID:
        try:
            _get_ctrl_client().update_registry_record_status(registryId=REGISTRY_ID, recordId=record_id, status=status)
        except Exception:
            pass
    return {"success": True, "record_id": record_id, "status": status}


@router.delete("/registry/{record_id}")
async def delete_registry_record(record_id: str, current_user: User = Depends(get_current_user)):
    """删除 Skill —— 从 EFS .claude/skills 移除 (内置 skill 不可删); 同时尽力清理 Registry。"""
    from agents.skill_store import delete_skill
    removed = delete_skill(record_id)
    if REGISTRY_ID:
        try:
            _get_ctrl_client().delete_registry_record(registryId=REGISTRY_ID, recordId=record_id)
        except Exception:
            pass
    if not removed:
        return {"success": False, "error": "内置 skill 不可删除或不存在"}
    return {"success": True, "record_id": record_id}


# ═══════════════════════════════════════════════════════
# Import from GitHub URL
# ═══════════════════════════════════════════════════════

class ImportGithubRequest(BaseModel):
    url: str


@router.post("/import-github")
async def import_from_github(request: ImportGithubRequest, current_user: User = Depends(get_current_user)):
    """从URL导入Skill到Registry (支持GitHub, LobeHub等)"""
    import httpx, re, html as html_lib

    url = request.url
    try:
        # Convert GitHub URL to raw content
        raw_url = url
        if "github.com" in url and "/blob/" in url:
            raw_url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
        elif "github.com" in url and "/tree/" in url:
            raw_url = url.replace("github.com", "raw.githubusercontent.com").replace("/tree/", "/") + "/SKILL.md"

        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(raw_url, headers={"User-Agent": "AgentSkillImporter/1.0"})
            resp.raise_for_status()
            raw_content = resp.text

        # Determine if content is HTML or Markdown
        is_html = raw_content.strip().startswith("<!") or "<html" in raw_content[:500].lower()

        if is_html:
            # Extract skill info from HTML meta tags (LobeHub, etc.)
            title_match = re.search(r'<meta property="og:title" content="(.*?)"', raw_content)
            desc_match = re.search(r'<meta (?:property="og:description"|name="description") content="(.*?)"', raw_content)

            name = ""
            desc = ""
            if title_match:
                name = html_lib.unescape(title_match.group(1)).split("|")[0].strip().lower().replace(" ", "-")
            if desc_match:
                desc = html_lib.unescape(desc_match.group(1))

            if not name:
                # Extract from URL path
                path_parts = url.rstrip("/").split("/")
                name = path_parts[-1].replace("_", "-").lower()

            # Build a proper SKILL.md from extracted metadata
            content = f"""---
name: {name}
description: >
  {desc[:300]}
source: {url}
---

# {name}

{desc}

## Source

Imported from: {url}
"""
        else:
            # Raw markdown content (GitHub SKILL.md)
            content = raw_content

            # Parse name from YAML frontmatter
            name = ""
            desc = ""
            if "---" in content:
                parts = content.split("---")
                if len(parts) >= 3:
                    name_match = re.search(r"name:\s*(.+)", parts[1])
                    desc_match = re.search(r"description:\s*(.+)", parts[1])
                    if name_match:
                        name = name_match.group(1).strip().strip('"').strip("'")
                    if desc_match:
                        desc = desc_match.group(1).strip().strip('"').strip("'")[:200]

            if not name:
                path_parts = url.rstrip("/").split("/")
                name = path_parts[-1].replace(".md", "").replace("_", "-").lower()

        # Sanitize content: remove null bytes and control characters
        content = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', content)

        # Ensure content fits Registry limit (64KB)
        if len(content.encode('utf-8')) > 60000:
            content = content[:50000] + f"\n\n[Truncated. Full content at: {url}]"

        if not desc:
            lines = [l.strip() for l in content.split("\n") if l.strip() and not l.startswith(("#", "---", "```"))]
            desc = (lines[0] if lines else f"Imported from {url}")[:200]

        # 写入 EFS .claude/skills —— agent 自动读取的位置 (无需 Registry)
        from agents.skill_store import write_skill
        info = write_skill(name, content, desc)

        # Registry 发布为可选增强 (配置了才做, 失败不影响导入)
        registry_status = _publish_to_registry_optional(info["name"], content, desc)

        return {
            "name": info["name"], "status": "INSTALLED",
            "path": info["path"], "content_length": info["bytes"],
            "registry": registry_status,
            "message": f"Skill '{info['name']}' 已导入, agent 下次调用即可自动使用",
        }
    except Exception as e:
        return {"error": f"导入失败: {str(e)[:200]}"}


# ═══════════════════════════════════════════════════════
# Import from uploaded file (zip or md)
# ═══════════════════════════════════════════════════════

from fastapi import UploadFile, File


@router.post("/import-file")
async def import_from_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """从上传文件导入Skill到Registry (支持 .zip, .md, .txt)"""
    import re, zipfile, io

    filename = file.filename or "unknown"
    file_bytes = await file.read()

    content = ""
    name = ""
    desc = ""

    if filename.endswith(".zip"):
        # Extract all relevant files from zip and combine into skill content
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                all_files = zf.namelist()
                # Categorize files
                md_files = [f for f in all_files if f.lower().endswith(".md") and not f.startswith("__")]
                code_files = [f for f in all_files if f.lower().endswith((".py", ".js", ".ts")) and not f.startswith("__")]
                config_files = [f for f in all_files if f.lower().endswith((".json", ".yaml", ".yml", ".toml")) and not f.startswith("__")]
                example_files = [f for f in all_files if "example" in f.lower() or "sample" in f.lower() or "demo" in f.lower()]
                txt_files = [f for f in all_files if f.lower().endswith(".txt") and not f.startswith("__")]

                # Find primary SKILL.md
                skill_md = next((f for f in md_files if "skill" in f.lower()), None)
                readme_md = next((f for f in md_files if "readme" in f.lower()), None)
                primary_md = skill_md or readme_md or (md_files[0] if md_files else None)

                parts = []

                # 1. Primary markdown (SKILL.md or README.md)
                if primary_md:
                    parts.append(zf.read(primary_md).decode("utf-8", errors="ignore"))

                # 2. Other markdown files
                for f in md_files:
                    if f != primary_md:
                        file_content = zf.read(f).decode("utf-8", errors="ignore")
                        parts.append(f"\n\n---\n## {f}\n\n{file_content}")

                # 3. Code examples (py, js, ts)
                if code_files:
                    parts.append("\n\n---\n## Code Examples\n")
                    for f in code_files[:5]:  # Max 5 code files
                        file_content = zf.read(f).decode("utf-8", errors="ignore")
                        ext = f.rsplit(".", 1)[-1]
                        parts.append(f"\n### {f}\n```{ext}\n{file_content[:20000]}\n```\n")

                # 4. Config files
                if config_files:
                    parts.append("\n\n---\n## Configuration\n")
                    for f in config_files[:3]:
                        file_content = zf.read(f).decode("utf-8", errors="ignore")
                        ext = f.rsplit(".", 1)[-1]
                        parts.append(f"\n### {f}\n```{ext}\n{file_content[:20000]}\n```\n")

                # 5. Example/sample files not already included
                for f in example_files:
                    if f not in md_files and f not in code_files and f not in config_files:
                        try:
                            file_content = zf.read(f).decode("utf-8", errors="ignore")
                            parts.append(f"\n### {f}\n```\n{file_content[:20000]}\n```\n")
                        except Exception:
                            pass

                # 6. If no md found, create from file listing
                if not primary_md:
                    file_list = "\n".join(f"- {f}" for f in all_files[:30])
                    parts.insert(0, f"---\nname: {filename.replace('.zip', '')}\n---\n\n# {filename}\n\nFiles:\n{file_list}\n")

                content = "\n".join(parts)
        except zipfile.BadZipFile:
            return {"error": "无效的ZIP文件"}

    elif filename.endswith((".md", ".txt")):
        content = file_bytes.decode("utf-8", errors="ignore")

    else:
        return {"error": f"不支持的文件格式: {filename}。支持 .zip, .md, .txt"}

    if not content.strip():
        return {"error": "文件内容为空"}

    # Parse name and description from content
    if "---" in content:
        parts = content.split("---")
        if len(parts) >= 3:
            name_match = re.search(r"name:\s*(.+)", parts[1])
            desc_match = re.search(r"description:\s*(.+)", parts[1])
            if name_match:
                name = name_match.group(1).strip().strip('"').strip("'")
            if desc_match:
                desc = desc_match.group(1).strip().strip('"').strip("'")[:200]

    if not name:
        name = filename.rsplit(".", 1)[0].replace("_", "-").replace(" ", "-").lower()

    if not desc:
        lines = [l.strip() for l in content.split("\n") if l.strip() and not l.startswith(("#", "---", "```"))]
        desc = (lines[0] if lines else filename)[:200]

    # Sanitize content
    content = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', content)
    if len(content.encode('utf-8')) > 60000:
        content = content[:50000] + f"\n\n[Truncated from {filename}]"

    # 写入 EFS .claude/skills —— agent 自动读取 (无需 Registry)
    try:
        from agents.skill_store import write_skill
        info = write_skill(name, content, desc)
        registry_status = _publish_to_registry_optional(info["name"], content, desc)
        return {
            "name": info["name"], "status": "INSTALLED",
            "path": info["path"], "filename": filename, "content_length": info["bytes"],
            "registry": registry_status,
            "message": f"Skill '{info['name']}' 已导入, agent 下次调用即可自动使用",
        }
    except Exception as e:
        return {"error": f"导入失败: {str(e)[:200]}"}


# ═══════════════════════════════════════════════════════
# Update all builtin skills in Registry
# ═══════════════════════════════════════════════════════

@router.post("/update-registry")
async def update_all_registry_records(current_user: User = Depends(get_current_user)):
    """读取所有SKILL.md并更新Registry记录"""
    if not REGISTRY_ID:
        return {"error": "Registry未配置"}

    base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "agents", "skills")
    ctrl = _get_ctrl_client()
    results = []

    for reg_name in BUILTIN_SKILLS:
        skill_md_path = os.path.join(base_dir, reg_name, "SKILL.md")
        if not os.path.exists(skill_md_path):
            results.append({"name": reg_name, "status": "SKIP", "reason": "No SKILL.md"})
            continue

        with open(skill_md_path) as f:
            md_content = f.read()

        desc = BUILTIN_SKILLS[reg_name].get("name", reg_name)[:200]

        try:
            # Find existing record
            dp = _get_dp_client()
            arn = f"arn:aws:bedrock-agentcore:{AWS_REGION}:632930644527:registry/{REGISTRY_ID}"
            search = dp.search_registry_records(registryIds=[arn], searchQuery=reg_name, maxResults=5)
            existing = None
            for rec in search.get("registryRecords", []):
                if rec.get("name") == reg_name:
                    existing = rec
                    break

            if existing and existing.get("recordId"):
                # Update existing
                try:
                    ctrl.update_registry_record(
                        registryId=REGISTRY_ID, recordId=existing["recordId"],
                        descriptors={"agentSkills": {"skillMd": {"inlineContent": md_content}}},
                        recordVersion="5.0.0", description=desc,
                    )
                    results.append({"name": reg_name, "status": "UPDATED", "record_id": existing["recordId"]})
                except Exception:
                    # If update fails, create new
                    r = ctrl.create_registry_record(
                        registryId=REGISTRY_ID, name=reg_name, descriptorType="AGENT_SKILLS",
                        descriptors={"agentSkills": {"skillMd": {"inlineContent": md_content}}},
                        recordVersion="5.0.0", description=desc,
                    )
                    rid = r["recordArn"].split("/")[-1]
                    time.sleep(1)
                    try:
                        ctrl.submit_registry_record_for_approval(registryId=REGISTRY_ID, recordId=rid)
                    except Exception:
                        pass
                    results.append({"name": reg_name, "status": "CREATED", "record_id": rid})
            else:
                # Create new
                r = ctrl.create_registry_record(
                    registryId=REGISTRY_ID, name=reg_name, descriptorType="AGENT_SKILLS",
                    descriptors={"agentSkills": {"skillMd": {"inlineContent": md_content}}},
                    recordVersion="5.0.0", description=desc,
                )
                rid = r["recordArn"].split("/")[-1]
                time.sleep(1)
                try:
                    ctrl.submit_registry_record_for_approval(registryId=REGISTRY_ID, recordId=rid)
                except Exception:
                    pass
                results.append({"name": reg_name, "status": "CREATED", "record_id": rid})
        except Exception as e:
            results.append({"name": reg_name, "status": "ERROR", "error": str(e)[:150]})

    return {"results": results, "total": len(results)}


# ═══════════════════════════════════════════════════════
# AI自然语言创建Skill
# ═══════════════════════════════════════════════════════

class AICreateSkillRequest(BaseModel):
    description: str
    skill_type: str = "analysis"
    install: bool = True  # 生成后直接写入 EFS .claude/skills 供 agent 使用


@router.post("/ai-create")
async def ai_create_skill(request: AICreateSkillRequest, current_user: User = Depends(get_current_user)):
    """用自然语言描述创建Skill, LLM生成SKILL.md"""
    try:
        import boto3
        client = boto3.client("bedrock-runtime", region_name=AWS_REGION)

        prompt = f"""根据用户描述生成一个Agent Skill的SKILL.md文件。

格式要求(agentskills.io规范):
---
name: skill-name-lowercase
description: >
  详细描述skill功能和使用场景
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: {request.skill_type}
allowed-tools: tool1 tool2
---

# Skill Name

## Tools
### tool1(param1, param2)
描述

## Examples
- 示例用法

用户描述: {request.description}

只输出SKILL.md内容:"""

        body = _json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}],
        })
        resp = client.invoke_model(modelId=_settings.LLM_MODEL_ID, body=body)
        content = _json.loads(resp["body"].read()).get("content", [{}])[0].get("text", "")

        # Extract name from generated content
        import re
        name_match = re.search(r"name:\s*(.+)", content)
        name = (name_match.group(1).strip().strip('"').strip("'") if name_match else "custom-skill")
        desc_match = re.search(r"description:\s*(.+)", content)
        desc = desc_match.group(1).strip() if desc_match else request.description[:200]

        result = {"name": name, "content": content, "skill_type": request.skill_type}
        if request.install:
            from agents.skill_store import write_skill
            info = write_skill(name, content, desc)
            result.update({
                "name": info["name"], "status": "INSTALLED", "path": info["path"],
                "registry": _publish_to_registry_optional(info["name"], content, desc),
                "message": f"Skill '{info['name']}' 已生成并安装, agent 下次调用即可自动使用",
            })
        return result
    except Exception as e:
        return {"error": f"AI生成失败: {str(e)[:200]}"}


# ═══════════════════════════════════════════════════════
# Builtin skill source code
# ═══════════════════════════════════════════════════════

@router.get("/code/{skill_name}")
async def get_skill_source(skill_name: str, current_user: User = Depends(get_current_user)):
    """获取builtin skill的Python源码和SKILL.md"""
    builtin = BUILTIN_SKILLS.get(skill_name)
    if not builtin:
        return {"error": "Skill not found"}

    base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    code = ""
    if builtin.get("file"):
        try:
            with open(os.path.join(base, builtin["file"])) as f:
                code = f.read()
        except Exception:
            pass

    skill_md = ""
    md_path = os.path.join(base, "agents", "skills", skill_name, "SKILL.md")
    try:
        with open(md_path) as f:
            skill_md = f.read()
    except Exception:
        pass

    return {"name": skill_name, "display_name": builtin["name"], "code": code, "skill_md": skill_md}


# ═══════════════════════════════════════════════════════
# Legacy endpoints (backward compatibility)
# ═══════════════════════════════════════════════════════

@router.get("/builtin")
async def get_builtin_skills(current_user: User = Depends(get_current_user)):
    """获取内置Skills列表"""
    skills = []
    for reg_name, info in BUILTIN_SKILLS.items():
        skills.append({
            "id": f"builtin-{reg_name.replace('-skill', '')}",
            "name": info["name"],
            "registry_name": reg_name,
            "skill_type": info["type"],
            "description": info["name"],
            "tools": [],
            "source": "builtin",
            "version": "5.0.0",
            "registry_status": "",
        })
    return {"skills": skills}


@router.get("/all")
async def get_all_skills(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """获取所有Skills"""
    builtin = []
    for reg_name, info in BUILTIN_SKILLS.items():
        builtin.append({
            "id": f"builtin-{reg_name.replace('-skill', '')}",
            "name": info["name"],
            "registry_name": reg_name,
            "skill_type": info["type"],
            "description": info["name"],
            "tools": [],
            "source": "builtin",
            "version": "5.0.0",
        })

    result = await db.execute(select(CustomSkill).where(CustomSkill.user_id == current_user.id))
    custom = [{"id": str(s.id), "name": s.name, "skill_type": s.skill_type, "description": s.description,
               "tools": [], "source": "custom", "version": s.version, "code": s.code} for s in result.scalars().all()]

    return {"builtin": builtin, "custom": custom, "total": len(builtin) + len(custom)}


# Legacy CRUD for custom skills (DB-based)
@router.post("/", response_model=CustomSkillResponse)
async def create_skill(skill: CustomSkillCreate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    new_skill = CustomSkill(user_id=current_user.id, name=skill.name, description=skill.description,
                            skill_type=skill.skill_type, code=skill.code, parameters_schema=skill.parameters_schema)
    db.add(new_skill)
    await db.commit()
    await db.refresh(new_skill)
    return CustomSkillResponse(id=str(new_skill.id), name=new_skill.name, description=new_skill.description,
                               skill_type=new_skill.skill_type, code=new_skill.code, is_published=new_skill.is_published, version=new_skill.version)


@router.delete("/{skill_id}")
async def delete_skill(skill_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CustomSkill).where(CustomSkill.id == skill_id, CustomSkill.user_id == current_user.id))
    existing = result.scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=404, detail="Skill不存在")
    await db.delete(existing)
    await db.commit()
    return {"message": "Skill已删除"}


# MCP placeholder
@router.get("/mcp")
async def get_mcp_servers(current_user: User = Depends(get_current_user)):
    return {"servers": []}
