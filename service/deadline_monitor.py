import logging
from datetime import date, timedelta
from html import escape
from config import TELEGRAM_USER_ID
from service.jira_client import get_my_tasks
from service.notification_store import (notification_was_sent, mark_notification_sent)

logger = logging.getLogger(__name__)


async def get_upcoming_deadlines(days=3):
    tasks = await get_my_tasks()
    today = date.today()
    limit_date = today + timedelta(days=days)
    upcoming = []
    for task in tasks:
        deadline = task.get("deadline")
        if not deadline:
            continue
        deadline_date = date.fromisoformat(deadline)
        if today <= deadline_date <= limit_date:
            days_left = (deadline_date - today).days
            upcoming.append((task, days_left))

    return upcoming


async def check_deadlines(bot):
    logger.info("Запущена автоматическая проверка дедлайнов")

    try:
        tasks = await get_my_tasks()
        tomorrow = date.today() + timedelta(days=1)
        for task in tasks:
            deadline = task.get("deadline")
            if not deadline:
                continue

            deadline_date = date.fromisoformat(deadline)

            if deadline_date != tomorrow:
                continue

            if notification_was_sent(task["key"], deadline):
                continue
            message = (
                "🔔 <b>Напоминание о дедлайне</b>\n\n"
                f"<b>{escape(task['key'])} — ближайшие 3 дня</b>\n"
                f"Срок выполнения: {deadline}\n"
                "До дедлайна остался 1 день. "
                "Не забудь завершить задачу!"
            )
            await bot.send_message(chat_id=TELEGRAM_USER_ID, text=message)
            mark_notification_sent(task["key"], deadline)
            logger.info("Отправлено напоминание: %s, дедлайн %s", task["key"],deadline)

    except Exception:
        logger.exception("Ошибка при проверке дедлайнов")
