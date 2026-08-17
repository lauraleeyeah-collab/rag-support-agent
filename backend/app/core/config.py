from typing import List
from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # 数据库
    DATABASE_URL: str = "postgresql+asyncpg://rag_user:rag_password@localhost:5432/rag_db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_CACHE_TTL: int = 3600  # 缓存 1 小时

    # ChromaDB
    CHROMA_HOST: str = "localhost"
    CHROMA_PORT: int = 8001

    # 阿里云 DashScope
    DASHSCOPE_API_KEY: str = ""
    LLM_MODEL: str = "qwen-max"
    EMBEDDING_MODEL: str = "text-embedding-v2"

    # JWT
    SECRET_KEY: str = "change-this-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # 管理员
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "123456"

    # 文件上传
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE: int = 50_000_000  # 50MB
    ALLOWED_EXTENSIONS: List[str] = [".pdf", ".docx", ".txt", ".md"]

    # RAG 参数
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50
    RETRIEVAL_TOP_K: int = 5

    # 分诊与拒答阈值（客服分诊增量，可用环境变量覆盖，便于 QA 校准）
    # Top-1 检索分数低于此值 → 判定知识库未覆盖，直接拒答（不调用 LLM）
    RETRIEVAL_MIN_SCORE: float = 0.45
    # 供分诊 LLM 参考：Top-1 ≥ 此值时倾向 covered
    TRIAGE_COVERED_SCORE: float = 0.55
    # 分诊层使用的轻量模型（结构化判断，比生成模型更快更便宜）
    TRIAGE_MODEL: str = "qwen-turbo"

    # 评测脚本账号（eval/run_eval.py 使用，默认复用管理员账号）
    EVAL_USERNAME: str = "admin"
    EVAL_PASSWORD: str = "123456"

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @model_validator(mode="after")
    def _check_production_security(self):
        """生产环境必须显式覆盖默认密钥与默认密码，防止演示配置上线。"""
        if self.ENVIRONMENT == "production":
            if self.SECRET_KEY == "change-this-in-production":
                raise ValueError("生产环境必须通过环境变量 SECRET_KEY 设置随机密钥")
            if self.ADMIN_PASSWORD == "123456":
                raise ValueError("生产环境必须通过环境变量 ADMIN_PASSWORD 修改默认管理员密码")
        return self


settings = Settings()
