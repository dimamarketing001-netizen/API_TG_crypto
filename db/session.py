import aiomysql
from core.config import settings

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        if not self.pool:
            self.pool = await aiomysql.create_pool(
                host=settings.DB_HOST,
                port=settings.DB_PORT,
                user=settings.DB_USER,
                password=settings.DB_PASSWORD,
                db=settings.DB_NAME,
                minsize=5,
                maxsize=20,
                autocommit=True  
            )

    async def disconnect(self):
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()

db = Database()