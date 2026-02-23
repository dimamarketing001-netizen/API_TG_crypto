import random
import httpx
from aiogram import Bot
from core.config import settings
from core.constants import CITIES_TO_GROUPS, OPERATORS_TO_GROUPS
from db.repository import get_online_operators

bot = Bot(token=settings.BOT_TOKEN)

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
    async def assign_operator_and_notify(data):
        """Распределение операторов (MySQL)"""
        operators = await get_online_operators()
        if not operators: return "🔴 Нет операторов онлайн"

        target_op = random.choice(operators)
        op_id = str(target_op['personal_telegram_id'])
        op_user = target_op['personal_telegram_username']
        
        op_group = OPERATORS_TO_GROUPS.get(op_id)
        if op_group:
            clean_id = str(data.chat_id).replace("-100", "")
            topic_url = f"https://t.me/c/{clean_id}/{data.message_thread_id}"
            task_msg = f"🎯 <b>ЗАДАЧА НА РАСЧЕТ</b>\n\n🔗 <a href='{data.link}'>ФОРМА</a>\n💬 <a href='{topic_url}'>ЧАТ</a>"
            await bot.send_message(chat_id=op_group, text=task_msg, parse_mode="HTML")
            return f"@{op_user}"
        return f"@{op_user} (группа не настроена)"