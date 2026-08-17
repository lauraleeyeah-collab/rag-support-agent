import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Boolean, DateTime, ForeignKey,
    Text, Integer
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc)


def new_uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=new_uuid)
    username = Column(String(50), unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String(20), default="user")  # "user" 或 "admin"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True, default=new_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(200), default="新对话")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="sessions")
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=new_uuid)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)  # "user" 或 "assistant"
    content = Column(Text, nullable=False)
    citations = Column(Text, nullable=True)  # JSON 字符串，存引用片段
    # 客服分诊增量：分诊结果（仅 assistant 消息有值；历史消息为 NULL，前端不渲染标签）
    triage_type = Column(String(20), nullable=True)    # 问题类型：产品选型/故障排查/售后政策/其他
    triage_action = Column(String(20), nullable=True)  # 处理方式：direct/cautious/human/refusal
    created_at = Column(DateTime(timezone=True), default=utcnow)

    session = relationship("Session", back_populates="messages")


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=new_uuid)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_size = Column(Integer, nullable=False)
    status = Column(String(20), default="processing")  # processing / ready / failed
    chunk_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    uploaded_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
