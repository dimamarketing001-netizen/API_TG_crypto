import asyncio
from db.repository import get_online_operators

class TaskBalancer:
    def __init__(self):
        # Храним {telegram_id: count}
        self.counts = {} 
        self.last_online_ids = set()
        self.lock = asyncio.Lock()

    async def get_next_operator(self):
        async with self.lock:
            # 1. Получаем список из БД
            online_ops = await get_online_operators()
            if not online_ops:
                return None

            # Текущие ID операторов в линии
            current_ids = {str(op['personal_telegram_id']) for op in online_ops}

            # 2. Если состав изменился (кто-то зашел или вышел) — СБРОС
            if current_ids != self.last_online_ids:
                self.counts = {op_id: 0 for op_id in current_ids}
                self.last_online_ids = current_ids
            
            # На всякий случай проверяем, что все онлайн-ID есть в словаре
            for op_id in current_ids:
                if op_id not in self.counts:
                    self.counts[op_id] = 0

            # 3. Фильтруем счетчики (только те, кто реально онлайн)
            active_stats = {op_id: cnt for op_id, cnt in self.counts.items() if op_id in current_ids}

            # 4. Выбираем оператора с наименьшим количеством задач
            # min() вернет ключ (op_id), у которого значение (count) минимально
            best_op_id = min(active_stats, key=active_stats.get)
            
            # Увеличиваем счетчик
            self.counts[best_op_id] += 1
            
            # Возвращаем полные данные оператора
            for op in online_ops:
                if str(op['personal_telegram_id']) == best_op_id:
                    return op
            return None

# Создаем экземпляр здесь
balancer = TaskBalancer()