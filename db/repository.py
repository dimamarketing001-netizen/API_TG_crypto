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
        
async def create_task_log(operator_id, chat_id, thread_id, form_url, assigned_at):
    """Создает запись о назначении задачи и возвращает её ID"""
    async with db.pool.acquire() as conn:
        async with conn.cursor() as cur:
            query = """
                INSERT INTO task_logs (operator_id, chat_id, message_thread_id, form_url, assigned_at)
                VALUES (%s, %s, %s, %s, %s)
            """
            await cur.execute(query, (operator_id, chat_id, thread_id, form_url, assigned_at))
            return cur.lastrowid

async def log_task_click(task_id, clicked_at):
    """Фиксирует время нажатия и возвращает URL формы для редиректа"""
    async with db.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            # Сначала получаем URL
            await cur.execute("SELECT form_url FROM task_logs WHERE id = %s", (task_id,))
            result = await cur.fetchone()
            if result:
                # Обновляем время нажатия
                await cur.execute(
                    "UPDATE task_logs SET clicked_at = %s WHERE id = %s AND clicked_at IS NULL",
                    (clicked_at, task_id)
                )
                return result['form_url']
            return None