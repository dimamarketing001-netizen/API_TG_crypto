import asyncio
from db.repository import get_online_operators, get_active_tasks_count, get_oldest_pending_task

class TaskBalancer:
    def __init__(self):
        self.lock = asyncio.Lock()

    async def get_available_operator(self):
        """Находит оператора, который онлайн и у которого 0 активных (не на паузе) задач"""
        async with self.lock:
            online_ops = await get_online_operators()
            if not online_ops:
                return None

            for op in online_ops:
                op_id = str(op['personal_telegram_id'])
                # Проверяем в БД, есть ли у него задачи со статусом 'active'
                active_count = await get_active_tasks_count(op_id)
                if active_count == 0:
                    return op # Этот оператор свободен (у него либо нет задач, либо все на паузе)
            
            return None # Все заняты

balancer = TaskBalancer()