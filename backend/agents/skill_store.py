"""
Skill 文件存储 - Skill Store (EFS / 本地 .claude/skills)

Agent 通过 Claude Agent SDK 的 setting_sources=["project"] + cwd 从
`<root>/.claude/skills/<name>/SKILL.md` 自动读取 skill。

本模块把"导入/AI生成的 skill"直接落到该目录:
- Runtime/ECS 上 root = AGENTCORE_SKILLS_ROOT (EFS 挂载点, 如 /mnt/skills), 跨会话共享
- 本地开发 root = backend 目录 (镜像内置)

写到这里的 skill, agent 下次调用即自动可见, 无需 Registry, 无需重建镜像。
"""
from __future__ import annotations

import os
import re
import shutil

# backend 目录 (镜像内置 .claude/skills 所在)
_BAKED_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def skills_root() -> str:
    """skill 根目录 (含 .claude/skills 子目录)。优先 EFS。"""
    return os.environ.get("AGENTCORE_SKILLS_ROOT", "").strip() or _BAKED_ROOT


def skills_dir() -> str:
    """`.claude/skills` 绝对路径, 不存在则创建。"""
    d = os.path.join(skills_root(), ".claude", "skills")
    os.makedirs(d, exist_ok=True)
    return d


def sanitize_name(name: str) -> str:
    """规范化 skill 目录名: 小写, 仅留 [a-z0-9-]。"""
    n = (name or "").strip().lower().replace(" ", "-").replace("_", "-")
    n = re.sub(r"[^a-z0-9-]", "", n)
    n = re.sub(r"-+", "-", n).strip("-")
    return n or "imported-skill"


def _ensure_frontmatter(content: str, name: str, description: str) -> str:
    """确保 SKILL.md 含 YAML frontmatter (name/description), 否则补上。
    SDK 靠 frontmatter 的 description 做渐进式披露 (决定何时加载该 skill)。
    """
    stripped = content.lstrip()
    if stripped.startswith("---"):
        # 已有 frontmatter — 检查 name/description 是否齐全
        end = stripped.find("---", 3)
        if end != -1:
            fm = stripped[3:end]
            has_name = re.search(r"^\s*name:\s*\S", fm, re.M)
            has_desc = re.search(r"^\s*description:\s*\S", fm, re.M)
            if has_name and has_desc:
                return content
            # 补缺失字段
            inject = ""
            if not has_name:
                inject += f"name: {name}\n"
            if not has_desc:
                inject += f"description: {description[:300]}\n"
            return stripped[:3] + "\n" + inject + stripped[3:]
    # 无 frontmatter — 生成
    desc = (description or f"Imported skill {name}").replace("\n", " ")[:300]
    return f"---\nname: {name}\ndescription: {desc}\n---\n\n{content}"


def write_skill(name: str, content: str, description: str = "") -> dict:
    """把 SKILL.md 写入 `.claude/skills/<name>/SKILL.md`。返回元信息。"""
    safe = sanitize_name(name)
    content = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", content or "")
    content = _ensure_frontmatter(content, safe, description)
    target_dir = os.path.join(skills_dir(), safe)
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, "SKILL.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return {"name": safe, "path": path, "bytes": len(content.encode("utf-8")), "root": skills_root()}


def list_skills() -> list[dict]:
    """列出 `.claude/skills` 下所有 skill (name + description + 是否内置)。"""
    d = skills_dir()
    out: list[dict] = []
    builtin = {"investment-analysis", "stock-trading", "quant-trading", "market-data"}
    for name in sorted(os.listdir(d)):
        md = os.path.join(d, name, "SKILL.md")
        if not os.path.isfile(md):
            continue
        desc = ""
        try:
            with open(md, encoding="utf-8") as f:
                head = f.read(2000)
            m = re.search(r"^\s*description:\s*(.+)$", head, re.M)
            if m:
                desc = m.group(1).strip().strip('"').strip("'")
        except Exception:
            pass
        out.append({"name": name, "description": desc[:200], "builtin": name in builtin})
    return out


def delete_skill(name: str) -> bool:
    """删除一个 skill 目录 (内置 skill 不允许删)。"""
    safe = sanitize_name(name)
    if safe in {"investment-analysis", "stock-trading", "quant-trading", "market-data"}:
        return False
    target = os.path.join(skills_dir(), safe)
    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)
        return True
    return False
