# client_kb.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import date, timedelta
from calendar import monthrange
import random


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def _create_markup(buttons, width=1):
    """Разбивает список кнопок на ряды."""
    keyboard = []
    row = []
    for btn in buttons:
        row.append(btn)
        if len(row) == width:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return keyboard


def _back_btn(callback_data):
    """Возвращает кнопку Назад как список."""
    return [InlineKeyboardButton(text="🔙 Назад", callback_data=callback_data)]


# --- 1. ГЛАВНОЕ МЕНЮ ---
def main_menu(services_data):
    buttons = []
    for sid, name, price in services_data:
        buttons.append(InlineKeyboardButton(text=f"{name} ({price}₽)", callback_data=f"service_{sid}"))
    
    keyboard = _create_markup(buttons, width=2)
    keyboard.append([InlineKeyboardButton(text="📅 Мои записи", callback_data="my_book")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# --- 2. СПИСОК БРОНЕЙ ---
def my_bookings(bookings_list):
    keyboard = []
    for idx, booking in enumerate(bookings_list, 1):
        # Распаковка согласно вашему SQL: id, barber_id, service_id, date, start_time, barber_name, ...
        idbook = booking[0]
        date_d = booking[3]
        time_t = booking[4]
        b_name = booking[5]
        s_name = booking[6]
        
        keyboard.append([InlineKeyboardButton(
            text=f"{idx}. {b_name} | {s_name} | {date_d} {time_t}",
            callback_data=f"sett_book_{idbook}"
        )])
    
    keyboard.append(_back_btn("mainMenu"))
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# --- 3. НАСТРОЙКИ БРОНИ ---
def booking_settings(idbook, show_cancel=True, is_unpaid_book=False, date_d=None, date_t=None):
    kb = []
    
    # Действия
    actions = []
    if show_cancel:
        actions.append(InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_book_{idbook}"))
    actions.append(InlineKeyboardButton(text="🔄 Перенести", callback_data=f"chooseMonth_change_{idbook}"))
    kb.append(actions)
    
    # Оплата
    if is_unpaid_book and date_d and date_t:
        cb_pay = f"pay_online_for_after_{date_d}_{date_t}_{idbook}"
        kb.append([InlineKeyboardButton(text="💳 Оплатить", callback_data=cb_pay)])
    
    kb.append(_back_btn("my_book"))
    return InlineKeyboardMarkup(inline_keyboard=kb)


# --- 4. ПОДТВЕРЖДЕНИЕ ОТМЕНЫ ---
def cancel_confirm(idbook, condition):
    kb = []
    if condition == 'paid':
        kb.append([InlineKeyboardButton(text="💸 Вернуть деньги", callback_data=f"money_back_{idbook}")])
    else:
        kb.append([InlineKeyboardButton(text="✅ Да, отменить", callback_data=f"mainMenu_really_{idbook}")])
    
    kb.append([InlineKeyboardButton(text="🔙 Нет, назад", callback_data=f"sett_book_{idbook}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


# --- 5. ВЫБОР БАРБЕРА ---
def barbers_kb(barbers_data, service_id):
    buttons = []
    for bid, name in barbers_data:
        buttons.append(InlineKeyboardButton(text=name, callback_data=f"chooseMonth_{bid}_{service_id}"))
    
    keyboard = _create_markup(buttons, width=2)
    keyboard.append([InlineKeyboardButton(text="⚡️ Любой мастер", callback_data=f"chooseMonth_{-1}_{service_id}")])
    keyboard.append(_back_btn("mainMenu"))
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def barbers_for_time_kb(barbers_data, date_str, time_str):
    """
    Показывает список мастеров, доступных в выбранное время.
    Также добавляет кнопку 'Любой мастер', которая выбирает случайного из доступных.
    """
    buttons = []
    for bid, name in barbers_data:
        cb = f"chooseBarber_{date_str}_{time_str}_{bid}"
        buttons.append(InlineKeyboardButton(text=f"👤 {name}", callback_data=cb))
    
    # Мастера по 2 в ряд
    keyboard = _create_markup(buttons, width=2)
    
    # --- КНОПКА "ЛЮБОЙ МАСТЕР" ---
    if barbers_data:
        # Выбираем случайного мастера из списка доступных
        random_barber = random.choice(barbers_data)
        random_id = random_barber[0]
        
        # Формируем колбэк с ID этого случайного мастера
        # Для пользователя это "Любой", а для базы данных - конкретный человек (чтобы не было ошибок)
        any_cb = f"chooseBarber_{date_str}_{time_str}_{random_id}"
        
        keyboard.append([InlineKeyboardButton(text="⚡️ Любой мастер", callback_data=any_cb)])
    # -----------------------------
    
    # Кнопка назад возвращает к выбору даты (перезагрузка слотов)
    back_cb = f"chooseDate_{date_str}"
    keyboard.append(_back_btn(back_cb))
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# --- 6. КАЛЕНДАРЬ ---
def calendar_kb(year, month, service_id, idbook=None):
    days_in_month = monthrange(year, month)[1]
    today = date.today()
    first_day = today.day if (year == today.year and month == today.month) else 1
    
    buttons = []
    for day in range(first_day, days_in_month + 1):
        full_date = date(year, month, day).isoformat()
        if idbook:
            cb = f"chooseDate_change_{full_date}_{idbook}"
        else:
            cb = f"chooseDate_{full_date}"
        buttons.append(InlineKeyboardButton(text=str(day), callback_data=cb))
    
    inline = _create_markup(buttons, width=5)
    
    # Навигация
    nav = []
    if not (year == today.year and month == today.month):
        prev = date(year, month, 1) - timedelta(days=1)
        suffix = f"_{service_id}_{idbook}" if idbook else f"_{service_id}"
        cb_type = "changeMonth_change" if idbook else "changeMonth"
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{cb_type}_{prev}{suffix}"))
    
    next_d = date(year, month, days_in_month) + timedelta(days=1)
    suffix = f"_{service_id}_{idbook}" if idbook else f"_{service_id}"
    cb_type = "changeMonth_change" if idbook else "changeMonth"
    nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{cb_type}_{next_d}{suffix}"))
    
    inline.append(nav)
    
    # Выход
    
    if idbook: back_target = f"sett_book_{idbook}"
    else: back_target = f"service_{service_id}"
    inline.append(_back_btn(back_target))
    return InlineKeyboardMarkup(inline_keyboard=inline)


# --- 7. ВРЕМЕННЫЕ СЛОТЫ (ИСПРАВЛЕНО) ---
def time_slots_kb(slots, date_str, idbook=None, service_id=None):
    buttons = []
    for t in slots:
        if idbook:
            cb = f"chooseTime_change_{date_str}_{t}_{idbook}"
        else:
            cb = f"chooseTime_{date_str}_{t}"
        buttons.append(InlineKeyboardButton(text=t, callback_data=cb))
    
    inline = _create_markup(buttons, width=4)
    
    # ЛОГИКА КНОПКИ НАЗАД
    # Чтобы вернуться в календарь, нам нужен changeMonth_{date}_{service_id}
    # Если service_id не передан, мы не можем сформировать правильную ссылку.
    
    if idbook:
        # Для переноса (тут service_id обычно достается из базы в changeMonth_change, но лучше передать)
        # Если service_id None, кнопка может не сработать идеально, но попробуем IDBOOK
        back_cb = f"chooseMonth_change_{idbook}"
    else:
        if service_id:
            # Правильный возврат в календарь
            back_cb = f"changeMonth_{date_str}_{service_id}"
        else:
            # АВАРИЙНЫЙ возврат (если вы забыли обновить BarberToClient.py)
            # Возвращаем просто перезагрузку даты, чтобы не крашилось
            back_cb = f"chooseDate_{date_str}"
    
    inline.append([InlineKeyboardButton(text="🔙 Назад к датам", callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=inline)


# --- 8. ПОДТВЕРЖДЕНИЕ ПЕРЕНОСА ---
def confirm_reschedule(date_d, date_t, duration, idbook, old_date_iso):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить перенос", callback_data=f"sett_book_change_{date_d}_{date_t}_{duration}_{idbook}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"chooseDate_change_{old_date_iso}_{idbook}")]
    ])


# --- 9. ВЫБОР МЕТОДА ОПЛАТЫ ---
def payment_method_choice(date_str, time_str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💳 Оплатить онлайн", callback_data=f"pay_online_for_{date_str}_{time_str}"),
            InlineKeyboardButton(text="📍 Оплата на месте", callback_data=f"book_100_for_{date_str}_{time_str}")
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"chooseDate_{date_str}")]
    ])


# --- 10. ВЫБОР ПЛАТЕЖНОЙ СИСТЕМЫ ---
def payment_gateway_choice(date_str, time_str, idbook=None):
    kb = []
    if idbook:
        suffix = f"_after_{date_str}_{time_str}_{idbook}"
        back_cb = f"sett_book_{idbook}"
    else:
        suffix = f"_{date_str}_{time_str}"
        # Назад возвращает к выбору "Онлайн/На месте"
        back_cb = f"pay_online_for{suffix}"
    
    kb.append([
        InlineKeyboardButton(text="🪙 Криптовалюта", callback_data=f"pay_crypto{suffix}"),
        InlineKeyboardButton(text="⭐️ Telegram Stars", callback_data=f"pay_telegram_stars{suffix}")
    ])
    kb.append([InlineKeyboardButton(text="💵 Карточкой (UAH)", callback_data=f"pay_payments{suffix}")])
    kb.append(_back_btn(back_cb))
    return InlineKeyboardMarkup(inline_keyboard=kb)


# --- 11. КРИПТО ИНВОЙС ---
def crypto_actions_kb(date_str, time_str, idbook=None, bot_url=None):
    kb = []
    if idbook:
        suffix = f"_after_{date_str}_{time_str}_{idbook}"
        check_cb = f"crypto_api_check_pay_{idbook}"
        retry_cb = f"pay_crypto{suffix}"
        back_cb = f"pay_online_for{suffix}"
    else:
        suffix = f"_{date_str}_{time_str}"
        check_cb = "crypto_api_check_"
        retry_cb = f"pay_crypto{suffix}"
        back_cb = f"pay_online_for{suffix}"
    
    if bot_url:
        kb.append([InlineKeyboardButton(text="💳 Открыть оплату", url=bot_url)])
        kb.append([InlineKeyboardButton(text="🔄 Проверить статус", callback_data=check_cb)])
    else:
        kb.append([InlineKeyboardButton(text="♻️ Попробовать снова", callback_data=retry_cb)])
    
    kb.append(_back_btn(back_cb))
    return InlineKeyboardMarkup(inline_keyboard=kb)


# --- ОСТАЛЬНЫЕ ФУНКЦИИ ---
def crypto_recheck_kb(call_data):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="♻️ Перепроверить статус", callback_data=call_data)]])


def success_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В главное меню", callback_data="mainMenu")]])


def back_to_main():
    return InlineKeyboardMarkup(inline_keyboard=[_back_btn("mainMenu")])


def back_to_booking(idbook):
    return InlineKeyboardMarkup(inline_keyboard=[_back_btn(f"sett_book_{idbook}")])


def back_to_date(date_str, idbook=None):
    cb = f"chooseDate_change_{date_str}_{idbook}" if idbook else f"chooseDate_{date_str}"
    return InlineKeyboardMarkup(inline_keyboard=[_back_btn(cb)])