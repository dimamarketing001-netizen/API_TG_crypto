from db.session import db

async def get_online_operators():
    """Возвращает список всех онлайн операторов"""
    query = """
        SELECT personal_telegram_id, personal_telegram_username 
        FROM employees 
        WHERE status = 'online' AND role = 'Operator'
    """
    async with db.pool.acquire() as conn:
        return await conn.fetch(query)