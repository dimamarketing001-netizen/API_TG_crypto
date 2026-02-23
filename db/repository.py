import aiomysql
from db.session import db

async def get_online_operators():
    """Возвращает список онлайн операторов в виде списка словарей"""
    async with db.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            query = """
                SELECT personal_telegram_id, personal_telegram_username 
                FROM employees 
                WHERE status = 'online' AND role = 'Operator'
            """
            await cur.execute(query)
            return await cur.fetchall()