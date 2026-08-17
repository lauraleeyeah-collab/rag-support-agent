# -*- coding: utf-8 -*-
"""轻量数据库迁移（架构 D5）。

项目未引入 Alembic，采用启动时幂等 ALTER TABLE 方案：
- 仅用于「给已有表加可空列」这类轻量变更；
- 每条语句必须幂等（ADD COLUMN IF NOT EXISTS），重复执行无副作用；
- 后续新增列时按顺序往 MIGRATION_STATEMENTS 追加即可。
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

# 迁移语句列表（按执行顺序排列，PostgreSQL 9.6+ 支持 IF NOT EXISTS）
MIGRATION_STATEMENTS = [
    # 客服分诊增量：messages 表新增分诊字段（可空，历史数据无需回填）
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS triage_type VARCHAR(20)",
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS triage_action VARCHAR(20)",
]


async def run_migrations(engine: AsyncEngine) -> None:
    """启动时执行全部迁移语句（幂等）。"""
    async with engine.begin() as conn:
        for stmt in MIGRATION_STATEMENTS:
            await conn.execute(text(stmt))
