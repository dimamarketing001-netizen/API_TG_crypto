import logging
import httpx
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from typing import Any
from db.session import db
from models.schemas import TransactionData, CalculationData, StatusUpdateData
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from models.schemas import TransactionData, CalculationData, StatusUpdateData, ProfitabilityData, DocumentData
from fastapi.responses import RedirectResponse
from datetime import datetime
from aiogram import Dispatcher, types, F
from services.bot_service import BotService, bot, TaskCB, DealCB
from db.repository import (
    update_task_status, 
    set_expected_amount, 
    get_deal_by_id,
    get_task_by_id, 
    log_task_click,
    get_last_active_task,  
    get_oldest_pending_task,
    get_active_tasks_count,
    log_task_event,
    assign_task_to_operator,
    find_or_create_security_topic,
    create_security_task
)
import asyncio
from core.constants import STATUS_MAP, OPERATORS_TO_GROUPS, SECURITY_TO_GROUPS
from services.crypto_monitor import CryptoMonitor
from services.operator_logic import security_balancer

monitor = CryptoMonitor()

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
    logging.info(f"Получен запрос на обновление статуса: {data.model_dump_json(indent=2)}")
    # Берем текст из STATUS_MAP или используем переданный текст
    msg = STATUS_MAP.get(data.status, data.status)
    op_tag = "Система"

    if data.status == "calc_requested":
        op_tag = await BotService.assign_operator_and_notify(data)
        msg = f"📩 <b>Запросили расчет</b>\n\n👨‍💻 <b>Оператор:</b> {op_tag}"

    await bot.send_message(
        chat_id=data.chat_id, 
        message_thread_id=data.message_thread_id, 
        text=f"📢 {msg}", 
        parse_mode="HTML"
    )
    return {"status": "success", "operator": op_tag}

@app.post("/transaction/calculation")
async def send_calc(data: CalculationData):
    logging.info(f"Получен запрос на расчет: {data.model_dump_json(indent=2)}")
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
    logging.info(f"Получен запрос на загрузку документа: {data.model_dump_json(indent=2)}")
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

# --- НОВЫЕ ОБРАБОТЧИКИ ДЛЯ ЗАЯВОК В ГОРОДСКИХ ЧАТАХ ---

@dp.callback_query(DealCB.filter(F.action == "accept"))
async def handle_deal_accept(query: types.CallbackQuery, callback_data: DealCB):
    """
    Обрабатывает нажатие 'Принять' на основной заявке.
    Эта логика аналогична старому эндпоинту /transaction/status.
    """
    deal = await get_deal_by_id(callback_data.id)
    if not deal:
        await query.answer("Заявка не найдена!", show_alert=True)
        return

    # Создаем объект, похожий на `StatusUpdateData` для переиспользования логики
    fake_data = type('obj', (object,), {
        'chat_id': deal['chat_id'], 
        'message_thread_id': deal['topic_id'],
        'link': deal.get('form_url', '#') # Предполагаем, что form_url есть в CryptoDeals
    })

    operator_tag = await BotService.assign_operator_and_notify(fake_data)
    msg = f"📩 <b>Запросили расчет</b>\n\n👨‍💻 <b>Оператор:</b> {operator_tag}"

    await bot.send_message(
        chat_id=deal['chat_id'], 
        message_thread_id=deal['message_thread_id'], 
        text=f"📢 {msg}", 
        parse_mode="HTML"
    )
    # Убираем кнопки с исходного сообщения
    await query.message.edit_reply_markup(reply_markup=None)
    await query.answer(f"Заявка принята. Назначен оператор: {operator_tag}")


@dp.callback_query(DealCB.filter(F.action.in_({"transfer", "reject"})))
async def handle_deal_escalation(query: types.CallbackQuery, callback_data: DealCB):
    """Обрабатывает 'Перенести' и 'Отклонить' на основной заявке."""
    action_text = "перенесена" if callback_data.action == "transfer" else "отклонена"
    action_verb = "Перенос" if callback_data.action == "transfer" else "Отклонение"
    
    deal = await get_deal_by_id(callback_data.id)
    if not deal:
        await query.answer("Заявка не найдена!", show_alert=True)
        return

    # 1. Находим свободного сотрудника СБ
    security_officer = await security_balancer.get_available_security_officer()
    if not security_officer:
        await query.answer("Все сотрудники СБ заняты, попробуйте позже.", show_alert=True)
        return

    # 2. Находим или создаем тему для клиента в чате СБ
    security_group_id = SECURITY_TO_GROUPS.get(str(security_officer['personal_telegram_id']))
    if not security_group_id:
        await query.answer("Не настроена группа для сотрудника СБ.", show_alert=True)
        return

    # В таблице CryptoDeals должен быть client_id, связанный с клиентом.
    # Если его нет, можно использовать client_full_name или другой уникальный идентификатор.
    client_identifier = deal.get('client_id') or deal.get('client_full_name')
    if not client_identifier:
        await query.answer("Не удалось идентифицировать клиента для создания темы СБ.", show_alert=True)
        return

    topic_id = await find_or_create_security_topic(client_identifier, security_group_id, security_officer['id'])

    # 3. Создаем задачу для СБ (связываем с deal_id)
    security_task_id = await create_security_task(deal['deals_id'], security_officer['id'], topic_id, is_deal_task=True)

    # 4. Отправляем уведомление в тему СБ
    sb_message = (f"🚨 <b>Новая задача от менеджера #{security_task_id}!</b>\n\n"
                  f"<b>Действие:</b> {action_verb}\n"
                  f"<b>Менеджер:</b> @{query.from_user.username}\n"
                  f"<b>Клиент:</b> {deal.get('client_full_name', 'N/A')}")
    await bot.send_message(security_group_id, message_thread_id=topic_id, text=sb_message, parse_mode="HTML")

    await query.message.edit_text(f"{query.message.text}\n\n---\n"
                                  f"❗️ Заявка была <b>{action_text.upper()}</b> менеджером @{query.from_user.username}.\n"
                                  f"Задача передана в Службу Безопасности.", parse_mode="HTML")
    await query.answer(f"Заявка {action_text} и передана в СБ")

# Новые обработчики для кнопок "Перенести" и "Отклонить"
@dp.callback_query(TaskCB.filter(F.action.in_({"transfer", "reject"})))
async def handle_escalation(query: types.CallbackQuery, callback_data: TaskCB):
    action_text = "перенесена" if callback_data.action == "transfer" else "отклонена"
    action_verb = "Перенос" if callback_data.action == "transfer" else "Отклонение"

    # 1. Находим свободного сотрудника СБ
    security_officer = await security_balancer.get_available_security_officer()
    if not security_officer:
        await query.answer("Все сотрудники СБ заняты, попробуйте позже.", show_alert=True)
        return

    # 2. Получаем информацию о задаче
    task = await get_task_by_id(callback_data.id)
    if not task:
        await query.answer("Задача не найдена.", show_alert=True)
        return

    # 3. Находим или создаем тему для клиента в чате СБ
    security_group_id = SECURITY_TO_GROUPS.get(str(security_officer['personal_telegram_id']))
    if not security_group_id:
        await query.answer("Не настроена группа для сотрудника СБ.", show_alert=True)
        return

    # Предполагаем, что client_id есть в задаче. Если нет, нужна доп. логика.
    client_id = task.get('client_id', 0) 
    topic_id = await find_or_create_security_topic(client_id, security_group_id, security_officer['id'])

    # 4. Создаем задачу для СБ (связываем с task_id)
    security_task_id = await create_security_task(task['id'], security_officer['id'], topic_id)

    # 5. Отправляем уведомление в тему СБ
    await bot.send_message(security_group_id, message_thread_id=topic_id, text=f"🚨 Новая задача от оператора #{security_task_id}!\n<b>Действие:</b> {action_verb}\n<b>Оператор:</b> @{query.from_user.username}", parse_mode="HTML")

    await query.message.edit_text(f"Задача #{callback_data.id} {action_text} в СБ. Назначен: @{security_officer['personal_telegram_username']}")
    await query.answer(f"Задача передана в СБ")

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
@dp.message(F.text.regexp(r'[a-zA-Z0-9+/=]{32,}'))
async def verify_transaction(message: types.Message):
    tx_hash = message.text.strip()
    task = await get_last_active_task(message.from_user.id)
    
    if not task:
        await message.answer("❌ У вас нет активных задач.")
        return

    # 1. Запускаем поиск (используем search_tx, который возвращает словарь)
    loop = asyncio.get_event_loop()
    # Передаем кошелек для проверки безопасности
    tx_data = await loop.run_in_executor(None, monitor.search_tx, tx_hash, task.get('wallet_address'))

    if not tx_data:
        await message.answer("❌ Транзакция не найдена в сети или адрес получателя не совпадает.")
        return

    # 2. Формируем красивый отчет
    expected = float(task.get('expected_amount', 0))
    found = tx_data['amount']
    
    reply_text = (
        f"✅ <b>Транзакция найдена!</b>\n\n"
        f"🪙 <b>Крипта:</b> {tx_data['symbol']}\n"
        f"💰 <b>Сумма:</b> {found} (Ожидалось: {expected})\n"
        f"👤 <b>От:</b> <code>{tx_data['from_addr']}</code>\n"
        f"🏦 <b>Куда:</b> <code>{tx_data['to_addr']}</code>\n"
        f"🕒 <b>Дата:</b> {tx_data['dt']}\n"
    )

    # 3. Сверка и завершение
    if abs(found - expected) < 0.01:
        await update_task_status(task['id'], "completed")
        await log_task_event(task['id'], 'complete')
        await message.answer(reply_text + "\n✅ <b>Сумма совпала! Задача завершена.</b>", parse_mode="HTML")
        
        # Логика очереди
        pending_task = await get_oldest_pending_task()
        if pending_task:
            op_id = str(message.from_user.id)
            op_group = OPERATORS_TO_GROUPS.get(op_id)
            
            if op_group:
                # 1. Привязываем задачу к оператору
                await assign_task_to_operator(pending_task['id'], op_id)
                # 2. Вызываем тот же самый метод создания топика
                await BotService.create_operator_topic(
                    pending_task['id'], 
                    op_group, 
                    pending_task['message_thread_id']
                )
    else:
        await message.answer(reply_text + "\n❌ <b>Сумма не совпала!</b>", parse_mode="HTML")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=4000)