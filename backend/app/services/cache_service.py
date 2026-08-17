import json
import hashlib
import redis.asyncio as aioredis
from typing import Optional
from app.core.config import settings

_redis: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def _make_key(question: str) -> str:
    h = hashlib.md5(question.strip().lower().encode()).hexdigest()
    return f"rag:cache:{h}"


async def get_cached_answer(question: str) -> Optional[dict]:
    r = await get_redis()
    raw = await r.get(_make_key(question))
    if raw:
        return json.loads(raw)
    return None


async def set_cached_answer(question: str, answer: dict) -> None:
    r = await get_redis()
    await r.setex(_make_key(question), settings.REDIS_CACHE_TTL, json.dumps(answer, ensure_ascii=False))


async def clear_cache() -> None:
    r = await get_redis()
    keys = await r.keys("rag:cache:*")
    if keys:
        await r.delete(*keys)
