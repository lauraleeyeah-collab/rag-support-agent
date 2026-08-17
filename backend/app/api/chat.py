# -*- coding: utf-8 -*-
"""问答与会话接口（T5：集成分诊字段透传与入库）。

变更点（相对旧版，最小改动）：
- /ask 接收 AnswerBundle（含 triage_type/triage_action/retrieved_sources），
  分诊字段随 assistant 消息入库，并在响应中透传给前端；
- 缓存对象从 {answer, citations} 扩展为整个 AnswerBundle（兼容旧缓存结构）；
- 消息历史接口透出 triage 字段（历史消息为 NULL，前端不渲染标签）。
"""

import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.base import get_db
from app.db.models import Session, Message, User
from app.api.auth import get_current_user
from app.services.rag_service import answer_question, AnswerBundle
from app.services.cache_service import get_cached_answer, set_cached_answer
from app.schemas.schemas import (
    SessionCreate, SessionOut, MessageOut, ChatRequest, ChatResponse, Citation
)

router = APIRouter(prefix="/chat", tags=["问答"])


# ── 会话管理 ─────────────────────────────────────────────

@router.get("/sessions", response_model=List[SessionOut])
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Session)
        .where(Session.user_id == current_user.id)
        .order_by(Session.updated_at.desc())
    )
    return result.scalars().all()


@router.post("/sessions", response_model=SessionOut)
async def create_session(
    body: SessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    session = Session(user_id=current_user.id, title=body.title)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return SessionOut.model_validate(session)


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == current_user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    await db.delete(session)
    await db.commit()
    return {"message": "删除成功"}


# ── 消息 ─────────────────────────────────────────────────

@router.get("/sessions/{session_id}/messages", response_model=List[MessageOut])
async def get_messages(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 确认会话属于当前用户
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="会话不存在")

    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()

    # 反序列化 citations，并透出分诊字段
    out = []
    for msg in messages:
        citations = None
        if msg.citations:
            try:
                citations = [Citation(**c) for c in json.loads(msg.citations)]
            except Exception:
                citations = None
        out.append(MessageOut(
            id=msg.id,
            role=msg.role,
            content=msg.content,
            citations=citations,
            triage_type=msg.triage_type,
            triage_action=msg.triage_action,
            created_at=msg.created_at
        ))
    return out


@router.post("/ask", response_model=ChatResponse)
async def ask(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 确认会话属于当前用户
    result = await db.execute(
        select(Session).where(Session.id == body.session_id, Session.user_id == current_user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 1. 存储用户消息
    user_msg = Message(session_id=body.session_id, role="user", content=body.question)
    db.add(user_msg)
    await db.commit()

    # 2. 检查缓存（缓存整个 AnswerBundle，命中时分诊字段同样一致）
    cached = await get_cached_answer(body.question)
    if cached:
        bundle = AnswerBundle.from_cache_dict(cached)
    else:
        # 3. 获取历史消息作为上下文
        hist_result = await db.execute(
            select(Message)
            .where(Message.session_id == body.session_id)
            .order_by(Message.created_at)
            .limit(10)
        )
        history = [{"role": m.role, "content": m.content} for m in hist_result.scalars().all()]

        # 4. RAG 问答（规则拦截 → 检索 → 阈值短路 → 分诊 → 分支生成）
        bundle = await answer_question(body.question, history)

        # 5. 写入缓存（规则拦截/拒答结果同为确定性内容，安全缓存）
        await set_cached_answer(body.question, bundle.to_cache_dict())

    # 6. 存储 AI 回答（含分诊字段）
    ai_msg = Message(
        session_id=body.session_id,
        role="assistant",
        content=bundle.answer,
        citations=json.dumps([c.model_dump() for c in bundle.citations], ensure_ascii=False),
        triage_type=bundle.triage_type,
        triage_action=bundle.triage_action,
    )
    db.add(ai_msg)

    # 7. 更新会话时间，自动从第一个问题提取标题
    if session.title == "新对话":
        title = body.question[:30] + ("..." if len(body.question) > 30 else "")
        session.title = title

    await db.commit()
    await db.refresh(ai_msg)

    return ChatResponse(
        message_id=ai_msg.id,
        answer=bundle.answer,
        citations=bundle.citations,
        triage_type=bundle.triage_type,
        triage_action=bundle.triage_action,
        retrieved_sources=bundle.retrieved_sources,
    )
