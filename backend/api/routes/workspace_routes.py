"""
Agent 工作区路由 - 浏览/下载 Agent 产出物 (持久化在 EFS)。

Agent (orchestrator/子Agent) 生成的代码、文档、数据、报告等持久化到 EFS:
  <AGENTCORE_SKILLS_ROOT>/workspace/<user_id>/...
本路由让用户列出和下载自己工作区里的文件 (按 user_id 隔离, 不能跨用户访问)。
"""
from __future__ import annotations

import os
from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse, FileResponse, JSONResponse

from db.models import User
from api.auth import get_current_user

router = APIRouter(prefix="/api/workspace", tags=["Agent工作区"])

_TEXT_EXTS = {".py", ".md", ".txt", ".json", ".csv", ".yaml", ".yml", ".html", ".js",
              ".ts", ".sh", ".ipynb", ".log", ".sql", ".toml", ".ini", ".tsv"}
_MAX_TEXT_BYTES = 2 * 1024 * 1024  # 2MB 文本预览上限

# 工作区一级类型目录 (与 orchestrator 系统提示一致)
_TYPE_DIRS = ["code", "documents", "data", "skills"]
# 类型 → 中文名 (前端分组用)
WORKSPACE_CATEGORIES = {
    "code": "代码/脚本",
    "documents": "文档/报告",
    "data": "数据文件",
    "skills": "Skill",
    "general": "其他",
}
# 按扩展名兜底归类 (文件不在类型目录下时)
_CODE_EXTS = {".py", ".js", ".ts", ".sh", ".sql", ".ipynb", ".java", ".go", ".rs", ".c", ".cpp", ".rb"}
_DATA_EXTS = {".csv", ".json", ".tsv", ".xlsx", ".parquet", ".xml", ".yaml", ".yml"}
_DOC_EXTS = {".md", ".txt", ".html", ".pdf", ".doc", ".docx"}


def _categorize(rel_path: str, ext: str) -> str:
    """按一级目录归类, 否则按扩展名兜底。"""
    top = rel_path.replace("\\", "/").split("/", 1)[0].lower()
    if top in _TYPE_DIRS:
        return top
    if ext in _CODE_EXTS:
        return "code"
    if ext in _DATA_EXTS:
        return "data"
    if ext in _DOC_EXTS:
        return "documents"
    # 含 SKILL.md 的目录视为 skill
    if rel_path.upper().endswith("SKILL.MD"):
        return "skills"
    return "general"


def _safe_actor(actor_id: str) -> str:
    a = "".join(c if (c.isalnum() or c in "-_") else "-" for c in str(actor_id or "shared"))
    return a[:64] or "shared"


def _user_root(user: User) -> str:
    root = os.environ.get("AGENTCORE_SKILLS_ROOT", "").strip() or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
    d = os.path.join(root, "workspace", _safe_actor(str(user.id)))
    os.makedirs(d, exist_ok=True)
    return d


def _resolve(user: User, rel_path: str) -> str | None:
    """把用户给的相对路径解析为绝对路径, 并确保仍在该用户工作区内 (防目录穿越)。"""
    base = os.path.realpath(_user_root(user))
    target = os.path.realpath(os.path.join(base, rel_path or ""))
    if target == base or target.startswith(base + os.sep):
        return target
    return None


@router.get("/files")
async def list_files(current_user: User = Depends(get_current_user)):
    """递归列出当前用户工作区里的全部文件 (相对路径 + 大小 + 修改时间)。"""
    base = _user_root(current_user)
    files = []
    for dirpath, _dirs, names in os.walk(base):
        for n in names:
            fp = os.path.join(dirpath, n)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            rel = os.path.relpath(fp, base)
            ext = os.path.splitext(n)[1].lower()
            files.append({
                "path": rel,
                "size": st.st_size,
                "modified_at": int(st.st_mtime),
                "ext": ext,
                "category": _categorize(rel, ext),
            })
    files.sort(key=lambda f: f["modified_at"], reverse=True)
    # 各类别计数 (前端分组展示用)
    cat_counts: dict[str, int] = {}
    for f in files:
        cat_counts[f["category"]] = cat_counts.get(f["category"], 0) + 1
    return {"root": "workspace", "count": len(files), "files": files,
            "categories": WORKSPACE_CATEGORIES, "category_counts": cat_counts}


@router.get("/file")
async def read_file(
    path: str = Query(..., description="相对工作区的文件路径"),
    download: bool = Query(default=False, description="true 则作为附件下载"),
    current_user: User = Depends(get_current_user),
):
    """读取/下载工作区单个文件。文本类返回内容, 其他类型作为文件下载。"""
    target = _resolve(current_user, path)
    if not target or not os.path.isfile(target):
        return JSONResponse(status_code=404, content={"error": "文件不存在"})

    fname = os.path.basename(target)
    ext = os.path.splitext(fname)[1].lower()

    if download or ext not in _TEXT_EXTS:
        return FileResponse(target, filename=fname, media_type="application/octet-stream")

    try:
        if os.path.getsize(target) > _MAX_TEXT_BYTES:
            return JSONResponse(status_code=413, content={"error": "文件过大, 请下载查看"})
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return PlainTextResponse(content)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(e)[:200]})


@router.delete("/file")
async def delete_file(
    path: str = Query(..., description="相对工作区的文件路径"),
    current_user: User = Depends(get_current_user),
):
    """删除工作区里的某个文件 (仅限自己的工作区)。"""
    target = _resolve(current_user, path)
    if not target or not os.path.isfile(target):
        return JSONResponse(status_code=404, content={"error": "文件不存在"})
    try:
        os.remove(target)
        return {"success": True, "path": path}
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(e)[:200]})
