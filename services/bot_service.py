import random
import httpx
from aiogram import Bot
from core.config import settings
from core.constants import CITIES_TO_GROUPS, OPERATORS_TO_GROUPS
from db.repository import get_online_operators, create_task_log
from services.operator_logic import balancer 
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData
import logging

bot = Bot(token=settings.BOT_TOKEN)

class TaskCB(CallbackData, prefix="task"):
    action: str
    id: int

class BotService:
    @staticmethod
    def format_main_message(data, city_name: str, partner_name: str) -> str:
        """Текст сообщения для нового топика (из исходника)"""
        wallet_owner_text = "Клиентский" if data.wallet_owner_type == "client" else \
                             "Партнёрский" if data.wallet_owner_type == "partner" else str(data.wallet_owner_type)
        
        # Логика определения типа и суммы из исходника
        if data.transaction_type == "direct":
            type_text, amount = "ПРЯМАЯ", f"{data.cash_amount} {data.cash_currency}"
        elif data.transaction_type == "reverse":
            type_text, amount = "ОБРАТНАЯ", f"{data.wallet_amount} {data.wallet_currency}"
        else:
            type_text, amount = str(data.transaction_type).upper(), "0"

        return (
            f"🔄 <b>Тип сделки:</b> <b>{type_text}</b>\n"
            f"🏛 <b>Город:</b> {city_name}\n"
            f"🤝 <b>Чья сделка:</b> {partner_name}\n\n"
            f"👤 <b>Клиент:</b> {data.client_full_name}\n"
            f"💰 <b>Сумма:</b> {amount}\n\n"
            f"🏦 <b>Кошелек:</b> <code>{data.wallet_address}</code>\n"
            f"🌐 <b>Сеть:</b> {data.wallet_network}\n"
            f"💰 <b>Тип кошелька:</b> {wallet_owner_text}\n\n"
            f"🕒 <b>Дата и время:</b> {data.visit_time}\n\n"
            f"🔗 <a href='{data.form_url}'>Ссылка на форму</a>"
        )

    @staticmethod
    async def create_transaction_topic(data):
        """Создание топика и отправка первого сообщения"""
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(settings.EXTERNAL_API_URL, timeout=5.0)
                api_vals = resp.json()
            except: api_vals = {}

        city_name = next((d["NAME"] for d in api_vals.get("DEPARTMENTS", []) if str(d["ID"]) == str(data.city_id)), "Неизвестно")
        partner_name = next((p["NAME"] for p in api_vals.get("PARTNERS", []) if str(p["ID"]) == str(data.brand_id)), "Неизвестно")

        group_id = CITIES_TO_GROUPS.get(city_name)
        if not group_id: return None

        # Заголовок топика как в исходнике
        type_text = "ПРЯМАЯ" if data.transaction_type == "direct" else "ОБРАТНАЯ"
        amount = data.cash_amount if data.transaction_type == "direct" else data.wallet_amount
        topic_title = f"{type_text} | {amount} | {data.visit_time}"
        
        topic = await bot.create_forum_topic(chat_id=group_id, name=topic_title)
        
        await bot.send_message(
            chat_id=group_id,
            message_thread_id=topic.message_thread_id,
            text=BotService.format_main_message(data, city_name, partner_name),
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return {"chat_id": group_id, "topic_id": topic.message_thread_id}

    @staticmethod
    def get_task_keyboard(task_id: int, status: str, form_url: str = "#"):
        kb = []
        if status == "pending":
            kb.append([InlineKeyboardButton(text="✅ Принять и перейти", callback_data=TaskCB(action="accept", id=task_id).pack())])
        elif status == "active":
            kb.append([InlineKeyboardButton(text="🔗 Открыть форму", url=form_url)])
            kb.append([InlineKeyboardButton(text="⏸ Пауза", callback_data=TaskCB(action="pause", id=task_id).pack())])
            kb.append([InlineKeyboardButton(text="🏁 Завершить", callback_data=TaskCB(action="complete", id=task_id).pack())])
        elif status == "paused":
            kb.append([InlineKeyboardButton(text="▶️ Продолжить", callback_data=TaskCB(action="resume", id=task_id).pack())])
        
        return InlineKeyboardMarkup(inline_keyboard=kb)

    @staticmethod
    async def assign_operator_and_notify(data):
        """Улучшенное распределение задач с защитой от ошибок"""
        # 1. Получаем свободного оператора через балансировщик
        target_op = await balancer.get_available_operator()
        assigned_time = datetime.now()
        
        # Если никто не онлайн или все заняты
        if not target_op:
            await create_task_log(
                operator_id="queue",
                chat_id=str(data.chat_id),
                thread_id=data.message_thread_id,
                form_url=data.link,
                assigned_at=assigned_time
            )
            return "⏳ В очереди (все заняты)"

        op_id = str(target_op['personal_telegram_id'])
        op_user = target_op['personal_telegram_username']
        
        # 2. Создаем запись в логах задач
        task_id = await create_task_log(
            operator_id=op_id,
            chat_id=str(data.chat_id),
            thread_id=data.message_thread_id,
            form_url=data.link,
            assigned_at=assigned_time
        )

        # 3. Ищем группу оператора в константах
        op_group = OPERATORS_TO_GROUPS.get(op_id)
        
        if op_group:
            try:
                # Отправляем сообщение только если op_group существует
                await bot.send_message(
                    chat_id=op_group,
                    text=f"🆕 <b>Новая задача на расчет!</b>\nТопик: {data.message_thread_id}",
                    reply_markup=BotService.get_task_keyboard(task_id, "pending"),
                    parse_mode="HTML"
                )
                return f"@{op_user}"
            except Exception as e:
                logging.error(f"Ошибка отправки в TG для оператора {op_id}: {e}")
                return f"@{op_user} (ошибка связи с TG)"
        else:
            # Если оператор есть в БД, но его ID нет в OPERATORS_TO_GROUPS в constants.py
            logging.error(f"КРИТИЧЕСКАЯ ОШИБКА: Оператор {op_id} (@{op_user}) онлайн, но его ID не прописан в OPERATORS_TO_GROUPS!")
            return f"@{op_user} (настройте группу оператора!)"