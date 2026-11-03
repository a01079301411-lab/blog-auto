"""운영 원장(SQLite). 게시 예정·발행·성과를 한 곳에서 관리."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

from .config import STATE, fmt_when, now

DB = STATE / "insaengtem.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT NOT NULL,              -- instagram | threads
  when_kst TEXT NOT NULL,              -- 'YYYY-MM-DD HH:MM'
  product TEXT, variant TEXT,
  kind TEXT NOT NULL DEFAULT 'video',  -- video | text
  video TEXT, text TEXT, reply TEXT,
  status TEXT NOT NULL DEFAULT 'draft',-- draft|approved|publishing|published|failed|missed|skipped|external
  remote_id TEXT, reply_remote_id TEXT, permalink TEXT,
  error TEXT, source TEXT, week TEXT,
  created_at TEXT, approved_at TEXT, published_at TEXT,
  UNIQUE(platform, when_kst)
);
CREATE TABLE IF NOT EXISTS metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id INTEGER NOT NULL REFERENCES posts(id),
  fetched_at TEXT NOT NULL,
  views INTEGER, reach INTEGER, likes INTEGER, comments INTEGER, saves INTEGER, shares INTEGER,
  reposts INTEGER, quotes INTEGER, replies INTEGER, profile_visits INTEGER, follows INTEGER,
  avg_watch_ms INTEGER, raw TEXT
);
CREATE TABLE IF NOT EXISTS account_metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT, fetched_at TEXT, followers INTEGER, raw TEXT
);
CREATE TABLE IF NOT EXISTS replies_seen (
  platform TEXT, reply_id TEXT PRIMARY KEY, post_id INTEGER, username TEXT, text TEXT,
  ts TEXT, answered INTEGER DEFAULT 0
);
"""


@contextmanager
def connect():
    STATE.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def upsert_post(con, p: dict) -> int:
    cols = ["platform", "when_kst", "product", "variant", "kind", "video", "text", "reply", "status", "source", "week",
            "remote_id", "permalink"]
    vals = [p.get(c) for c in cols]
    con.execute(
        f"INSERT INTO posts ({','.join(cols)}, created_at) VALUES ({','.join('?' * len(cols))}, ?) "
        "ON CONFLICT(platform, when_kst) DO UPDATE SET "
        + ",".join(f"{c}=excluded.{c}" for c in cols if c not in ("platform", "when_kst"))
        + " WHERE posts.status IN ('draft','failed','skipped')",
        vals + [fmt_when(now())])
    return con.execute("SELECT id FROM posts WHERE platform=? AND when_kst=?", (p["platform"], p["when_kst"])).fetchone()[0]


def set_status(con, post_id: int, status: str, **fields) -> None:
    sets = ["status=?"] + [f"{k}=?" for k in fields]
    con.execute(f"UPDATE posts SET {','.join(sets)} WHERE id=?", [status, *fields.values(), post_id])


def add_metrics(con, post_id: int, m: dict) -> None:
    cols = ["views", "reach", "likes", "comments", "saves", "shares", "reposts", "quotes", "replies",
            "profile_visits", "follows", "avg_watch_ms"]
    con.execute(f"INSERT INTO metrics (post_id, fetched_at, {','.join(cols)}, raw) VALUES (?,?,{','.join('?' * len(cols))},?)",
                [post_id, fmt_when(now()), *[m.get(c) for c in cols], json.dumps(m.get("raw", {}), ensure_ascii=False)])


def latest_metrics(con) -> list[sqlite3.Row]:
    return con.execute("""
      SELECT p.*, m.views, m.reach, m.likes, m.comments, m.saves, m.shares, m.reposts, m.quotes, m.replies,
             m.profile_visits, m.follows, m.avg_watch_ms, m.fetched_at
      FROM posts p LEFT JOIN metrics m ON m.id = (SELECT id FROM metrics WHERE post_id=p.id ORDER BY id DESC LIMIT 1)
      ORDER BY p.when_kst""").fetchall()
