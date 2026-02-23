import logging
import httpx
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from typing import Any
from db.session import db
from models.schemas import TransactionData, CalculationData, StatusUpdateData
from services.bot_service import BotService, bot
from core.constants import STATUS_MAP
from aiogram.types import BufferedInputFile
from models.schemas import TransactionData, CalculationData, StatusUpdateData, ProfitabilityData, DocumentData

logging.basicConfig(level=logging.INFO)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    yield
    await db.disconnect()
    await bot.session.close()

app = FastAPI(title="CryptoOps API", lifespan=lifespan)

@app.post("/transaction/create")
async def create_tx(data: TransactionData):
    result = await BotService.create_transaction_topic(data)
    if not result: raise HTTPException(status_code=404, detail="City not found")
    return {"status": "success", **result}

@app.post("/transaction/status")
async def update_status(data: StatusUpdateData):
    # Берем текст из STATUS_MAP или используем переданный текст
    msg = STATUS_MAP.get(data.text, data.text)
    op_tag = "Система"

    if data.text == "calc_requested":
        op_tag = await BotService.assign_operator_and_notify(data)
        msg = f"📩 <b>Запросили расчет</b>\n\n👨‍💻 <b>Оператор:</b> {op_tag}"
        if data.link:
            msg += f"\n🔗 <a href='{data.link}'>Ссылка на расчет</a>"

    await bot.send_message(
        chat_id=data.chat_id, 
        message_thread_id=data.message_thread_id, 
        text=f"📢 {msg}", 
        parse_mode="HTML"
    )
    return {"status": "success", "operator": op_tag}

@app.post("/transaction/calculation")
async def send_calc(data: CalculationData):
    """Текст расчета полностью из исходника"""
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
    await bot.send_message(data.chat_id, message_thread_id=data.message_thread_id, text=message_text, parse_mode="HTML")
    return {"status": "success"}

@app.post("/transaction/document")
async def upload_doc(data: DocumentData):
    """Скачивание файла по ссылке и отправка в Telegram"""
    async with httpx.AsyncClient() as client:
        try:
            # Скачиваем файл (ставим таймаут побольше для тяжелых файлов)
            resp = await client.get(data.file_url, timeout=20.0)
            
            if resp.status_code != 200:
                logging.error(f"Failed to download file: {resp.status_code}")
                raise HTTPException(status_code=400, detail="Could not download file from provided URL")

            # Определяем имя файла из URL или ставим дефолтное
            file_name = data.file_url.split("/")[-1] or "document.doc"
            if "." not in file_name:
                file_name += ".doc"

            # Формируем файл для aiogram
            input_file = BufferedInputFile(resp.content, filename=file_name)
            
            await bot.send_document(
                chat_id=data.chat_id,
                message_thread_id=data.message_thread_id,
                document=input_file,
                caption="📝 <b>Распечатай ДКП и дай на подпись клиенту.</b>",
                parse_mode="HTML"
            )
            
            return {"status": "success", "file_sent": file_name}
            
        except Exception as e:
            logging.error(f"Document upload error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/transaction/unprofitable")
async def notify_unprofitable(data: ProfitabilityData):
    """Уведомление о волатильности курса"""
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
        logging.error(f"Unprofitable notify error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=4000)