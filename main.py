import logging
import httpx
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from db.session import db
from models.schemas import TransactionCreate, StatusUpdate, CalculationReport, DocumentUpload
from services.bot_service import BotService, bot
from core.constants import STATUS_MAP
from aiogram.types import BufferedInputFile

logging.basicConfig(level=logging.INFO)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    yield
    await db.disconnect()
    await bot.session.close()

app = FastAPI(title="CryptoOps API", lifespan=lifespan)

@app.post("/transaction/create")
async def create_tx(data: TransactionCreate):
    result = await BotService.create_transaction_topic(data)
    if not result: raise HTTPException(status_code=404, detail="City not found")
    return result

@app.post("/transaction/status")
async def update_status(data: StatusUpdate):
    msg = STATUS_MAP.get(data.status, "Обновление")
    op_tag = None

    if data.status == "calc_requested":
        op_tag = await BotService.assign_operator_and_notify(data)
        msg += f"\n👨‍💻 Назначен: {op_tag}"
        if data.link: msg += f"\n🔗 {data.link}"

    await bot.send_message(data.chat_id, message_thread_id=data.message_thread_id, text=f"📢 {msg}", parse_mode="HTML")
    return {"status": "success", "operator": op_tag}

@app.post("/transaction/calculation")
async def send_calc(data: CalculationReport):
    msg = f"📊 <b>РАСЧЕТ СДЕЛКИ</b>\n\n✅ ИТОГ: <b>{data.total_to_transfer}</b>"
    await bot.send_message(data.chat_id, message_thread_id=data.message_thread_id, text=msg, parse_mode="HTML")
    return {"status": "success"}

@app.post("/transaction/document")
async def upload_doc(data: DocumentUpload):
    async with httpx.AsyncClient() as client:
        resp = await client.get(data.file_url)
        if resp.status_code == 200:
            file = BufferedInputFile(resp.content, filename="dkp.doc")
            await bot.send_document(data.chat_id, message_thread_id=data.message_thread_id, document=file, caption="📝 ДКП для подписи")
            return {"status": "success"}
    return {"status": "error"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=4000)