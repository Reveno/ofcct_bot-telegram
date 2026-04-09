from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

# Два перші цифри коду набору в назві групи: «23 Д1», «23Д1», «25 ТТ1»
_COHORT_PREFIX_RE = re.compile(r"^\s*(\d{2})(?=\s|$|\D)")

logger = logging.getLogger(__name__)

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
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_feedback_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS schedule (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name     TEXT NOT NULL,
    day_of_week    INTEGER NOT NULL,
    lesson_number  INTEGER NOT NULL,
    subject        TEXT,
    teacher        TEXT,
    room           TEXT,
    course         INTEGER
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
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    text           TEXT NOT NULL,
    sent_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_by        INTEGER,
    photo_file_id  TEXT,
    title          TEXT,
    link_url       TEXT
);

CREATE TABLE IF NOT EXISTS faq (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    question     TEXT NOT NULL,
    answer       TEXT NOT NULL,
    order_index  INTEGER DEFAULT 0
);
"""

_PG_CONNECT_ATTEMPTS = 20
_PG_CONNECT_DELAY_SEC = 3.0


async def _create_pg_pool() -> Any:
    assert DATABASE_URL
    if asyncpg is None:
        raise RuntimeError(
            "asyncpg is required when DATABASE_URL is set. "
            "Install asyncpg or unset DATABASE_URL to use SQLite."
        )
    ssl_kw: dict[str, Any] = {}
    mode = (os.getenv("PGSSLMODE") or "").strip().lower()
    if mode == "require":
        ssl_kw["ssl"] = True
    elif mode == "disable":
        ssl_kw["ssl"] = False

    last_err: BaseException | None = None
    for attempt in range(1, _PG_CONNECT_ATTEMPTS + 1):
        try:
            return await asyncpg.create_pool(
                DATABASE_URL,
                min_size=1,
                max_size=10,
                **ssl_kw,
            )
        except Exception as e:
            last_err = e
            logger.warning(
                "PostgreSQL: спроба %s/%s не вдалася: %s",
                attempt,
                _PG_CONNECT_ATTEMPTS,
                e,
            )
            if attempt < _PG_CONNECT_ATTEMPTS:
                await asyncio.sleep(_PG_CONNECT_DELAY_SEC)
    assert last_err is not None
    raise last_err


async def init_db() -> None:
    global _sqlite_conn, _pg_pool
    async with _db_lock:
        if USE_POSTGRES:
            assert DATABASE_URL
            _pg_pool = await _create_pg_pool()
            async with _pg_pool.acquire() as conn:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        user_id     BIGINT PRIMARY KEY,
                        username    TEXT,
                        subscribed  INTEGER DEFAULT 0,
                        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_feedback_at TIMESTAMP
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
                        room           TEXT,
                        course         INTEGER
                    )
                    """
                )
                await conn.execute(
                    "ALTER TABLE schedule ADD COLUMN IF NOT EXISTS course INTEGER"
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
                        id             SERIAL PRIMARY KEY,
                        text           TEXT NOT NULL,
                        sent_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        sent_by        BIGINT,
                        photo_file_id  TEXT,
                        title          TEXT,
                        link_url       TEXT
                    )
                    """
                )
                await conn.execute(
                    "ALTER TABLE broadcasts ADD COLUMN IF NOT EXISTS photo_file_id TEXT"
                )
                await conn.execute(
                    "ALTER TABLE broadcasts ADD COLUMN IF NOT EXISTS title TEXT"
                )
                await conn.execute(
                    "ALTER TABLE broadcasts ADD COLUMN IF NOT EXISTS link_url TEXT"
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
                await conn.execute(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_feedback_at TIMESTAMP"
                )
        else:
            db_path = Path(SQLITE_PATH)
            _sqlite_conn = await aiosqlite.connect(str(db_path))
            _sqlite_conn.row_factory = aiosqlite.Row
            await _sqlite_conn.executescript(CREATE_TABLES_SQL)
            await _sqlite_conn.commit()
            await _migrate_sqlite_schedule_course()
            await _migrate_sqlite_broadcasts_photo()
            await _migrate_sqlite_broadcasts_meta()
            await _migrate_sqlite_users_last_feedback()


async def _migrate_sqlite_schedule_course() -> None:
    assert _sqlite_conn
    try:
        await _sqlite_conn.execute(
            "ALTER TABLE schedule ADD COLUMN course INTEGER"
        )
        await _sqlite_conn.commit()
    except aiosqlite.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise


async def _migrate_sqlite_broadcasts_photo() -> None:
    assert _sqlite_conn
    try:
        await _sqlite_conn.execute(
            "ALTER TABLE broadcasts ADD COLUMN photo_file_id TEXT"
        )
        await _sqlite_conn.commit()
    except aiosqlite.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise


async def _migrate_sqlite_broadcasts_meta() -> None:
    assert _sqlite_conn
    for col in ("title", "link_url"):
        try:
            await _sqlite_conn.execute(
                f"ALTER TABLE broadcasts ADD COLUMN {col} TEXT"
            )
            await _sqlite_conn.commit()
        except aiosqlite.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise


async def _migrate_sqlite_users_last_feedback() -> None:
    assert _sqlite_conn
    try:
        await _sqlite_conn.execute(
            "ALTER TABLE users ADD COLUMN last_feedback_at TIMESTAMP"
        )
        await _sqlite_conn.commit()
    except aiosqlite.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise


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


async def get_feedback_cooldown_remaining_sec(user_id: int) -> int:
    """Секунди до дозволу наступного звернення (0 = можна надсилати)."""
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT last_feedback_at FROM users WHERE user_id = $1
                """,
                user_id,
            )
            if not row or row["last_feedback_at"] is None:
                return 0
            raw = row["last_feedback_at"]
            if isinstance(raw, datetime):
                at = raw
                if at.tzinfo is None:
                    at = at.replace(tzinfo=timezone.utc)
            else:
                return 0
            now = datetime.now(timezone.utc)
            elapsed = (now - at).total_seconds()
            cooldown = 3600.0
            if elapsed >= cooldown:
                return 0
            return int(cooldown - elapsed)
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        "SELECT last_feedback_at FROM users WHERE user_id = ?", (user_id,)
    ) as cur:
        row = await cur.fetchone()
    if not row or row[0] is None:
        return 0
    raw = row[0]
    if isinstance(raw, str):
        try:
            at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return 0
    elif isinstance(raw, datetime):
        at = raw
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
    else:
        return 0
    now = datetime.now(timezone.utc)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    elapsed = (now - at).total_seconds()
    cooldown = 3600.0
    if elapsed >= cooldown:
        return 0
    return int(cooldown - elapsed)


async def touch_user_last_feedback(user_id: int) -> None:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO users (user_id, username, last_feedback_at)
                VALUES ($1, '', CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO UPDATE SET
                    last_feedback_at = CURRENT_TIMESTAMP
                """,
                user_id,
            )
        return
    assert _sqlite_conn
    await _sqlite_conn.execute(
        """
        INSERT INTO users (user_id, username, last_feedback_at)
        VALUES (?, '', CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET last_feedback_at = CURRENT_TIMESTAMP
        """,
        (user_id,),
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
                INSERT INTO schedule (group_name, day_of_week, lesson_number, subject, teacher, room, course)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                [
                    (
                        e["group_name"],
                        e["day_of_week"],
                        e["lesson_number"],
                        e.get("subject"),
                        e.get("teacher"),
                        e.get("room"),
                        e.get("course"),
                    )
                    for e in entries
                ],
            )
    else:
        assert _sqlite_conn
        await _sqlite_conn.executemany(
            """
            INSERT INTO schedule (group_name, day_of_week, lesson_number, subject, teacher, room, course)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    e["group_name"],
                    e["day_of_week"],
                    e["lesson_number"],
                    e.get("subject"),
                    e.get("teacher"),
                    e.get("room"),
                    e.get("course"),
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


async def get_distinct_course_numbers() -> list[int]:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT course FROM schedule
                WHERE course IS NOT NULL
                ORDER BY course
                """
            )
            return [int(r["course"]) for r in rows]
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        """
        SELECT DISTINCT course FROM schedule
        WHERE course IS NOT NULL
        ORDER BY course
        """
    ) as cur:
        rows = await cur.fetchall()
        return [int(r[0]) for r in rows]


async def has_groups_without_course() -> bool:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            v = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM schedule WHERE course IS NULL LIMIT 1)"
            )
            return bool(v)
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        "SELECT EXISTS(SELECT 1 FROM schedule WHERE course IS NULL LIMIT 1)"
    ) as cur:
        row = await cur.fetchone()
        return bool(row and row[0])


async def get_groups_by_course_num(course: int) -> list[str]:
    if course == 0:
        return await get_groups_without_course()
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT group_name FROM schedule
                WHERE course = $1
                ORDER BY group_name
                """,
                course,
            )
            return [r["group_name"] for r in rows]
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        """
        SELECT DISTINCT group_name FROM schedule
        WHERE course = ?
        ORDER BY group_name
        """,
        (course,),
    ) as cur:
        rows = await cur.fetchall()
        return [r["group_name"] for r in rows]


async def get_groups_without_course() -> list[str]:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT group_name FROM schedule
                WHERE course IS NULL
                ORDER BY group_name
                """
            )
            return [r["group_name"] for r in rows]
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        """
        SELECT DISTINCT group_name FROM schedule
        WHERE course IS NULL
        ORDER BY group_name
        """
    ) as cur:
        rows = await cur.fetchall()
        return [r["group_name"] for r in rows]


def cohort_prefix_from_group_name(name: str) -> int | None:
    m = _COHORT_PREFIX_RE.match(name.strip())
    if not m:
        return None
    return int(m.group(1))


async def get_distinct_cohort_prefixes() -> list[int]:
    groups = await get_all_groups()
    seen: set[int] = set()
    for g in groups:
        p = cohort_prefix_from_group_name(g)
        if p is not None:
            seen.add(p)
    return sorted(seen)


async def has_groups_without_cohort_prefix() -> bool:
    groups = await get_all_groups()
    return any(cohort_prefix_from_group_name(g) is None for g in groups)


async def get_groups_by_cohort_prefix(prefix: int) -> list[str]:
    groups = await get_all_groups()
    out = [g for g in groups if cohort_prefix_from_group_name(g) == prefix]
    return sorted(out)


async def get_groups_without_cohort_prefix() -> list[str]:
    groups = await get_all_groups()
    out = [g for g in groups if cohort_prefix_from_group_name(g) is None]
    return sorted(out)


async def is_cohort_ui_mode() -> bool:
    """True, якщо курсів у БД немає, але є ≥2 різних коду набору в назвах груп."""
    if await get_distinct_course_numbers():
        return False
    return len(await get_distinct_cohort_prefixes()) >= 2


async def get_groups_for_course_selection(course: int) -> list[str]:
    """
    Групи після вибору кнопки sch:c:*.
    Спочатку колонка course (аркуші «1 курс» у Excel), інакше — за кодом набору (23, 24…).
    """
    if await get_distinct_course_numbers():
        return await get_groups_by_course_num(course)
    cohorts = await get_distinct_cohort_prefixes()
    if len(cohorts) >= 2:
        if course == 0:
            return await get_groups_without_cohort_prefix()
        return await get_groups_by_cohort_prefix(course)
    return await get_groups_by_course_num(course)


async def get_ui_course_buttons() -> list[int] | None:
    """
    Список номерів курсів для клавіатури.
    None — показати плоский список усіх груп (немає ані курсів у БД, ані ≥2 наборів за назвою).
    [] — немає жодної групи в базі.
    """
    nums = await get_distinct_course_numbers()
    if nums:
        out = sorted(nums)
        if await has_groups_without_course():
            out.append(0)
        return out
    cohorts = await get_distinct_cohort_prefixes()
    if len(cohorts) >= 2:
        out = list(cohorts)
        if await has_groups_without_cohort_prefix():
            out.append(0)
        return out
    if await has_groups_without_course():
        return None
    return []


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


async def insert_broadcast(
    text: str,
    sent_by: int,
    photo_file_id: str | None = None,
    title: str | None = None,
    link_url: str | None = None,
) -> int:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO broadcasts (text, sent_by, photo_file_id, title, link_url)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                text,
                sent_by,
                photo_file_id,
                title,
                link_url,
            )
            return int(row["id"])
    assert _sqlite_conn
    cur = await _sqlite_conn.execute(
        """
        INSERT INTO broadcasts (text, sent_by, photo_file_id, title, link_url)
        VALUES (?, ?, ?, ?, ?)
        RETURNING id
        """,
        (text, sent_by, photo_file_id, title, link_url),
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
                SELECT id, text, sent_at, sent_by, photo_file_id, title, link_url
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
        SELECT id, text, sent_at, sent_by, photo_file_id, title, link_url
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


async def get_broadcast_by_id(broadcast_id: int) -> dict[str, Any] | None:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, text, sent_at, sent_by, photo_file_id, title, link_url
                FROM broadcasts WHERE id = $1
                """,
                broadcast_id,
            )
            return _row_to_dict(row) if row else None
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        """
        SELECT id, text, sent_at, sent_by, photo_file_id, title, link_url
        FROM broadcasts WHERE id = ?
        """,
        (broadcast_id,),
    ) as cur:
        row = await cur.fetchone()
        return _row_to_dict(row) if row else None


async def delete_broadcast(broadcast_id: int) -> bool:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "DELETE FROM broadcasts WHERE id = $1 RETURNING id", broadcast_id
            )
            return row is not None
    assert _sqlite_conn
    cur = await _sqlite_conn.execute(
        "DELETE FROM broadcasts WHERE id = ?", (broadcast_id,)
    )
    await _sqlite_conn.commit()
    return cur.rowcount > 0


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


async def migrate_faq_content() -> None:
    """Видаляє застарілі питання та оновлює контакти (ідемпотентно)."""
    path = Path(__file__).resolve().parent / "locales" / "uk.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    mig = data.get("faq_migration") or {}
    remove_list = mig.get("remove_questions") or []
    old_contact_q = mig.get("contact_old_question")
    new_contact_q = mig.get("contact_new_question")
    new_contact_a = mig.get("contact_new_answer")
    add_entries = mig.get("add_if_missing") or []
    sync_answers = mig.get("sync_answers") or []

    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            for q in remove_list:
                await conn.execute("DELETE FROM faq WHERE question = $1", q)
            if old_contact_q and new_contact_q and new_contact_a is not None:
                await conn.execute(
                    """
                    UPDATE faq SET question = $2, answer = $3
                    WHERE question = $1
                    """,
                    old_contact_q,
                    new_contact_q,
                    new_contact_a,
                )
            for entry in add_entries:
                if not isinstance(entry, dict):
                    continue
                qn = (entry.get("question") or "").strip()
                an = (entry.get("answer") or "").strip()
                if not qn or not an:
                    continue
                oi = int(entry.get("order_index", 0))
                n = await conn.fetchval(
                    "SELECT COUNT(*) FROM faq WHERE question = $1", qn
                )
                if int(n or 0) == 0:
                    await conn.execute(
                        """
                        INSERT INTO faq (question, answer, order_index)
                        VALUES ($1, $2, $3)
                        """,
                        qn,
                        an,
                        oi,
                    )
            for entry in sync_answers:
                if not isinstance(entry, dict):
                    continue
                qn = (entry.get("question") or "").strip()
                an = (entry.get("answer") or "").strip()
                if not qn or not an:
                    continue
                await conn.execute(
                    "UPDATE faq SET answer = $2 WHERE question = $1",
                    qn,
                    an,
                )
        return

    assert _sqlite_conn
    for q in remove_list:
        await _sqlite_conn.execute("DELETE FROM faq WHERE question = ?", (q,))
    if old_contact_q and new_contact_q and new_contact_a is not None:
        await _sqlite_conn.execute(
            """
            UPDATE faq SET question = ?, answer = ?
            WHERE question = ?
            """,
            (new_contact_q, new_contact_a, old_contact_q),
        )
    for entry in add_entries:
        if not isinstance(entry, dict):
            continue
        qn = (entry.get("question") or "").strip()
        an = (entry.get("answer") or "").strip()
        if not qn or not an:
            continue
        oi = int(entry.get("order_index", 0))
        async with _sqlite_conn.execute(
            "SELECT COUNT(*) FROM faq WHERE question = ?", (qn,)
        ) as cur:
            row = await cur.fetchone()
        if row and row[0] == 0:
            await _sqlite_conn.execute(
                """
                INSERT INTO faq (question, answer, order_index)
                VALUES (?, ?, ?)
                """,
                (qn, an, oi),
            )
    for entry in sync_answers:
        if not isinstance(entry, dict):
            continue
        qn = (entry.get("question") or "").strip()
        an = (entry.get("answer") or "").strip()
        if not qn or not an:
            continue
        await _sqlite_conn.execute(
            "UPDATE faq SET answer = ? WHERE question = ?",
            (an, qn),
        )
    await _sqlite_conn.commit()


async def insert_faq(question: str, answer: str, order_index: int = 0) -> int:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO faq (question, answer, order_index)
                VALUES ($1, $2, $3)
                RETURNING id
                """,
                question,
                answer,
                order_index,
            )
            return int(row["id"])
    assert _sqlite_conn
    cur = await _sqlite_conn.execute(
        """
        INSERT INTO faq (question, answer, order_index)
        VALUES (?, ?, ?)
        RETURNING id
        """,
        (question, answer, order_index),
    )
    row = await cur.fetchone()
    await _sqlite_conn.commit()
    return int(row[0])


async def update_faq(
    faq_id: int,
    *,
    question: str | None = None,
    answer: str | None = None,
    order_index: int | None = None,
) -> None:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            if question is not None:
                await conn.execute(
                    "UPDATE faq SET question = $1 WHERE id = $2", question, faq_id
                )
            if answer is not None:
                await conn.execute(
                    "UPDATE faq SET answer = $1 WHERE id = $2", answer, faq_id
                )
            if order_index is not None:
                await conn.execute(
                    "UPDATE faq SET order_index = $1 WHERE id = $2",
                    order_index,
                    faq_id,
                )
        return
    assert _sqlite_conn
    if question is not None:
        await _sqlite_conn.execute(
            "UPDATE faq SET question = ? WHERE id = ?", (question, faq_id)
        )
    if answer is not None:
        await _sqlite_conn.execute(
            "UPDATE faq SET answer = ? WHERE id = ?", (answer, faq_id)
        )
    if order_index is not None:
        await _sqlite_conn.execute(
            "UPDATE faq SET order_index = ? WHERE id = ?", (order_index, faq_id)
        )
    await _sqlite_conn.commit()


async def delete_faq(faq_id: int) -> bool:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "DELETE FROM faq WHERE id = $1 RETURNING id", faq_id
            )
            return row is not None
    assert _sqlite_conn
    cur = await _sqlite_conn.execute("DELETE FROM faq WHERE id = ?", (faq_id,))
    await _sqlite_conn.commit()
    return cur.rowcount > 0


async def get_next_faq_order_index() -> int:
    if USE_POSTGRES:
        assert _pg_pool
        async with _pg_pool.acquire() as conn:
            v = await conn.fetchval("SELECT COALESCE(MAX(order_index), -1) FROM faq")
            return int(v or -1) + 1
    assert _sqlite_conn
    async with _sqlite_conn.execute(
        "SELECT COALESCE(MAX(order_index), -1) FROM faq"
    ) as cur:
        row = await cur.fetchone()
        return int(row[0] if row else -1) + 1


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
