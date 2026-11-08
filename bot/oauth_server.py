from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from service.auth_service import complete_oauth

app = FastAPI()

@app.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(code: str = Query(None), state: str = Query(None), error: str = Query(None)):
    if error:
        return """<h2>Авторизация отменена</h2> <p>Вернитесь в Telegram и попробуйте ещё раз.</p>"""

    if not code or not state:
        return HTMLResponse("<h2>Не получены параметры авторизации</h2>", status_code=400)

    try:
        site = await complete_oauth(code, state)

        return f"""<h2>Jira успешно подключена!</h2> <p>Аккаунт: {site['name']}</p>
        <p>Теперь вернитесь в Telegram и отправьте команду /jira_status</p>"""

    except Exception:
        return HTMLResponse("""<h2>Не удалось подключить Jira</h2> 
        <p>Вернитесь в Telegram и попробуйте снова</p>""", status_code=400)