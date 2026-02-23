import asyncpg
from core.config import settings

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        if not self.pool:
            self.pool = await asyncpg.create_pool(
                dsn=settings.db_url,
                min_size=5,
                max_size=20
            )

    async def disconnect(self):
        if self.pool:
            await self.pool.close()

db = Database()