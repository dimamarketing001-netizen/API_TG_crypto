import aiomysql
import uuid
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

async def find_or_create_security_topic(client_identifier, security_group_id: int, officer_id: int, task_type: str) -> int:
    """Ищет тему для клиента в чате СБ, создает новую или переименовывает существующую."""
    async with db.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            from services.bot_service import bot
            topic_title = f"{task_type} | Клиент: {client_identifier}"

            # Ищем существующую тему по идентификатору клиента
            await cur.execute("SELECT topic_id FROM security_topics WHERE client_identifier = %s", (str(client_identifier),))
            existing = await cur.fetchone()

            if existing:
                topic_id = existing['topic_id']
                try:
                    # Переименовываем существующую тему
                    await bot.edit_forum_topic(chat_id=security_group_id, message_thread_id=topic_id, name=topic_title)
                except Exception as e:
                    # Логируем ошибку, если не удалось переименовать, но продолжаем работу
                    print(f"Could not rename topic {topic_id}: {e}")
                return topic_id
            
            # Если не нашли, создаем новую
            topic = await bot.create_forum_topic(chat_id=security_group_id, name=topic_title)
            
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

async def get_deal_by_id(deal_id: str):
    """Получает информацию о сделке из таблицы CryptoDeals по ее ID."""
    async with db.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM CryptoDeals WHERE deals_id = %s", (deal_id,))
            return await cur.fetchone()

async def create_deal_from_topic(data, chat_id, topic_id) -> str | None:
    """Создает запись в CryptoDeals и возвращает ее ID."""
    async with db.pool.acquire() as conn:
        async with conn.cursor() as cur:
            deals_id = str(uuid.uuid4())

            # Определяем суммы в зависимости от типа транзакции
            if data.transaction_type == 'direct':
                amount_to_give = data.cash_amount
                currency_to_give = data.cash_currency
                amount_to_get = data.wallet_amount
                currency_to_get = data.wallet_currency
            else:  # reverse
                amount_to_give = data.wallet_amount
                currency_to_give = data.wallet_currency
                amount_to_get = data.cash_amount
                currency_to_get = data.cash_currency

            query = """
                INSERT INTO CryptoDeals (
                    deals_id, employee_id, direction,
                    amount_to_get, currency_to_get, amount_to_give, currency_to_give,
                    status, datetime_meeting, topic_id, chat_id, client_full_name, form_url
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            params = (
                deals_id,
                data.creator_id,
                data.transaction_type,
                amount_to_get,
                currency_to_get,
                amount_to_give,
                currency_to_give,
                'new',  # Начальный статус
                data.visit_time,
                topic_id,
                chat_id,
                data.client_full_name,
                data.form_url
            )
            await cur.execute(query, params)
            return deals_id

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


async def get_employee_by_id(employee_id: int):
    """Возвращает данные сотрудника по его ID из таблицы employees."""
    async with db.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            query = "SELECT * FROM employees WHERE id = %s"
            await cur.execute(query, (employee_id,))
            return await cur.fetchone()

async def get_online_managers():
    """Возвращает список онлайн сотрудников с ролью 'Manager'."""
    async with db.pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            query = """
                SELECT id, personal_telegram_id, personal_telegram_username
                FROM employees
                WHERE status = 'online' AND role = 'Manager'
            """
            await cur.execute(query)
            return await cur.fetchall()

async def update_security_task_status(deal_id: int, status: str):
    """Обновляет статус задачи СБ, связанной с deal_id."""
    async with db.pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Обновляем самую последнюю задачу СБ для данной сделки
            query = """
                UPDATE security_tasks SET status = %s
                WHERE deal_id = %s ORDER BY id DESC LIMIT 1
            """
            await cur.execute(query, (status, deal_id))