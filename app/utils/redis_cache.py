import json
import os
from typing import Any, Optional

from redis.asyncio import Redis, from_url

_redis_client: Optional[Redis] = None


def get_redis_client() -> Optional[Redis]:
    url = os.getenv("UPSTASH_REDIS_URL")
    if not url:
        return None
    global _redis_client
    if _redis_client is None:
        _redis_client = from_url(url, decode_responses=True)
    return _redis_client


async def get_json(key: str) -> Optional[Any]:
    client = get_redis_client()
    if not client:
        return None
    try:
        raw = await client.get(key)
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        return None


async def set_json(key: str, value: Any, ttl_seconds: int) -> None:
    client = get_redis_client()
    if not client:
        return
    try:
        payload = json.dumps(value, ensure_ascii=False)
        await client.set(key, payload, ex=ttl_seconds)
    except Exception:
        return
