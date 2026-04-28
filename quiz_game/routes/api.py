import json
import unicodedata

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_connection

router = APIRouter(prefix="/api", tags=["api"])


def _norm(s: str) -> str:
    """Normalize for comparison: NFC unicode, lowercase, collapse whitespace."""
    return " ".join(unicodedata.normalize("NFC", s).strip().lower().split())


# ── Payloads ──────────────────────────────────────────────────────────────────

class RegisterPayload(BaseModel):
    name: str
    phone: str = ""
    session_id: str


class AnswerPayload(BaseModel):
    session_id: str
    question_id: int
    selected: str
    elapsed_ms: int = 0


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/register")
def register(payload: RegisterPayload):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM players WHERE session_id=?", (payload.session_id,)
        ).fetchone()
        if existing:
            return {"status": "already_registered", "player_id": existing["id"]}
        cur = conn.execute(
            "INSERT INTO players (name, phone, session_id) VALUES (?,?,?)",
            (name, payload.phone.strip(), payload.session_id),
        )
        return {"status": "registered", "player_id": cur.lastrowid}


@router.get("/questions")
def get_questions():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, question, options, category FROM questions ORDER BY order_num"
        ).fetchall()
    return [
        {
            "id":       r["id"],
            "question": r["question"],
            "options":  json.loads(r["options"]),
            "category": r["category"],
        }
        for r in rows
    ]


@router.post("/answer")
def submit_answer(payload: AnswerPayload):
    with get_connection() as conn:
        player = conn.execute(
            "SELECT id FROM players WHERE session_id=?", (payload.session_id,)
        ).fetchone()
        if not player:
            raise HTTPException(status_code=404, detail="Player not found — register first")

        existing = conn.execute(
            "SELECT a.is_correct, q.answer FROM answers a "
            "JOIN questions q ON q.id = a.question_id "
            "WHERE a.player_id=? AND a.question_id=?",
            (player["id"], payload.question_id),
        ).fetchone()
        if existing:
            return {
                "status":       "already_answered",
                "correct":      bool(existing["is_correct"]),
                "correct_answer": existing["answer"],
            }

        q = conn.execute(
            "SELECT answer FROM questions WHERE id=?", (payload.question_id,)
        ).fetchone()
        if not q:
            raise HTTPException(status_code=404, detail="Question not found")

        is_correct = _norm(q["answer"]) == _norm(payload.selected)

        conn.execute(
            "INSERT INTO answers (player_id, question_id, selected, is_correct, response_time_ms) "
            "VALUES (?,?,?,?,?)",
            (player["id"], payload.question_id, payload.selected,
             int(is_correct), payload.elapsed_ms if payload.elapsed_ms > 0 else None),
        )

    return {"status": "ok", "correct": is_correct, "correct_answer": q["answer"]}


@router.get("/my-score")
def my_score(session_id: str):
    with get_connection() as conn:
        player = conn.execute(
            "SELECT id FROM players WHERE session_id=?", (session_id,)
        ).fetchone()
        if not player:
            return {"correct": 0, "answered": 0, "total_time_sec": 0}
        row = conn.execute(
            "SELECT COUNT(*) AS answered, "
            "SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) AS correct, "
            "SUM(COALESCE(response_time_ms, 0)) AS total_ms "
            "FROM answers WHERE player_id=?",
            (player["id"],)
        ).fetchone()
    return {
        "correct":        int(row["correct"] or 0),
        "answered":       int(row["answered"] or 0),
        "total_time_sec": round((row["total_ms"] or 0) / 1000, 1),
    }


@router.delete("/my-session")
def delete_my_session(session_id: str):
    """Delete this player's answers and player record so they can start fresh."""
    with get_connection() as conn:
        player = conn.execute(
            "SELECT id FROM players WHERE session_id=?", (session_id,)
        ).fetchone()
        if player:
            conn.execute("DELETE FROM answers WHERE player_id=?", (player["id"],))
            conn.execute("DELETE FROM players  WHERE id=?",        (player["id"],))
    return {"status": "cleared"}


@router.get("/debug-score")
def debug_score(session_id: str):
    """Show raw DB state for this session — useful for diagnosing score issues."""
    with get_connection() as conn:
        player = conn.execute(
            "SELECT id, name FROM players WHERE session_id=?", (session_id,)
        ).fetchone()
        if not player:
            return {"error": "Player not found", "tip": "Click Play Again to get a fresh session"}
        rows = conn.execute(
            "SELECT a.question_id, a.selected, a.is_correct, q.answer "
            "FROM answers a JOIN questions q ON q.id = a.question_id "
            "WHERE a.player_id=? ORDER BY a.id",
            (player["id"],)
        ).fetchall()
    return {
        "player":       player["name"],
        "total_answers": len(rows),
        "answers": [
            {
                "qid":            r["question_id"],
                "stored_answer":  r["answer"],
                "player_selected": r["selected"],
                "is_correct_db":  r["is_correct"],
                "recomputed":     _norm(r["answer"]) == _norm(r["selected"]),
                "match":          r["answer"] == r["selected"],
            }
            for r in rows
        ],
    }
