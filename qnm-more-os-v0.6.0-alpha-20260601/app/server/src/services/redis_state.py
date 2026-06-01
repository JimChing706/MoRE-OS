import json
import asyncio
from typing import Any, Optional
from datetime import datetime, timedelta

import redis.asyncio as redis

class RedisStateManager:
    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0):
        self.host = host
        self.port = port
        self.db = db
        self.client: Optional[redis.Redis] = None
        self.connected = False
        self._reconnect_task = None

    async def connect(self) -> bool:
        """建立 Redis 连接"""
        try:
            self.client = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
            )
            await self.client.ping()
            self.connected = True
            print(f"[Redis] Connected to {self.host}:{self.port}")
            return True
        except Exception as e:
            print(f"[Redis] Connection failed: {e}")
            self.connected = False
            self._start_reconnect()
            return False

    def _start_reconnect(self):
        """启动自动重连"""
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(self._auto_reconnect())

    async def _auto_reconnect(self, max_retries: int = 10, interval: int = 5):
        """自动重连机制"""
        for attempt in range(1, max_retries + 1):
            print(f"[Redis] Reconnecting... attempt {attempt}/{max_retries}")
            if await self.connect():
                return
            await asyncio.sleep(interval)
        print("[Redis] Max reconnection attempts reached")

    async def disconnect(self):
        """断开连接"""
        if self.client:
            await self.client.close()
            self.connected = False
            print("[Redis] Disconnected")

    async def set(self, key: str, value: Any, expire: int = None) -> bool:
        """设置键值对"""
        if not self.connected:
            return False
        try:
            serialized = json.dumps(value, default=str)
            if expire:
                await self.client.setex(key, expire, serialized)
            else:
                await self.client.set(key, serialized)
            return True
        except Exception as e:
            print(f"[Redis] Set error: {e}")
            return False

    async def get(self, key: str) -> Optional[Any]:
        """获取键值"""
        if not self.connected:
            return None
        try:
            value = await self.client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            print(f"[Redis] Get error: {e}")
            return None

    async def delete(self, key: str) -> bool:
        """删除键"""
        if not self.connected:
            return False
        try:
            await self.client.delete(key)
            return True
        except Exception as e:
            print(f"[Redis] Delete error: {e}")
            return False

    async def exists(self, key: str) -> bool:
        """检查键是否存在"""
        if not self.connected:
            return False
        try:
            return await self.client.exists(key) > 0
        except Exception as e:
            print(f"[Redis] Exists error: {e}")
            return False

    async def expire(self, key: str, seconds: int) -> bool:
        """设置过期时间"""
        if not self.connected:
            return False
        try:
            return await self.client.expire(key, seconds)
        except Exception as e:
            print(f"[Redis] Expire error: {e}")
            return False

    async def ttl(self, key: str) -> int:
        """获取剩余生存时间"""
        if not self.connected:
            return -1
        try:
            return await self.client.ttl(key)
        except Exception as e:
            print(f"[Redis] TTL error: {e}")
            return -1

    async def keys(self, pattern: str = "*") -> list:
        """获取匹配的键列表"""
        if not self.connected:
            return []
        try:
            return await self.client.keys(pattern)
        except Exception as e:
            print(f"[Redis] Keys error: {e}")
            return []

    async def incr(self, key: str, amount: int = 1) -> int:
        """递增计数器"""
        if not self.connected:
            return 0
        try:
            return await self.client.incrby(key, amount)
        except Exception as e:
            print(f"[Redis] Incr error: {e}")
            return 0

    async def zadd(self, key: str, mapping: dict, expire: int = None) -> bool:
        """添加有序集合成员"""
        if not self.connected:
            return False
        try:
            await self.client.zadd(key, mapping)
            if expire:
                await self.client.expire(key, expire)
            return True
        except Exception as e:
            print(f"[Redis] Zadd error: {e}")
            return False

    async def zrange(self, key: str, start: int = 0, end: int = -1, desc: bool = False) -> list:
        """获取有序集合成员"""
        if not self.connected:
            return []
        try:
            return await self.client.zrange(key, start, end, desc=desc)
        except Exception as e:
            print(f"[Redis] Zrange error: {e}")
            return []

    async def publish(self, channel: str, message: Any) -> bool:
        """发布消息到频道"""
        if not self.connected:
            return False
        try:
            serialized = json.dumps(message, default=str)
            await self.client.publish(channel, serialized)
            return True
        except Exception as e:
            print(f"[Redis] Publish error: {e}")
            return False

    def is_connected(self) -> bool:
        """检查连接状态"""
        return self.connected

redis_state_manager = RedisStateManager()
