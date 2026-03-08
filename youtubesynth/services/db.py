import os
from datetime import datetime, timezone

import aiosqlite


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,
    status       TEXT NOT NULL,
    style        TEXT NOT NULL,
    title        TEXT,
    total_videos INTEGER NOT NULL,
    done_videos  INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS video_progress (
    job_id          TEXT NOT NULL,
    video_id        TEXT NOT NULL,
    title           TEXT,
    url             TEXT NOT NULL,
    status          TEXT NOT NULL,
    transcript_type TEXT,
    error           TEXT,
    PRIMARY KEY (job_id, video_id)
);

CREATE TABLE IF NOT EXISTS token_usage (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        TEXT NOT NULL,
    video_id      TEXT,
    agent         TEXT NOT NULL,
    model         TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd      REAL NOT NULL,
    created_at    TEXT NOT NULL
);
"""


class Database:
    def __init__(self, db_path: str = ".data/youtubesynth.db"):
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if self._db_path != ":memory:":
            os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Job operations
    # ------------------------------------------------------------------

    async def create_job(
        self, job_id: str, style: str, title: str | None, total_videos: int
    ) -> None:
        now = _now()
        await self._conn.execute(
            """
            INSERT INTO jobs (id, status, style, title, total_videos, done_videos, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (job_id, "pending", style, title, total_videos, now, now),
        )
        await self._conn.commit()

    async def update_job_status(self, job_id: str, status: str) -> None:
        await self._conn.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), job_id),
        )
        await self._conn.commit()

    async def increment_done_videos(self, job_id: str) -> None:
        await self._conn.execute(
            "UPDATE jobs SET done_videos = done_videos + 1, updated_at = ? WHERE id = ?",
            (_now(), job_id),
        )
        await self._conn.commit()

    async def get_job(self, job_id: str) -> dict | None:
        async with self._conn.execute(
            "SELECT id AS job_id, status, style, title, total_videos, done_videos,"
            " created_at, updated_at FROM jobs WHERE id = ?",
            (job_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    # ------------------------------------------------------------------
    # Video progress
    # ------------------------------------------------------------------

    async def upsert_video_progress(
        self,
        job_id: str,
        video_id: str,
        title: str | None,
        url: str,
        status: str,
        transcript_type: str | None = None,
        error: str | None = None,
    ) -> None:
        await self._conn.execute(
            """
            INSERT INTO video_progress (job_id, video_id, title, url, status, transcript_type, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id, video_id) DO UPDATE SET
                title           = excluded.title,
                url             = excluded.url,
                status          = excluded.status,
                transcript_type = excluded.transcript_type,
                error           = excluded.error
            """,
            (job_id, video_id, title, url, status, transcript_type, error),
        )
        await self._conn.commit()

    async def update_video_status(
        self,
        job_id: str,
        video_id: str,
        status: str,
        transcript_type: str | None = None,
        error: str | None = None,
    ) -> None:
        await self._conn.execute(
            """
            UPDATE video_progress
            SET status = ?, transcript_type = ?, error = ?
            WHERE job_id = ? AND video_id = ?
            """,
            (status, transcript_type, error, job_id, video_id),
        )
        await self._conn.commit()

    async def get_job_videos(self, job_id: str) -> list[dict]:
        async with self._conn.execute(
            "SELECT * FROM video_progress WHERE job_id = ?", (job_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Token usage
    # ------------------------------------------------------------------

    async def insert_token_usage(
        self,
        job_id: str,
        video_id: str | None,
        agent: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        await self._conn.execute(
            """
            INSERT INTO token_usage
                (job_id, video_id, agent, model, input_tokens, output_tokens, cost_usd, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, video_id, agent, model, input_tokens, output_tokens, cost_usd, _now()),
        )
        await self._conn.commit()

    async def get_token_usage(self, job_id: str) -> list[dict]:
        async with self._conn.execute(
            "SELECT * FROM token_usage WHERE job_id = ? ORDER BY id", (job_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
