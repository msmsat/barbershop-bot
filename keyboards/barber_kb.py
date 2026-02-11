# barber_kb.py
from datetime import date, timedelta
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from calendar import monthrange


def _btn(text: str, callback_data: str) -> InlineKeyboardButton:
    """Вспомогательная функция для сокращения кода"""
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def _back_btn(callback_data: str = "main_menu") -> InlineKeyboardButton:
    """Стандартная кнопка назад"""
    text = "🔙 Главное меню" if callback_data == "main_menu" else "🔙 Назад"
    return _btn(text, callback_data)


# --- ГЛАВНОЕ МЕНЮ ---

# barber_kb.py

# Добавляем аргумент reminders_status (1 = вкл, 0 = выкл). По умолчанию 1.
def main_menu(reminders_status: int = 1) -> InlineKeyboardMarkup:
    # Определяем текст и иконку
    if reminders_status: text_reminders = "🔔 Напоминания: Вкл"
    else: text_reminders = "🔕 Напоминания: Выкл"

    keyboard = [[_btn("📅 Расписание дня", f"schedule_day_{date.today().isoformat()}"),
                 _btn("🛠️ Мои выходные", "offdays_view")],
                [_btn(text_reminders, "toggle_reminders")]]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def back_to_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_back_btn()]])


# --- РАСПИСАНИЕ И БРОНИ ---

def format_booking_label(bk_row) -> str:
    """Форматирование текста кнопки брони"""
    # bk_row: (id, usr_id, service_id, date, start_time, end_time, service_name, condition, price)
    try:
        _, _, _, _, start_t, end_t, service_name, condition, _ = bk_row
    except Exception:
        return "Неизвестная бронь"
    
    status_icon = "✅" if condition == 'paid' else ("↩️" if condition == 'refunded' else "⏳")
    return f"{start_t}-{end_t} | {service_name} | {status_icon}"


def day_schedule(show_date: date, bookings: list) -> InlineKeyboardMarkup:
    """Клавиатура просмотра расписания на день"""
    prev_day = show_date - timedelta(days=1)
    next_day = show_date + timedelta(days=1)
    
    # Навигация по дням
    nav_row = []
    if show_date > date.today():
        nav_row.append(_btn("⬅️ Предыдущий", f"schedule_day_{prev_day.isoformat()}"))
    nav_row.append(_btn("➡️ Следующий", f"schedule_day_{next_day.isoformat()}"))

    keyboard = [nav_row]
    
    # Список броней
    for bk in bookings:
        idb = bk[0]  # id брони
        btn_text = format_booking_label(bk)
        keyboard.append([_btn(btn_text, f"booking_{idb}")])
    
    keyboard.append([_back_btn("main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def booking_details(booking_id: int, condition: str, date_d: str) -> InlineKeyboardMarkup:
    """Действия с конкретной бронью"""
    keyboard = []
    
    # Кнопка отмены/возврата
    if condition == 'paid':
        keyboard.append([_btn("❌ Отменить бронь (с возвратом)", f"refund_booking_{booking_id}")])
    else:
        keyboard.append([_btn("❌ Отменить бронь", f"cancel_booking_{booking_id}")])
    
    # Кнопка назад к расписанию этого дня
    keyboard.append([_btn("🔙 Назад к дню", f"schedule_day_{date_d}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def cancel_confirmation(booking_id: int) -> InlineKeyboardMarkup:
    """Подтверждение отмены"""
    keyboard = [
        [_btn("✅ Да, отменить", f"cancel_confirm_{booking_id}")],
        [_btn("🔙 Нет, назад", f"booking_{booking_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def back_to_date(date_obj: date) -> InlineKeyboardMarkup:
    """Кнопка возврата к конкретной дате (используется после возврата средств)"""
    # Находим первое число месяца для возврата (как было в оригинале) или к конкретному дню
    # В оригинале было: date(dd.year, dd.month, 1), но логичнее вернуться к тому же дню.
    # Сделаем возврат к первому числу, как просили в оригинале, чтобы не ломать логику.
    target_date = date(date_obj.year, date_obj.month, 1)
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("⬅️ Назад к календарю", f"schedule_day_{target_date.isoformat()}")]
    ])


# --- ВЫХОДНЫЕ (OFF-DAYS) ---

def off_days_calendar(days_list: list, today: date, days_in_month: int, date_view: date, off_days: list = []) -> InlineKeyboardMarkup:
    """Генерация календаря для выбора выходных"""
    keyboard = []
    row = []
    
    # Сетка дней
    for d in days_list:
        if d > today:
            # Проверяем, есть ли дата в списке выходных (off_days)
            btn_text = f"🔴 {d.day}" if d.isoformat() in off_days else str(d.day)
            row.append(_btn(btn_text, f"offday_toggle_{d.isoformat()}"))
        
        if len(row) >= 5:  # 5 кнопок в ряд (красивее чем 4)
            keyboard.append(row)
            row = []
    
    if row:
        keyboard.append(row)
    
    # Навигация по месяцам
    nav_row = []
    # Проверка, чтобы не уйти в прошлое глубже текущего месяца
    if not (date_view.year == today.year and date_view.month == today.month):
        prev_month = date(date_view.year, date_view.month, 1) - timedelta(days=1)
        # Берем 1 число предыдущего месяца для корректного отображения
        prev_target = date(prev_month.year, prev_month.month, 1)
        nav_row.append(_btn("⬅️ Назад", f"offdays_view{prev_target.isoformat()}"))
        
    next_month = date(date_view.year, date_view.month, days_in_month) + timedelta(days=1)
    nav_row.append(_btn("➡️ Далее", f"offdays_view{next_month.isoformat()}"))
    
    keyboard.append(nav_row)
    
    # Действия
    keyboard.append([_btn("🗑️ Удалить все выходные", f"offdays_clear_all{date_view.isoformat()}")])
    keyboard.append([_back_btn("main_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
