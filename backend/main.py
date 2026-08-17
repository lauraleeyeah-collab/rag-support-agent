from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.base import engine
from app.db.models import Base
from app.db.migrate import run_migrations
from app.api import auth, knowledge, chat


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时建表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 轻量迁移：为已有表补充新增列（幂等，可重复执行）
    await run_migrations(engine)

    # 自动创建管理员账号
    from sqlalchemy import select
    from app.db.base import AsyncSessionLocal
    from app.db.models import User
    from app.core.security import hash_password

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == settings.ADMIN_USERNAME))
        if not result.scalar_one_or_none():
            admin = User(
                username=settings.ADMIN_USERNAME,
                hashed_password=hash_password(settings.ADMIN_PASSWORD),
                role="admin"
            )
            db.add(admin)
            await db.commit()
            print(f"管理员账号已创建：{settings.ADMIN_USERNAME}")

    yield

    await engine.dispose()


app = FastAPI(
    title="RAG 企业知识库问答系统",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(chat.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
