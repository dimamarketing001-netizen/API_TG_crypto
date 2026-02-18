import uvicorn
import httpx
import sys
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from aiogram import Bot
from aiogram.types import ForumTopic
from typing import Optional, Union, Any
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

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

# --- МОДЕЛИ ДАННЫХ ---

class TransactionData(BaseModel):
    city_id: Union[int, str]
    brand_id: Optional[Union[int, str]] = None
    creator_id: Optional[Union[int, str]] = None
    visit_time: Optional[str] = ""
    transaction_type: Optional[str] = "direct"
    client_full_name: Optional[str] = "Не указано"
    cash_amount: Any = 0
    cash_currency: Optional[str] = ""
    wallet_address: Optional[str] = ""
    wallet_network: Optional[str] = ""
    wallet_amount: Any = 0
    wallet_currency: Optional[str] = ""
    wallet_owner_type: Optional[str] = ""
    form_url: Optional[str] = ""

    class Config:
        extra = "allow"

# --- ВОТ ЭТИ МОДЕЛИ НУЖНО БЫЛО ВЕРНУТЬ ---

class CalculationData(BaseModel):
    chat_id: Union[int, str]
    message_thread_id: Union[int, str]
    transaction_type: str        
    calculation_type: str        
    operator_rate: Any 
    total_percentage: Any 
    client_rate: Any
    fee: Any                    
    formula: Optional[str] = ""                 
    total_to_transfer: Any       
    test_info: Optional[str] = "Без теста"

    class Config:
        extra = "allow"

class StatusUpdateData(BaseModel):
    chat_id: Union[int, str]
    message_thread_id: Union[int, str]
    text: str
    operator_name: Optional[str] = "Система"

    class Config:
        extra = "allow"

# ---------------------------------------

app = FastAPI()
bot = Bot(token=BOT_TOKEN)

# --- ОБРАБОТЧИК ОШИБОК ВАЛИДАЦИИ ---
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Кодируем в ascii, чтобы не падать на кириллице в консоли
    error_str = str(exc.errors()).encode('ascii', 'replace').decode()
    print(f"Validation Error detail: {error_str}")
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_transaction_info(data: TransactionData):
    if data.transaction_type == "direct":
        return "ПРЯМАЯ", f"{data.cash_amount} {data.cash_currency}"
    elif data.transaction_type == "reverse":
        return "ОБРАТНАЯ", f"{data.wallet_amount} {data.wallet_currency}"
    return str(data.transaction_type).upper(), "0"

def format_main_message(data: TransactionData, city_name: str, partner_name: str) -> str:
    wallet_owner_type_text = "Клиентский" if data.wallet_owner_type == "client" else \
                             "Партнёрский" if data.wallet_owner_type == "partner" else str(data.wallet_owner_type)
    
    type_text, amount = get_transaction_info(data)

    return (
        f"🔄 <b>Тип сделки:</b> <b>{type_text}</b>\n"
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

# --- ЭНДПОИНТЫ ---

@app.post("/new-transaction")
async def handle_transaction(data: TransactionData):
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(EXTERNAL_API_URL, timeout=5.0)
            api_values = resp.json()
        except Exception:
            api_values = {}

    departments = api_values.get("DEPARTMENTS", [])
    city_name = "Неизвестный город"
    for d in departments:
        if str(d.get("ID")) == str(data.city_id):
            city_name = d.get("NAME")
            break

    partners_list = api_values.get("PARTNERS", [])
    partner_name = "Неизвестный партнер"
    for p in partners_list:
        if str(p.get("ID")) == str(data.brand_id):
            partner_name = p.get("NAME")
            break

    group_id = CITIES_TO_GROUPS.get(city_name)
    if not group_id or group_id == 0:
        raise HTTPException(status_code=404, detail=f"Group not found for city: {city_name}")

    try:
        type_text, amount = get_transaction_info(data)
        topic_title = f"{type_text} | {amount} | {data.visit_time}"
        new_topic = await bot.create_forum_topic(chat_id=group_id, name=topic_title)
        
        await bot.send_message(
            chat_id=group_id,
            message_thread_id=new_topic.message_thread_id,
            text=format_main_message(data, city_name, partner_name),
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        
        return {
            "status": "success",
            "group_id": group_id,
            "topic_id": new_topic.message_thread_id,
        }
    except Exception as e:
        print(f"Bot error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/transaction-calculation")
async def handle_calculation(data: CalculationData):
    try:
        transaction_type_text = "<b>ПРЯМАЯ</b>" if data.transaction_type == "direct" else \
                                "<b>ОБРАТНАЯ</b>" if data.transaction_type == "reverse" else data.transaction_type

        calculation_type_text = "<b>ПРЯМОЙ</b>" if data.calculation_type == "direct" else \
                                "<b>ОБРАТНЫЙ</b>" if data.calculation_type == "reverse" else data.calculation_type

        message_text = (
            f"📊 <b>РАСЧЕТ СДЕЛКИ</b>\n\n"
            f"🔄 <b>Тип сделки:</b> {transaction_type_text}\n"
            f"📐 <b>Тип просчета:</b> {calculation_type_text}\n"
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
        print(f"Calculation Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/transaction-message")
async def handle_status_update(data: StatusUpdateData):
    try:
        await bot.send_message(
            chat_id=data.chat_id,
            message_thread_id=data.message_thread_id,
            text=f"📝 {data.text}",
            parse_mode="HTML"
        )
        return {"status": "success"}
    except Exception as e:
        print(f"Status update Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=4000)