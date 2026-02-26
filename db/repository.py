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
        
async def get_active_tasks_count(operator_id):
    """Считает количество задач в статусе 'active' для конкретного оператора"""
    async with db.pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM task_logs WHERE operator_id = %s AND status = 'active'", 
                (str(operator_id),)
            )
            res = await cur.fetchone()
            # Возвращаем первый элемент кортежа (результат COUNT)
            return res[0] if res else 0

async def update_task_status(task_id, status, blockchain_url=None):
    async with db.pool.acquire() as conn:
        async with conn.cursor() as cur:
            if blockchain_url:
                await cur.execute("UPDATE task_logs SET status=%s, blockchain_url=%s WHERE id=%s", (status, blockchain_url, task_id))
            else:
                await cur.execute("UPDATE task_logs SET status=%s WHERE id=%s", (status, task_id))

async def set_expected_amount(chat_id, thread_id, amount):
    """Сохраняет сумму из расчета в последнюю активную задачу этого топика"""
    async with db.pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE task_logs SET expected_amount = %s WHERE chat_id = %s AND message_thread_id = %s ORDER BY id DESC LIMIT 1",
                (amount, str(chat_id), thread_id)
            )

async def get_task_by_id(task_id):
    async with db.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM task_logs WHERE id = %s", (task_id,))
            return await cur.fetchone()

async def get_last_active_task(operator_id):
    """Находит последнюю активную задачу конкретного оператора"""
    async with db.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            query = """
                SELECT * FROM task_logs 
                WHERE operator_id = %s AND status = 'active' 
                ORDER BY assigned_at DESC LIMIT 1
            """
            await cur.execute(query, (str(operator_id),))
            return await cur.fetchone()

async def get_oldest_pending_task():
    """Находит самую старую задачу в очереди (статус pending)"""
    async with db.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            query = "SELECT * FROM task_logs WHERE status = 'pending' ORDER BY assigned_at ASC LIMIT 1"
            await cur.execute(query)
            return await cur.fetchone()

async def update_operator_thread(task_id, thread_id):
    """Сохраняет ID созданного топика оператора"""
    async with db.pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE task_logs SET operator_thread_id = %s WHERE id = %s",
                (thread_id, task_id)
            )
