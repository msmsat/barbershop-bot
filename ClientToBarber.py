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
# Try importing refund/payment utilities from BarberToClient.py
# ------------------------
portmone_refund = None
cryptobot_transfer = None
try:
    # Attempt import; if functions have other names, adjust accordingly.
    portmone_refund = _pm_refund
    cryptobot_transfer = _crypto_invoice
    logger.info("Imported payment helpers from BarberToClient.py")
except Exception as e:
    logger.info("Payment helpers not available from BarberToClient.py — refund operations will be unavailable unless provided.")
    portmone_refund = None
    cryptobot_transfer = None

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
        return "Невідома броня"
    status = "Оплачено" if condition == 'paid' else ("Повернено" if condition == 'refunded' else "Заброньовано")
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
        await message.answer(f"❌ Доступ заборонено. Ви не зареєстровані як барбер у системі.\n Ваш айди: <b><code>{usr_id}</code></b> \nВаш юзернейм: <b><code>{usr_name}</code></b>", parse_mode="HTML")
        logger.info(f"Unauthorized access attempt: {usr_id} ({user.username})")
        return

    barber_id, barber_name = barber
    await message.answer(f"👋 Вітаю, {barber_name}! Головне меню:", reply_markup=barber_kb.main_menu())

# ------------------------
# Callback router (modularized)
# ------------------------
@dp.callback_query(F.data.startswith("schedule_day_"))
async def main_menu_handler(call: CallbackQuery):
    barber = await services.get_barber_by_telegram_user(call.from_user.id, call.from_user.username)
    if not barber:
        await call.answer("Доступ заборонено.", show_alert=True)
        return
    barber_id, barber_name = barber

    # schedule_day_{date}
    await handle_schedule_day(call, barber_id, barber_name)
    return

@dp.callback_query(F.data.startswith("prev_locked"))
async def main_menu_handler(call: CallbackQuery):
    await call.answer("Немає доступу до минулих днів.", show_alert=True)
    return

@dp.callback_query(F.data.startswith("main_menu"))
async def main_menu_handler(call: CallbackQuery):
    await call.message.edit_text("Головне меню:", reply_markup=barber_kb.main_menu())
    return

@dp.callback_query(F.data.startswith("booking_"))
async def main_menu_handler(call: CallbackQuery):
    barber = await services.get_barber_by_telegram_user(call.from_user.id, call.from_user.username)
    if not barber:
        await call.answer("Доступ заборонено.", show_alert=True)
        return
    barber_id, barber_name = barber
    await handle_booking_details(call, barber_id, barber_name)
    return

@dp.callback_query(F.data.startswith("cancel_booking_") or F.data.startswith("cancel_confirm_"))
async def main_menu_handler(call: CallbackQuery):
    barber = await services.get_barber_by_telegram_user(call.from_user.id, call.from_user.username)
    if not barber:
        await call.answer("Доступ заборонено.", show_alert=True)
        return
    barber_id, barber_name = barber
    await handle_cancel_flow(call, barber_id, barber_name)
    return

@dp.callback_query(F.data.startswith("refund_booking_"))
async def main_menu_handler(call: CallbackQuery):
    barber = await services.get_barber_by_telegram_user(call.from_user.id, call.from_user.username)
    if not barber:
        await call.answer("Доступ заборонено.", show_alert=True)
        return
    barber_id, barber_name = barber
    await handle_refund(call, barber_id, barber_name)
    return

@dp.callback_query(F.data.startswith("offdays_view") or F.data.startswith("offday_toggle_") or F.data.startswith("offdays_clear_all"))
async def main_menu_handler(call: CallbackQuery):
    barber = await services.get_barber_by_telegram_user(call.from_user.id, call.from_user.username)
    if not barber:
        await call.answer("Доступ заборонено.", show_alert=True)
        return
    barber_id, barber_name = barber
    await handle_offdays(call, barber_id, barber_name)
    return

@dp.callback_query(F.data.startswith("toggle_reminders"))
async def main_menu_handler(call: CallbackQuery):
    # toggle reminders placeholder
    await call.answer("Функція нагадувань (тимчасово) не налаштована.", show_alert=True)
    return

# ------------------------
# Handler implementations
# ------------------------
async def handle_schedule_day(call: CallbackQuery, barber_id: int, barber_name: str):
    data = call.data
    date_str = data[len("schedule_day_"):]
    try:
        show_date = date.fromisoformat(date_str)
    except Exception:
        await call.answer("Невірна дата.", show_alert=True)
        return

    bookings = await database.fetch_all("""SELECT id, usr_id, service_id, date, start_time, end_time, service_name, condition, price
                      FROM bookings WHERE barber_id = ? AND date = ? ORDER BY start_time""", (barber_id, show_date.isoformat()))

    if not bookings:
        text = f"📅 Розклад на {show_date.day}.{show_date.month}.{show_date.year}\n\nНемає броней."
        free_candidates = await services.get_free_slots(barber_id, show_date, 30)
        if free_candidates: text += "\n\nЄ вільні слоти — можливо, додайте додаткові години."
    else:
        text = f"📅 Розклад на {show_date.day}.{show_date.month}.{show_date.year}:\n"
        for idx, bk in enumerate(bookings, start=1):
            idb, usr_id, service_id, date_d, start_t, end_t, service_name, condition, price = bk
            status = "✅ Оплачено" if condition == 'paid' else ("↩️ Повернено" if condition == 'refunded' else "⏳ Заброньовано")
            client_label = f"Клієнт ID: {usr_id}"
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
                    client_label = f"Клієнт: @{chat_username} (ID:{usr_id})"
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
        await call.answer("Невірний ідентифікатор броні.", show_alert=True)
        return

    row = await database.fetch_one("""SELECT id, usr_id, barber_id, service_id, date, start_time, end_time, barber_name, service_name, condition, price, duration
                      FROM bookings WHERE id = ?""", (idbook,))
    if not row:
        await call.answer("Броня не знайдена.", show_alert=True)
        return
    (idb, usr_id, bid, service_id, date_d, start_t, end_t, barber_name_db, service_name, condition, price, duration) = row

    client_label = f"Клієнт ID: {usr_id}"
    # Try to fetch Telegram username (do not invent)
    try:
        chat = await bot.get_chat(usr_id)
        username = getattr(chat, "username", None)
        if username:
            client_label = f"Клієнт: @{username} (ID:{usr_id})"
    except Exception:
        # bot may be blocked or user not found
        pass

    status_text = "Оплачено" if condition == 'paid' else ("Повернено" if condition == 'refunded' else "Заброньовано")
    text = (f"🔎 Інформація про бронь (ID {idb}):\n\n"
            f"{client_label}\n"
            f"Послуга: {service_name}\n"
            f"Дата: {date_d}\n"
            f"Час: {start_t} — {end_t}\n"
            f"Ціна: {price}₽\n"
            f"Статус: {status_text}\n")

    kb_rows = []
    if condition == 'paid': kb_rows.append([InlineKeyboardButton(text="❌ Відмінити бронь", callback_data=f"refund_booking_{idb}")])
    else: kb_rows.append([InlineKeyboardButton(text="❌ Відмінити бронь", callback_data=f"cancel_booking_{idb}")])
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад до дня", callback_data=f"schedule_day_{date_d}")])
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
            await call.answer("Невірний ID.", show_alert=True)
            return
        await call.message.edit_text("Ви впевнені, що хочете відмінити цю бронь? Це видалить запис.", reply_markup=barber_kb.cancel_confirmation(idbook))
        return

    if data.startswith("cancel_confirm_"):
        payload = data[len("cancel_confirm_"):]
        try:
            idbook = int(payload)
        except Exception:
            await call.answer("Невірний ID.", show_alert=True)
            return
        try:
            # Получаем данные для уведомления ПЕРЕД удалением (сервис не возвращает детали)
            r = await database.fetch_one("SELECT usr_id, barber_name, service_name, date, start_time, price FROM bookings WHERE id = ?", (idbook,))
            if not r:
                await call.answer("Броня вже видалена.", show_alert=True)
                return
            usr_id, b_name, service_name, date_d, start_t, price = r

            # Используем сервис для удаления (БД + Календарь)
            if await services.delete_booking(idbook):
                try:
                    # Используем bot_client из loader
                    await bot_client.send_message(usr_id, f"⚠️ Ваша броня була скасована барбером {b_name}.\nПослуга: {service_name}\nДата: {date_d}\nЧас: {start_t}\nСума: {price}₽")
                except Exception:
                    logger.warning(f"Cannot notify client {usr_id} about cancellation {idbook}")

                await call.message.edit_text("✅ Броня відмінена та клієнт повідомлений.", reply_markup=barber_kb._back_btn("main_menu"))
            else:
                await call.answer("Помилка видалення.", show_alert=True)
        except Exception as e:
            logger.exception(f"Error cancelling booking {idbook}: {e}")
            await call.answer("Сталася помилка при відміні броні.", show_alert=True)
        return

async def handle_refund(call: CallbackQuery, barber_id: int, barber_name: str):
    data = call.data
    payload = data[len("refund_booking_"):]
    try: idbook = int(payload)
    except Exception:
        await call.answer("Невірний ID.", show_alert=True)
        return
    # fetch booking details to know amount
    r = await database.fetch_one("SELECT usr_id, price, condition FROM bookings WHERE id = ?", (idbook,))
    if not r:
        await call.answer("Броня не знайдена.", show_alert=True)
        return
    usr_id, price, condition = r
    if condition != 'paid':
        await call.answer("Повернення можливе тільки для оплаченої броні.", show_alert=True)
        return
    success, msg = await services.process_refund(idbook, call.message.chat.id)
    if success:
        # Конвертируем строку даты обратно в объект для клавиатуры
        try: date_obj = date.fromisoformat(date_d)
        except: date_obj = date.today()
        await call.message.edit_text(f"✅ {msg}", reply_markup=barber_kb.back_to_date(date_obj))
    else: await call.message.edit_text(f"❌ {msg}")

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
    text = f"<b>Сейчас {d.year}-{d.month}</b>\n🛠️ Ваші вихідні (Використано {used}/20 днів на наступні 6 місяців):\n"
    if not rows: text += "Поки що немає позначених вихідних."
    else:
        for idx, (oid, dstr) in enumerate(rows, start=1):
            dd = date.fromisoformat(dstr)
            text += f"\n{idx}. {dd.day}.{dd.month}.{dd.year} (ID:{oid})"
    return text

async def handle_offdays(call: CallbackQuery, barber_id: int, barber_name: str):
    data = call.data
    print(data)
    if data.startswith("offdays_view"):
        try:
            date_now = data[len("offdays_view"):]
            if date_now == '': date_now = date.today()
            else: date_now = date.fromisoformat(date_now)
            print(date_now)

            # Нужно передать barber_id
            used = await services.count_offdays_in_next_6_months(barber_id, date_now)
            print(used)
            text = await text_render(barber_id, used, date_now)

            today = date.today()
            year_t = date_now.year
            month_t = date_now.month
            days_in_month = monthrange(year_t, month_t)[1]

            days = [date(year_t, month_t, d) for d in range(1, days_in_month + 1)]
            await call.message.edit_text(text, reply_markup=barber_kb.off_days_calendar(days, today, days_in_month, date_now), parse_mode="HTML")
        except Exception as e:
            logger.exception("Error in offdays_view")
            await call.answer("Не вдалося показати вихідні.", show_alert=True)
        return

    if data.startswith("offday_toggle_"):
        dstr = data[len("offday_toggle_"):]
        print(dstr)
        try:
            dd = date.fromisoformat(dstr)
        except Exception:
            await call.answer("Невірна дата.", show_alert=True)
            return
        if dd < date.today():
            await call.answer("Неможливо додати вихідний у минулому.", show_alert=True)
            return

        try:
            if dstr == '': date_now = date.today()
            else: date_now = date.fromisoformat(dstr)

            row = await database.fetch_one("SELECT id FROM off_days WHERE barber_id = ? AND date = ?", (barber_id, dd.isoformat()))
            today = date.today()
            year_t = date_now.year
            month_t = date_now.month
            days_in_month = monthrange(year_t, month_t)[1]
            days = [date(year_t, month_t, d) for d in range(1, days_in_month + 1)]
            if row:
                # remove
                await database.execute("DELETE FROM off_days WHERE id = ?", (row[0],))
                used = await services.count_offdays_in_next_6_months(barber_id, date_now)
                text = await text_render(barber_id, used, date_now)
                await call.message.edit_text(f"{text}\nВидалено вихідний: {dd.day}.{dd.month}.{dd.year}", reply_markup=barber_kb.off_days_calendar(days, today, days_in_month, date_now), parse_mode="HTML")
                logger.info(f"Barber {barber_id} removed off-day {dd}")
            else:
                used = await services.count_offdays_in_next_6_months(barber_id, date_now)
                if used >= 20:
                    text = await text_render(barber_id, used, date_now)
                    await call.message.edit_text(f"{text}\nПеревищено ліміт: не більше 20 вихідних на наступні 6 місяців.", reply_markup=barber_kb.off_days_calendar(days, today, days_in_month, date_now), parse_mode="HTML")
                    return
                # check for bookings that day
                cnt = (await database.fetch_one("SELECT COUNT(*) FROM bookings WHERE barber_id = ? AND date = ?", (barber_id, dd.isoformat())))[0]
                if cnt > 0:
                    await call.message.edit_text(f"Неможливо поставити вихідний — існують броні на цей день.", reply_markup=barber_kb.off_days_calendar(days, today, days_in_month, date_now), parse_mode="HTML")
                    return
                await database.execute("INSERT INTO off_days (barber_id, date) VALUES (?, ?)", (barber_id, dd.isoformat()))
                used = await services.count_offdays_in_next_6_months(barber_id, date_now)
                text = await text_render(barber_id, used, date_now)
                await call.message.edit_text(f"{text}\nДодано вихідний: {dd.day}.{dd.month}.{dd.year}", reply_markup=barber_kb.off_days_calendar(days, today, days_in_month, date_now), parse_mode="HTML")
                logger.info(f"Barber {barber_id} added off-day {dd}")
        except Exception as e:
            logger.exception("Error toggling offday")
            await call.answer("Сталася помилка при зміні вихідного.", show_alert=True)

        return

    if data.startswith("offdays_clear_all"):
        date_now = data[len("offdays_clear_all"):]
        if date_now == '': date_now = date.today()
        else: date_now = date.fromisoformat(date_now)

        today = date.today()
        year_t = date_now.year
        month_t = date_now.month
        days_in_month = monthrange(year_t, month_t)[1]
        days = [date(year_t, month_t, d) for d in range(1, days_in_month + 1)]
        try:
            await database.execute("DELETE FROM off_days WHERE barber_id = ?", (barber_id,))
            used = await services.count_offdays_in_next_6_months(barber_id, date_now)
            text = await text_render(barber_id, used, date_now)
            await call.message.edit_text(f"{text}\nВсі вихідні видалено.", reply_markup=barber_kb.off_days_calendar(days, today, days_in_month, date_now), parse_mode="HTML")
            logger.info(f"Barber {barber_id} cleared all off-days")
        except Exception:
            logger.exception("Failed to clear off-days")
            used = await services.count_offdays_in_next_6_months(barber_id, date_now)
            text = await text_render(barber_id, used, date_now)
            await call.message.edit_text(f"{text}\nНе вдалося видалити вихідні.", reply_markup=barber_kb.off_days_calendar(days, today, days_in_month, date_now), parse_mode="HTML")
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