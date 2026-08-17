from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, field_validator


# ── 用户相关 ──────────────────────────────────────────────

class UserRegister(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def username_valid(cls, v):
        if len(v) < 3 or len(v) > 50:
            raise ValueError("用户名长度需在 3-50 个字符之间")
        return v

    @field_validator("password")
    @classmethod
    def password_valid(cls, v):
        if len(v) < 6:
            raise ValueError("密码长度至少 6 个字符")
        return v


class UserLogin(BaseModel):
    username: str
    password: str


class ChangePassword(BaseModel):
    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_valid(cls, v):
        if len(v) < 6:
            raise ValueError("密码长度至少 6 个字符")
        return v


class UserOut(BaseModel):
    id: str
    username: str
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ── 会话相关 ──────────────────────────────────────────────

class SessionCreate(BaseModel):
    title: str = "新对话"


class SessionOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── 消息相关 ──────────────────────────────────────────────

class Citation(BaseModel):
    content: str
    source: str


class TriageResult(BaseModel):
    """分诊层结构化输出（triage_service 内部使用 + chat 层透传字段来源）"""
    question_type: str = "其他"      # 产品选型/故障排查/售后政策/其他
    kb_coverage: str = "partial"     # covered/partial/uncovered
    action: str = "cautious"         # direct/cautious/human（解析失败兜底 cautious）
    reason: str = ""                 # 一句话判断依据（仅日志用）


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    citations: Optional[List[Citation]] = None
    # 客服分诊增量：分诊字段（历史消息为 NULL，前端不渲染标签）
    triage_type: Optional[str] = None
    triage_action: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    session_id: str
    question: str


class ChatResponse(BaseModel):
    message_id: str
    answer: str
    citations: List[Citation]
    # 客服分诊增量：分诊结果 + 检索来源（供评测脚本估算命中率）
    triage_type: Optional[str] = None
    triage_action: Optional[str] = None
    retrieved_sources: List[str] = []


# ── 知识库相关 ────────────────────────────────────────────

class DocumentOut(BaseModel):
    id: str
    original_filename: str
    file_size: int
    status: str
    chunk_count: int
    error_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
