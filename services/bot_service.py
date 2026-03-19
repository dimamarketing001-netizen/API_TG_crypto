import random
import httpx
from aiogram import Bot
from core.config import settings
from core.constants import CITIES_TO_GROUPS, OPERATORS_TO_GROUPS
from db.repository import get_online_operators, create_task_log, update_operator_thread
from services.operator_logic import balancer 
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime
from aiogram.filters.callback_data import CallbackData
import logging

log = logging.getLogger(__name__)

bot = Bot(token=settings.BOT_TOKEN)

class TaskCB(CallbackData, prefix="task"):
    action: str
    id: int

# Новый CallbackData для кнопок на основной заявке
class DealCB(CallbackData, prefix="deal"):
    action: str
    id: str # ID из таблицы CryptoDeals


class SecurityTaskCB(CallbackData, prefix="sec_task"):
    action: str
    deal_id: str


class BotService:
    @staticmethod
    async def send_task_to_operator(task_id, op_group):
        from db.repository import update_operator_thread
        # Создаем топик
        new_op_topic = await bot.create_forum_topic(chat_id=op_group, name=f"Задача #{task_id}")
        # Сохраняем ID топика в БД
        await update_operator_thread(task_id, new_op_topic.message_thread_id)
        # Отправляем сообщение
        await bot.send_message(
            chat_id=op_group,
            message_thread_id=new_op_topic.message_thread_id,
            text=f"📥 <b>Новая задача!</b>",
            reply_markup=BotService.get_task_keyboard(task_id, "pending"),
            parse_mode="HTML"
        )

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
        log.info(f"Получен запрос на создание заявки: {data.model_dump_json(indent=2)}")
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

        # --- НОВАЯ ЛОГИКА ---
        # 1. Создаем запись в БД, чтобы получить ID сделки (deals_id)
        from db.repository import create_deal_from_topic
        deals_id = await create_deal_from_topic(data, group_id, topic.message_thread_id)
        if not deals_id:
            log.error("Не удалось создать запись в CryptoDeals, ID не получен.")
            return None

        # 2. Создаем клавиатуру с этим ID
        deal_keyboard = BotService.get_deal_keyboard(deals_id)
        
        await bot.send_message(
            chat_id=group_id,
            message_thread_id=topic.message_thread_id,
            text=BotService.format_main_message(data, city_name, partner_name),
            reply_markup=deal_keyboard, # <--- ДОБАВЛЯЕМ КНОПКИ
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return {"chat_id": group_id, "topic_id": topic.message_thread_id}

    @staticmethod
    def get_task_keyboard(task_id: int, status: str, form_url: str = "#"):
        # ... (код этой функции без изменений)
        pass

    @staticmethod
    def get_deal_keyboard(deal_id: int):
        """Создает клавиатуру для основной заявки в городском чате."""
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Принять", callback_data=DealCB(action="accept", id=str(deal_id)).pack())
        builder.button(text="↪️ Перенести", callback_data=DealCB(action="transfer", id=str(deal_id)).pack())
        builder.button(text="❌ Отклонить", callback_data=DealCB(action="reject", id=str(deal_id)).pack())
        builder.adjust(3)
        return builder.as_markup()

    @staticmethod
    def get_client_arrived_keyboard(deal_id: str):
        """Создает клавиатуру для кнопки 'Клиент пришел'."""
        builder = InlineKeyboardBuilder()
        builder.button(text="Клиент пришел", callback_data=DealCB(action="client_arrived", id=deal_id).pack())
        return builder.as_markup()

    @staticmethod
    def get_security_task_keyboard(deal_id: str):
        """Создает клавиатуру для задачи СБ (Перенос/Отмена)."""
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Принять", callback_data=SecurityTaskCB(action="accept", deal_id=deal_id).pack())
        builder.button(text="❌ Отклонить", callback_data=SecurityTaskCB(action="decline", deal_id=deal_id).pack())
        builder.adjust(2)
        return builder.as_markup()

    @staticmethod
    def get_task_keyboard(task_id: int, status: str, form_url: str = "#"):
        kb = []
        if status == "pending":
            kb.append([InlineKeyboardButton(text="✅ Принять и перейти", callback_data=TaskCB(action="accept", id=task_id).pack())])
        elif status == "active":
            # Важно: здесь ссылка на форму
            kb.append([InlineKeyboardButton(text="🔗 Открыть форму", url=form_url)])
            kb.append([InlineKeyboardButton(text="⏸ Пауза", callback_data=TaskCB(action="pause", id=task_id).pack())])
            kb.append([InlineKeyboardButton(text="🏁 Завершить", callback_data=TaskCB(action="complete", id=task_id).pack())])
        elif status == "paused":
            # Кнопка для возврата в работу
            kb.append([InlineKeyboardButton(text="▶️ Продолжить", callback_data=TaskCB(action="resume", id=task_id).pack())])
        
        return InlineKeyboardMarkup(inline_keyboard=kb)
    

    @staticmethod
    async def create_operator_topic(task_id, op_group, thread_id_original):
        """Создает топик для оператора и шлет туда кнопку 'Принять'"""
        topic_name = f"Заявка #{task_id} | Топик {thread_id_original}"
        new_op_topic = await bot.create_forum_topic(chat_id=op_group, name=topic_name)
        
        # Сохраняем ID созданного топика в БД
        await update_operator_thread(task_id, new_op_topic.message_thread_id)

        await bot.send_message(
            chat_id=op_group,
            message_thread_id=new_op_topic.message_thread_id,
            text=f"🆕 <b>Новая задача на расчет!</b>\nПоставлена: {datetime.now().strftime('%H:%M:%S')}",
            reply_markup=BotService.get_task_keyboard(task_id, "pending"),
            parse_mode="HTML"
        )
        return new_op_topic.message_thread_id

    @staticmethod
    async def assign_operator_and_notify(data):
        target_op = await balancer.get_available_operator()
        if not target_op:
            await create_task_log("queue", str(data.chat_id), data.message_thread_id, data.link, datetime.now())
            return "⏳ В очереди (все заняты)"

        op_id = str(target_op['personal_telegram_id'])
        op_group = OPERATORS_TO_GROUPS.get(op_id)
        task_id = await create_task_log(op_id, str(data.chat_id), data.message_thread_id, data.link, datetime.now())

        if op_group:
            await BotService.create_operator_topic(task_id, op_group, data.message_thread_id)
            return f"@{target_op['personal_telegram_username']}"
        
        return "Ошибка: группа не настроена"