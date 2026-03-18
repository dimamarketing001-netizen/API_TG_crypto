import aiomysql
from db.session import db
from datetime import datetime

async def assign_task_to_operator(task_id, operator_id):
    async with db.pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE task_logs SET operator_id = %s WHERE id = %s",
                (str(operator_id), task_id)
            )

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

async def get_online_security_officers():
    """Возвращает список онлайн сотрудников СБ."""
    async with db.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            query = """
                SELECT id, personal_telegram_id, personal_telegram_username 
                FROM employees 
                WHERE status = 'online' AND role = 'Security'
            """
            await cur.execute(query)
            return await cur.fetchall()

async def get_active_security_tasks_count(officer_id: int):
    """Считает активные задачи для сотрудника СБ."""
    async with db.pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM security_tasks WHERE officer_id = %s AND status = 'active'", 
                (officer_id,)
            )
            res = await cur.fetchone()
            return res[0] if res else 0

async def find_or_create_security_topic(client_identifier, security_group_id: int, officer_id: int) -> int:
    """Ищет тему для клиента в чате СБ или создает новую."""
    async with db.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            # Ищем существующую тему по идентификатору клиента
            await cur.execute("SELECT topic_id FROM security_topics WHERE client_identifier = %s", (str(client_identifier),))
            existing = await cur.fetchone()
            if existing:
                return existing['topic_id']
            
            # Если не нашли, создаем новую
            from services.bot_service import bot
            topic = await bot.create_forum_topic(chat_id=security_group_id, name=f"Клиент: {client_identifier}")
            
            # Сохраняем в БД
            await cur.execute(
                "INSERT INTO security_topics (client_identifier, security_chat_id, officer_id, topic_id) VALUES (%s, %s, %s, %s)",
                (str(client_identifier), security_group_id, officer_id, topic.message_thread_id)
            )
            return topic.message_thread_id

async def create_security_task(original_task_id: int, officer_id: int, topic_id: int, is_deal_task: bool = False) -> int:
    """Создает задачу в таблице security_tasks."""
    async with db.pool.acquire() as conn:
        async with conn.cursor() as cur:
            # В зависимости от флага, пишем ID в deal_id или в operator_task_id
            task_id_field = "deal_id" if is_deal_task else "operator_task_id"
            query = f"INSERT INTO security_tasks ({task_id_field}, officer_id, topic_id) VALUES (%s, %s, %s)"
            await cur.execute(query, (original_task_id, officer_id, topic_id))
            return cur.lastrowid

async def get_deal_by_id(deal_id: int):
    """Получает информацию о сделке из таблицы CryptoDeals по ее ID."""
    async with db.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM CryptoDeals WHERE deals_id = %s", (deal_id,))
            return await cur.fetchone()

async def create_deal_from_topic(data, chat_id, topic_id) -> int | None:
    """Создает запись в CryptoDeals и возвращает ID."""
    async with db.pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Минимально рабочий запрос, чтобы избежать ошибок с неизвестными колонками.
            # Сохраняет только ID топика, ФИО клиента и ссылку на форму.
            query = """
                INSERT INTO CryptoDeals (
                    topic_id, client_full_name, form_url, status
                ) VALUES (%s, %s, %s, %s)
            """
            params = (
                topic_id,
                data.client_full_name,
                data.form_url,
                'new'  # Начальный статус
            )
            await cur.execute(query, params)
            return cur.lastrowid

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

async def log_task_event(task_id: int, event_type: str):
    """Записывает событие (пауза, продолжение и т.д.) в историю"""
    async with db.pool.acquire() as conn:
        async with conn.cursor() as cur:
            query = """
                INSERT INTO task_events (task_id, event_type, event_time)
                VALUES (%s, %s, %s)
            """
            await cur.execute(query, (task_id, event_type, datetime.now()))