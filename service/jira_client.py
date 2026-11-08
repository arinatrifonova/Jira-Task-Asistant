import time
import httpx
import os
from service.user_store import (get_user, update_user_tokens)


JIRA_API_BASE = "https://api.atlassian.com/ex/jira"


async def refresh_access_token(telegram_id, user):
    if user["expires_at"] > time.time() + 60:
        return user

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://auth.atlassian.com/oauth/token",
            json={
                "grant_type": "refresh_token",
                "client_id": __import__("os").getenv("ATLASSIAN_CLIENT_ID"),
                "client_secret": __import__("os").getenv("ATLASSIAN_CLIENT_SECRET"),
                "refresh_token": user["refresh_token"]
            }
        )
        response.raise_for_status()
        tokens = response.json()

    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token", user["refresh_token"])
    expires_at = time.time() + tokens["expires_in"]

    update_user_tokens(telegram_id=telegram_id, access_token=access_token, refresh_token=refresh_token,
                       expires_at=expires_at)

    user["access_token"] = access_token
    user["refresh_token"] = refresh_token
    user["expires_at"] = expires_at

    return user


async def jira_request(telegram_id, method, endpoint, params=None, json=None):
    user = get_user(telegram_id)

    if not user:
        raise ValueError("Аккаунт Jira не подключён. Используйте /connect")

    user = await refresh_access_token(telegram_id, user)

    url = (f"{JIRA_API_BASE}/"
           f"{user['cloud_id']}/rest/api/3/{endpoint}")

    headers = {"Authorization": f"Bearer {user['access_token']}",
               "Accept": "application/json"}

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.request(method=method, url=url, headers=headers, params=params, json=json)
            if response.status_code == 401:
                raise RuntimeError("Jira вернула 401 Unauthorized. "
                                   "Токен недействителен или требуется повторное подключение.")

            if response.status_code >= 400:
                raise RuntimeError(f"Jira API вернула HTTP {response.status_code}: "
                                   f"{response.text[:1500]}")

            if not response.content:
                return {}

            return response.json()

        except httpx.RequestError as error:
            raise RuntimeError(f"Ошибка соединения с Jira: {type(error).__name__}: {error}") from error

async def get_projects(telegram_id):
    projects = []
    start_at = 0
    max_results = 50
    while True:
        data = await jira_request(telegram_id,"GET","project/search",
            params={"startAt": start_at, "maxResults": max_results, "orderBy": "name"})
        batch = data.get("values", [])
        projects.extend(batch)
        if data.get("isLast", True) or not batch:
            break
        start_at += len(batch)

    return projects


async def get_my_tasks(telegram_id, project_key):
    jql = (f'project = "{project_key}" '
           'AND assignee = currentUser() '
           'AND statusCategory != Done '
           'ORDER BY duedate ASC')

    data = await jira_request(telegram_id,"POST","search/jql",
        json={"jql": jql, "maxResults": 100,
            "fields": ["summary", "status", "assignee", "duedate", "priority", "issuetype"]
        }
    )
    issues = data.get("issues", [])

    return [
        {
            "key": issue.get("key", ""),
            "summary": issue.get("fields", {}).get("summary") or "",
            "status": (issue.get("fields", {}).get("status", {}).get("name", "")),
            "deadline": issue.get("fields", {}).get("duedate")
        }
        for issue in issues
    ]


async def create_task(telegram_id, project_key, summary, deadline=None):
    fields = {
        "project": {"key": project_key},
        "summary": summary,
        "issuetype": {"name": "Task"}
    }
    if deadline:
        fields["duedate"] = deadline

    return await jira_request(telegram_id,"POST","issue", json={"fields": fields})


async def get_issue_transitions(telegram_id, issue_key):
    data = await jira_request(telegram_id,"GET",f"issue/{issue_key}/transitions")
    return data.get("transitions", [])

async def change_task_status(telegram_id, issue_key, transition_id):
    return await jira_request(telegram_id,"POST",f"issue/{issue_key}/transitions",
        json={
            "transition": {"id": str(transition_id)}
        }
    )