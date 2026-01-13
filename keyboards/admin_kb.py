from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- 1. НАСТРОЙКИ ТЕКСТА (Меняем всё тут) ---
BTN_TEXTS = {
    "add": "➕ Добавить",
    "delete": "🗑️ Удалить",
    "back_menu": "🏠 В главное меню",
    "back": "⬅️ Назад",
    "cancel": "🚫 Отмена",
    "services_btn": "🛠️ Услуги",
    "confirm_yes": "✅ Да, удалить",
    "confirm_no": "❌ Нет, оставить",
    "refresh": "🔄 Обновить",
    "next": "Далее ▶️",
    "prev": "◀️ Назад",
    "details": "🔍 Подробнее",
    "price_edit": "✏️ Изм. цену"
}


# --- 2. ГЛАВНОЕ МЕНЮ ---
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="menu_stats"),
         InlineKeyboardButton(text="👥 Барберы", callback_data="menu_barbers")],
        [InlineKeyboardButton(text="🛠️ Услуги", callback_data="menu_services"),
         InlineKeyboardButton(text="💰 Цены", callback_data="menu_prices")]
    ])


# --- 3. КНОПКИ ДЕЙСТВИЙ (Универсальные, но текст внутри) ---

def cancel(callback_data: str):
    """Просто кнопка отмены. Текст берется из констант."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_TEXTS["cancel"], callback_data=callback_data)]
    ])


def back_to_main():
    """Возврат в главное меню"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_TEXTS["back_menu"], callback_data="back_main")]
    ])


def back_custom(callback_data: str):
    """Кнопка 'Назад' (например, к списку барберов), текст стандартный"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_TEXTS["back"], callback_data=callback_data)]
    ])


def confirm_delete(yes_data: str, no_data: str):
    """Подтверждение удаления"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_TEXTS["confirm_yes"], callback_data=yes_data),
         InlineKeyboardButton(text=BTN_TEXTS["confirm_no"], callback_data=no_data)]
    ])


# --- 4. СПИСКИ ---

def barbers_list(barbers_rows):
    # barbers_rows = [(id, name), ...]
    kb_rows = [[InlineKeyboardButton(text=BTN_TEXTS["add"], callback_data="barber_add")]]

    for bid, name in barbers_rows:
        kb_rows.append([
            InlineKeyboardButton(text=f"{BTN_TEXTS['delete']} {name}", callback_data=f"barber_delete_{bid}"),
            InlineKeyboardButton(text=f"{BTN_TEXTS['services_btn']}: {name}", callback_data=f"barber_services_{bid}")
        ])

    kb_rows.append([InlineKeyboardButton(text=BTN_TEXTS["back_menu"], callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)


def services_list(services_rows):
    # services_rows = [(id, name, price), ...]
    kb_rows = [[InlineKeyboardButton(text=BTN_TEXTS["add"], callback_data="service_add")]]

    for sid, name, *_ in services_rows:
        kb_rows.append([
            InlineKeyboardButton(text=f"{BTN_TEXTS['delete']} {name}", callback_data=f"service_delete_{sid}")
        ])

    kb_rows.append([InlineKeyboardButton(text=BTN_TEXTS["back_menu"], callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)


def prices_list(services_rows):
    kb_rows = []
    for sid, name, *_ in services_rows:
        kb_rows.append([
            InlineKeyboardButton(text=f"{BTN_TEXTS['price_edit']} — {name}", callback_data=f"price_change_{sid}")
        ])
    kb_rows.append([InlineKeyboardButton(text=BTN_TEXTS["back_menu"], callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)


# --- 5. УСЛУГИ БАРБЕРА ---

def manage_barber_services(barber_id, all_services, assigned_ids):
    kb = []
    row = []
    for sid, name in all_services:
        if sid in assigned_ids:
            action, icon = "remove", "✅"  # Галочка, т.к. уже есть
        else:
            action, icon = "add", "❌"  # Пустой квадрат, т.к. нет

        row.append(InlineKeyboardButton(
            text=f"{icon} {name}",
            callback_data=f"barber_service_{action}_{barber_id}_{sid}"
        ))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row: kb.append(row)

    # Кнопка назад ведет к списку барберов
    kb.append([InlineKeyboardButton(text=BTN_TEXTS["back"], callback_data="menu_barbers")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


# --- 6. СТАТИСТИКА ---

def stats_menu(period, page, displayed_barbers, has_prev, has_next):
    kb_rows = [
        [InlineKeyboardButton(text="За всё время", callback_data="stats_period_all_0"),
         InlineKeyboardButton(text="За месяц", callback_data="stats_period_month_0")],
        [InlineKeyboardButton(text="За неделю", callback_data="stats_period_week_0")],
    ]

    # Кнопки барберов
    barber_btns = []
    for bid, name in displayed_barbers:
        barber_btns.append(InlineKeyboardButton(
            text=f"{BTN_TEXTS['details']} — {name}",
            callback_data=f"stats_barber_{bid}_{period}_{page}"
        ))
    for i in range(0, len(barber_btns), 2):
        kb_rows.append(barber_btns[i:i + 2])

    # Пагинация
    pag_row = []
    if has_prev:
        pag_row.append(InlineKeyboardButton(text=BTN_TEXTS["prev"], callback_data=f"stats_period_{period}_{page - 1}"))
    if has_next:
        pag_row.append(InlineKeyboardButton(text=BTN_TEXTS["next"], callback_data=f"stats_period_{period}_{page + 1}"))
    if pag_row: kb_rows.append(pag_row)

    kb_rows.append([
        InlineKeyboardButton(text=BTN_TEXTS["refresh"], callback_data=f"stats_period_{period}_{page}"),
        InlineKeyboardButton(text=BTN_TEXTS["back_menu"], callback_data="stats_back")
    ])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)


def barber_stats_back(period, page):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_TEXTS["back"], callback_data=f"stats_period_{period}_{page}"),
         InlineKeyboardButton(text=BTN_TEXTS["back_menu"], callback_data="back_main")]
    ])