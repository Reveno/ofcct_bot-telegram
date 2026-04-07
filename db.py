from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import aiosqlite

try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore[misc, assignment]

from config import DATABASE_URL, SQLITE_PATH, USE_POSTGRES

_sqlite_conn: aiosqlite.Connection | None = None
_pg_pool: asyncpg.Pool | None = None
_db_lock = asyncio.Lock()

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    subscribed  INTEGER DEFAULT 0,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS schedule (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name     TEXT NOT NULL,
    day_of_week    INTEGER NOT NULL,
    lesson_number  INTEGER NOT NULL,
    subject        TEXT,
    teacher        TEXT,
    room           TEXT
);

CREATE TABLE IF NOT EXISTS schedule_changes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name     TEXT NOT NULL,
    day_of_week    INTEGER NOT NULL,
    lesson_number  INTEGER NOT NULL,
    change_type    TEXT NOT NULL,
    subject        TEXT,
    teacher        TEXT,
    room           TEXT,
    note           TEXT,
    week_start     TEXT NOT NULL,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by     INTEGER
);

CREATE TABLE IF NOT EXISTS retakes (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher  TEXT NOT NULL,
    subject  TEXT NOT NULL,
    date     TEXT NOT NULL,
    time     TEXT NOT NULL,
    room     TEXT NOT NULL,
    notes    TEXT
);

CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    text        TEXT NOT NULL,
    answered    INTEGER DEFAULT 0,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS broadcasts (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    text     TEXT NOT NULL,
    sent_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_by  INTEGER
);

CREATE TABLE IF NOT EXISTS faq (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    question     TEXT NOT NULL,
    answer       TEXT NOT NULL,
    order_index  INTEGER DEFAULT 0
);
"""


async def init_db() -> None:
    global _sqlite_conn, _pg_pool
    async with _db_lock:
        if USE_POSTGRES:
            assert DATABASE_URL
            if asyncpg is None:
                raise RuntimeError(
                    "asyncpg is required when DATABASE_URL is set. "
                    "Install asyncpg or unset DATABASE_URL to use SQLite."
                )
            _pg_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
            async with _pg_pool.acquire() as conn:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        user_id     BIGINT PRIMARY KEY,
                        username    TEXT,
                        subscribed  INTEGER DEFAULT 0,
                        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schedule (
                        id             SERIAL PRIMARY KEY,
                        group_name     TEXT NOT NULL,
                        day_of_week    INTEGER NOT NULL,
                        lesson_number  INTEGER NOT NULL,
                        subject        TEXT,
                        teacher        TEXT,
                        room           TEXT
                    )
                    """
                )
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schedule_changes (
                        id             SERIAL PRIMARY KEY,
                        group_name     TEXT NOT NULL,
                        day_of_week    INTEGER NOT NULL,
                        lesson_number  INTEGER NOT NULL,
                        change_type    TEXT NOT NULL,
                        subject        TEXT,
                        teacher        TEXT,
                        room           TEXT,
                        note           TEXT,
                        week_start     TEXT NOT NULL,
                        created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        created_by     BIGINT
                    )
                    """
                )
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS retakes (
                        id       SERIAL PRIMARY KEY,
                        teacher  TEXT NOT NULL,
                        subject  TEXT NOT NULL,
                        date     TEXT NOT NULL,
                        time     TEXT NOT NULL,
                        room     TEXT NOT NULL,
                        notes    TEXT
                    )
                    """
                )
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS feedback (
                        id          SERIAL PRIMARY KEY,
                        user_id     BIGINT NOT NULL,
                        text        TEXT NOT NULL,
                        answered    INTEGER DEFAULT 0,
                        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS broadcasts (
                        id       SERIAL PRIMARY KEY,
                        text     TEXT NOT NULL,
                        sent_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        sent_by  BIGINT
                    )
                    """
                )
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS faq (
                        id           SERIAL PRIMARY KEY,
                        question     TEXT NOT NULL,
                        answer       TEXT NOT NULL,
                        order_index  INTEGER DEFAULT 0
                    )
                    """
                )
        else:
            db_path = Path(SQLITE_PATH)
            _sqlite_conn = await aiosqlite.connect(str(db_path))
            _sqlite_conn.row_factory = aiosqlite.Row
            await _sqlite_conn.executescript(CREATE_TABLES_SQL)
            await _sqlite_conn.commit()


async def close_db() -> None:
    global _sqlite_conn, _pg_pool
    async with _db_lock:
        if _sqlite_conn:
            await _sqlite_conn.close()
            _sqlite_conn = None
        if _pg_pool:
            await _pg_pool.close()
            _pg_pool = None


def _row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, aiosqlite.Row):
        return {k: row[k] for k in row.keys()}
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    if isinstance(row, dict):
        return dict(row)
    return dict(row)


# --- users ---


async def upsert_user(user_id: int, username: str | None) -> None:
    un = username or ""
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO users (user_id, username)
                VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username
                """,
                user_id,
                un,
            )
    else:
        assert _sqlite_conn
        await _sqlite_conn.execute(
            """
            INSERT INTO users (user_id, username)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username = excluded.username
            """,
            (user_id, un),
        )
        await _sqlite_conn.commit()


async def get_all_subscribers() -> list[dict[str, Any]]:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_id, username, subscribed, created_at FROM users WHERE subscribed = 1"
            )
            return [_row_to_dict(r) for r in rows]
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        "SELECT user_id, username, subscribed, created_at FROM users WHERE subscribed = 1"
    ) as cur:
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]


async def toggle_subscription(user_id: int) -> bool:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT subscribed FROM users WHERE user_id = $1", user_id
            )
            cur = 1 if not row or row["subscribed"] != 1 else 0
            await conn.execute(
                """
                INSERT INTO users (user_id, subscribed)
                VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET subscribed = $2
                """,
                user_id,
                cur,
            )
            return bool(cur)
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        "SELECT subscribed FROM users WHERE user_id = ?", (user_id,)
    ) as cur:
        row = await cur.fetchone()
    new_val = 0 if row and row["subscribed"] == 1 else 1
    await _sqlite_conn.execute(
        """
        INSERT INTO users (user_id, subscribed)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET subscribed = excluded.subscribed
        """,
        (user_id, new_val),
    )
    await _sqlite_conn.commit()
    return bool(new_val)


async def get_user(user_id: int) -> dict[str, Any] | None:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id, username, subscribed, created_at FROM users WHERE user_id = $1",
                user_id,
            )
            return _row_to_dict(row) if row else None
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        "SELECT user_id, username, subscribed, created_at FROM users WHERE user_id = ?",
        (user_id,),
    ) as cur:
        row = await cur.fetchone()
        return _row_to_dict(row) if row else None


async def count_users() -> int:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            v = await conn.fetchval("SELECT COUNT(*) FROM users")
            return int(v or 0)
    assert _sqlite_conn
    async with _sqlite_conn.execute("SELECT COUNT(*) FROM users") as cur:
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def count_subscribers() -> int:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            v = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE subscribed = 1"
            )
            return int(v or 0)
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        "SELECT COUNT(*) FROM users WHERE subscribed = 1"
    ) as cur:
        row = await cur.fetchone()
        return int(row[0]) if row else 0


# --- schedule ---


async def insert_schedule_bulk(entries: list[dict[str, Any]]) -> None:
    if not entries:
        return
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO schedule (group_name, day_of_week, lesson_number, subject, teacher, room)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                [
                    (
                        e["group_name"],
                        e["day_of_week"],
                        e["lesson_number"],
                        e.get("subject"),
                        e.get("teacher"),
                        e.get("room"),
                    )
                    for e in entries
                ],
            )
    else:
        assert _sqlite_conn
        await _sqlite_conn.executemany(
            """
            INSERT INTO schedule (group_name, day_of_week, lesson_number, subject, teacher, room)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    e["group_name"],
                    e["day_of_week"],
                    e["lesson_number"],
                    e.get("subject"),
                    e.get("teacher"),
                    e.get("room"),
                )
                for e in entries
            ],
        )
        await _sqlite_conn.commit()


async def delete_all_schedule() -> None:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            await conn.execute("DELETE FROM schedule")
    else:
        assert _sqlite_conn
        await _sqlite_conn.execute("DELETE FROM schedule")
        await _sqlite_conn.commit()


async def get_schedule(group: str, day: int) -> list[dict[str, Any]]:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, group_name, day_of_week, lesson_number, subject, teacher, room
                FROM schedule
                WHERE group_name = $1 AND day_of_week = $2
                ORDER BY lesson_number
                """,
                group,
                day,
            )
            return [_row_to_dict(r) for r in rows]
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        """
        SELECT id, group_name, day_of_week, lesson_number, subject, teacher, room
        FROM schedule
        WHERE group_name = ? AND day_of_week = ?
        ORDER BY lesson_number
        """,
        (group, day),
    ) as cur:
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]


async def get_all_groups() -> list[str]:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT group_name FROM schedule ORDER BY group_name"
            )
            return [r["group_name"] for r in rows]
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        "SELECT DISTINCT group_name FROM schedule ORDER BY group_name"
    ) as cur:
        rows = await cur.fetchall()
        return [r["group_name"] for r in rows]


async def delete_schedule_lesson(group_name: str, day_of_week: int, lesson_number: int) -> None:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM schedule
                WHERE group_name = $1 AND day_of_week = $2 AND lesson_number = $3
                """,
                group_name,
                day_of_week,
                lesson_number,
            )
    else:
        assert _sqlite_conn
        await _sqlite_conn.execute(
            """
            DELETE FROM schedule
            WHERE group_name = ? AND day_of_week = ? AND lesson_number = ?
            """,
            (group_name, day_of_week, lesson_number),
        )
        await _sqlite_conn.commit()


# --- schedule_changes ---


async def insert_change(data: dict[str, Any]) -> int:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO schedule_changes (
                    group_name, day_of_week, lesson_number, change_type,
                    subject, teacher, room, note, week_start, created_by
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
                """,
                data["group_name"],
                data["day_of_week"],
                data["lesson_number"],
                data["change_type"],
                data.get("subject"),
                data.get("teacher"),
                data.get("room"),
                data.get("note"),
                data["week_start"],
                data.get("created_by"),
            )
            return int(row["id"])
    assert _sqlite_conn
    cur = await _sqlite_conn.execute(
        """
        INSERT INTO schedule_changes (
            group_name, day_of_week, lesson_number, change_type,
            subject, teacher, room, note, week_start, created_by
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            data["group_name"],
            data["day_of_week"],
            data["lesson_number"],
            data["change_type"],
            data.get("subject"),
            data.get("teacher"),
            data.get("room"),
            data.get("note"),
            data["week_start"],
            data.get("created_by"),
        ),
    )
    row = await cur.fetchone()
    await _sqlite_conn.commit()
    return int(row[0])


async def get_changes(group: str, day: int, week_start: str) -> list[dict[str, Any]]:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, group_name, day_of_week, lesson_number, change_type,
                       subject, teacher, room, note, week_start, created_at, created_by
                FROM schedule_changes
                WHERE group_name = $1 AND day_of_week = $2 AND week_start = $3
                ORDER BY lesson_number
                """,
                group,
                day,
                week_start,
            )
            return [_row_to_dict(r) for r in rows]
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        """
        SELECT id, group_name, day_of_week, lesson_number, change_type,
               subject, teacher, room, note, week_start, created_at, created_by
        FROM schedule_changes
        WHERE group_name = ? AND day_of_week = ? AND week_start = ?
        ORDER BY lesson_number
        """,
        (group, day, week_start),
    ) as cur:
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]


async def get_all_changes_for_week(week_start: str) -> list[dict[str, Any]]:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, group_name, day_of_week, lesson_number, change_type,
                       subject, teacher, room, note, week_start, created_at, created_by
                FROM schedule_changes
                WHERE week_start = $1
                ORDER BY group_name, day_of_week, lesson_number
                """,
                week_start,
            )
            return [_row_to_dict(r) for r in rows]
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        """
        SELECT id, group_name, day_of_week, lesson_number, change_type,
               subject, teacher, room, note, week_start, created_at, created_by
        FROM schedule_changes
        WHERE week_start = ?
        ORDER BY group_name, day_of_week, lesson_number
        """,
        (week_start,),
    ) as cur:
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]


async def delete_change(change_id: int) -> None:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            await conn.execute("DELETE FROM schedule_changes WHERE id = $1", change_id)
    else:
        assert _sqlite_conn
        await _sqlite_conn.execute(
            "DELETE FROM schedule_changes WHERE id = ?", (change_id,)
        )
        await _sqlite_conn.commit()


async def delete_all_changes_for_week(week_start: str) -> None:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM schedule_changes WHERE week_start = $1", week_start
            )
    else:
        assert _sqlite_conn
        await _sqlite_conn.execute(
            "DELETE FROM schedule_changes WHERE week_start = ?", (week_start,)
        )
        await _sqlite_conn.commit()


async def count_changes_for_week(week_start: str) -> int:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            v = await conn.fetchval(
                "SELECT COUNT(*) FROM schedule_changes WHERE week_start = $1",
                week_start,
            )
            return int(v or 0)
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        "SELECT COUNT(*) FROM schedule_changes WHERE week_start = ?", (week_start,)
    ) as cur:
        row = await cur.fetchone()
        return int(row[0]) if row else 0


# --- retakes ---


async def insert_retake(data: dict[str, Any]) -> int:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO retakes (teacher, subject, date, time, room, notes)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                data["teacher"],
                data["subject"],
                data["date"],
                data["time"],
                data["room"],
                data.get("notes"),
            )
            return int(row["id"])
    assert _sqlite_conn
    cur = await _sqlite_conn.execute(
        """
        INSERT INTO retakes (teacher, subject, date, time, room, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            data["teacher"],
            data["subject"],
            data["date"],
            data["time"],
            data["room"],
            data.get("notes"),
        ),
    )
    row = await cur.fetchone()
    await _sqlite_conn.commit()
    return int(row[0])


async def get_all_retakes() -> list[dict[str, Any]]:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, teacher, subject, date, time, room, notes FROM retakes ORDER BY date, time"
            )
            return [_row_to_dict(r) for r in rows]
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        "SELECT id, teacher, subject, date, time, room, notes FROM retakes ORDER BY date, time"
    ) as cur:
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]


async def delete_retake(retake_id: int) -> None:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            await conn.execute("DELETE FROM retakes WHERE id = $1", retake_id)
    else:
        assert _sqlite_conn
        await _sqlite_conn.execute("DELETE FROM retakes WHERE id = ?", (retake_id,))
        await _sqlite_conn.commit()


# --- feedback ---


async def insert_feedback(user_id: int, text: str) -> int:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO feedback (user_id, text)
                VALUES ($1, $2)
                RETURNING id
                """,
                user_id,
                text,
            )
            return int(row["id"])
    assert _sqlite_conn
    cur = await _sqlite_conn.execute(
        """
        INSERT INTO feedback (user_id, text)
        VALUES (?, ?)
        RETURNING id
        """,
        (user_id, text),
    )
    row = await cur.fetchone()
    await _sqlite_conn.commit()
    return int(row[0])


async def get_unanswered_feedback() -> list[dict[str, Any]]:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT f.id, f.user_id, f.text, f.answered, f.created_at,
                       u.username AS username
                FROM feedback f
                LEFT JOIN users u ON u.user_id = f.user_id
                WHERE f.answered = 0
                ORDER BY f.created_at ASC
                """
            )
            return [_row_to_dict(r) for r in rows]
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        """
        SELECT f.id, f.user_id, f.text, f.answered, f.created_at,
               u.username AS username
        FROM feedback f
        LEFT JOIN users u ON u.user_id = f.user_id
        WHERE f.answered = 0
        ORDER BY f.created_at ASC
        """
    ) as cur:
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]


async def get_feedback_by_id(feedback_id: int) -> dict[str, Any] | None:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, user_id, text, answered, created_at
                FROM feedback WHERE id = $1
                """,
                feedback_id,
            )
            return _row_to_dict(row) if row else None
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        """
        SELECT id, user_id, text, answered, created_at
        FROM feedback WHERE id = ?
        """,
        (feedback_id,),
    ) as cur:
        row = await cur.fetchone()
        return _row_to_dict(row) if row else None


async def mark_feedback_answered(feedback_id: int) -> None:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                "UPDATE feedback SET answered = 1 WHERE id = $1", feedback_id
            )
    else:
        assert _sqlite_conn
        await _sqlite_conn.execute(
            "UPDATE feedback SET answered = 1 WHERE id = ?", (feedback_id,)
        )
        await _sqlite_conn.commit()


async def count_feedback() -> int:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            v = await conn.fetchval("SELECT COUNT(*) FROM feedback")
            return int(v or 0)
    assert _sqlite_conn
    async with _sqlite_conn.execute("SELECT COUNT(*) FROM feedback") as cur:
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def count_unanswered() -> int:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            v = await conn.fetchval(
                "SELECT COUNT(*) FROM feedback WHERE answered = 0"
            )
            return int(v or 0)
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        "SELECT COUNT(*) FROM feedback WHERE answered = 0"
    ) as cur:
        row = await cur.fetchone()
        return int(row[0]) if row else 0


# --- broadcasts ---


async def insert_broadcast(text: str, sent_by: int) -> int:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO broadcasts (text, sent_by)
                VALUES ($1, $2)
                RETURNING id
                """,
                text,
                sent_by,
            )
            return int(row["id"])
    assert _sqlite_conn
    cur = await _sqlite_conn.execute(
        """
        INSERT INTO broadcasts (text, sent_by)
        VALUES (?, ?)
        RETURNING id
        """,
        (text, sent_by),
    )
    row = await cur.fetchone()
    await _sqlite_conn.commit()
    return int(row[0])


async def get_recent_broadcasts(limit: int = 5) -> list[dict[str, Any]]:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, text, sent_at, sent_by
                FROM broadcasts
                ORDER BY sent_at DESC
                LIMIT $1
                """,
                limit,
            )
            return [_row_to_dict(r) for r in rows]
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        """
        SELECT id, text, sent_at, sent_by
        FROM broadcasts
        ORDER BY sent_at DESC
        LIMIT ?
        """,
        (limit,),
    ) as cur:
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]


async def count_broadcasts() -> int:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            v = await conn.fetchval("SELECT COUNT(*) FROM broadcasts")
            return int(v or 0)
    assert _sqlite_conn
    async with _sqlite_conn.execute("SELECT COUNT(*) FROM broadcasts") as cur:
        row = await cur.fetchone()
        return int(row[0]) if row else 0


# --- faq ---


async def get_all_faq() -> list[dict[str, Any]]:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, question, answer, order_index FROM faq ORDER BY order_index, id"
            )
            return [_row_to_dict(r) for r in rows]
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        "SELECT id, question, answer, order_index FROM faq ORDER BY order_index, id"
    ) as cur:
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]


async def get_faq_by_id(faq_id: int) -> dict[str, Any] | None:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, question, answer, order_index FROM faq WHERE id = $1",
                faq_id,
            )
            return _row_to_dict(row) if row else None
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        "SELECT id, question, answer, order_index FROM faq WHERE id = ?", (faq_id,)
    ) as cur:
        row = await cur.fetchone()
        return _row_to_dict(row) if row else None


async def seed_faq() -> None:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            n = await conn.fetchval("SELECT COUNT(*) FROM faq")
            if int(n or 0) > 0:
                return
            entries = _faq_seed_tuples()
            await conn.executemany(
                """
                INSERT INTO faq (question, answer, order_index)
                VALUES ($1, $2, $3)
                """,
                entries,
            )
        return
    assert _sqlite_conn
    async with _sqlite_conn.execute("SELECT COUNT(*) FROM faq") as cur:
        row = await cur.fetchone()
        if row and row[0] > 0:
            return
    entries = _faq_seed_tuples()
    await _sqlite_conn.executemany(
        "INSERT INTO faq (question, answer, order_index) VALUES (?, ?, ?)",
        entries,
    )
    await _sqlite_conn.commit()


def _faq_seed_tuples() -> list[tuple[str, str, int]]:
    path = Path(__file__).resolve().parent / "locales" / "uk.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    rows = data.get("faq_seed", [])
    return [
        (r["question"], r["answer"], int(r["order_index"]))
        for r in rows
        if isinstance(r, dict)
    ]
