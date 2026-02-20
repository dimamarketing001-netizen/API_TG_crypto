import uvicorn
import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from aiogram import Bot
from aiogram.types import BufferedInputFile
from typing import Optional, Union, Any
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

STATUS_MAP = {
    "calc_new": "🆕 Новый расчет",
    "calc_requested": "📩 Запросили расчет",
    "calc_issued": "📤 Выдали расчет",
    "calc_accepted": "🤝 Клиент согласился с расчетом",
    "deal_processing": "⏳ Сделка в процессе",
    "deal_data_verification": "🔍 Идет проверка данных",
    "deal_data_verified": "✅ Данные проверены",
    "deal_dkp_uploading": "📑 Загрузка подписанного ДКП",
    "deal_verified": "🆗 Проверено",
    "deal_dkp_verification": "🧐 Проверка подписанного ДКП",
    "deal_signatures_verified": "🖋 Наличие подписей в ДКП проверено",
    "deal_success": "🎉 Успех",
    "deal_failed": "❌ Провал"
}

app = FastAPI()
bot = Bot(token=BOT_TOKEN)

# --- МОДЕЛИ ДАННЫХ ---

class TransactionCreate(BaseModel):
    city_id: Union[int, str]
    brand_id: Optional[Union[int, str]] = None
    visit_time: Optional[str] = ""
    transaction_type: Optional[str] = "direct"
    client_full_name: Optional[str] = "Не указано"
    cash_amount: Any = 0
    cash_currency: Optional[str] = ""
    wallet_address: Optional[str] = ""
    wallet_network: Optional[str] = ""
    wallet_owner_type: Optional[str] = ""
    form_url: Optional[str] = ""
    individual_conditions: int = 0 

class StatusUpdate(BaseModel):
    chat_id: Union[int, str]
    message_thread_id: Union[int, str]
    status: str 
    link: Optional[str] = None 

class CalculationReport(BaseModel):
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

class DocumentUpload(BaseModel):
    chat_id: Union[int, str]
    message_thread_id: Union[int, str]
    file_url: str

class ProfitabilityIssue(BaseModel):
    chat_id: Union[int, str]
    message_thread_id: Union[int, str]
    is_unprofitable: bool = True

# --- ЭНДПОИНТЫ ---

@app.post("/transaction/create")
async def create_transaction(data: TransactionCreate):
    """1. Создание новой транзакции и топика"""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(EXTERNAL_API_URL, timeout=5.0)
            api_values = resp.json()
        except:
            api_values = {}

    city_name = next((d["NAME"] for d in api_values.get("DEPARTMENTS", []) if str(d["ID"]) == str(data.city_id)), "Неизвестный город")
    partner_name = next((p["NAME"] for p in api_values.get("PARTNERS", []) if str(p["ID"]) == str(data.brand_id)), "Неизвестный партнер")

    group_id = CITIES_TO_GROUPS.get(city_name, 0)
    if not group_id:
        raise HTTPException(status_code=404, detail=f"Group not found for {city_name}")

    ind_text = "Да, согласовано с @didididi001" if data.individual_conditions == 1 else "Нет"
    type_text = "ПРЯМАЯ" if data.transaction_type == "direct" else "ОБРАТНАЯ"
    amount = f"{data.cash_amount} {data.cash_currency}" if data.transaction_type == "direct" else "Сумма в валюте"

    try:
        topic = await bot.create_forum_topic(chat_id=group_id, name=f"{type_text} | {amount}")
        
        msg = (
            f"🔄 <b>Тип сделки:</b> {type_text}\n"
            f"🏛 <b>Город:</b> {city_name}\n"
            f"🤝 <b>Партнер:</b> {partner_name}\n\n"
            f"👤 <b>Клиент:</b> {data.client_full_name}\n"
            f"💰 <b>Сумма:</b> {amount}\n"
            f"🏦 <b>Кошелек:</b> <code>{data.wallet_address}</code> ({data.wallet_network})\n\n"
            f"💎 <b>Индивидуальные условия:</b> {ind_text}\n"
            f"🕒 <b>Время:</b> {data.visit_time}\n"
            f"🔗 <a href='{data.form_url}'>Открыть форму</a>"
        )
        
        await bot.send_message(group_id, message_thread_id=topic.message_thread_id, text=msg, parse_mode="HTML")
        return {"status": "success", "chat_id": group_id, "topic_id": topic.message_thread_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/transaction/status")
async def update_status(data: StatusUpdate):
    """2. Отправка статуса по ключу"""
    message_text = STATUS_MAP.get(data.status)
    if not message_text:
        raise HTTPException(status_code=400, detail="Invalid status key")

    if data.status == "calc_requested" and data.link:
        message_text += f"\n🔗 <b>Ссылка:</b> {data.link}"

    try:
        await bot.send_message(
            chat_id=data.chat_id,
            message_thread_id=data.message_thread_id,
            text=f"📢 {message_text}",
            parse_mode="HTML"
        )
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/transaction/calculation")
async def send_calculation(data: CalculationReport):
    """3. Отправка подробного расчета"""
    try:
        t_type = "<b>ПРЯМАЯ</b>" if data.transaction_type == "direct" else "<b>ОБРАТНАЯ</b>"
        c_type = "<b>ПРЯМОЙ</b>" if data.calculation_type == "direct" else "<b>ОБРАТНЫЙ</b>"

        message_text = (
            f"📊 <b>РАСЧЕТ СДЕЛКИ</b>\n\n"
            f"🔄 <b>Тип сделки:</b> {t_type}\n"
            f"📐 <b>Тип просчета:</b> {c_type}\n"
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

@app.post("/transaction/document")
async def upload_document(data: DocumentUpload):
    """4. Скачивание и отправка файла ДКП"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(data.file_url, timeout=15.0)
            if response.status_code != 200:
                return JSONResponse(status_code=400, content={"status": "error", "message": "Download failed"})
            
            file_name = data.file_url.split("/")[-1] or "document.doc"
            if not file_name.lower().endswith(('.doc', '.docx')):
                file_name += ".doc"

            input_file = BufferedInputFile(response.content, filename=file_name)
            
            await bot.send_document(
                chat_id=data.chat_id,
                message_thread_id=data.message_thread_id,
                document=input_file,
                caption="📝 <b>Распечатай ДКП и дай на подпись клиенту.</b>",
                parse_mode="HTML"
            )
            return {"status": "success"}
        except Exception as e:
            return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})

@app.post("/transaction/unprofitable")
async def notify_unprofitable(data: ProfitabilityIssue):
    """5. Уведомление о нерентабельности"""
    if not data.is_unprofitable:
        return {"status": "ignored"}
    try:
        await bot.send_message(
            chat_id=data.chat_id,
            message_thread_id=data.message_thread_id,
            text="⚠️ <b>Волатильность курса, нужно поменять расчет.</b>",
            parse_mode="HTML"
        )
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=4000)