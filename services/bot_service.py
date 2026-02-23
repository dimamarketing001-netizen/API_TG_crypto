import random
import httpx
from aiogram import Bot
from aiogram.types import BufferedInputFile
from core.config import settings
from core.constants import CITIES_TO_GROUPS, OPERATORS_TO_GROUPS, STATUS_MAP
from db.repository import get_online_operators

bot = Bot(token=settings.BOT_TOKEN)

class BotService:
    @staticmethod
    async def create_topic_and_notify(data):
        # Логика получения имен из внешнего API
        async with httpx.AsyncClient() as client:
            resp = await client.get(settings.EXTERNAL_API_URL)
            api_data = resp.json() if resp.status_code == 200 else {}

        city_name = next((d["NAME"] for d in api_data.get("DEPARTMENTS", []) if str(d["ID"]) == str(data.city_id)), "Неизвестно")
        partner_name = next((p["NAME"] for p in api_data.get("PARTNERS", []) if str(p["ID"]) == str(data.brand_id)), "Неизвестно")
        
        group_id = CITIES_TO_GROUPS.get(city_name)
        if not group_id: return None

        type_text = "ПРЯМАЯ" if data.transaction_type == "direct" else "ОБРАТНАЯ"
        amount = f"{data.cash_amount} {data.cash_currency}"
        
        topic = await bot.create_forum_topic(chat_id=group_id, name=f"{type_text} | {amount}")
        
        msg = (
            f"🔄 <b>Тип:</b> {type_text}\n🏛 <b>Город:</b> {city_name}\n🤝 <b>Партнер:</b> {partner_name}\n"
            f"👤 <b>Клиент:</b> {data.client_full_name}\n💰 <b>Сумма:</b> {amount}\n"
            f"🔗 <a href='{data.form_url}'>Форма</a>"
        )
        await bot.send_message(group_id, message_thread_id=topic.message_thread_id, text=msg, parse_mode="HTML")
        return {"chat_id": group_id, "topic_id": topic.message_thread_id}

    @staticmethod
    async def assign_operator(data):
        operators = await get_online_operators()
        if not operators:
            return "🔴 Нет операторов онлайн"

        target_op = random.choice(operators)
        op_tg_id = str(target_op['personal_telegram_id'])
        op_user = target_op['personal_telegram_username']
        
        op_group_id = OPERATORS_TO_GROUPS.get(op_tg_id)
        if op_group_id:
            # Ссылка на топик для оператора
            clean_chat_id = str(data.chat_id).replace("-100", "")
            topic_url = f"https://t.me/c/{clean_chat_id}/{data.message_thread_id}"
            
            task_msg = f"🆕 <b>ЗАДАЧА:</b>\n🔗 <a href='{data.link}'>Расчет</a>\n💬 <a href='{topic_url}'>Чат сделки</a>"
            await bot.send_message(chat_id=op_group_id, text=task_msg, parse_mode="HTML")
            
            return f"@{op_user}"
        return "⚠️ Группа оператора не настроена"