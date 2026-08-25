"""SQLite access. Raw SQL, no ORM - the whole surface is 7 functions."""
import hashlib
import os
import sqlite3
from datetime import date, datetime, timedelta

DB_PATH = os.environ.get("DB_PATH", "deadlines.db")


def now() -> date:
    """Pinned clock so 'this week' is reproducible during the demo."""
    return date.fromisoformat(os.environ["NOW"]) if os.environ.get("NOW") else date.today()


def connect(path: str | None = None) -> sqlite3.Connection:
    # check_same_thread=False because Pydantic AI runs sync tools in a worker
    # thread, and the query agent's find_tasks reads through this connection.
    # Safe here: the agent serialises its tool calls and they only read.
    conn = sqlite3.connect(path or DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    with open(os.path.join(os.path.dirname(__file__), "schema.sql")) as f:
        conn.executescript(f.read())
    return conn


def _stamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def add_message(conn, raw_text, source, sender_role, received_at) -> int | None:
    """Returns None if this exact body was already ingested (idempotency)."""
    h = hashlib.sha256(raw_text.strip().lower().encode()).hexdigest()
    try:
        cur = conn.execute(
            "INSERT INTO messages (raw_text, source, sender_role, received_at, body_hash)"
            " VALUES (?,?,?,?,?)",
            (raw_text, source, sender_role, received_at, h),
        )
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def set_outcome(conn, message_id, outcome, note=None):
    conn.execute("UPDATE messages SET outcome=?, note=? WHERE id=?", (outcome, note, message_id))


def candidate_tasks(conn, course: str | None, days: int = 60) -> list[sqlite3.Row]:
    """Deterministic narrowing before the model decides. Same course when we
    have one; otherwise recent open tasks, since course is often implicit."""
    cutoff = (now() - timedelta(days=days)).isoformat()
    if course:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status='open' AND lower(course)=lower(?)"
            " AND created_at >= ? ORDER BY updated_at DESC LIMIT 10",
            (course, cutoff),
        ).fetchall()
        if rows:
            return rows
    return conn.execute(
        "SELECT * FROM tasks WHERE status='open' AND created_at >= ?"
        " ORDER BY updated_at DESC LIMIT 10",
        (cutoff,),
    ).fetchall()


def insert_task(conn, **f) -> int:
    f.setdefault("created_at", _stamp())
    f.setdefault("updated_at", _stamp())
    cols = ",".join(f)
    cur = conn.execute(
        f"INSERT INTO tasks ({cols}) VALUES ({','.join('?' * len(f))})", tuple(f.values())
    )
    return cur.lastrowid


def update_task(conn, task_id: int, **f):
    f["updated_at"] = _stamp()
    conn.execute(
        f"UPDATE tasks SET {'=?,'.join(f)}=? WHERE id=?", (*f.values(), task_id)
    )


def add_event(conn, task_id, message_id, field, old_value, new_value, source, authority, reason):
    conn.execute(
        "INSERT INTO task_events (task_id, message_id, field, old_value, new_value,"
        " source, authority, reason, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (task_id, message_id, field, old_value, new_value, source, authority, reason, _stamp()),
    )


def get_task(conn, task_id) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()


def events_for(conn, task_id) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM task_events WHERE task_id=? ORDER BY id", (task_id,)
    ).fetchall()
