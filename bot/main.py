import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config import TELEGRAM_BOT_TOKEN
from bot.handlers import router
from service.notification_store import init_db
from service.deadline_monitor import check_deadlines
import uvicorn
from bot.oauth_server import app as oauth_app
from service.user_store import init_user_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def set_bot_commands(bot):
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="help", description="Список команд"),
        BotCommand(command="connect", description="Подключить Jira"),
        BotCommand(command="jira_status", description="Статус подключения Jira"),
        BotCommand(command="projects", description="Выбрать проект Jira"),
        BotCommand(command="my_tasks", description="Мои незавершённые задачи"),
        BotCommand(command="deadlines", description="Посмотреть дедлайны"),
        BotCommand(command="check_now", description="Проверить дедлайны сейчас"),
        BotCommand(command="create_task", description="Создать задачу"),
        BotCommand(command="change_status", description="Изменить статус задачи"),
        BotCommand(command="notifications", description="История уведомлений"),
    ]

    await bot.set_my_commands(commands)


async def main():
    bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    init_user_db()

    oauth_server = uvicorn.Server(uvicorn.Config(oauth_app, host="0.0.0.0", port=8000, log_level="info"))
    oauth_task = asyncio.create_task(oauth_server.serve())

    @dp.message(CommandStart())
    async def start(message: Message):
        await message.answer(
            "<b>Привет! Я JiraBot.</b>\n\n"
            "Я помогаю управлять проектами, просматривать задачи и следить за сроками их выполнения. "
            "Со мной вы сможете создавать новые задачи, менять их статусы и получать напоминания о "
            "приближающихся дедлайнах.\n\n"
            "Подключите свой аккаунт в Jira, выберите проект и начните работу прямо сейчас!"
        )

    @dp.message(Command("help"))
    async def help_message(message: Message):
        await message.answer(
            "<b>Список доступных команд: </b>\n\n"
            "/connect — подключить аккаунт Jira\n"
            "/projects — получить список проектов\n"
            "/my_tasks — получить список задач\n"
            "/deadlines — посмотреть состояние дедлайнов\n"
            "/check_now — сведения о приближающихся дедлайнах\n"
            "/create_task — создать задачу\n"
            "/change_status — изменить статус задачи\n"
            "/jira_status — проверить подключение аккаунта\n"
            "/help — получить список команд"
        )

    init_db()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_deadlines, trigger="interval", minutes=15, args=[bot], id="deadline_check",
                      replace_existing=True,  next_run_time=datetime.now())

    scheduler.start()
    logging.info("Бот запущен. Проверка дедлайнов каждые 15 минут")

    try:
        await set_bot_commands(bot)
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        oauth_server.should_exit = True
        await oauth_task
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

# python -m bot.main
