# ClientToBarber.py
import asyncio
import time
import logging
from datetime import date, datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
import database
from keyboards import barber_kb

from calendar import monthrange

from dotenv import load_dotenv
import services
from loader import bot_barber as bot, dp_barber as dp, bot_client
load_dotenv()

# ------------------------
# Logging
# ------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------------
# Time / slot utilities (reused/adapted)
# ------------------------
def str_to_time(t: str) -> datetime:
    """Parse 'HH:MM' into datetime (date component is arbitrary/ignored)."""
    return datetime.strptime(t, "%H:%M")

def time_to_str(dt: datetime) -> str:
    return dt.strftime("%H:%M")

# ------------------------
# UI helpers
# ------------------------
def format_booking_short(bk_row):
    # bk_row: (id, usr_id, service_id, date, start_time, end_time, service_name, condition, price)
    try:
        idb, usr_id, service_id, date_d, start_t, end_t, service_name, condition, price = bk_row
    except Exception:
        return "Неизвестная бронь"
    status = "Оплачено" if condition == 'paid' else ("Возвращено" if condition == 'refunded' else "Забронировано")
    return f"{start_t} — {end_t} | {service_name} | {status}"


# ------------------------
# Handlers: /start
# ------------------------
@dp.message(F.text == "/start")
async def cmd_start(message: Message):
    user = message.from_user
    barber = await services.get_barber_by_telegram_user(user.id, user.username)
    if not barber:
        usr_id = user.id
        usr_name = user.username
        await message.answer(f"❌ Доступ запрещён. Вы не зарегистрированы как барбер в системе.\n Ваш айди: <b><code>{usr_id}</code></b> \nВаш юзернейм: <b><code>{usr_name}</code></b>", parse_mode="HTML")
        logger.info(f"Unauthorized access attempt: {usr_id} ({user.username})")
        return
    
    row = await database.fetch_one("SELECT reminders FROM barbers WHERE telegram_id = ?", (user.id,))
    status = row[0] if row else 1
    await message.answer("Главное меню:", reply_markup=barber_kb.main_menu(status))

# ------------------------
# Callback router (modularized)
# ------------------------
@dp.callback_query(F.data.startswith("schedule_day_"))
async def main_menu_handler(call: CallbackQuery):
    barber = await services.get_barber_by_telegram_user(call.from_user.id, call.from_user.username)
    if not barber:
        await call.answer("❌ Доступ запрещён.", show_alert=True)
        return
    barber_id, barber_name = barber

    # schedule_day_{date}
    await handle_schedule_day(call, barber_id, barber_name)
    return

@dp.callback_query(F.data.startswith("prev_locked"))
async def main_menu_handler(call: CallbackQuery):
    await call.answer("Нет доступа к прошлым дням.", show_alert=True)
    return


@dp.callback_query(F.data == "main_menu")
async def back_to_main_menu(call: CallbackQuery):
    # Получаем актуальный статус из базы перед показом меню
    row = await database.fetch_one("SELECT reminders FROM barbers WHERE telegram_id = ?", (call.from_user.id,))
    status = row[0] if row else 1
    
    await call.message.edit_text("Главное меню:", reply_markup=barber_kb.main_menu(status))

@dp.callback_query(F.data.startswith("booking_"))
async def main_menu_handler(call: CallbackQuery):
    barber = await services.get_barber_by_telegram_user(call.from_user.id, call.from_user.username)
    if not barber:
        await call.answer("❌ Доступ запрещён.", show_alert=True)
        return
    barber_id, barber_name = barber
    await handle_booking_details(call, barber_id, barber_name)
    return

@dp.callback_query(F.data.startswith("cancel_booking_") or F.data.startswith("cancel_confirm_"))
async def main_menu_handler(call: CallbackQuery):
    barber = await services.get_barber_by_telegram_user(call.from_user.id, call.from_user.username)
    if not barber:
        await call.answer("❌ Доступ запрещён.", show_alert=True)
        return
    barber_id, barber_name = barber
    await handle_cancel_flow(call, barber_id, barber_name)
    return

@dp.callback_query(F.data.startswith("refund_booking_"))
async def main_menu_handler(call: CallbackQuery):
    barber = await services.get_barber_by_telegram_user(call.from_user.id, call.from_user.username)
    if not barber:
        await call.answer("❌ Доступ запрещён.", show_alert=True)
        return
    barber_id, barber_name = barber
    await handle_refund(call, barber_id, barber_name)
    return

@dp.callback_query(F.data.startswith(("offdays_view", "offday_toggle_", "offdays_clear_all")))
async def main_menu_handler(call: CallbackQuery):
    barber = await services.get_barber_by_telegram_user(call.from_user.id, call.from_user.username)
    if not barber:
        await call.answer("❌ Доступ запрещён.", show_alert=True)
        return
    barber_id, barber_name = barber
    await handle_offdays(call, barber_id, barber_name)
    return

@dp.callback_query(F.data == "toggle_reminders")
async def toggle_reminders(call: CallbackQuery):
    # 1. Получаем данные и сразу проверяем (walrus operator :=)
    if not (row := await database.fetch_one("SELECT id, reminders FROM barbers WHERE telegram_id = ?", (call.from_user.id,))):
        return await call.answer("❌ Доступ запрещён", show_alert=True)

    # 2. Переключаем статус (было 1 станет 0, было 0 станет 1) и обновляем БД
    new_status = 1 - row[1]
    await database.execute("UPDATE barbers SET reminders = ? WHERE id = ?", (new_status, row[0]))

    # 3. Обновляем кнопку (в одну строку, игнорируя ошибки, если не изменилось)
    try: await call.message.edit_reply_markup(reply_markup=barber_kb.main_menu(new_status))
    except: pass

    # 4. Отвечаем
    await call.answer(f"Напоминания {'Включены ✅' if new_status else 'Выключены 🔕'}")

# ------------------------
# Handler implementations
# ------------------------
async def handle_schedule_day(call: CallbackQuery, barber_id: int, barber_name: str):
    data = call.data
    date_str = data[len("schedule_day_"):]
    try:
        show_date = date.fromisoformat(date_str)
    except Exception:
        await call.answer("Неверная дата.", show_alert=True)
        return

    bookings = await database.fetch_all("""SELECT id, usr_id, service_id, date, start_time, end_time, service_name, condition, price
                      FROM bookings WHERE barber_id = ? AND date = ? ORDER BY start_time""", (barber_id, show_date.isoformat()))
    
    if not bookings:
        text = f"📅 Расписание на {show_date.day}.{show_date.month}.{show_date.year}\n\nБроней нет."
        free_candidates = await services.get_free_slots(barber_id, show_date, 30)
        if free_candidates: text += "\n\nЕсть свободные слоты — возможно, добавьте дополнительные часы."
    else:
        text = f"📅 Расписание на {show_date.day}.{show_date.month}.{show_date.year}:\n"
        for idx, bk in enumerate(bookings, start=1):
            idb, usr_id, service_id, date_d, start_t, end_t, service_name, condition, price = bk
            status = "✅ Оплачено" if condition == 'paid' else ("↩️ Возвращено" if condition == 'refunded' else "⏳ Забронировано")
            client_label = f"Клиент ID: {usr_id}"
            # Try to get username from DB/users table: note users.name is telegram user_id per your schema
            try:
                user_row = await database.fetch_one("SELECT name FROM users WHERE name = ?", (usr_id,))
                # based on user's statement: users.name contains telegram user_id
                # if present we still prefer fetching username via API
                chat_username = None
                try:
                    chat = await bot.get_chat(usr_id)
                    chat_username = getattr(chat, "username", None)
                except Exception:
                    chat_username = None
                if chat_username:
                    client_label = f"Клиент: @{chat_username} (ID:{usr_id})"
            except Exception:
                pass
            text += f"\n{idx}. {start_t} — {end_t} | {service_name} | {status} | {client_label} (ID:{idb})"

    try:
        await call.message.edit_text(text, reply_markup=barber_kb.day_schedule(show_date, bookings))
    except Exception:
        # Safeguard: if message cannot be edited (maybe inline), attempt to send new message
        await call.message.answer(text, reply_markup=barber_kb.day_schedule(show_date, bookings))

async def handle_booking_details(call: CallbackQuery, barber_id: int, barber_name: str):
    data = call.data
    payload = data[len("booking_"):]
    try:
        idbook = int(payload)
    except Exception:
        await call.answer("Неверный идентификатор брони.", show_alert=True)
        return

    row = await database.fetch_one("""SELECT id, usr_id, barber_id, service_id, date, start_time, end_time, barber_name, service_name, condition, price, duration
                      FROM bookings WHERE id = ?""", (idbook,))
    if not row:
        await call.answer("Броня не найдена.", show_alert=True)
        return
    (idb, usr_id, bid, service_id, date_d, start_t, end_t, barber_name_db, service_name, condition, price, duration) = row

    client_label = f"Клиент ID: {usr_id}"
    # Try to fetch Telegram username (do not invent)
    try:
        chat = await bot.get_chat(usr_id)
        username = getattr(chat, "username", None)
        if username:
            client_label = f"Клиент: @{username} (ID:{usr_id})"
    except Exception:
        # bot may be blocked or user not found
        pass
    
    status_text = "Оплачено" if condition == 'paid' else ("Возвращено" if condition == 'refunded' else "Забронировано")
    text = (f"🔎 Информация о брони (ID {idb}):\n\n"
            f"{client_label}\n"
            f"Услуга: {service_name}\n"
            f"Дата: {date_d}\n"
            f"Время: {start_t} — {end_t}\n"
            f"Цена: {price}₽\n"
            f"Статус: {status_text}\n")
    
    kb_rows = []
    if condition == 'paid': kb_rows.append([InlineKeyboardButton(text="❌ Отменить бронь", callback_data=f"refund_booking_{idb}")])
    else: kb_rows.append([InlineKeyboardButton(text="❌ Отменить бронь", callback_data=f"cancel_booking_{idb}")])
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад к дню", callback_data=f"schedule_day_{date_d}")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    try:
        await call.message.edit_text(text, reply_markup=barber_kb.booking_details(idbook, condition, date_d))
    except Exception:
        await call.message.answer(text, reply_markup=barber_kb.booking_details(idbook, condition, date_d))


async def handle_cancel_flow(call: CallbackQuery, barber_id: int, barber_name: str):
    data = call.data
    if data.startswith("cancel_booking_"):
        payload = data[len("cancel_booking_"):]
        try:
            idbook = int(payload)
        except Exception:
            await call.answer("Неверный ID.", show_alert=True)
            return
        await call.message.edit_text("Вы уверены, что хотите отменить эту бронь? Это удалит запись.", reply_markup=barber_kb.cancel_confirmation(idbook))
        return

    if data.startswith("cancel_confirm_"):
        payload = data[len("cancel_confirm_"):]
        try:
            idbook = int(payload)
        except Exception:
            await call.answer("Неверный ID.", show_alert=True)
            return
        
        try:
            # 1. Получаем данные для уведомления ПЕРЕД удалением
            r = await database.fetch_one(
                "SELECT usr_id, barber_name, service_name, date, start_time, price FROM bookings WHERE id = ?",
                (idbook,)
            )
            
            if not r:
                await call.answer("Бронь уже удалена.", show_alert=True)
                return
            
            usr_id, b_name, service_name, date_d, start_t, price = r
            
            # 2. Удаляем бронь
            if await services.delete_booking(idbook):
                # 3. Уведомляем клиента
                try:
                    msg_client = (f"⚠️ <b>Ваша запись была отменена мастером!</b>\n\n"
                                  f"💈 Мастер: {b_name}\n"
                                  f"📅 Дата: {date_d}\n"
                                  f"⏰ Время: {start_t}\n"
                                  f"✂️ Услуга: {service_name}\n"
                                  f"Пожалуйста, выберите другое время или свяжитесь с мастером.")
                    # Отправляем сообщение КЛИЕНТУ (используем bot_client)
                    await bot_client.send_message(usr_id, msg_client, parse_mode="HTML")
                except Exception as e:
                    logger.warning(f"Cannot notify client {usr_id} about cancellation {idbook}: {e}")
                
                await call.message.edit_text("✅ Бронь отменена и клиент уведомлён.", reply_markup=barber_kb._back_btn("main_menu"))
            else:
                await call.answer("Ошибка удаления.", show_alert=True)

        except Exception as e:
            logger.exception(f"Error cancelling booking {idbook}: {e}")
            await call.answer("Произошла ошибка при отмене брони.", show_alert=True)
        return


async def handle_refund(call: CallbackQuery, barber_id: int, barber_name: str):
    data = call.data
    payload = data[len("refund_booking_"):]
    try:
        idbook = int(payload)
    except Exception:
        await call.answer("Неверный ID.", show_alert=True)
        return
    
    # 1. Запрашиваем расширенные данные (чтобы было что писать в уведомлении)
    # Добавили: service_name, start_time, barber_name
    row = await database.fetch_one(
        "SELECT usr_id, price, condition, date, service_name, start_time, barber_name FROM bookings WHERE id = ?",
        (idbook,)
    )
    
    if not row:
        await call.answer("Броня не найдена.", show_alert=True)
        return
    
    # Распаковываем всё
    usr_id, price, condition, date_d, service_name, start_time, b_name = row
    
    if condition != 'paid':
        await call.answer("Возврат возможен только для оплаченной брони.", show_alert=True)
        return
    
    # 2. Выполняем возврат
    # (Даже если process_refund не возвращает дату, мы её уже взяли из базы выше в переменную date_d)
    res = await services.process_refund(idbook, call.message.chat.id)
    
    # Обрабатываем результат (учтем, если функция возвращает 2 или 3 значения)
    if len(res) == 3:
        success, msg, _ = res
    else:
        success, msg = res
    
    if success:
        # 3. УВЕДОМЛЯЕМ КЛИЕНТА
        try:
            await bot_client.send_message(
                usr_id,
                f"💸 <b>Возврат средств!</b>\n"
                f"Мастер {b_name} отменил вашу запись и вернул средства.\n\n"
                f"📅 Дата: {date_d}\n"
                f"⏰ Время: {start_time}\n"
                f"✂️ Услуга: {service_name}\n"
                f"💰 Сумма: {price}₽",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление клиенту: {e}")
        # 4. Обновляем меню БАРБЕРА (возвращаем его в календарь)
        try:
            date_obj = date.fromisoformat(date_d)
        except:
            date_obj = date.today()
        
        await call.message.edit_text(f"✅ {msg}\nКлиент уведомлен.", reply_markup=barber_kb.back_to_date(date_obj))
    else:
        await call.message.edit_text(f"❌ {msg}")

async def text_render(barber_id:int, used, d):
    if d is None:
        d = date.today()
    year = d.year
    if d.month <= 6:
        start = date(year, 1, 1)
        end = date(year, 6, 30)
    else:
        start = date(year, 7, 1)
        end = date(year, 12, 31)
    rows = await database.fetch_all("SELECT id, date FROM off_days WHERE barber_id = ? AND date BETWEEN ? AND ?", (barber_id, start.isoformat(), end.isoformat()))
    text = f"<b>Сейчас {d.year}-{d.month}</b>\n🛠️ Ваши выходные (Использовано {used}/20 дней на следующие 6 месяцев):\n"
    if not rows: text += "Пока что нет отмеченных выходных."
    else:
        for idx, (oid, dstr) in enumerate(rows, start=1):
            dd = date.fromisoformat(dstr)
            text += f"\n{idx}. {dd.day}.{dd.month}.{dd.year} (ID:{oid})"
    return text


async def handle_offdays(call: CallbackQuery, barber_id: int, barber_name: str):
    data = call.data
    
    # --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ВНУТРИ (чтобы не дублировать код) ---
    async def get_keyboard_data(date_obj):
        # 1. Считаем дни для отрисовки кнопок
        today = date.today()
        year_t = date_obj.year
        month_t = date_obj.month
        days_in_month = monthrange(year_t, month_t)[1]
        days = [date(year_t, month_t, d) for d in range(1, days_in_month + 1)]
        
        # 2. ПОЛУЧАЕМ СПИСОК ВЫХОДНЫХ (чтобы отметить их на кнопках)
        rows = await database.fetch_all("SELECT date FROM off_days WHERE barber_id = ?", (barber_id,))
        # Превращаем в множество (set) объектов date
        off_days_set = {date.fromisoformat(r[0]) for r in rows}
        
        return days, today, days_in_month, off_days_set
    
    # ---------------------------------------------------------------
    
    if data.startswith("offdays_view"):
        try:
            date_now_str = data[len("offdays_view"):]
            if date_now_str == '':
                date_now = date.today()
            else:
                date_now = date.fromisoformat(date_now_str)
            
            used = await services.count_offdays_in_next_6_months(barber_id, date_now)
            text = await text_render(barber_id, used, date_now)
            
            # Получаем данные для клавиатуры
            days, today, dim, off_set = await get_keyboard_data(date_now)
            
            # Передаем off_set в клавиатуру
            await call.message.edit_text(text, reply_markup=barber_kb.off_days_calendar(days, today, dim, date_now, off_set), parse_mode="HTML")
        except Exception as e:
            logger.exception("Error in offdays_view")
            await call.answer("Не удалось показать выходные.", show_alert=True)
        return
    
    if data.startswith("offday_toggle_"):
        dstr = data[len("offday_toggle_"):]
        try:
            dd = date.fromisoformat(dstr)
        except Exception:
            await call.answer("Неверная дата.", show_alert=True)
            return
        
        if dd <= date.today():  # Исправил на <=, чтобы сегодня тоже нельзя было менять, если это прошлое
            await call.answer("Невозможно изменить прошлое.", show_alert=True)
        return
        
        try:
            # Определяем дату просмотра (чтобы календарь не скакал)
            date_now = dd
            
            row = await database.fetch_one("SELECT id FROM off_days WHERE barber_id = ? AND date = ?", (barber_id, dd.isoformat()))
            
            # Логика добавления/удаления
            if row:
                await database.execute("DELETE FROM off_days WHERE id = ?", (row[0],))
                action_text = f"Удалён выходной: {dd.day}.{dd.month}"
            else:
                used = await services.count_offdays_in_next_6_months(barber_id, date_now)
                if used >= 20:
                    await call.answer("Превышен лимит (20 дней)!", show_alert=True)
                    return
                
                cnt = (await database.fetch_one("SELECT COUNT(*) FROM bookings WHERE barber_id = ? AND date = ?", (barber_id, dd.isoformat())))[0]
                if cnt > 0:
                    await call.answer("Невозможно! Есть брони на этот день.", show_alert=True)
                    return
                
                await database.execute("INSERT INTO off_days (barber_id, date) VALUES (?, ?)", (barber_id, dd.isoformat()))
                action_text = f"Добавлен выходной: {dd.day}.{dd.month}"
            
            # Обновляем интерфейс
            used = await services.count_offdays_in_next_6_months(barber_id, date_now)
            text = await text_render(barber_id, used, date_now)
            
            # Снова получаем актуальные данные для кнопок (уже с учетом изменений)
            days, today, dim, off_set = await get_keyboard_data(date_now)
            
            await call.message.edit_text(f"{text}\n✅ {action_text}", reply_markup=barber_kb.off_days_calendar(days, today, dim, date_now, off_set), parse_mode="HTML")
        
        except Exception as e:
            logger.exception("Error toggling offday")
            await call.answer("❌ Ошибка.", show_alert=True)
        return
    
    if data.startswith("offdays_clear_all"):
        date_now_str = data[len("offdays_clear_all"):]
        if date_now_str == '':
            date_now = date.today()
        else:
            date_now = date.fromisoformat(date_now_str)
        
        try:
            await database.execute("DELETE FROM off_days WHERE barber_id = ?", (barber_id,))
            
            used = await services.count_offdays_in_next_6_months(barber_id, date_now)
            text = await text_render(barber_id, used, date_now)
            
            days, today, dim, off_set = await get_keyboard_data(date_now)  # off_set будет пустым
            
            await call.message.edit_text(f"{text}\n🗑️ Все выходные удалены.", reply_markup=barber_kb.off_days_calendar(days, today, dim, date_now, off_set), parse_mode="HTML")
        except Exception:
            logger.exception("Failed to clear off-days")
            await call.answer("Ошибка удаления.", show_alert=True)

    return

# ------------------------
# Startup
# ------------------------
async def main():
    logger.info("Starting ClientToBarber bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: logger.info("Bot stopped by user.")