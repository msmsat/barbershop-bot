# Стандарт
import time
import json
import os
from datetime import datetime, date, timedelta
from calendar import monthrange
from dotenv import load_dotenv

# Стороние
import asyncio
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery, SuccessfulPayment

# Локальные
import loader
from loader import bot_client as bot, dp_client as dp
from loader import bot_barber  # Берем бота барбера отсюда, чтобы писать ему уведомления
import database
import services
import GoogleCalendar
from keyboards import client_kb

load_dotenv()
# Токены платежек оставляем тут (или тоже можно в loader, но тут ок)
PORTMONE_TEST_TOKEN = os.getenv("PORTMONE_TEST_TOKEN")  # <--- Добавить это


async def show_dates(call, service_id, start_date=None, idbook=None):
    today = date.today()

    if start_date is None: start_date = today
    year = start_date.year
    month = start_date.month

    # Текст диапазона
    header = f"{start_date.year}.{start_date.month}"
    await call.message.edit_text(f"📅 Выберите дату: <b>{header}</b>", reply_markup=client_kb.calendar_kb(year, month, service_id, idbook), parse_mode="HTML")


@dp.message(F.text == "/start")
async def start_cmd(message: Message):
    usr_id = message.from_user.id
    data = await database.fetch_all("SELECT name FROM users WHERE name = ?", (usr_id,))
    if not data:
        await database.execute("""INSERT OR IGNORE INTO users (name, chat_id) VALUES(?, ?)""", (usr_id, int(message.chat.id)))
    data = await database.fetch_all("SELECT id, name, price FROM services")
    text = ''
    for serviceId, serviceName, servicePrice in data: text += f'{serviceName}: <b>{servicePrice}₽</b>\n'
    await message.answer(f"👋 Привет! Выберите услугу:\n{text}", reply_markup=client_kb.main_menu(data), parse_mode="HTML")


@dp.callback_query(F.data.startswith("mainMenu"))
async def main_menu_handler(call: CallbackQuery):
    """Возврат в главное меню"""
    # Если это удаление брони перед возвратом
    if call.data.startswith("mainMenu_really_"):
        idbook = call.data[len("mainMenu_really_"):]
        
        # --- НОВАЯ ЛОГИКА УВЕДОМЛЕНИЯ БАРБЕРА ---
        try:
            # 1. Получаем данные брони ПЕРЕД удалением
            b_row = await database.fetch_one(
                "SELECT barber_id, date, start_time, service_name FROM bookings WHERE id = ?",
                (idbook,)
            )
            
            # 2. Удаляем бронь
            await services.delete_booking(int(idbook))
            
            # 3. Если данные были, ищем барбера и шлем ему сообщение
            if b_row:
                barber_id, date_d, start_t, s_name = b_row
                # Ищем Telegram ID барбера
                tg_row = await database.fetch_one("SELECT telegram_id FROM barbers WHERE id = ?", (barber_id,))
                
                if tg_row and tg_row[0]:
                    barber_tg_id = tg_row[0]
                    # Красивое имя клиента
                    client_name = f"@{call.from_user.username}" if call.from_user.username else f"ID:{call.from_user.id}"
                    
                    msg = (f"❌ <b>Отмена записи клиентом!</b>\n"
                           f"👤 Клиент: {client_name}\n"
                           f"📅 Дата: {date_d}\n"
                           f"⏰ Время: {start_t}\n"
                           f"✂️ Услуга: {s_name}")
                    
                    # Отправляем сообщение барберу (используем bot_barber из loader)
                    await loader.bot_barber.send_message(barber_tg_id, msg, parse_mode="HTML")
        except Exception as e:
            print(f"Ошибка при уведомлении барбера: {e}")
        # ----------------------------------------
        
        st_text = '✅ Бронь удачно удалена'
    else:
        st_text = '👋 Привет! Выберите услугу:'
    data = await database.fetch_all("SELECT id, name, price FROM services")
    text = ''
    for serviceId, serviceName, servicePrice in data:
        text += f'{serviceName}: <b>{servicePrice}₽</b>\n'
    await call.message.edit_text(f"{st_text}\n{text}", reply_markup=client_kb.main_menu(data), parse_mode="HTML")
    return

@dp.callback_query(F.data.startswith("my_book"))
async def my_bookings_handler(call: CallbackQuery):
    """Просмотр своих броней"""
    my_books = await database.fetch_all("SELECT id, barber_id, service_id, date, start_time, barber_name, service_name, condition FROM bookings WHERE usr_id = ?", (call.from_user.id,))
    if not my_books: return await call.message.edit_text("❌ Нет активных броней", reply_markup=client_kb.back_to_main(), parse_mode="HTML")
    text = '👋 Ваши брони:\n' + "\n".join([f"{i + 1}. {b[5]}: {b[4]} {b[3]} | {b[6]}" for i, b in enumerate(my_books)])
    await call.message.edit_text(text, reply_markup=client_kb.my_bookings(my_books), parse_mode="HTML")

@dp.callback_query(F.data.startswith("sett_book_"))
async def set_booking_handler(call: CallbackQuery):
    # 1. Логика ИЗМЕНЕНИЯ (если нажали перенос)
    # 1. Логика ИЗМЕНЕНИЯ (если нажали перенос)
    if call.data.startswith("sett_book_change_"):
        # Используем срез строки, чтобы убрать префикс 'sett_book_change_',
        # и только потом разбиваем оставшуюся часть
        data_parts = call.data[len("sett_book_change_"):].split("_")
        date_d, date_t, duration, idbook = data_parts
        idbook = int(idbook)
        # Вызываем нашу функцию из services
        result = await services.reschedule_booking(idbook, date_d, date_t, int(duration), call.from_user.username or "Client")

        # Если успешно перенесли — уведомляем барбера
        if result:
            try:
                # Получаем TG ID барбера для отправки
                bid = result['barber_id']
                if tg_row := await database.fetch_one("SELECT telegram_id FROM barbers WHERE id=?", (bid,)):
                    msg = (f"🔄 <b>Перенос записи!</b>\n"
                           f"Юзер @{call.from_user.username}\n"
                           f"Было: {result['old_time']} {result['old_date']}\n"
                           f"Стало: {date_t} {date_d}\n"
                           f"Услуга: {result['service_name']}")
                    await loader.bot_barber.send_message(tg_row[0], msg, parse_mode="HTML")
            except Exception:
                pass  # Не ломаем интерфейс, если барбер заблочил бота

            change_text = '✅ Время изменено\n'
        else:
            await call.answer("Ошибка при переносе времени.", show_alert=True)
            return
    else:
        # Просто просмотр
        idbook = int(call.data.split("_")[2])
        change_text = ''

    # 2. Логика ОТОБРАЖЕНИЯ (получаем чистые данные)
    details = await services.get_booking_details(idbook)
    if not details:
        await call.answer("Бронь не найдена.", show_alert=True)
        return

    # 3. Подготовка интерфейса
    now = int(time.time())
    if isinstance(details['date'], str):
        date_obj = date.fromisoformat(details['date'])
    else:
        date_obj = details['date']

    # Разрешаем отмену, если до записи больше часа и это не сегодня (или по вашей логике)
    can_cancel = (date_obj != date.today() and details['timestamp'] - 3600 > now)

    status_str = 'Не оплачено' if details['condition'] == 'book' else 'Оплачено'

    text = (f"{change_text}Вы забронировали на {details['time']} ⏰ {details['date']}\n"
            f"Ваш барбер: {details['barber_name']}\n"
            f"Его телеграм: {details['barber_username']}\n"
            f"Его телефон: {details['barber_phone']}\n"
            f"Услуга стоит <b>{details['price']}₽</b>\n"
            f"Состояние брони: <b>{status_str}</b>")

    await call.message.edit_text(
        text,
        reply_markup=client_kb.booking_settings(
            idbook, can_cancel, (details['condition'] == 'book'), details['date'], details['time']
        ),
        parse_mode="HTML"
    )
    return

@dp.callback_query(F.data.startswith("cancel_book_"))
async def set_cancel_book(call: CallbackQuery):
    if call.data.startswith("cancel_book_"):
        idbook = call.data[len("cancel_book_"):]
        condition, timestamp_date, price, dd = await database.fetch_one(
            "SELECT condition, timestamp_date, price, date FROM bookings WHERE id = ?", (idbook,))
        now = int(time.time())
        if date.fromisoformat(dd) == date.today() and timestamp_date - 3600 * 1 < now:
            await call.message.edit_text(
                "Вы не можете отменить бронь уже за час до стрижки, для этого уже надо связываться с барбером",
                reply_markup=client_kb.back_to_booking(idbook), parse_mode="HTML")
            return
        if condition == 'paid':
            text = f'Тогда давайте вернем вам <b>{price}₽</b>'
        elif condition == 'book':
            text = f'Вы уверены что хотите отменить бронь?'
        await call.message.edit_text(text, reply_markup=client_kb.cancel_confirm(idbook, condition), parse_mode="HTML")
        return


@dp.callback_query(F.data.startswith("money_back_"))
async def set_money_back(call: CallbackQuery):
    idbook = call.data[len("money_back_"):]
    
    # 1. ЗАПРАШИВАЕМ БОЛЬШЕ ДАННЫХ (добавили barber_id, service_name, start_time)
    result = await database.fetch_one(
        """SELECT usr_id, telegram_payment_charge_id, price, paid_think, date,
                  barber_id, service_name, start_time
           FROM bookings WHERE id = ?""",
        (idbook,)
    )
    
    if result is None:
        await call.message.edit_text("Ошибка: бронь не найдена.")
        return
    
    # Распаковываем
    usr_id, charge_id, price, paid_think, dd, barber_id, service_name, start_time = result
    
    if paid_think is None:
        await call.message.edit_text("Ошибка: нет данных для возврата (возможно, оплаты не было).")
        return
    
    # 2. ВЫПОЛНЯЕМ ВОЗВРАТ
    success, msg = await services.process_refund(idbook, call.message.chat.id)
    
    if success:
        # 3. УВЕДОМЛЯЕМ БАРБЕРА (Новый код)
        try:
            tg_row = await database.fetch_one("SELECT telegram_id FROM barbers WHERE id = ?", (barber_id,))
            if tg_row and tg_row[0]:
                barber_tg_id = tg_row[0]
                user_link = f"@{call.from_user.username}" if call.from_user.username else f"ID:{call.from_user.id}"
                
                msg_to_barber = (
                    f"💸 <b>Клиент оформил возврат!</b>\n"
                    f"👤 Клиент: {user_link}\n"
                    f"📅 Дата: {dd}\n"
                    f"⏰ Время: {start_time}\n"
                    f"✂️ Услуга: {service_name}\n"
                    f"💰 Сумма возврата: {price}₽"
                )
                await loader.bot_barber.send_message(barber_tg_id, msg_to_barber, parse_mode="HTML")
        except Exception as e:
            print(f"Ошибка уведомления барбера о возврате: {e}")
        
        await call.message.edit_text(f"✅ {msg}", reply_markup=client_kb.back_to_main())
    else:
        await call.message.edit_text(f"❌ {msg}")

@dp.callback_query(F.data.startswith("service_"))
async def set_service(call: CallbackQuery):
    service_id = call.data[len("service_"):]  # "3_Стрижка"
    print(service_id)
    bookings = await database.fetch_all("SELECT barber_id FROM bookings WHERE usr_id = ?", (call.from_user.id,))
    print(len(bookings))
    if len(bookings) >= 4:
        await call.message.edit_text(f"Вы заюронировали уже слишком много", reply_markup=client_kb.back_to_main(),
                                     parse_mode="HTML")
        return
    # service_id_str, service_name = s_clean.split("_", 1)  # split только на 2 части
    # service_id = int(service_id_str)
    barbers = await database.fetch_all("""
    SELECT b.id, b.name
    FROM barbers b
    JOIN barber_services bs ON b.id = bs.barber_id
    WHERE bs.service_id = ?
    """, (service_id,))
    text = ''
    for barberId, barberName in barbers:
        text += f'👤 <b>{barberName}</b>\n'
    await call.message.edit_text(
        f"✂️ Выберите мастера:\n{text}Или нажмите «Любой», чтобы увидеть свободное время всех мастеров ⏰",
        reply_markup=client_kb.barbers_kb(barbers, service_id), parse_mode="HTML")
    return

@dp.callback_query(F.data.startswith("chooseMonth_"))
async def set_choose_month(call: CallbackQuery):
    if call.data.startswith("chooseMonth_change_"):
        idbook = call.data[len("chooseMonth_change_"):]
        barber_id, service_id = map(int, await database.fetch_one("SELECT barber_id, service_id FROM bookings WHERE id = ?", (idbook,)))
    else:
        barber_id, service_id = map(int, call.data[len("chooseMonth_"):].split("_"))
    await database.execute("UPDATE users SET any_service = ?, any_barber = ?, choose = ? WHERE name = ?",
                           (service_id, barber_id, barber_id, call.from_user.id))
    if call.data.startswith("chooseMonth_change_"):
        await show_dates(call, service_id, None, idbook)
    else:
        await show_dates(call, service_id)
    return

@dp.callback_query(F.data.startswith("changeMonth_"))
async def set_change_month(call: CallbackQuery):
    if call.data.startswith("changeMonth_change_"):
        start_date, service_id, idbook = call.data[len("changeMonth_change_"):].split("_")
        await show_dates(call, service_id, start_date=date.fromisoformat(start_date), idbook=idbook)
        return
    # Изменено: убрал if для текущего месяца, теперь всегда показываем на основе start_date
    start_date, service_id = call.data[len("changeMonth_"):].split("_")
    await show_dates(call, service_id, start_date=date.fromisoformat(start_date))
    return

@dp.callback_query(F.data.startswith("chooseDate_"))
async def set_choose_date(call: CallbackQuery):
    if call.data.startswith("chooseDate_change_"):
        date_d, idbook = call.data[len("chooseDate_change_"):].split("_")
    else:
        date_d = call.data[len("chooseDate_"):].split("_")[0]
        idbook = None
    date_btn = date.fromisoformat(date_d)
    barber_data = await database.fetch_one("SELECT choose, any_service FROM users WHERE name = ?",
                                           (call.from_user.id,))
    barber_id, service_id = map(int, barber_data)  # Здесь int!
    data = await database.fetch_one("SELECT duration FROM services WHERE id = ?", (service_id,))
    free_slots = await services.get_free_slots(barber_id, date_btn, data[0], service_id if barber_id == -1 else None)
    await call.message.edit_text(f"✂️ Выберите удобное вам время ⏰",
                                 reply_markup=client_kb.time_slots_kb(free_slots, date_d, idbook, service_id),
                                 parse_mode="HTML")
    return

@dp.callback_query(F.data.startswith("chooseTime_"))
async def set_choose_time(call: CallbackQuery):
    if call.data.startswith("chooseTime_change_"):
        date_d, date_t, idbook = call.data[len("chooseTime_change_"):].split("_")
        date_d = date.fromisoformat(date_d)
        date_d_now, date_t_now, duration = await database.fetch_one(
            "SELECT date, start_time, duration FROM bookings WHERE id = ?", (idbook,))
        date_d_now = date.fromisoformat(date_d_now)
        await call.message.edit_text(
            f"✂️ Вы хотите поменять {date_d_now.day}.{date_d_now.month}.{date_d_now.year} {date_t_now} на {date_d.day}.{date_d.month}.{date_d.year} {date_t} ⏰",
            reply_markup=client_kb.confirm_reschedule(date_d, date_t, duration, idbook, date_d_now),
            parse_mode="HTML")
        return
    else:
        date_d_str, date_t_str = call.data[len("chooseTime_"):].split("_")
        date_d = date.fromisoformat(date_d_str)
        text = f"✂️ Вы предпочитаете заплатить онлайн, или же на месте?"
    barber_data = await database.fetch_one("SELECT any_barber, any_service, choose FROM users WHERE name = ?",
                                           (call.from_user.id,))
    barber_id, service_id, choose = barber_data
    reply_markup = client_kb.payment_method_choice(date_d_str, date_t_str)
    if int(choose) == -1:
        data = await database.fetch_one("SELECT duration FROM services WHERE id = ?", (service_id,))
        barbers = await services.get_available_barbers_for_slot(service_id, date_d, date_t_str, data[0])
        if not barbers:
            await call.message.edit_text(f"❌ Это время занято у всех барберов",
                                         reply_markup=client_kb.back_to_date(date_d_str), parse_mode="HTML")
            return
        barbers_text = ", ".join([barber_name for barber_id, barber_name in barbers])
        text_t = f'\nДоступные барберы: {barbers_text}'
        text = f"✂️ Вы выбрали {date_d.day}.{date_d.month}.{date_d.year} {date_t_str} ⏰\n{text_t}"
        reply_markup = client_kb.barbers_for_time_kb(barbers, date_d_str, date_t_str)

    await call.message.edit_text(f"{text}", reply_markup=reply_markup, parse_mode="HTML")
    return

@dp.callback_query(F.data.startswith("chooseBarber_"))
async def set_choose_barber(call: CallbackQuery):
    date_d_str, date_t_str, barber_id = call.data[len("chooseBarber_"):].split("_")
    await database.execute(f"UPDATE users SET any_barber = ? WHERE name = ?", (barber_id, call.from_user.id))
    await call.message.edit_text(f"✂️ Вы предпочитаете заплатить онлайн, или же на месте?",
                                 reply_markup=client_kb.payment_method_choice(date_d_str, date_t_str),
                                 parse_mode="HTML")
    return

@dp.callback_query(F.data.startswith("pay_online_for_"))
async def set_pay_online_for(call: CallbackQuery):
    if call.data.startswith("pay_online_for_after_"):
        date_d_str, date_t_str, idbook = call.data[len("pay_online_for_after_"):].split("_")
    else:
        date_d_str, date_t_str = call.data[len("pay_online_for_"):].split("_")
        idbook = None
    await call.message.edit_text(f"✅ Выберете как заплатить",
                                 reply_markup=client_kb.payment_gateway_choice(date_d_str, date_t_str, idbook),
                                 parse_mode="HTML")
    return

@dp.callback_query(F.data.startswith("pay_payments_"))
async def set_pay_payments(call: CallbackQuery):
    if call.data.startswith("pay_payments_after_"):
        date_d_str, date_t_str, idbook = call.data[len("pay_payments_after_"):].split("_")
        after_id = idbook
    else:
        date_d_str, date_t_str = call.data[len("pay_payments_"):].split("_")
        after_id = -1
    barber_id, service_id = map(int,
                                await database.fetch_one("SELECT choose, any_service FROM users WHERE name = ?",
                                                         (call.from_user.id,)))
    price = int((await database.fetch_one("SELECT price FROM services WHERE id = ?", (service_id,)))[0])
    prices = [LabeledPrice(label="Оплата услуги", amount=price*100)]  # 100 UAH = 10000 копеек

    data = {"usr_id": call.from_user.id, "date": date_d_str, "start_time": date_t_str, "after_id": after_id}
    await bot.send_invoice(
        chat_id=call.message.chat.id,
        title="Тестовая оплата",
        description="Оплата услуги через Portmone",
        payload=json.dumps(data),
        provider_token=PORTMONE_TEST_TOKEN,
        currency="UAH",
        prices=prices,
        need_email=False
    )
    return

@dp.callback_query(F.data.startswith("pay_crypto_"))
async def set_pay_crypto(call: CallbackQuery):
    # 1. Парсинг данных
    if "after" in call.data:
        parts = call.data[len("pay_crypto_after_"):].split("_")
        date_d_str, date_t_str, idbook = parts[0], parts[1], parts[2]
    else:
        parts = call.data[len("pay_crypto_"):].split("_")
        date_d_str, date_t_str = parts[0], parts[1]
        idbook = None

    # 2. Получаем ID услуги и Цену (АСИНХРОННО)
    # Получаем service_id из таблицы users
    u_rows = await database.fetch_all("SELECT any_service FROM users WHERE name = ?", (call.from_user.id,))
    if not u_rows: return await call.answer("Ошибка сессии")
    service_id = int(u_rows[0][0])

    # Получаем цену из services
    # Получаем цену из services
    s_rows = await database.fetch_all("SELECT price FROM services WHERE id = ?", (service_id,))
    if s_rows: price = int(s_rows[0][0])  # <--- Берем первый элемент кортежа
    else:
        await call.answer("Ошибка: цена не найдена")
        return

    # 3. Создаем инвойс
    # Вызываем твою функцию создания инвойса
    unique_payload = f"book_{call.from_user.id}_{int(time.time())}_{date_d_str}_{date_t_str}"
    desc = f"{date_d_str}_{date_t_str}_{price}_RUB_{service_id}"

    j, invoice_id, bot_url = await services.create_crypto_invoice(float(price), desc, unique_payload)

    # 4. Обработка ОШИБКИ создания
    if invoice_id is None or bot_url is None:
        print(j)
        if j == 502: msg = "❌ Не удалось создать счёт автоматически. Проблемы на сервере крипты — Попробуйте снова позже"
        else: msg = "❌ Не удалось создать счёт автоматически — Попробуйте снова"
        await call.message.edit_text(
            msg, reply_markup=client_kb.crypto_actions_kb(date_d_str, date_t_str, idbook, bot_url=None),
            parse_mode="HTML"
        )
        return

    # 5. Обработка УСПЕХА
    # Сохраняем данные инвойса в пользователя (как у тебя было)
    crypto_invoice_str = f'{invoice_id}_{bot_url}_{date_d_str}_{date_t_str}_{service_id}'
    await database.execute("UPDATE users SET crypto_invoice = ? WHERE name = ?",
                           (crypto_invoice_str, call.from_user.id))

    await call.message.edit_text(
        f"💰 Счёт создан. Нажмите «Открыть оплату» — это откроет бота с кнопкой оплаты.\n\nСумма: <b>{price}₽</b>",
        reply_markup=client_kb.crypto_actions_kb(date_d_str, date_t_str, idbook, bot_url=bot_url),
        parse_mode="HTML"
    )
    return

@dp.callback_query(F.data.startswith("crypto_api_check_"))
async def set_crypto_api_check(call: CallbackQuery):
    if call.data.startswith("crypto_api_check_pay_"):
        # 1. Исправляем извлечение ID (берем [0], чтобы получить строку, а не список)
        idbook = call.data[len("crypto_api_check_pay_"):].split("_")[0]
        usr_id = call.from_user.id
        # 2. Исправляем получение данных из БД (сначала получаем кортеж, потом берем элемент [0])
        row = await database.fetch_one("SELECT crypto_invoice FROM users WHERE name = ?", (usr_id,))
        if not row or not row[0]:
            await call.answer("Данные счета устарели. Попробуйте создать счет заново.", show_alert=True)
            return
        invoice_id, bot_url, date_d_str, date_t_str, service_id = row[0].split("_")
        call_data = f"crypto_api_check_pay_{invoice_id}_{idbook}"
    else:
        usr_id = call.from_user.id
        crypto_info = await database.fetch_one("SELECT crypto_invoice FROM users WHERE name = ?", (usr_id,))
        if not crypto_info or not crypto_info[0]:
            await call.answer("Ошибка данных. Начните сначала.", show_alert=True)
            return
        invoice_id, bot_url, date_d_str, date_t_str, service_id = crypto_info[0].split("_")
        call_data = f"crypto_api_check_{invoice_id}"
    status = await services.check_crypto_invoice_status(int(invoice_id))
    if status is None:
        await call.message.edit_text(f"Ошибка при запросе статуса. Попробуйте позже.", reply_markup=client_kb.crypto_recheck_kb(call_data, bot_url), parse_mode="HTML")
        return

    if status == "paid":
        if call.data.startswith("crypto_api_check_pay_"):
            await database.execute(
                "UPDATE bookings SET paid_think = 'crypto', condition = 'paid', crypto_invoice = ?, crypto_bot_url = ?, crypto_status = ? WHERE id = ?",
                (invoice_id, bot_url, "paid", idbook))
            date_d, end_t_str, barber_name = await database.fetch_one(
                """SELECT date, start_time, barber_name FROM bookings WHERE id = ?""", (idbook,))
            date_d = date.fromisoformat(date_d)
        else:
            # 1. Создаем бронь через сервис
            date_d, end_t_str, barber_name, idbook = await services.create_booking(call.from_user.id, date_d_str, date_t_str, 'paid', 'crypto')
            # 2. Профессиональное уведомление барбера
            if idbook:
                try:
                    # Надежно получаем ID барбера по ID созданной брони
                    barber_row = await database.fetch_one(
                        """SELECT b.telegram_id
                           FROM bookings k
                           JOIN barbers b ON k.barber_id = b.id
                           WHERE k.id = ?""",
                        (idbook,)
                    )
                    if barber_row and barber_row[0]:
                        barber_tg_id = barber_row[0]
                        user_link = f"@{call.from_user.username}" if call.from_user.username else f"ID:{call.from_user.id}"
                        msg_to_barber = (
                            f"💰 <b>Новая оплаченная запись (Crypto)!</b>\n"
                            f"👤 Клиент: {user_link}\n"
                            f"🗓 Дата: {date_d.day}.{date_d.month}.{date_d.year}\n"
                            f"⏰ Время: {date_t_str} - {end_t_str}"
                        )
                        # Отправляем от имени бота барбера
                        await loader.bot_barber.send_message(barber_tg_id, msg_to_barber, parse_mode="HTML")
                except Exception as e:
                    # Логируем ошибку, но не прерываем работу, чтобы клиент получил подтверждение
                    print(f"⚠️ Не удалось уведомить барбера о крипто-оплате: {e}")
            # 3. Обновляем статус инвойса в БД
            await database.execute("UPDATE bookings SET crypto_invoice = ?, crypto_bot_url = ?, crypto_status = ? WHERE id = ?", (invoice_id, bot_url, "paid", idbook))
            # 4. Финальный ответ клиенту
        text = f"✅ Оплата подтверждена — бронь создана.\nДата: {date_d.day}.{date_d.month}.{date_d.year}\nВремя: {date_t_str} - {end_t_str}\nМастер: {barber_name}"
        await call.message.edit_text(text=text, reply_markup=client_kb.success_kb(), parse_mode="HTML")
        return
    else:
        await call.message.edit_text(
            f"Статус счета: {status}. Если оплатили — дождитесь уведомления или попробуйте позже.",
            reply_markup=client_kb.crypto_recheck_kb(call_data, bot_url), parse_mode="HTML")
        return

@dp.callback_query(F.data.startswith("pay_telegram_stars_"))
async def set_pay_telegram_stars(call: CallbackQuery):
    if call.data.startswith("pay_telegram_stars_after_"):
        date_d_str, date_t_str, idbook = call.data[len("pay_payments_stars_after_"):].split("_")
        after_id = idbook
    else:
        after_id = -1
        date_d_str, date_t_str = call.data[len("pay_telegram_stars_"):].split("_")
    date_d = date.fromisoformat(date_d_str)
    date_t = services.str_to_time(date_t_str)
    barber_id, service_id = map(int,
                                await database.fetch_one("SELECT choose, any_service FROM users WHERE name = ?",
                                                         (call.from_user.id,)))
    duration, price = map(int, await database.fetch_one("SELECT duration, price FROM services WHERE id = ?",
                                                        (service_id,)))
    # Если "Любой" барбер, выбираем первого доступного
    selected_barber_id = barber_id
    if barber_id == -1:
        available_barbers = await services.get_available_barbers_for_slot(service_id, date_d, date_t_str, duration)
        if not available_barbers:
            await call.message.edit_text("Ошибка: нет доступных мастеров на это время.")
            return
        selected_barber_id = available_barbers[0][0]  # Берем ID первого доступного

    barber_name = await database.fetch_one("SELECT name FROM barbers WHERE id = ?", (selected_barber_id,))[0]
    service_name = (await database.fetch_one("SELECT name FROM services WHERE id = ?", (service_id,)))[0]

    str_date_t = services.time_to_str(date_t)
    data = {"usr_id": call.from_user.id, "date": date_d.isoformat(), "start_time": str_date_t, "after_id": after_id}
    await bot.send_invoice(
        chat_id=call.message.chat.id,
        title=f"BarberToClient",
        description=f"{barber_name}: {str_date_t} {date_d.year}-{date_d.month}-{date_d.day} | {service_name}",
        payload=json.dumps(data),  # Здесь все данные для идентификации после оплаты
        currency="XTR",  # Для Telegram Stars
        prices=[LabeledPrice(label='RUB', amount=price)],  # amount - целое число звёзд
        start_parameter="pay"  # Опционально
    )
    return

@dp.callback_query(F.data.startswith("book_100_for_"))
async def set_book_100_for(call: CallbackQuery):
    date_d_str, date_t_str = call.data[len("book_100_for_"):].split("_")
    date_d, end_t_str, barber_name, idbook = await services.create_booking(
        call.from_user.id, date_d_str, date_t_str, 'book'
    )
    if not idbook:
        await call.answer("Ошибка бронирования (время занято).", show_alert=True)
        return

    # Уведомление барберу (так как services.py это не делает для чистоты)
    # Получаем ID барбера из базы по брони или возвращаем его из create_booking
    # Для простоты можно оставить как есть, если services.py не возвращает TG ID.
    # Рекомендую добавить в services.py возврат TG ID барбера, или запросить здесь:
    # Но чтобы код работал сразу:
    try:
        # 1. Получаем ID барбера из базы
        bid = (await database.fetch_one("SELECT barber_id FROM bookings WHERE id=?", (idbook,)))[0]
        # 2. Получаем TG ID барбера
        btg = (await database.fetch_one("SELECT telegram_id FROM barbers WHERE id=?", (bid,)))[0]

        # --- [ЗАПОЛНИЛИ ВЕРХНИЙ, УДАЛИЛИ НИЖНИЙ] ---

        # Красивое имя клиента
        user_name = f"@{call.from_user.username}" if call.from_user.username else f"ID: {call.from_user.id}"

        msg_to_barber = (
            f"📝 <b>Новая запись!</b>\n"
            f"👤 Клиент: {user_name}\n"
            f"🗓 Дата: {date_d.day}.{date_d.month}.{date_d.year}\n"
            f"⏰ Время: {date_t_str} - {end_t_str}\n"
            f"💳 Тип: <b>Оплата на месте</b>"
        )

        # Отправляем красивое сообщение
        await loader.bot_barber.send_message(btg, msg_to_barber, parse_mode="HTML")

        # -------------------------------------------

    except Exception as e:
        print(f"Ошибка отправки барберу: {e}")

        # Подтверждение клиенту
    text = f"✅ Бронирование успешно!\nДата: {date_d.day}.{date_d.month}.{date_d.year}\nВремя: {date_t_str} - {end_t_str}\nМастер: {barber_name}"
    await call.message.edit_text(text, reply_markup=client_kb.success_kb(), parse_mode="HTML")
    return




@dp.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    # Здесь можно добавить проверку (например, если слот ещё свободен), но для простоты просто подтверждаем
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True, error_message="")  # ok=True для подтверждения

@dp.message(F.content_type == "successful_payment")
async def successful_payment(message: Message):
    payment = message.successful_payment

    payload_str = message.successful_payment.invoice_payload
    try:
        data = json.loads(payload_str)  # Распарсим данные
    except json.JSONDecodeError:
        await message.answer("Ошибка обработки платежа. Свяжитесь с поддержкой.")
        return

    usr_id = data["usr_id"]
    date_d_str = data["date"]
    date_t_str = data["start_time"]
    idbook = data["after_id"]
    if payment.currency == "XTR":
        paid_think = 'stars'
    else:
        paid_think = 'card'

    if idbook == -1:
        # Стало (исправление):
        date_d, end_t_str, barber_name, idbook = await services.create_booking(usr_id, date_d_str, date_t_str, 'paid', paid_think)
    else:
        await database.execute("UPDATE bookings SET paid_think = ?, condition = ? WHERE id = ?",
                               (paid_think, 'paid', int(idbook)))
        date_d, end_t_str, barber_name, service_name, duration, price, google_event_id = await database.fetch_one(
            """SELECT date, start_time, barber_name, service_name, duration, price, google_event_id FROM bookings WHERE id = ?""",
            (idbook,))
        date_d = date.fromisoformat(date_d)

        # --- GOOGLE CALENDAR: Если события нет, создаем ---
        if not google_event_id:
            new_gid = await GoogleCalendar.create_event(barber_name, service_name, f"@{message.from_user.username}",
                                                        data["date"], data["start_time"], duration, price)
            await database.execute("UPDATE bookings SET google_event_id = ? WHERE id = ?", (new_gid, int(idbook)))
        # --------------------------------------------------

    if idbook is None:
        await message.answer("Ошибка при бронировании. Платеж будет возвращен автоматически.")
        return

    if payment.currency == "XTR":
        charge_id = message.successful_payment.telegram_payment_charge_id
    else:
        charge_id = message.successful_payment.provider_payment_charge_id
    await database.execute("UPDATE bookings SET telegram_payment_charge_id = ? WHERE id = ?", (charge_id, idbook))

    # Подтверждение
    try:
        # 1. Получаем ID барбера из брони
        barber_id_row = await database.fetch_one("SELECT barber_id FROM bookings WHERE id=?", (int(idbook),))
        if barber_id_row:
            bid = barber_id_row[0]
            # 2. Получаем Telegram ID барбера
            tg_row = await database.fetch_one("SELECT telegram_id FROM barbers WHERE id=?", (bid,))
            if tg_row:
                barber_tg_id = tg_row[0]
                # 3. Формируем текст (используем переменные, которые уже есть в функции: date_d, date_t_str, end_t_str)
                user_name = f"@{message.from_user.username}" if message.from_user.username else f"ID: {message.from_user.id}"
                msg_to_barber = (f"💰 <b>Новая оплаченная запись!</b>\n"
                    f"👤 Клиент: {user_name}\n🗓 Дата: {date_d.day}.{date_d.month}.{date_d.year}\n"
                    f"⏰ Время: {date_t_str} - {end_t_str}\n💳 Тип оплаты: {paid_think}")
                # 4. Отправляем сообщение барберу
                await loader.bot_barber.send_message(barber_tg_id, msg_to_barber, parse_mode="HTML")
    except Exception as e: print(f"⚠️ Не удалось уведомить барбера об оплате: {e}")
    text = f"\nДата: {date_d.day}.{date_d.month}.{date_d.year}\nВремя: {date_t_str} - {end_t_str}\nМастер: {barber_name}"
    await message.answer(f"✅ Оплата прошла успешно! {text}", reply_markup=client_kb.success_kb(), parse_mode="HTML")

# --- Старый main можно оставить для локальных тестов, но через barbershopbot работает dp.startup ---
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped by user.")