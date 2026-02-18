import uvicorn
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from aiogram import Bot
from aiogram.types import ForumTopic
from typing import Optional, Union, Any

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = "8229314742:AAHM35Yx6_t8C6qfIvALcckdO9hFqQOKpBw"
EXTERNAL_API_URL = "https://form2.tethertrc20.ru/api/values"

CITIES_TO_GROUPS = {
    "Владимир": 0,
    "Екатеринбург": -1003834359521,
    "Иваново": -1003409849410,
    "Казань": 0,
    "Кострома": -1003749359451,
    "Москва": -1003559739114,
    "Нижний Новгород": -1003731754411,
    "Нижний Тагил": -1003659046288,
    "Новосибирск": -1003760499721,
    "Омск": -1003742180272,
    "Пермь": -1003849401068,
    "Ростов-на-Дону": -1003837153559,
    "Рязань": 0,
    "Самара": -1003809968038,
    "Санкт-Петербург": -1003766727039,
    "Сочи": -1003822120037,
    "Сургут": -1003812933026,
    "Тверь": -1003743410590,
    "Тольятти": -1003836081700,
    "Тула": -1003770447273,
    "Тюмень": -1003814406575,
    "Уфа": -1003793984695,
    "Челябинск": -1003600530409,
    "Ярославль": -1003721184896
}

# --- МОДЕЛИ ДАННЫХ ---

# 1 тип: Создание транзакции
class TransactionData(BaseModel):
    city_id: int
    brand_id: Optional[int] = None
    creator_id: int
    visit_time: str
    transaction_type: str
    client_full_name: str
    cash_amount: float
    cash_currency: str
    wallet_address: str
    wallet_network: str
    wallet_amount: Any
    wallet_currency: str
    wallet_owner_type: str
    form_url: str

# 2 тип: Расчет по сделке
class CalculationData(BaseModel):
    chat_id: int
    message_thread_id: int
    transaction_type: str        
    calculation_type: str        
    operator_rate: str 
    total_percentage: str 
    client_rate: str
    fee: str                    
    formula: str                 
    total_to_transfer: str       
    test_info: Optional[str] = "Без теста"

# 3 тип: Обновление статуса или доп. инфо
class StatusUpdateData(BaseModel):
    chat_id: int
    message_thread_id: int
    text: str
    operator_name: Optional[str] = "Система"

app = FastAPI()
bot = Bot(token=BOT_TOKEN)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def format_main_message(data: TransactionData, city_name: str, partner_name: str) -> str:
    wallet_owner_type_text = "Клиентский" if data.wallet_owner_type == "client" else \
                             "Партнёрский" if data.wallet_owner_type == "partner" else data.wallet_owner_type
    
    if data.transaction_type == "direct":
        type_text = "<b>ПРЯМАЯ</b>"
        amount = f"{data.cash_amount} {data.cash_currency}"
    else:
        data.transaction_type

    if data.transaction_type == "reverse":
        type_text = "<b>ОБРАТНАЯ</b>"
        amount = f"{data.wallet_amount} {data.wallet_currency}"
    else:
        data.transaction_type


    return (
        f"🔄 <b>Тип сделки:</b> {type_text}\n"
        f"🏛 <b>Город:</b> {city_name}\n"
        f"🤝 <b>Чья сделка:</b> {partner_name}\n\n"
        f"👤 <b>Клиент:</b> {data.client_full_name}\n"
        f"💰 <b>Сумма:</b> {amount}\n\n"
        f"🏦 <b>Кошелек:</b> <code>{data.wallet_address}</code>\n"
        f"🌐 <b>Сеть:</b> {data.wallet_network}\n"
        f"💰 <b>Тип кошелька:</b> {wallet_owner_type_text}\n\n"
        f"🕒 <b>Дата и время:</b> {data.visit_time}\n\n"
        f"🔗 <a href='{data.form_url}'>Ссылка на форму</a>"
    )

async def get_external_data():
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(EXTERNAL_API_URL, timeout=10.0)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Ошибка при запросе к API: {e}")
            return None

# --- ЭНДПОИНТЫ ---

# 1. СОЗДАНИЕ ЗАЯВКИ (Тип 1)
@app.post("/new-transaction")
async def handle_transaction(data: TransactionData):
    print('data', data)
    api_values = await get_external_data()
    if not api_values:
        raise HTTPException(status_code=500, detail="Ошибка API")

    # Поиск города
    departments = api_values.get("DEPARTMENTS", [])
    city_name = "Неизвестный город"
    for d in departments:
        if str(d.get("ID")) == str(data.city_id):
            city_name = d.get("NAME")
            break

    # Поиск партнера
    partners_list = api_values.get("PARTNERS", [])
    partner_name = "Неизвестный партнер"
    if data.brand_id is not None:
        for p in partners_list:
            if str(p.get("ID")) == str(data.brand_id):
                partner_name = p.get("NAME", "Имя не указано")
                break

    group_id = CITIES_TO_GROUPS.get(city_name)
    if not group_id:
        raise HTTPException(status_code=404, detail=f"Группа для {city_name} не найдена")

    try:
        if data.transaction_type == "direct":
            type_text = "<b>ПРЯМАЯ</b>"
            amount = f"{data.cash_amount} {data.cash_currency}"
        else:
            data.transaction_type

        if data.transaction_type == "reverse":
            type_text = "<b>ОБРАТНАЯ</b>"
            amount = f"{data.wallet_amount} {data.wallet_currency}"
        else:
            data.transaction_type

        topic_title = f"{type_text} | {amount} | {data.visit_time}"
        new_topic: ForumTopic = await bot.create_forum_topic(chat_id=group_id, name=topic_title)
        
        await bot.send_message(
            chat_id=group_id,
            message_thread_id=new_topic.message_thread_id,
            text=format_main_message(data, city_name, partner_name),
            parse_mode="HTML",
            disable_web_page_preview=True
        )

        # Возвращаем ID группы и темы, чтобы другие скрипты могли их использовать
        return {
            "status": "success",
            "group_id": group_id,
            "topic_id": new_topic.message_thread_id,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 2. РАСЧЕТ ПО СДЕЛКЕ (Тип 2)
@app.post("/transaction-calculation")
async def handle_calculation(data: CalculationData):
    try:
        transaction_type = "<b>ПРЯМАЯ</b>" if data.transaction_type == "direct" else \
                    "<b>ОБРАТНАЯ</b>" if data.transaction_type == "reverse" else data.transaction_type

        calculation_type = "<b>ПРЯМОЙ</b>" if data.calculation_type == "direct" else \
                    "<b>ОБРАТНЫЙ</b>" if data.calculation_type == "reverse" else data.calculation_type

        message_text = (
            f"📊 <b>РАСЧЕТ СДЕЛКИ</b>\n\n"
            f"🔄 <b>Тип сделки:</b> {transaction_type}\n"
            f"📐 <b>Тип просчета:</b> {calculation_type}\n"
            f"📈 <b>Курс оператора:</b> {data.operator_rate}\n"
            f"📊 <b>Общий процент:</b> {data.total_percentage}\n"
            f"👤 <b>Курс для клиента:</b> {data.client_rate}\n"
            f"💸 <b>Комиссия за сделку:</b> {data.fee}\n\n"
            f"📝 <b>Формула:</b>\n<code>{data.formula}</code>\n\n"
            f"✅ <b>Итог к переводу:</b> <b>{data.total_to_transfer}</b>\n"
            f"🧪 <b>Тест:</b> {data.test_info}"
        )
        
        await bot.send_message(
            chat_id=data.chat_id,
            message_thread_id=data.message_thread_id,
            text=message_text,
            parse_mode="HTML"
        )
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 3. ИЗМЕНЕНИЕ СТАТУСА (Тип 3)
@app.post("/transaction-message")
async def handle_status_update(data: StatusUpdateData):
    try:
        message_text = (
            f"📝 {data.text}\n"
        )
        
        await bot.send_message(
            chat_id=data.chat_id,
            message_thread_id=data.message_thread_id,
            text=message_text,
            parse_mode="HTML"
        )
        return {"status": "success"}
    except Exception as e:
        print(f"Ошибка отправки статуса: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=4000)