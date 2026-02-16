import uvicorn
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from aiogram import Bot
from aiogram.types import ForumTopic
from typing import Optional, Any, Dict

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = "8229314742:AAHM35Yx6_t8C6qfIvALcckdO9hFqQOKpBw"
EXTERNAL_API_URL = "https://form2.tethertrc20.ru/api/values"

CITIES_TO_GROUPS = {
    "Владимир": 0, "Екатеринбург": -1003834359521, "Иваново": -1003409849410,
    "Казань": 0, "Кострома": -1003749359451, "Москва": -1003559739114,
    "Нижний Новгород": -1003731754411, "Нижний Тагил": -1003659046288,
    "Новосибирск": -1003760499721, "Омск": -1003742180272, "Пермь": -1003849401068,
    "Ростов-на-Дону": -1003837153559, "Рязань": 0, "Самара": -1003809968038,
    "Санкт-Петербург": -1003766727039, "Сочи": -1003822120037, "Сургут": -1003812933026,
    "Тверь": -1003743410590, "Тольятти": -1003836081700, "Тула": -1003770447273,
    "Тюмень": -1003814406575, "Уфа": -1003793984695, "Челябинск": -1003600530409,
    "Ярославль": -1003721184896
}

# Универсальная модель для всех типов запросов
class UniversalRequest(BaseModel):
    # Поля для Типа 1 (Создание)
    city_id: Optional[int] = None
    brand_id: Optional[int] = None
    creator_id: Optional[int] = None
    visit_time: Optional[str] = None
    transaction_type: Optional[str] = None
    client_full_name: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    wallet_address: Optional[str] = None
    network: Optional[str] = None
    wallet_owner_type: Optional[str] = None
    form_url: Optional[str] = None

    # Поля для Типа 2 и 3 (Существующая тема)
    group_id: Optional[int] = None
    topic_id: Optional[int] = None
    
    # Для Типа 2 (Расчет)
    calc_data: Optional[Dict[str, Any]] = None # Сюда можно слать любой набор данных для расчета
    
    # Для Типа 3 (Просто сообщение)
    text: Optional[str] = None

app = FastAPI()
bot = Bot(token=BOT_TOKEN)

async def get_external_data():
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(EXTERNAL_API_URL, timeout=10.0)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"API Error: {e}")
            return None

def format_new_transaction(data: UniversalRequest, city_name: str, partner_name: str) -> str:
    type_text = "<b>ПРЯМАЯ</b>" if data.transaction_type == "direct" else "<b>ОБРАТНАЯ</b>"
    wallet_text = "Клиентский" if data.wallet_owner_type == "client" else "Партнёрский"
    return (
        f"🔄 <b>Тип сделки:</b> {type_text}\n"
        f"🏛 <b>Город:</b> {city_name}\n"
        f"🤝 <b>Чья сделка:</b> {partner_name}\n\n"
        f"👤 <b>Клиент:</b> {data.client_full_name}\n"
        f"💰 <b>Сумма:</b> {data.amount} {data.currency}\n\n"
        f"🏦 <b>Кошелек:</b> <code>{data.wallet_address}</code>\n"
        f"🌐 <b>Сеть:</b> {data.network}\n"
        f"💰 <b>Тип кошелька:</b> {wallet_text}\n\n"
        f"🕒 <b>Дата и время:</b> {data.visit_time}\n\n"
        f"🔗 <a href='{data.form_url}'>Ссылка на форму</a>"
    )

def format_calculation(calc_dict: Dict[str, Any]) -> str:
    msg = "📊 <b>Расчёт сделки:</b>\n\n"
    for key, value in calc_dict.items():
        msg += f"▫️ <b>{key}:</b> {value}\n"
    return msg

@app.post("/process")
async def process_request(data: UniversalRequest):
    # --- ТИП 1: СОЗДАНИЕ ЗАЯВКИ ---
    if data.city_id and not data.topic_id:
        api_values = await get_external_data()
        if not api_values: raise HTTPException(status_code=500, detail="API Values error")

        # Ищем город и партнера
        departments = api_values.get("DEPARTMENTS", [])
        city_name = next((d["NAME"] for d in departments if int(d["ID"]) == data.city_id), "Неизвестный город")
        
        partners = api_values.get("PARTNERS", [])
        partner_name = next((p["NAME"] for p in partners if data.brand_id and int(p["ID"]) == data.brand_id), "Неизвестный партнер")

        group_id = CITIES_TO_GROUPS.get(city_name)
        if not group_id: raise HTTPException(status_code=404, detail="Group not mapped")

        try:
            topic_title = f"{data.client_full_name} | {data.amount} {data.currency}"
            new_topic: ForumTopic = await bot.create_forum_topic(chat_id=group_id, name=topic_title)
            
            await bot.send_message(
                chat_id=group_id, 
                message_thread_id=new_topic.message_thread_id,
                text=format_new_transaction(data, city_name, partner_name),
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return {"status": "success", "group_id": group_id, "topic_id": new_topic.message_thread_id}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # --- ТИП 2: РАСЧЕТ СДЕЛКИ ---
    elif data.topic_id and data.group_id and data.calc_data:
        try:
            await bot.send_message(
                chat_id=data.group_id,
                message_thread_id=data.topic_id,
                text=format_calculation(data.calc_data),
                parse_mode="HTML"
            )
            return {"status": "success", "group_id": data.group_id, "topic_id": data.topic_id}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Telegram error: {e}")

    # --- ТИП 3: ПРОСТО СООБЩЕНИЕ ---
    elif data.topic_id and data.group_id and data.text:
        try:
            await bot.send_message(
                chat_id=data.group_id,
                message_thread_id=data.topic_id,
                text=f"💬 <b>Сообщение:</b>\n\n{data.text}",
                parse_mode="HTML"
            )
            return {"status": "success", "group_id": data.group_id, "topic_id": data.topic_id}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Telegram error: {e}")

    raise HTTPException(status_code=400, detail="Unknown request type (missed fields)")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=4000)