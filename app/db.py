import time
import aiosqlite
from pathlib import Path

from .config import settings
from .security import fernet

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tg_hash TEXT UNIQUE NOT NULL,
  created_at INTEGER NOT NULL,
  counter_reset_at INTEGER NOT NULL,
  subscription_tier TEXT NOT NULL DEFAULT 'FREE',
  subscription_until INTEGER,
  daily_limit_remaining INTEGER NOT NULL DEFAULT 10,
  bonus_messages INTEGER NOT NULL DEFAULT 0,
  earned_referral_messages INTEGER NOT NULL DEFAULT 0,
  referrer_hash TEXT,
  tz_name TEXT,
  gender TEXT NOT NULL DEFAULT 'male'
);

CREATE TABLE IF NOT EXISTS usage_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tg_hash TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  type TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS referrals(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  referrer_hash TEXT NOT NULL,
  invitee_hash TEXT NOT NULL UNIQUE,
  created_at INTEGER NOT NULL,
  activated_at INTEGER,
  status TEXT NOT NULL DEFAULT 'pending',
  progress_count INTEGER NOT NULL DEFAULT 0,
  expires_at INTEGER
);

CREATE TABLE IF NOT EXISTS purchases(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tg_hash TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  kind TEXT NOT NULL,
  meta TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tg_hash TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  blob BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS conv_buffer(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tg_hash TEXT NOT NULL,
  role TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  blob BLOB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conv_hash_id ON conv_buffer(tg_hash, id);
CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON feedback(created_at);

CREATE TABLE IF NOT EXISTS flags(
  user_id TEXT NOT NULL,
  flag TEXT NOT NULL,
  value TEXT NOT NULL,
  updated REAL NOT NULL,
  PRIMARY KEY(user_id, flag)
);

CREATE TABLE IF NOT EXISTS kv(
  user_id TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT,
  updated REAL NOT NULL,
  PRIMARY KEY(user_id, key)
);

CREATE TABLE IF NOT EXISTS stability(
  user_id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  count INTEGER NOT NULL
);
"""

async def open_db():
    db_path = Path(settings.db_path)
    if db_path.parent and not db_path.parent.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)

    db = await aiosqlite.connect(str(db_path))
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute("PRAGMA foreign_keys=ON;")
    await db.executescript(SCHEMA)

    try:
        cur = await db.execute("PRAGMA table_info(users)")
        cols = [row[1] for row in await cur.fetchall()]
        await cur.close()
        if "tz_name" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN tz_name TEXT")
        if "gender" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN gender TEXT DEFAULT 'male'")
        await db.commit()
    except Exception:
        pass

    await db.commit()
    return db

async def conv_load_history(tg_hash: str, limit: int = 8):
    if not tg_hash:
        return []
    db = await open_db()
    try:
        cur = await db.execute(
            "SELECT role, blob FROM conv_buffer WHERE tg_hash=? ORDER BY id DESC LIMIT ?",
            (tg_hash, int(limit))
        )
        rows = await cur.fetchall()
        await cur.close()
        rows = rows[::-1]
        out = []
        for role, blob in rows:
            if fernet:
                try:
                    text = fernet.decrypt(blob).decode("utf-8")
                except Exception:
                    continue
            else:
                text = blob.decode("utf-8", errors="ignore")
            out.append({"role": role, "content": text})
        return out
    finally:
        await db.close()

async def conv_append(tg_hash: str, role: str, text: str, keep: int = 8):
    if not tg_hash:
        return
    db = await open_db()
    try:
        payload = text.encode("utf-8")
        blob = fernet.encrypt(payload) if fernet else payload
        await db.execute(
            "INSERT INTO conv_buffer(tg_hash, role, created_at, blob) VALUES(?,?,?,?)",
            (tg_hash, role, int(time.time()), blob)
        )
        await db.execute(
            """
            DELETE FROM conv_buffer
            WHERE tg_hash=? AND id NOT IN (
              SELECT id FROM conv_buffer WHERE tg_hash=? ORDER BY id DESC LIMIT ?
            )
            """,
            (tg_hash, tg_hash, int(keep))
        )
        await db.commit()
    finally:
        await db.close()

async def conv_clear(tg_hash: str):
    if not tg_hash:
        return
    db = await open_db()
    try:
        await db.execute("DELETE FROM conv_buffer WHERE tg_hash=?", (tg_hash,))
        await db.commit()
    finally:
        await db.close()

async def get_user_flag(user_id: str, flag: str) -> bool:
    db = await open_db()
    try:
        cur = await db.execute("SELECT value FROM flags WHERE user_id=? AND flag=?", (user_id, flag))
        row = await cur.fetchone()
        await cur.close()
        return bool(row and row[0] == "true")
    finally:
        await db.close()

async def set_user_flag(user_id: str, flag: str, value: bool):
    db = await open_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO flags(user_id, flag, value, updated) VALUES(?,?,?,?)",
            (user_id, flag, "true" if value else "false", time.time()),
        )
        await db.commit()
    finally:
        await db.close()

async def get_user_kv(user_id: str, key: str) -> str | None:
    db = await open_db()
    try:
        cur = await db.execute("SELECT value FROM kv WHERE user_id=? AND key=?", (user_id, key))
        row = await cur.fetchone()
        await cur.close()
        return None if row is None else (row[0] if row[0] is not None else None)
    finally:
        await db.close()

async def set_user_kv(user_id: str, key: str, value: str | int | float | None):
    v = "" if value is None else str(value)
    db = await open_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO kv(user_id, key, value, updated) VALUES(?,?,?,?)",
            (user_id, key, v, time.time()),
        )
        await db.commit()
    finally:
        await db.close()

async def get_user_state_stability(user_id: str, expected_label: str) -> int:
    db = await open_db()
    try:
        cur = await db.execute("SELECT label, count FROM stability WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if not row or row[0] != expected_label:
            await db.execute(
                "INSERT OR REPLACE INTO stability(user_id, label, count) VALUES(?,?,?)",
                (user_id, expected_label, 1)
            )
            await db.commit()
            return 1
        else:
            count = row[1] + 1
            await db.execute("UPDATE stability SET count=? WHERE user_id=?", (count, user_id))
            await db.commit()
            return count
    finally:
        await db.close()

async def get_user_gender(tg_hash: str) -> str:
    db = await open_db()
    try:
        cur = await db.execute("SELECT gender FROM users WHERE tg_hash=? LIMIT 1", (tg_hash,))
        row = await cur.fetchone()
        await cur.close()
        g = (row[0] if row else None)
        g = (g or "").strip().lower()
        return "female" if g == "female" else "male"
    finally:
        await db.close()

async def set_user_gender(tg_hash: str, gender: str) -> None:
    g = "female" if str(gender).strip().lower() == "female" else "male"
    db = await open_db()
    try:
        await db.execute(
            """
            INSERT INTO users (tg_hash, created_at, counter_reset_at, gender)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(tg_hash) DO UPDATE SET gender=excluded.gender
            """,
            (tg_hash, int(time.time()), int(time.time()), g)
        )
        await db.commit()
    finally:
        await db.close()

async def get_active_counts(now_ts: int | None = None) -> tuple[int, int, int]:
    now = int(now_ts or time.time())
    day = now - 24 * 3600
    week = now - 7 * 24 * 3600
    month = now - 30 * 24 * 3600

    db = await open_db()
    try:
        async def _count_since(since_ts: int) -> int:
            cur = await db.execute(
                "SELECT COUNT(DISTINCT tg_hash) FROM conv_buffer WHERE created_at >= ?",
                (int(since_ts),)
            )
            row = await cur.fetchone()
            await cur.close()
            return int(row[0] or 0)

        dau = await _count_since(day)
        wau = await _count_since(week)
        mau = await _count_since(month)
        return dau, wau, mau
    finally:
        await db.close()

async def get_total_users_count() -> int:
    db = await open_db()
    try:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        row = await cur.fetchone()
        await cur.close()
        return int(row[0] or 0)
    finally:
        await db.close()

async def get_user_stats_30d(limit: int = 50) -> list[dict]:
    cutoff = int(time.time()) - 30 * 24 * 3600
    db = await open_db()
    try:
        cur = await db.execute(
            """
            SELECT tg_hash, COUNT(*) AS cnt
            FROM conv_buffer
            WHERE created_at >= ?
            GROUP BY tg_hash
            ORDER BY cnt DESC
            LIMIT ?
            """,
            (cutoff, int(limit))
        )
        rows = await cur.fetchall()
        await cur.close()

        results: list[dict] = []
        for tg_hash, cnt in rows:
            cur1 = await db.execute("SELECT 1 FROM purchases WHERE tg_hash=? LIMIT 1", (tg_hash,))
            has_purchases = bool(await cur1.fetchone())
            await cur1.close()

            cur2 = await db.execute(
                "SELECT subscription_until FROM users WHERE tg_hash=? LIMIT 1",
                (tg_hash,)
            )
            r2 = await cur2.fetchone()
            await cur2.close()
            now = int(time.time())
            has_subscription = bool(r2 and (int(r2[0] or 0) > now))

            results.append({
                "tg_hash": tg_hash,
                "msg_30d": int(cnt),
                "has_purchases": has_purchases,
                "has_subscription": has_subscription,
            })

        return results
    finally:
        await db.close()
