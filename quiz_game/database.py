import os
import sqlite3

# On cloud: set DB_PATH env var to a persistent volume path e.g. /data/quiz.db
# Locally: defaults to quiz_event.db in the project folder
DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "quiz_event.db")
)


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS players (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            phone      TEXT,
            session_id TEXT UNIQUE NOT NULL,
            joined_at  TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
        );
        CREATE TABLE IF NOT EXISTS answers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            question_id INTEGER NOT NULL,
            selected    TEXT NOT NULL,
            is_correct  INTEGER NOT NULL DEFAULT 0,
            answered_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
            UNIQUE(session_id, question_id)
        );
        CREATE TABLE IF NOT EXISTS game_state (
            id                  INTEGER PRIMARY KEY CHECK (id = 1),
            current_question    INTEGER NOT NULL DEFAULT 0,
            question_started_at TEXT
        );
        INSERT OR IGNORE INTO game_state (id, current_question) VALUES (1, 0);
    """)
    conn.commit()
    conn.close()
