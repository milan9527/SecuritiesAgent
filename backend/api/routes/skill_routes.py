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


# ═══════════════════════════════════════════════════════
# Builtin skill 名称映射 (展示用)
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
# Skill 记录 API —— 全部基于 EFS .claude/skills (agent 实际读取处), 不再用 Registry
# 路由路径保持 /registry* 不变, 避免前端改动
# ═══════════════════════════════════════════════════════

def _efs_records() -> list[dict]:
    """把 EFS .claude/skills 下的 skill 表示成记录形状, 供前端列表展示。"""
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
    """列出所有 skill (来自 EFS .claude/skills)。"""
    return {"records": _efs_records(), "source": "efs"}


@router.get("/registry/{record_id}")
async def get_registry_record(record_id: str, current_user: User = Depends(get_current_user)):
    """获取单个 skill 详情 + 完整 SKILL.md 内容 (来自 EFS)。"""
    from agents.skill_store import read_skill
    s = read_skill(record_id)
    if not s:
        return {"error": "Skill 不存在"}
    return {
        "record_id": s["name"], "name": s["name"], "status": "INSTALLED",
        "version": "1.0.0", "description": s["description"], "type": "AGENT_SKILLS",
        "is_builtin": s["builtin"], "content": s["content"], "source": "efs",
    }


class CreateRecordRequest(BaseModel):
    name: str
    description: str = ""
    content: str = ""  # SKILL.md content
    version: str = "1.0.0"


@router.post("/registry")
async def create_registry_record(request: CreateRecordRequest, current_user: User = Depends(get_current_user)):
    """创建/发布一个 Skill —— 写入 EFS .claude/skills, agent 自动读取。"""
    if not request.name:
        return {"error": "请输入名称"}
    try:
        from agents.skill_store import write_skill
        content = request.content or f"# {request.name}\n\n{request.description}\n"
        info = write_skill(request.name, content, request.description)
        return {
            "record_id": info["name"], "name": info["name"], "status": "INSTALLED",
            "path": info["path"],
            "message": f"Skill '{info['name']}' 已发布, agent 下次调用即可自动使用",
        }
    except Exception as e:
        return {"error": str(e)[:200]}


@router.put("/registry/{record_id}/status")
async def update_record_status(record_id: str, status: str = "APPROVED", current_user: User = Depends(get_current_user)):
    """EFS skill 安装即生效, 无审批流程, 直接返回成功。"""
    return {"success": True, "record_id": record_id, "status": status}


@router.delete("/registry/{record_id}")
async def delete_registry_record(record_id: str, current_user: User = Depends(get_current_user)):
    """删除 Skill —— 从 EFS .claude/skills 移除 (内置 skill 不可删)。"""
    from agents.skill_store import delete_skill
    removed = delete_skill(record_id)
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
    """从 URL 导入 Skill: 自动取名 + 分析内容 + 按 Skill 格式落盘 (SKILL.md + scripts 等)。

    - GitHub 仓库/目录/文件: 抓取整个 skill 目录 (SKILL.md + scripts/ + references/ 等)
    - 普通网页: 提取正文, 用 LLM 生成规范 SKILL.md
    全部写入 EFS .claude/skills, agent 自动读取。
    """
    import asyncio
    try:
        from agents.skill_importer import import_from_url
        info = await asyncio.to_thread(
            import_from_url, request.url, AWS_REGION, _settings.LLM_MODEL_ID
        )
        return {
            "name": info["name"], "status": "INSTALLED",
            "path": info["path"], "files": info["files"],
            "script_count": info.get("script_count", 0),
            "source": info.get("source", ""),
            "content_length": info.get("bytes", 0),
            "message": (f"Skill '{info['name']}' 已导入 "
                        f"({len(info['files'])} 个文件, 含 {info.get('script_count', 0)} 个脚本/资源), "
                        f"agent 下次调用即可自动使用"),
        }
    except Exception as e:
        return {"error": f"导入失败: {str(e)[:200]}"}


# 旧版纯 markdown 导入逻辑保留 (未使用), 以备回退
async def _legacy_import_from_github(request: ImportGithubRequest, current_user: User):
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
        return {
            "name": info["name"], "status": "INSTALLED",
            "path": info["path"], "content_length": info["bytes"],
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
    """上传文件导入 Skill。.zip 保留完整目录结构 (SKILL.md + scripts/ 等), .md/.txt 单文件。"""
    import re, zipfile, io, os as _os
    from agents.skill_store import write_skill, write_skill_bundle, sanitize_name

    filename = file.filename or "unknown"
    file_bytes = await file.read()

    def _parse_fm(md: str):
        n = d = ""
        if md.lstrip().startswith("---"):
            body = md.lstrip()[3:]
            end = body.find("---")
            if end != -1:
                fm = body[:end]
                nm = re.search(r"^\s*name:\s*(.+)$", fm, re.M)
                dm = re.search(r"^\s*description:\s*(.+)$", fm, re.M)
                if nm: n = nm.group(1).strip().strip('"').strip("'")
                if dm: d = dm.group(1).strip().strip('"').strip("'")[:300]
        return n, d

    try:
        if filename.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                names = [n for n in zf.namelist() if not n.endswith("/") and "__MACOSX" not in n]
                if not names:
                    return {"error": "ZIP 为空"}
                # 去掉公共顶层目录前缀 (如 my-skill/SKILL.md -> SKILL.md)
                top = ""
                firsts = {n.split("/")[0] for n in names if "/" in n}
                if len(firsts) == 1 and all("/" in n for n in names):
                    top = firsts.pop() + "/"

                files: dict[str, bytes] = {}
                skill_md = ""
                ALLOWED = {".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml",
                           ".toml", ".txt", ".sh", ".sql", ".csv"}
                for n in names:
                    rel = n[len(top):] if top and n.startswith(top) else n
                    if not rel or rel.startswith("."):
                        continue
                    ext = _os.path.splitext(rel)[1].lower()
                    if ext and ext not in ALLOWED:
                        continue
                    data = zf.read(n)
                    if len(data) > 200_000:
                        continue
                    if rel.lower() == "skill.md":
                        skill_md = data.decode("utf-8", "ignore")
                    else:
                        files[rel] = data

                # 无 SKILL.md → 用 README 或合成
                if not skill_md:
                    readme = next((k for k in files if k.lower() in ("readme.md", "readme.markdown")), None)
                    if readme:
                        skill_md = files.pop(readme).decode("utf-8", "ignore")
                    else:
                        listing = "\n".join(f"- {k}" for k in list(files)[:30])
                        skill_md = f"# {sanitize_name(filename[:-4])}\n\n打包导入的 skill。\n\n## 文件\n{listing}\n"

                name, desc = _parse_fm(skill_md)
                name = name or filename[:-4]
                info = write_skill_bundle(name, skill_md, files, desc)
                return {
                    "name": info["name"], "status": "INSTALLED", "path": info["path"],
                    "filename": filename, "files": info["files"],
                    "script_count": len([f for f in info["files"] if f != "SKILL.md"]),
                    "content_length": info["bytes"],
                    "message": f"Skill '{info['name']}' 已导入 ({len(info['files'])} 个文件), agent 下次调用即可自动使用",
                }

        elif filename.endswith((".md", ".txt")):
            content = file_bytes.decode("utf-8", "ignore")
            if not content.strip():
                return {"error": "文件内容为空"}
            name, desc = _parse_fm(content)
            name = name or filename.rsplit(".", 1)[0]
            info = write_skill(name, content, desc)
            return {
                "name": info["name"], "status": "INSTALLED", "path": info["path"],
                "filename": filename, "content_length": info["bytes"],
                "message": f"Skill '{info['name']}' 已导入, agent 下次调用即可自动使用",
            }
        else:
            return {"error": f"不支持的文件格式: {filename}。支持 .zip, .md, .txt"}
    except zipfile.BadZipFile:
        return {"error": "无效的ZIP文件"}
    except Exception as e:
        return {"error": f"导入失败: {str(e)[:200]}"}


# ═══════════════════════════════════════════════════════
# 重新同步内置 skill 到 EFS (从镜像内置副本)
# ═══════════════════════════════════════════════════════

@router.post("/update-registry")
async def resync_builtin_skills(current_user: User = Depends(get_current_user)):
    """把镜像内置的 4 个 skill 重新同步到 EFS .claude/skills (缺失才补)。"""
    from agents.orchestrator_agent import seed_skills_to
    from agents.skill_store import skills_root, list_skills
    seed_skills_to(skills_root())
    return {"results": list_skills(), "source": "efs"}


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
