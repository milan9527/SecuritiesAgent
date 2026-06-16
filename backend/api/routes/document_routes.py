"""
文档管理 & 知识库路由
Documents stored in DB, files in AgentCore Runtime Session Storage
Knowledge base uses pgvector for semantic search
"""
from __future__ import annotations

import uuid
import traceback
from datetime import datetime
from fastapi import APIRouter, Depends, Query, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from db.models import User, Document, KnowledgeChunk
from api.auth import get_current_user
from api.internal_auth import resolve_internal_actor
from config.settings import get_settings

router = APIRouter(prefix="/api/documents", tags=["文档管理"])
settings = get_settings()

CATEGORY_DIRS = {
    "analysis": "reports/analysis",
    "strategy": "reports/strategy",
    "quant": "reports/quant",
    "market": "reports/market",
    "research": "reports/research",
    "imported": "imports",
    "general": "general",
}


class DocumentCreate(BaseModel):
    title: str
    category: str = "general"
    content: str = ""
    tags: list = []
    source: str = "user"
    add_to_kb: bool = False


class KBSearchRequest(BaseModel):
    query: str
    category: str = ""
    limit: int = 5


# ═══════════════════════════════════════════════════════
# 文档 CRUD
# ═══════════════════════════════════════════════════════

@router.get("/")
async def list_documents(
    category: str = Query(default="", description="Filter by category"),
    limit: int = Query(default=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取文档列表"""
    q = select(Document).where(Document.user_id == current_user.id)
    if category:
        q = q.where(Document.category == category)
    q = q.order_by(Document.updated_at.desc()).limit(limit)
    result = await db.execute(q)
    docs = result.scalars().all()
    return {"documents": [{
        "id": str(d.id), "title": d.title, "category": d.category,
        "file_type": d.file_type, "file_size": d.file_size,
        "tags": d.tags, "source": d.source,
        "is_in_knowledge_base": d.is_in_knowledge_base,
        "created_at": d.created_at.isoformat() if d.created_at else "",
        "updated_at": d.updated_at.isoformat() if d.updated_at else "",
    } for d in docs]}


@router.get("/categories")
async def get_categories(current_user: User = Depends(get_current_user)):
    """获取文档分类"""
    return {"categories": [
        {"id": "analysis", "name": "投资分析", "dir": "reports/analysis"},
        {"id": "strategy", "name": "交易策略", "dir": "reports/strategy"},
        {"id": "quant", "name": "量化策略", "dir": "reports/quant"},
        {"id": "market", "name": "市场研究", "dir": "reports/market"},
        {"id": "research", "name": "深度研报", "dir": "reports/research"},
        {"id": "imported", "name": "导入文档", "dir": "imports"},
        {"id": "general", "name": "通用文档", "dir": "general"},
    ]}


@router.post("/")
async def create_document(
    request: DocumentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建文档"""
    doc = Document(
        user_id=current_user.id,
        title=request.title,
        category=request.category,
        content=request.content,
        file_type="md",
        file_size=len(request.content.encode("utf-8")),
        tags=request.tags,
        source=request.source,
        session_id=f"doc-{current_user.id}-{uuid.uuid4().hex[:8]}",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # Add to knowledge base if requested
    if request.add_to_kb and request.content:
        await _add_to_knowledge_base(db, doc, current_user.id)

    return {"id": str(doc.id), "title": doc.title, "category": doc.category}


# ── 内部端点: Agent (Runtime) 把生成的文档存入【文档知识库】(token 鉴权) ──
class _InternalSaveDoc(BaseModel):
    token: str = ""
    actor_id: str = ""
    title: str
    content: str
    category: str = "general"
    tags: list = []
    file_type: str = "md"
    add_to_kb: bool = True


@router.post("/internal/save")
async def internal_save_document(req: _InternalSaveDoc, db: AsyncSession = Depends(get_db)):
    """Agent 调用: 把生成的文档/研报保存到该用户的【文档知识库】, 可选入库做语义检索。"""
    user = await resolve_internal_actor(req.token, req.actor_id, db)
    doc = Document(
        user_id=user.id,
        title=req.title[:300],
        category=req.category or "general",
        content=req.content,
        file_type=req.file_type or "md",
        file_size=len(req.content.encode("utf-8")),
        tags=req.tags or [],
        source="agent",
        session_id=f"doc-{user.id}-{uuid.uuid4().hex[:8]}",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    kb = False
    if req.add_to_kb and req.content:
        try:
            await _add_to_knowledge_base(db, doc, user.id)
            kb = True
        except Exception as e:  # noqa: BLE001
            print(f"[documents] internal add_to_kb failed: {e}")
    return {"id": str(doc.id), "title": doc.title, "status": "created",
            "module": "documents", "in_knowledge_base": kb}


@router.get("/{doc_id}")
async def get_document(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取文档详情"""
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.user_id == current_user.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return {"error": "文档不存在"}
    return {
        "id": str(doc.id), "title": doc.title, "category": doc.category,
        "content": doc.content, "file_type": doc.file_type,
        "file_size": doc.file_size, "tags": doc.tags, "source": doc.source,
        "is_in_knowledge_base": doc.is_in_knowledge_base,
        "session_id": doc.session_id,
        "created_at": doc.created_at.isoformat() if doc.created_at else "",
    }


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除文档"""
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.user_id == current_user.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return {"error": "文档不存在"}

    # Delete knowledge chunks
    await db.execute(
        text("DELETE FROM knowledge_chunks WHERE document_id = :did").bindparams(did=doc.id)
    )
    await db.delete(doc)
    await db.commit()
    return {"success": True}


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    category: str = Form(default="imported"),
    add_to_kb: bool = Form(default=False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """上传外部文档"""
    content_bytes = await file.read()
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = content_bytes.decode("gbk", errors="ignore")

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "txt"

    doc = Document(
        user_id=current_user.id,
        title=file.filename,
        category=category,
        content=content,
        file_type=ext,
        file_size=len(content_bytes),
        tags=["imported"],
        source="imported",
        session_id=f"doc-{current_user.id}-{uuid.uuid4().hex[:8]}",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    if add_to_kb and content:
        await _add_to_knowledge_base(db, doc, current_user.id)

    return {"id": str(doc.id), "title": doc.title, "file_size": doc.file_size}


class ImportUrlRequest(BaseModel):
    url: str
    title: str = ""
    category: str = "imported"
    add_to_kb: bool = True


@router.post("/import-url")
async def import_from_url(
    request: ImportUrlRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """从URL导入文档"""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(request.url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            content = resp.text

        # Extract title from HTML if not provided
        title = request.title
        if not title:
            import re
            m = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
            title = m.group(1).strip() if m else request.url.split("/")[-1] or "导入文档"

        # Strip HTML tags for plain text storage
        import re
        text_content = re.sub(r"<script.*?</script>", "", content, flags=re.DOTALL | re.IGNORECASE)
        text_content = re.sub(r"<style.*?</style>", "", text_content, flags=re.DOTALL | re.IGNORECASE)
        text_content = re.sub(r"<[^>]+>", " ", text_content)
        text_content = re.sub(r"\s+", " ", text_content).strip()

        doc = Document(
            user_id=current_user.id,
            title=title[:300],
            category=request.category,
            content=text_content[:50000],
            file_type="txt",
            file_size=len(text_content.encode("utf-8")),
            tags=["imported", "url"],
            source="url",
            file_path=request.url,
            session_id=f"doc-{current_user.id}-{uuid.uuid4().hex[:8]}",
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)

        chunks = 0
        if request.add_to_kb and text_content:
            chunks = await _add_to_knowledge_base(db, doc, current_user.id)

        return {"id": str(doc.id), "title": doc.title, "file_size": doc.file_size, "chunks": chunks}

    except Exception as e:
        return {"error": f"导入失败: {str(e)[:200]}"}


# ═══════════════════════════════════════════════════════
# 知识库
# ═══════════════════════════════════════════════════════

@router.post("/{doc_id}/add-to-kb")
async def add_document_to_kb(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """将文档添加到知识库"""
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.user_id == current_user.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return {"error": "文档不存在"}
    if not doc.content:
        return {"error": "文档内容为空"}

    count = await _add_to_knowledge_base(db, doc, current_user.id)
    return {"success": True, "chunks": count}


@router.post("/kb/search")
async def search_knowledge_base(
    request: KBSearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """知识库RAG问答 - 检索相关内容后用LLM生成答案"""
    import json as _json

    # 1. Retrieve relevant chunks
    chunks_text = []
    sources = []
    try:
        embedding = await _get_embedding(request.query)
        if embedding:
            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
            sql = text("""
                SELECT kc.content, kc.metadata, kc.document_id,
                       1 - (kc.embedding <=> cast(:emb as vector)) as similarity
                FROM knowledge_chunks kc
                WHERE kc.user_id = :uid
                ORDER BY kc.embedding <=> cast(:emb as vector)
                LIMIT :lim
            """)
            result = await db.execute(sql, {"emb": embedding_str, "uid": current_user.id, "lim": request.limit})
            rows = result.fetchall()
            for r in rows:
                if float(r[3]) > 0.25:
                    chunks_text.append(r[0][:1500])
                    sources.append({"title": (r[1] or {}).get("title", ""), "similarity": round(float(r[3]), 3), "document_id": str(r[2])})
    except Exception as e:
        print(f"[KB RAG] Vector search failed: {e}")

    # Fallback to text search if no vector results
    if not chunks_text:
        try:
            q = select(KnowledgeChunk).where(
                KnowledgeChunk.user_id == current_user.id,
                KnowledgeChunk.content.ilike(f"%{request.query[:50]}%"),
            ).limit(request.limit)
            result = await db.execute(q)
            for r in result.scalars().all():
                chunks_text.append(r.content[:1500])
                sources.append({"title": (r.chunk_meta or {}).get("title", ""), "similarity": 0.5, "document_id": str(r.document_id)})
        except Exception:
            pass

    if not chunks_text:
        return {"answer": "知识库中未找到相关内容。请先添加相关文档到知识库。", "sources": []}

    # 2. Generate answer using LLM
    context = "\n\n---\n\n".join(chunks_text[:5])
    try:
        import boto3
        client = boto3.client("bedrock-runtime", region_name=settings.AWS_REGION)
        prompt = f"""基于以下知识库内容回答用户问题。只使用提供的内容回答,不要编造信息。如果内容不足以回答,请说明。用专业简洁的中文回答,数据用表格展示。

知识库内容:
{context}

用户问题: {request.query}

回答:"""

        body = _json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}],
        })
        resp = client.invoke_model(modelId=settings.LLM_MODEL_ID, body=body)
        resp_body = _json.loads(resp["body"].read())
        answer = resp_body.get("content", [{}])[0].get("text", "无法生成回答")
    except Exception as e:
        print(f"[KB RAG] LLM failed: {e}")
        answer = "LLM调用失败,以下是检索到的相关内容:\n\n" + "\n\n".join(c[:300] for c in chunks_text[:3])

    return {"answer": answer, "sources": sources}


@router.get("/kb/stats")
async def kb_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """知识库统计"""
    doc_count = await db.execute(
        select(func.count(Document.id)).where(
            Document.user_id == current_user.id, Document.is_in_knowledge_base == True
        )
    )
    chunk_count = await db.execute(
        select(func.count(KnowledgeChunk.id)).where(KnowledgeChunk.user_id == current_user.id)
    )
    return {
        "documents": doc_count.scalar() or 0,
        "chunks": chunk_count.scalar() or 0,
    }


@router.post("/kb/reindex")
async def reindex_knowledge_base(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """重建知识库索引 - 清理HTML后重新生成embeddings"""
    result = await db.execute(
        select(Document).where(
            Document.user_id == current_user.id,
            Document.is_in_knowledge_base == True,
        )
    )
    docs = result.scalars().all()
    total_chunks = 0
    for doc in docs:
        count = await _add_to_knowledge_base(db, doc, current_user.id)
        total_chunks += count
    return {"success": True, "documents": len(docs), "chunks": total_chunks}


# ═══════════════════════════════════════════════════════
# 内部函数
# ═══════════════════════════════════════════════════════

async def _add_to_knowledge_base(db: AsyncSession, doc: Document, user_id) -> int:
    """Split document into chunks, optionally generate embeddings"""
    import re as _re

    # Strip HTML/CSS before chunking for cleaner embeddings
    clean_content = doc.content or ""
    clean_content = _re.sub(r"<style[^>]*>[\s\S]*?</style>", "", clean_content, flags=_re.IGNORECASE)
    clean_content = _re.sub(r"<[^>]+>", " ", clean_content)
    clean_content = _re.sub(r"\s+", " ", clean_content).strip()

    if not clean_content:
        return 0

    chunks = _split_text(clean_content, chunk_size=800, overlap=100)
    count = 0

    # Delete existing chunks for this document
    try:
        await db.execute(
            text("DELETE FROM knowledge_chunks WHERE document_id = :did").bindparams(did=doc.id)
        )
    except Exception:
        pass

    for i, chunk_text in enumerate(chunks):
        chunk = KnowledgeChunk(
            document_id=doc.id,
            user_id=user_id,
            chunk_index=i,
            content=chunk_text,  # Store clean text, not HTML
            chunk_meta={"title": doc.title, "category": doc.category, "tags": doc.tags},
        )
        db.add(chunk)
        count += 1

    # Try to generate embeddings (non-blocking, skip if fails)
    try:
        await db.flush()
        for i, chunk_text in enumerate(chunks):
            embedding = await _get_embedding(chunk_text)
            if embedding:
                embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
                # Use raw connection to avoid SQLAlchemy parsing issues with ::vector
                await db.execute(
                    text("UPDATE knowledge_chunks SET embedding = cast(:emb as vector) WHERE document_id = :did AND chunk_index = :idx"),
                    {"emb": embedding_str, "did": doc.id, "idx": i}
                )
    except Exception as e:
        print(f"[KB] Embedding failed (non-critical): {e}")

    doc.is_in_knowledge_base = True
    await db.commit()
    return count


def _split_text(text_content: str, chunk_size: int = 800, overlap: int = 100) -> list:
    """Split text into overlapping chunks"""
    if not text_content:
        return []
    # Split by paragraphs first
    paragraphs = text_content.split("\n\n")
    chunks = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) > chunk_size and current:
            chunks.append(current.strip())
            # Keep overlap
            current = current[-overlap:] + "\n\n" + para if overlap else para
        else:
            current = current + "\n\n" + para if current else para
    if current.strip():
        chunks.append(current.strip())
    return chunks if chunks else [text_content[:chunk_size]]


async def _get_embedding(text_content: str) -> list:
    """Generate embedding using Amazon Titan Embed"""
    try:
        import boto3, json
        client = boto3.client("bedrock-runtime", region_name=settings.AWS_REGION)
        response = client.invoke_model(
            modelId="amazon.titan-embed-text-v2:0",
            body=json.dumps({"inputText": text_content[:8000]}),
        )
        result = json.loads(response["body"].read())
        return result.get("embedding", [])
    except Exception as e:
        print(f"[Embedding] Failed: {e}")
        return []


async def _text_search(db: AsyncSession, user_id, query: str, category: str, limit: int):
    """Fallback text search when vector search unavailable"""
    q = select(KnowledgeChunk).where(
        KnowledgeChunk.user_id == user_id,
        KnowledgeChunk.content.ilike(f"%{query}%"),
    ).limit(limit)
    result = await db.execute(q)
    rows = result.scalars().all()
    return {"results": [{
        "id": str(r.id), "content": r.content[:500], "metadata": r.chunk_meta,
        "document_id": str(r.document_id), "similarity": 0.5,
    } for r in rows]}
