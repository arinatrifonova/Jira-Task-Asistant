import os
import time
import secrets
import httpx
from urllib.parse import urlencode
from service.user_store import (save_oauth_state, consume_oauth_state, save_user)


CLIENT_ID = os.getenv("ATLASSIAN_CLIENT_ID")
CLIENT_SECRET = os.getenv("ATLASSIAN_CLIENT_SECRET")
REDIRECT_URI = os.getenv("ATLASSIAN_REDIRECT_URI")
scopes = ["read:jira-work", "write:jira-work", "read:jira-user", "offline_access"]


def create_authorization_url(telegram_id):
    state = secrets.token_urlsafe(32)
    save_oauth_state(state, telegram_id)
    params = {
        "audience": "api.atlassian.com",
        "client_id": CLIENT_ID,
        "scope": " ".join(scopes),
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "response_type": "code",
        "prompt": "consent"
    }

    return ("https://auth.atlassian.com/authorize?" + urlencode(params))


async def exchange_code(code):
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post("https://auth.atlassian.com/oauth/token",
            json={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": code,
                "redirect_uri": REDIRECT_URI
            }
        )
        response.raise_for_status()
        return response.json()


async def get_accessible_resources(access_token):
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get("https://api.atlassian.com/oauth/token/accessible-resources",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json"
            }
        )
        response.raise_for_status()
        return response.json()


async def complete_oauth(code, state):
    telegram_id = consume_oauth_state(state)

    if telegram_id is None:
        raise ValueError("Недействительный или просроченный OAuth state")

    tokens = await exchange_code(code)
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")

    if not access_token or not refresh_token:
        raise ValueError("Atlassian не вернул access token или refresh token. Проверьте scope offline_access")

    resources = await get_accessible_resources(access_token)

    jira_resources = [
        resource
        for resource in resources
        if "read:jira-work" in resource.get("scopes", [])
        or "write:jira-work" in resource.get("scopes", [])
    ]

    if not jira_resources:
        raise ValueError("Не найден доступный Jira Cloud сайт")
    site = jira_resources[0]
    save_user(telegram_id=telegram_id, cloud_id=site["id"], site_url=site["url"], site_name=site["name"],
              access_token=access_token, refresh_token=refresh_token, expires_at=time.time() + tokens["expires_in"])
    return site