# GoogleCalendar.py
import asyncio
import logging
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
import os
from dotenv import load_dotenv
load_dotenv()

CALENDAR_ID = os.getenv("CALENDAR_ID")
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDS_FILE")

SCOPES = ['https://www.googleapis.com/auth/calendar']
logger = logging.getLogger(__name__)


def get_service():
    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_FILE, scopes=SCOPES)
    service = build('calendar', 'v3', credentials=creds)
    return service


def _sync_create_event(barber_name, service_name, client_info, date_str, time_str, duration_minutes, price):
    """Создает событие и возвращает его ID"""
    try:
        service = get_service()

        # Парсим дату и время начала
        start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        event_body = {
            'summary': f"{barber_name}: {service_name}",
            'description': f"Клиент: {client_info}\nЦена: {price}₽\nУслуга: {service_name}",
            'start': {
                'dateTime': start_dt.isoformat(),
                'timeZone': 'Europe/Prague',  # Или Europe/Moscow, важно для корректного отображения
            },
            'end': {
                'dateTime': end_dt.isoformat(),
                'timeZone': 'Europe/Prague',
            },
            'colorId': '1',  # Красный цвет (можно менять от 1 до 11)
        }

        event = service.events().insert(calendarId=CALENDAR_ID, body=event_body).execute()
        logger.info(f"[GoogleCalendar] Created event: {event.get('htmlLink')}")
        return event['id']

    except Exception as e:
        logger.error(f"[GoogleCalendar] Error creating event: {e}")
        return None


def _sync_delete_event(event_id):
    """Удаляет событие по ID"""
    try:
        if not event_id: return
        service = get_service()
        service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
        logger.info(f"[GoogleCalendar] Deleted event {event_id}")
    except Exception as e:
        logger.error(f"[GoogleCalendar] Error deleting event: {e}")


# Асинхронные обертки
async def create_event(barber_name, service_name, client_info, date_str, time_str, duration_minutes, price):
    return await asyncio.to_thread(_sync_create_event, barber_name, service_name, client_info, date_str, time_str,
                                   duration_minutes, price)


async def delete_event(event_id):
    return await asyncio.to_thread(_sync_delete_event, event_id)