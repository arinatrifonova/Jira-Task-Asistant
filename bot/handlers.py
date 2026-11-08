from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from service.jira_client import get_projects
from service.user_store import (get_selected_project, set_selected_project)
from service.jira_client import get_my_tasks
from service.notification_store import get_sent_notifications
from service.deadline_monitor import get_upcoming_deadlines
from service.jira_client import (create_task, get_issue_transitions, change_task_status)
from service.auth_service import create_authorization_url
from service.user_store import get_user
from html import escape
from datetime import date, timedelta
import logging
from config import TELEGRAM_USER_ID

router = Router()


class CreateTaskStates(StatesGroup):
    waiting_summary = State()
    waiting_deadline = State()
    waiting_custom_deadline = State()
    confirming = State()


logger = logging.getLogger(__name__)


def is_authorized(message):
    return get_user(message.from_user.id) is not None


async def delete_message(message: Message):
    try:
        await message.delete()
    except Exception:
        pass


@router.message(Command("projects"))
@router.message(Command("switch_project"))
async def show_projects(message: Message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if not user:
        await message.answer("Сначала подключите аккаунт Jira командой /connect")
        return

    await message.answer("Получаю список проектов Jira...")
    try:
        projects = await get_projects(telegram_id)
    except Exception as error:
        logging.exception("Ошибка получения проектов Jira")
        await message.answer(
            f"Не удалось получить проекты Jira\n"
            f"Тип ошибки: {type(error).__name__}\n"
        )
        return

    if not projects:
        await message.answer("Не найдено доступных проектов Jira")
        return

    selected_key = get_selected_project(telegram_id)
    buttons = []
    for project in projects[:50]:
        project_key = project["key"]
        project_name = project["name"]
        prefix = "✓ " if project_key == selected_key else ""
        buttons.append([InlineKeyboardButton(text=f"{prefix}{project_name} ({project_key})",
                callback_data=f"project_select:{project_key}")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer("Выберите проект:\n\n", reply_markup=keyboard)


@router.callback_query(lambda callback: callback.data.startswith("project_select:"))
async def select_project(callback: CallbackQuery):
    telegram_id = callback.from_user.id
    user = get_user(telegram_id)
    if not user:
        await callback.answer("Сначала подключите аккаунт Jira через /connect.", show_alert=True)
        return

    project_key = callback.data.split(":", 1)[1]

    try:
        projects = await get_projects(telegram_id)
        selected_project = next((
            project for project in projects
            if project["key"] == project_key),
            None)

        if not selected_project:
            await callback.answer("Этот проект недоступен вашему аккаунту Jira", show_alert=True)
            return

        saved = set_selected_project(telegram_id, project_key)

        if not saved:
            await callback.answer("Не удалось сохранить проект.",show_alert=True)
            return

        await callback.message.edit_text(
            f"<b>Вы выбрали проект {selected_project['name']}.</b>\n\n"
            "Теперь я буду работать именно с этим проектом")
        await callback.answer("Проект выбран!")

    except Exception:
        logging.exception("Ошибка выбора проекта Jira")

        await callback.answer("Не удалось выбрать проект. Попробуйте позже.", show_alert=True)


@router.message(Command("my_tasks"))
async def show_my_tasks(message: Message):
    loading_message = await message.answer("Загружаю актуальные задачи из Jira...")
    try:
        telegram_id = message.from_user.id
        project_key = get_selected_project(telegram_id)
        if not project_key:
            await message.answer("Для того, чтобы начать работу с ботом, выберите проект Jira командой /projects")
            return
        tasks = await get_my_tasks(telegram_id, project_key)

        if not tasks:
            await message.answer("У вас нет завершенных задач в этом проекте!")
            return

        result = ["<b>Ваши незавершённые задачи:</b>\n"]

        for task in tasks:
            deadline = task["deadline"] or "Не указан"
            result.append(
                f"<b>{escape(task['key'])}</b> — {escape(task['summary'])}\n"
                f"Статус: {escape(task['status'])}\n"
                f"Дедлайн: {escape(deadline)}\n"
            )
        await message.answer("\n".join(result))
    except Exception:
        await message.answer("Не удалось получить задачи из Jira! "
                             "Пожалуйста, проверьте подключение и настройки доступа")
    finally:
        await delete_message(loading_message)


@router.message(Command("deadlines"))
async def show_deadlines(message: Message):
    loading_message = await message.answer("Проверяю дедлайны в Jira...")
    try:
        telegram_id = message.from_user.id
        project_key = get_selected_project(telegram_id)
        if not project_key:
            await message.answer("Для того, чтобы начать работу с ботом, выберите проект Jira командой /projects")
            return
        tasks = await get_my_tasks(telegram_id, project_key)
        overdue = []
        soon = []
        upcoming = []
        without_deadline = 0
        today = date.today()

        for task in tasks:
            deadline = task["deadline"]
            if not deadline:
                without_deadline += 1
                continue

            deadline_date = date.fromisoformat(deadline)
            days_left = (deadline_date - today).days

            if days_left < 0:
                overdue.append((task, abs(days_left)))
            elif days_left <= 3:
                soon.append((task, days_left))
            else:
                upcoming.append((task, days_left))

        result = ["<b>Дедлайны по проекту</b>\n"]

        if overdue:
            result.append("<b>🔴 Просроченный дедлайн:</b>")
            for task, days in overdue:
                result.append(
                    f"<b>{escape(task['key'])}</b> — "
                    f"{escape(task['summary'])}\n"
                    f"Дедлайн: {escape(task['deadline'])} "
                    f"(просрочен на {days} дней)"
                )

        if soon:
            result.append("\n<b>🟡 Дедлайн в ближайшие 3 дня:</b>")
            for task, days in soon:
                if days == 0:
                    remaining = "сегодня"
                elif days == 1:
                    remaining = "завтра"
                else:
                    remaining = f"через {days} дней"
                result.append(
                    f"<b>{escape(task['key'])}</b> — "
                    f"{escape(task['summary'])}\n"
                    f"Дедлайн: {escape(task['deadline'])} "
                    f"({remaining})"
                )

        if upcoming:
            result.append("\n<b>🟢 Дедлайн не скоро:</b>")
            for task, days in upcoming:
                result.append(
                    f"<b>{escape(task['key'])}</b> — "
                    f"{escape(task['summary'])}\n"
                    f"Дедлайн: {escape(task['deadline'])} "
                    f"(через {days} дней)"
                )

        if not overdue and not soon and not upcoming:
            result.append("Активных задач с дедлайнами нет")

        await message.answer("\n".join(result))

    except Exception:
        await message.answer("Не удалось проверить дедлайны! Пожалуйста, проверьте подключение к Jira")

    finally:
        await delete_message(loading_message)


@router.message(Command("notifications"))
async def show_notifications(message: Message):
    notifications = get_sent_notifications()

    if not notifications:
        await message.answer("Пока уведомлений не отправлялось")
        return

    result = ["<b>История уведомлений</b>\n"]

    for item in notifications:
        result.append(
            f"🔔 <b>{escape(item['issue_key'])}</b>\n"
            f"Дедлайн: {escape(item['deadline'])}\n"
            f"Отправлено: {escape(item['sent_at'])}\n"
        )

    await message.answer("\n".join(result))


@router.message(Command("check_now"))
async def check_now(message: Message):
    telegram_id = message.from_user.id
    project_key = get_selected_project(telegram_id)

    if not get_user(telegram_id):
        await message.answer("Сначала подключите Jira командой /connect")
        return

    if not project_key:
        await message.answer("Сначала выберите проект командой /projects")
        return

    loading_message = await message.answer(
        "Проверяю ближайшие дедлайны в Jira..."
    )

    try:
        tasks = await get_my_tasks(telegram_id, project_key)
        today = date.today()
        upcoming = []
        for task in tasks:
            deadline = task.get("deadline")
            if not deadline:
                continue

            deadline_date = date.fromisoformat(deadline)
            days_left = (deadline_date - today).days

            if 0 <= days_left <= 3:
                upcoming.append((task, days_left))

        if not upcoming:
            await message.answer("На ближайшие 3 дня нет незавершённых задач с дедлайнами!")
            return

        result = ["<b>🔔 Напоминания о ближайших дедлайнах</b>\n"]

        for task, days_left in upcoming:
            if days_left == 0:
                remaining = "Дедлайн уже сегодня!"
            elif days_left == 1:
                remaining = "До дедлайна остался всего 1 день"
            else:
                remaining = f"До дедлайна осталось {days_left} дня"

            result.append(
                f"<b>{escape(task['key'])}</b>\n"
                f"Срок выполнения: {escape(task['deadline'])}\n"
                f"{remaining}\n"
            )

        await message.answer("\n".join(result))

    except Exception:
        logger.exception("Ошибка команды /check_now")
        await message.answer("Не удалось проверить дедлайны")

    finally:
        await delete_message(loading_message)


def get_deadline_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Сегодня", callback_data="create_deadline:today"),
             InlineKeyboardButton(text="Завтра", callback_data="create_deadline:tomorrow")],
            [InlineKeyboardButton(text="Через неделю", callback_data="create_deadline:week")],
            [InlineKeyboardButton(text="Ввести дату вручную", callback_data="create_deadline:custom")],
            [InlineKeyboardButton(text="Без дедлайна", callback_data="create_deadline:none")],
            [InlineKeyboardButton(text="Отмена", callback_data="create_task:cancel")]
        ]
    )


def get_confirmation_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Создать задачу", callback_data="create_task:confirm")],
            [InlineKeyboardButton(text="Отмена", callback_data="create_task:cancel")]
        ]
    )


@router.message(Command("create_task"))
async def create_task_handler(message: Message, state: FSMContext):
    if not is_authorized(message):
        await message.answer("У вас нет доступа к этой операции")
        return

    await state.clear()
    await state.set_state(CreateTaskStates.waiting_summary)

    await message.answer("<b>Создание новой задачи</b>\n\n Введите название задачи:")


@router.message(CreateTaskStates.waiting_summary)
async def process_task_summary(message: Message, state: FSMContext):
    if not is_authorized(message):
        await state.clear()
        return
    summary = (message.text or "").strip()

    if not summary:
        await message.answer("Пожалуйста, введите название задачи")
        return

    if summary.startswith("/"):
        await message.answer("Пожалуйста, введите название задачи обычным текстом")
        return

    if len(summary) > 255:
        await message.answer("Название слишком длинное, попробуйте еще раз")
        return

    await state.update_data(summary=summary)
    await state.set_state(CreateTaskStates.waiting_deadline)

    await message.answer("<b>Выберите дедлайн задачи:</b>", reply_markup=get_deadline_keyboard())


@router.callback_query(F.data.startswith("create_deadline:"))
async def process_deadline_choice(callback: CallbackQuery, state: FSMContext):
    if not get_user(callback.from_user.id):
        await callback.answer("Сначала подключите Jira через /connect", show_alert=True)
        return

    if await state.get_state() != CreateTaskStates.waiting_deadline.state:
        await callback.answer("Этот выбор уже неактуален. Начните заново.", show_alert=True)
        return

    choice = callback.data.split(":", maxsplit=1)[1]
    today = date.today()

    if choice == "today":
        deadline = today.isoformat()
    elif choice == "tomorrow":
        deadline = (today + timedelta(days=1)).isoformat()
    elif choice == "week":
        deadline = (today + timedelta(days=7)).isoformat()
    elif choice == "none":
        deadline = None
    elif choice == "custom":
        await state.set_state(CreateTaskStates.waiting_custom_deadline)
        await callback.answer()
        await callback.message.edit_text("Введите дедлайн в формате <code>YYYY-MM-DD</code>.\n\n "
                                         "Например: <code>2026-11-10</code>")
        return
    else:
        await callback.answer("Неизвестный вариант", show_alert=True)
        return

    await state.update_data(deadline=deadline)
    await state.set_state(CreateTaskStates.confirming)

    data = await state.get_data()

    deadline_text = (date.fromisoformat(deadline).strftime("%d.%m.%Y") if deadline else "Не указан")

    await callback.answer()

    await callback.message.edit_text(
        "<b>Проверьте данные задачи:</b>\n\n"
        f"<b>Название:</b> {escape(data['summary'])}\n"
        f"<b>Дедлайн:</b> {escape(deadline_text)}\n\n"
        "Создать задачу?",
        reply_markup=get_confirmation_keyboard()
    )


@router.message(CreateTaskStates.waiting_custom_deadline)
async def process_custom_deadline(message: Message, state: FSMContext):
    if not is_authorized(message):
        await state.clear()
        return

    try:
        deadline = date.fromisoformat((message.text or "").strip())
        if deadline < date.today():
            await message.answer("Дедлайн не может быть в прошлом. Введите другую дату в формате YYYY-MM-DD.")
            return

    except ValueError:
        await message.answer("Неверный формат даты. Используйте YYYY-MM-DD.\n Например: 2026-11-10")
        return

    await state.update_data(deadline=deadline.isoformat())
    await state.set_state(CreateTaskStates.confirming)

    data = await state.get_data()

    await message.answer(
        "<b>Проверьте данные задачи:</b>\n\n"
        f"<b>Название:</b> {escape(data['summary'])}\n"
        f"<b>Дедлайн:</b> {deadline.strftime('%d.%m.%Y')}\n\n"
        "Создать задачу в Jira?",
        reply_markup=get_confirmation_keyboard()
    )


@router.callback_query(F.data == "create_task:confirm")
async def confirm_task_creation(callback: CallbackQuery, state: FSMContext):
    if not get_user(callback.from_user.id):
        await callback.answer("Сначала подключите Jira через /connect", show_alert=True)
        return

    if await state.get_state() != CreateTaskStates.confirming.state:
        await callback.answer("Создание задачи уже завершено или отменено.", show_alert=True)
        return

    await callback.answer("Создаю задачу...")
    data = await state.get_data()

    try:
        telegram_id = callback.from_user.id
        project_key = get_selected_project(telegram_id)
        if not get_user(telegram_id):
            await callback.message.edit_text("Сначала подключите Jira командой /connect.")
            return
        if not project_key:
            await callback.message.edit_text("Сначала выберите проект командой /projects.")
            return

        created = await create_task(telegram_id=telegram_id, project_key=project_key,
                                    summary=data["summary"], deadline=data.get("deadline"))
        issue_key = created["key"]
        deadline_text = (date.fromisoformat(data["deadline"]).strftime("%d.%m.%Y")
                         if data.get("deadline")
                         else "Не указан")
        await callback.message.edit_text("<b>Задача создана!</b>\n\n"
                                            f"<b>{escape(issue_key)}</b>\n"
                                            f"Название: {escape(data['summary'])}\n"
                                            f"Дедлайн: {escape(deadline_text)}")
    except Exception:
        logger.exception("Ошибка при создании задачи")
        await callback.message.edit_text("К сожалению, не удалось создать задачу в Jira. "
                                         "Проверьте настройки проекта и права доступа")
    finally:
        await state.clear()


@router.callback_query(F.data == "create_task:cancel")
async def cancel_task_creation(callback: CallbackQuery, state: FSMContext):
    if not get_user(callback.from_user.id):
        await callback.answer("Сначала подключите Jira через /connect", show_alert=True)
        return
    await state.clear()
    await callback.answer("Создание отменено")
    await callback.message.edit_text("Создание задачи отменено")


@router.message(Command("change_status"))
async def change_status_handler(message: Message):
    telegram_id = message.from_user.id
    if not get_user(telegram_id):
        await message.answer("Сначала подключите Jira командой /connect.")
        return
    project_key = get_selected_project(telegram_id)
    if not project_key:
        await message.answer("Сначала выберите проект командой /projects.")
        return
    loading_message = await message.answer("Загружаю ваши задачи из Jira...")

    try:
        tasks = await get_my_tasks(telegram_id, project_key)
        if not tasks:
            await message.answer("У вас нет незавершённых задач.")
            return
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"{task['key']} — {task['summary'][:35]}", callback_data=f"cs_task:{task['key']}")]
                for task in tasks[:20]
            ]
        )

        await message.answer("Выберите задачу, статус которой хотите изменить:", reply_markup=keyboard)
    except Exception:
        logger.exception("Ошибка при загрузке задач для смены статуса")
        await message.answer("Не удалось загрузить задачи из Jira.")
    finally:
        await delete_message(loading_message)


@router.callback_query(F.data.startswith("cs_task:"))
async def select_task_callback(callback: CallbackQuery):
    telegram_id = callback.from_user.id
    if not get_user(telegram_id):
        await callback.answer("Сначала подключите Jira через /connect", show_alert=True)
        return
    project_key = get_selected_project(telegram_id)
    if not project_key:
        await callback.answer("Сначала выберите проект через /projects", show_alert=True)
        return

    issue_key = callback.data.split(":", maxsplit=1)[1]
    await callback.answer()
    try:
        if not issue_key.startswith(f"{project_key}-"):
            await callback.answer("Эта задача не относится к выбранному проекту", show_alert=True)
            return
        transitions = await get_issue_transitions(telegram_id, issue_key)

        if not transitions:
            await callback.message.edit_text(f"Для задачи {escape(issue_key)} нет доступных переходов")
            return
        buttons = []
        for transition in transitions:
            target_status = transition.get("to", {}).get("name")

            button_text = target_status or transition["name"]

            buttons.append([InlineKeyboardButton(text=button_text,
                                                 callback_data=(f"cs_transition:{issue_key}:{transition['id']}"))])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text(f"Задача: <b>{escape(issue_key)}</b>\n\n Выберите новый статус:",
                                         reply_markup=keyboard)

    except Exception:
        logger.exception("Ошибка при получении переходов Jira")
        await callback.message.edit_text("Не удалось получить доступные статусы")


@router.callback_query(F.data.startswith("cs_transition:"))
async def select_transition_callback(callback: CallbackQuery):
    _, issue_key, transition_id = callback.data.split(":", maxsplit=2)
    telegram_id = callback.from_user.id
    if not get_user(telegram_id):
        await callback.answer("Сначала подключите Jira через /connect.", show_alert=True)
        return

    project_key = get_selected_project(telegram_id)

    if not project_key:
        await callback.answer("Сначала выберите проект через /projects.", show_alert=True)
        return
    if not issue_key.startswith(f"{project_key}-"):
        await callback.answer("Эта задача не относится к выбранному проекту.", show_alert=True)
        return

    await callback.answer()

    try:
        transitions = await get_issue_transitions(telegram_id, issue_key)
        selected_transition = next((item for item in transitions if str(item["id"]) == transition_id), None)
        if not selected_transition:
            await callback.message.edit_text("Переход в такой статус больше недоступен. "
                                             "Начните изменение статуса заново командой /change_status")
            return

        await change_task_status(telegram_id, issue_key, transition_id)
        new_status = selected_transition.get("to", {}).get("name")

        if not new_status:
            new_status = selected_transition["name"]

        await callback.message.edit_text("<b>Статус задачи успешно изменён!</b>\n\n"
                                            f"Задача: <b>{escape(issue_key)}</b>\n"
                                            f"Новый статус: <b>{escape(new_status)}</b>")

    except Exception:
        logger.exception("Ошибка при изменении статуса Jira")
        await callback.message.edit_text("Не удалось изменить статус задачи. Проверьте права доступа и настройки Jira.")


@router.message(Command("connect"))
async def connect_jira(message: Message):
    if not message.from_user:
        return

    try:
        auth_url = create_authorization_url(message.from_user.id)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Подключить Jira", url=auth_url)]])

        await message.answer("🔐 <b>Подключение Jira</b>\n\n Нажмите кнопку ниже, войдите в Atlassian "
                             "и разрешите доступ к вашему аккаунту в Jira", reply_markup=keyboard)

    except Exception:
        logger.exception("Не удалось начать OAuth")
        await message.answer("Не удалось начать авторизацию. Пожалуйста, проверьте настройки приложения")


@router.message(Command("jira_status"))
async def jira_status(message: Message):
    if not message.from_user:
        return

    user = get_user(message.from_user.id)

    if not user:
        await message.answer("К сожалению, Jira ещё не подключена.\n Используйте команду /connect")
        return

    await message.answer(
        "<b>Ура, Jira подключена!</b>\n\n"
        "Теперь вы можете начать полноценную работу со своим проектом."
        f"Аккаунт: {escape(user['site_name'])}\n"
    )
