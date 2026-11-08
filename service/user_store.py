import os
import sqlite3
from datetime import datetime, timezone
from cryptography.fernet import Fernet

DB_PATH = "users.db"


def get_fernet():
    key = os.getenv("TOKEN_ENCRYPTION_KEY")

    if not key:
        raise RuntimeError("Не задан TOKEN_ENCRYPTION_KEY в файле .env")

    try:
        return Fernet(key.encode())
    except Exception as error:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY имеет неверный формат") from error


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_user_db():
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                cloud_id TEXT NOT NULL,
                site_url TEXT NOT NULL,
                site_name TEXT NOT NULL,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_at REAL NOT NULL,
                created_at TEXT NOT NULL,
                selected_project_key TEXT
            )
        """)

        columns = connection.execute("PRAGMA table_info(users)" ).fetchall()
        column_names = [column["name"] for column in columns]
        if "selected_project_key" not in column_names:
            connection.execute("""
                ALTER TABLE users
                ADD COLUMN selected_project_key TEXT
            """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS oauth_states (
                state TEXT PRIMARY KEY,
                telegram_id INTEGER NOT NULL,
                created_at REAL NOT NULL
            )
        """)


def save_oauth_state(state, telegram_id):
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO oauth_states (state, telegram_id, created_at)
            VALUES (?, ?, ?)
            """,
            (state, telegram_id, datetime.now(timezone.utc).timestamp())
        )


def consume_oauth_state(state):
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT telegram_id, created_at
            FROM oauth_states
            WHERE state = ?
            """,
            (state,)
        ).fetchone()

        connection.execute("DELETE FROM oauth_states WHERE state = ?",(state,))

    if not row:
        return None

    age = (datetime.now(timezone.utc).timestamp() - row["created_at"])
    if age > 600:
        return None

    return row["telegram_id"]


def save_user(telegram_id, cloud_id, site_url, site_name, access_token, refresh_token, expires_at):
    fernet = get_fernet()
    encrypted_access = fernet.encrypt(access_token.encode()).decode()
    encrypted_refresh = fernet.encrypt(refresh_token.encode()).decode()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO users (
                telegram_id,
                cloud_id,
                site_url,
                site_name,
                access_token,
                refresh_token,
                expires_at,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                cloud_id = excluded.cloud_id,
                site_url = excluded.site_url,
                site_name = excluded.site_name,
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                expires_at = excluded.expires_at
            """,
            (telegram_id, cloud_id, site_url, site_name, encrypted_access, encrypted_refresh, expires_at,
             datetime.now(timezone.utc).isoformat())
        )


def get_user(telegram_id):
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM users
            WHERE telegram_id = ?
            """,
            (telegram_id,)
        ).fetchone()

    if not row:
        return None
    user = dict(row)
    fernet = get_fernet()
    user["access_token"] = fernet.decrypt(user["access_token"].encode()).decode()
    user["refresh_token"] = fernet.decrypt(user["refresh_token"].encode()).decode()

    return user


def set_selected_project(telegram_id, project_key):
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE users
            SET selected_project_key = ?
            WHERE telegram_id = ?
            """,
            (project_key, telegram_id)
        )

        return cursor.rowcount > 0


def get_selected_project(telegram_id):
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT selected_project_key
            FROM users
            WHERE telegram_id = ?
            """,
            (telegram_id,)
        ).fetchone()

    if not row:
        return None

    return row["selected_project_key"]


def delete_user(telegram_id):
    with get_connection() as connection:
        connection.execute("DELETE FROM users WHERE telegram_id = ?",(telegram_id,))


def update_user_tokens(telegram_id, access_token, refresh_token, expires_at):
    fernet = get_fernet()
    encrypted_access = fernet.encrypt(access_token.encode()).decode()

    encrypted_refresh = fernet.encrypt(refresh_token.encode()).decode()

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE users
            SET access_token = ?,
                refresh_token = ?,
                expires_at = ?
            WHERE telegram_id = ?
            """,
            (encrypted_access, encrypted_refresh, expires_at, telegram_id)
        )
