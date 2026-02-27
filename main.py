import logging
import httpx
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from typing import Any
from db.session import db
from models.schemas import TransactionData, CalculationData, StatusUpdateData
from aiogram.types import BufferedInputFile
from models.schemas import TransactionData, CalculationData, StatusUpdateData, ProfitabilityData, DocumentData
from fastapi.responses import RedirectResponse
from datetime import datetime
from aiogram import Dispatcher, types, F
from services.bot_service import BotService, bot, TaskCB
from db.repository import (
    update_task_status, 
    set_expected_amount, 
    get_task_by_id, 
    log_task_click,
    get_last_active_task,  
    get_oldest_pending_task,
    get_active_tasks_count,
    log_task_event
)
import asyncio
from core.constants import STATUS_MAP, OPERATORS_TO_GROUPS

logging.basicConfig(level=logging.INFO)

dp = Dispatcher()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # При старте
    await db.connect()
    
    # Запускаем polling бота в фоновом режиме, чтобы кнопки работали
    polling_task = asyncio.create_task(dp.start_polling(bot))
    logging.info("Aiogram Polling started")
    
    yield
    
    # При выключении
    polling_task.cancel()
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
    msg = STATUS_MAP.get(data.status, data.status)
    op_tag = "Система"

    if data.status == "calc_requested":
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
    amount = float(''.join(filter(lambda x: x.isdigit() or x == '.', str(data.total_to_transfer))))
    await set_expected_amount(data.chat_id, data.message_thread_id, amount)
    
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
    """Скачивание PDF по ссылке и отправка в Telegram"""
    async with httpx.AsyncClient() as client:
        try:
            # 1. Скачиваем файл
            resp = await client.get(data.file_url, timeout=30.0)
            
            if resp.status_code != 200:
                logging.error(f"Failed to download PDF: {resp.status_code}")
                raise HTTPException(status_code=400, detail="Ошибка при скачивании файла по ссылке")

            # 2. Логика определения имени файла
            # Берем имя из URL (удаляем параметры запроса, если они есть)
            original_name = data.file_url.split("/")[-1].split("?")[0]
            
            # Если имя пустое или не заканчивается на .pdf, принудительно ставим dkp.pdf
            if not original_name.lower().endswith(".pdf"):
                file_name = "dkp_document.pdf"
            else:
                file_name = original_name

            # 3. Подготовка файла для Telegram (BufferedInputFile работает в памяти)
            input_file = BufferedInputFile(resp.content, filename=file_name)
            
            # 4. Отправка документа
            await bot.send_document(
                chat_id=data.chat_id,
                message_thread_id=data.message_thread_id,
                document=input_file,
                caption="📄 <b>ДКП готов (PDF). Распечатай и дай на подпись клиенту.</b>",
                parse_mode="HTML"
            )
            
            logging.info(f"PDF sent successfully: {file_name} to chat {data.chat_id}")
            return {"status": "success", "file": file_name}
            
        except httpx.ReadTimeout:
            raise HTTPException(status_code=504, detail="Превышено время ожидания скачивания файла")
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

@app.get("/click/{task_id}")
async def track_op_click(task_id: int):
    """Эндпоинт для фиксации клика оператора"""
    click_time = datetime.now()
    
    # Фиксируем время в БД и получаем оригинальный URL
    original_form_url = await log_task_click(task_id, click_time)
    
    if original_form_url:
        logging.info(f"Operator clicked task {task_id} at {click_time}")
        # Мгновенно перенаправляем на форму
        return RedirectResponse(url=original_form_url)
    
    return {"status": "error", "message": "Task not found"}

# 1. Нажатие "Принять и перейти"
@dp.callback_query(TaskCB.filter(F.action == "accept"))
async def handle_accept(query: types.CallbackQuery, callback_data: TaskCB):
    task = await get_task_by_id(callback_data.id)
    await update_task_status(callback_data.id, "active")
    
    # ФИКСИРУЕМ ПРИНЯТИЕ
    await log_task_event(callback_data.id, 'accept')
    
    await query.message.edit_text(
        f"🟢 <b>Задача #{callback_data.id} в работе</b>\nПринята: {datetime.now().strftime('%H:%M:%S')}",
        reply_markup=BotService.get_task_keyboard(callback_data.id, "active", task['form_url']),
        parse_mode="HTML"
    )
    await query.answer("Успешно принято!")

# 2. Нажатие "Пауза"
@dp.callback_query(TaskCB.filter(F.action == "pause"))
async def handle_pause(query: types.CallbackQuery, callback_data: TaskCB):
    await update_task_status(callback_data.id, "paused")
    
    # ФИКСИРУЕМ ПАУЗУ
    await log_task_event(callback_data.id, 'pause')
    
    await query.message.edit_text(
        f"🟡 <b>Задача #{callback_data.id} на паузе</b>\nВы свободны для других задач.",
        reply_markup=BotService.get_task_keyboard(callback_data.id, "paused"),
        parse_mode="HTML"
    )
    await query.answer("Пауза активирована")

# 3. Нажатие "Продолжить"
@dp.callback_query(TaskCB.filter(F.action == "resume"))
async def handle_resume(query: types.CallbackQuery, callback_data: TaskCB):
    active_count = await get_active_tasks_count(query.from_user.id)
    if active_count > 0:
        await query.answer("❌ Сначала завершите текущую активную задачу!", show_alert=True)
        return

    task = await get_task_by_id(callback_data.id)
    await update_task_status(callback_data.id, "active")
    
    # ФИКСИРУЕМ ПРОДОЛЖЕНИЕ
    await log_task_event(callback_data.id, 'resume')
    
    await query.message.edit_text(
        f"🟢 <b>Задача #{callback_data.id} снова в работе</b>",
        reply_markup=BotService.get_task_keyboard(callback_data.id, "active", task['form_url']),
        parse_mode="HTML"
    )
    await query.answer("Продолжаем работу")

# 4. Нажатие "Завершить"
@dp.callback_query(TaskCB.filter(F.action == "complete"))
async def handle_complete_request(query: types.CallbackQuery, callback_data: TaskCB):
    # Сообщение отправляется в тот же топик оператора
    await query.message.answer(
        f"🏁 Чтобы завершить задачу #{callback_data.id}, отправьте ссылку на транзакцию в этот топик.",
        reply_markup=types.ForceReply(selective=True)
    )
    await query.answer()

# 5. Обработка входящей ссылки и сверка суммы
@dp.message(F.text.contains("hash") | F.text.contains("tx") | F.text.contains("tronscan"))
async def verify_transaction(message: types.Message):
    # ТУТ ВАШ ПАРСЕР (имитация)
    found_amount = 100.5 
    
    task = await get_last_active_task(message.from_user.id) 
    
    if task and float(found_amount) == float(task['expected_amount']):
        # 1. Завершаем текущую задачу
        await update_task_status(task['id'], "completed")
        await log_task_event(task['id'], 'complete')
        await message.answer("✅ Сумма совпала! Задача завершена.")
        
        # 2. ПРОВЕРКА ОЧЕРЕДИ: Есть ли ожидающие задачи?
        pending_task = await get_oldest_pending_task()
        if pending_task:
            # Назначаем эту задачу освободившемуся оператору
            await update_task_status(pending_task['id'], "pending") # Статус остается pending до нажатия "Принять"
            
            # В репозитории нужно добавить функцию смены оператора для задачи в очереди
            # Или просто отправить сообщение оператору
            op_group = OPERATORS_TO_GROUPS.get(str(message.from_user.id))
            await bot.send_message(
                chat_id=op_group,
                text=f"📥 <b>У вас новая задача из очереди!</b>\nТопик: {pending_task['message_thread_id']}",
                reply_markup=BotService.get_task_keyboard(pending_task['id'], "pending")
            )
    else:
        await message.answer("❌ Ошибка сверки суммы.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=4000)