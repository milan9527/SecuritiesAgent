"""
Skill 导入器 - 从 URL 抓取并按 Agent Skill 格式落盘

能力:
- GitHub 仓库/目录/文件 URL → 用 GitHub API 列出整个 skill 目录, 抓取 SKILL.md +
  scripts/ + references/ 等附带文件, 完整写入 EFS
- 任意网页 URL → 提取正文, 用 LLM 生成规范 SKILL.md
- 自动生成合适的 skill 名 (slug) 和 description
- 源缺少 SKILL.md 时, 用 LLM 按规范合成

写入位置由 agents.skill_store 决定 (EFS .claude/skills), agent 自动读取。
"""
from __future__ import annotations

import os
import re
import json
import base64
import httpx

from agents.skill_store import sanitize_name, write_skill_bundle

_UA = {"User-Agent": "SecuritiesTradingSkillImporter/1.0"}
# 附带文件: 抓取这些目录/扩展, 跳过大文件和二进制
_ALLOWED_EXT = {".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".toml",
                ".txt", ".sh", ".sql", ".csv"}
_MAX_FILE = 200_000   # 单文件最大 200KB
_MAX_FILES = 40       # 最多抓 40 个文件


# ─────────────────────────── GitHub ───────────────────────────
def _parse_github(url: str) -> dict | None:
    """解析 GitHub URL → {owner, repo, ref, path}。非 GitHub 返回 None。"""
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)(?:/(?:tree|blob)/([^/]+)/(.*))?/?$", url.strip())
    if not m:
        return None
    owner, repo, ref, path = m.group(1), m.group(2), m.group(3), m.group(4)
    return {"owner": owner, "repo": repo.replace(".git", ""),
            "ref": ref or "HEAD", "path": (path or "").rstrip("/")}


def _gh_headers() -> dict:
    h = dict(_UA)
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _fetch_github_skill(gh: dict) -> dict:
    """用 GitHub Contents API 抓取一个 skill 目录的所有文件。
    返回 {name, skill_md, files:{rel:bytes}, description}。
    """
    owner, repo, ref, path = gh["owner"], gh["repo"], gh["ref"], gh["path"]
    base = f"https://api.github.com/repos/{owner}/{repo}/contents"

    files: dict[str, bytes] = {}

    def walk(rel_path: str, prefix: str):
        if len(files) >= _MAX_FILES:
            return
        api = f"{base}/{rel_path}".rstrip("/") + f"?ref={ref}"
        r = httpx.get(api, headers=_gh_headers(), timeout=25, follow_redirects=True)
        r.raise_for_status()
        items = r.json()
        if isinstance(items, dict):  # 单文件
            items = [items]
        for it in items:
            if len(files) >= _MAX_FILES:
                break
            if it.get("type") == "dir":
                # 只递归常见 skill 子目录
                if it["name"] in ("scripts", "references", "assets", "examples", "templates", "data"):
                    walk(it["path"], f"{prefix}{it['name']}/")
                continue
            ext = os.path.splitext(it["name"])[1].lower()
            if ext and ext not in _ALLOWED_EXT:
                continue
            if (it.get("size") or 0) > _MAX_FILE:
                continue
            # 取文件内容
            data = None
            if it.get("download_url"):
                fr = httpx.get(it["download_url"], headers=_UA, timeout=25, follow_redirects=True)
                if fr.status_code == 200:
                    data = fr.content
            if data is None and it.get("content") and it.get("encoding") == "base64":
                data = base64.b64decode(it["content"])
            if data is not None:
                files[f"{prefix}{it['name']}"] = data

    # 如果 path 直接指向某个文件
    if path and os.path.splitext(path)[1]:
        walk(path, "")
        # 把该文件视为主内容
        only = next(iter(files.values()), b"")
        return _assemble(gh, files, raw_main=only.decode("utf-8", "ignore"))

    # 目录 (或仓库根) → 整目录抓取
    walk(path, "")
    return _assemble(gh, files)


def _assemble(gh: dict, files: dict[str, bytes], raw_main: str = "") -> dict:
    """从抓到的文件里挑出 SKILL.md/README, 组装结果。"""
    # 找主 markdown
    skill_md = ""
    main_key = None
    for k in list(files.keys()):
        if k.lower() == "skill.md":
            main_key = k
            break
    if not main_key:
        for k in files:
            if k.lower() in ("readme.md", "readme.markdown"):
                main_key = k
                break
    if main_key:
        skill_md = files[main_key].decode("utf-8", "ignore")
    elif raw_main:
        skill_md = raw_main

    # 名称: 优先 frontmatter name, 否则用目录/仓库名
    name, desc = _parse_frontmatter(skill_md)
    if not name:
        name = gh["path"].rstrip("/").split("/")[-1] or gh["repo"]
    return {"name": sanitize_name(name), "skill_md": skill_md, "files": files,
            "description": desc, "source_main_key": main_key}


def _parse_frontmatter(md: str) -> tuple[str, str]:
    name = desc = ""
    s = (md or "").lstrip()
    if s.startswith("---"):
        end = s.find("---", 3)
        if end != -1:
            fm = s[3:end]
            n = re.search(r"^\s*name:\s*(.+)$", fm, re.M)
            d = re.search(r"^\s*description:\s*(.+)$", fm, re.M)
            if n:
                name = n.group(1).strip().strip('"').strip("'")
            if d:
                desc = d.group(1).strip().strip('"').strip("'")
    return name, desc[:300]


# ─────────────────────────── 网页 → LLM 合成 ───────────────────────────
def _fetch_page_text(url: str) -> str:
    r = httpx.get(url, headers=_UA, timeout=25, follow_redirects=True)
    r.raise_for_status()
    text = r.text
    for tag in ("script", "style", "nav", "footer", "header", "aside"):
        text = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", " ", text, flags=re.DOTALL | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:12000]


def _llm_make_skill_md(name_hint: str, source_url: str, material: str, region: str, model_id: str) -> tuple[str, str]:
    """用 Bedrock 把素材整理成规范 SKILL.md。返回 (skill_md, description)。"""
    import boto3
    client = boto3.client("bedrock-runtime", region_name=region)
    prompt = f"""你是 Agent Skill 编写专家。根据下面的素材, 生成一个规范的 SKILL.md 文件。

严格要求:
1. 必须以 YAML frontmatter 开头, 含 name (小写连字符) 和 description (一句话说明何时使用该 skill)
2. 正文用 Markdown, 包含: 功能说明、使用场景、操作步骤/工作流; 若素材含工具/API/代码, 用代码块给出用法
3. description 要写清"什么情况下 agent 应该用这个 skill", 便于自动触发
4. 只输出 SKILL.md 内容本身, 不要额外解释

建议名称: {name_hint}
来源: {source_url}

素材:
{material[:9000]}

SKILL.md:"""
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 3000,
        "messages": [{"role": "user", "content": prompt}],
    })
    resp = client.invoke_model(modelId=model_id, body=body)
    content = json.loads(resp["body"].read()).get("content", [{}])[0].get("text", "")
    _, desc = _parse_frontmatter(content)
    return content, desc


# ─────────────────────────── 对外主入口 ───────────────────────────
def import_from_url(url: str, region: str, model_id: str) -> dict:
    """从 URL 导入 skill, 完整写入 EFS。返回 {name, path, files, source, ...}。"""
    gh = _parse_github(url)

    if gh:
        result = _fetch_github_skill(gh)
        name = result["name"]
        skill_md = result["skill_md"]
        files = dict(result["files"])
        desc = result["description"]

        # GitHub 抓到了文件但没有 SKILL.md (只有 README/代码) → 用 LLM 合成规范 SKILL.md
        has_skill_md = any(k.lower() == "skill.md" for k in files)
        if not has_skill_md:
            material = skill_md or ""
            # 附上代码/配置文件名作为素材线索
            file_list = "\n".join(f"- {k} ({len(v)}B)" for k, v in list(files.items())[:20])
            material = f"{material}\n\n[仓库文件清单]\n{file_list}"
            skill_md, gen_desc = _llm_make_skill_md(name, url, material, region, model_id)
            desc = desc or gen_desc
        # 不要把原始 README.md 当附件重复 (SKILL.md 已含)
        files = {k: v for k, v in files.items()
                 if k.lower() not in ("skill.md", "readme.md", "readme.markdown")}

        info = write_skill_bundle(name, skill_md, files, desc)
        info["source"] = "github"
        info["script_count"] = len([f for f in info["files"] if f != "SKILL.md"])
        return info

    # 非 GitHub: 抓正文 → LLM 合成 SKILL.md
    text = _fetch_page_text(url)
    name_hint = sanitize_name(url.rstrip("/").split("/")[-1] or "imported-skill")
    skill_md, desc = _llm_make_skill_md(name_hint, url, text, region, model_id)
    name, fm_desc = _parse_frontmatter(skill_md)
    info = write_skill_bundle(name or name_hint, skill_md, {}, desc or fm_desc)
    info["source"] = "web"
    info["script_count"] = 0
    return info
