import sqlite3

DB_PATH = "notifications.db"


def init_db():
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS sent_notifications (
                issue_key TEXT NOT NULL,
                deadline TEXT NOT NULL,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (issue_key, deadline)
            )
        """)


def notification_was_sent(issue_key, deadline):
    with sqlite3.connect(DB_PATH) as connection:
        result = connection.execute(
            """
            SELECT 1
            FROM sent_notifications
            WHERE issue_key = ? AND deadline = ?
            """,
            (issue_key, deadline)
        ).fetchone()

    return result is not None


def mark_notification_sent(issue_key, deadline):
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO sent_notifications
            (issue_key, deadline)
            VALUES (?, ?)
            """,
            (issue_key, deadline)
        )


def get_sent_notifications(limit=20):
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row

        rows = connection.execute(
            """
            SELECT issue_key, deadline, sent_at
            FROM sent_notifications
            ORDER BY sent_at DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()

    return [dict(row) for row in rows]
