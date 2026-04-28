from fastapi import APIRouter, HTTPException
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from database import get_connection

router = APIRouter(prefix="/api", tags=["player"])


def load_questions():
    path = os.path.join(os.path.dirname(__file__), "../data/questions.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@router.post("/register")
def register_player(data: dict):
    name       = str(data.get("name", "")).strip()
    phone      = str(data.get("phone", "")).strip()
    session_id = str(data.get("session_id", "")).strip()

    if not name or not session_id:
        raise HTTPException(status_code=400, detail="Name and session_id required")

    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM players WHERE session_id=?", (session_id,)
        ).fetchone()
        if existing:
            return {"status": "already_registered", "name": name}
        conn.execute(
            "INSERT INTO players (name, phone, session_id) VALUES (?,?,?)",
            (name, phone, session_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {"status": "registered", "name": name}


@router.get("/questions")
def get_questions():
    qs = load_questions()
    # Use 1-based index as id — no id field required in JSON
    return [
        {"id": i + 1, "question": q["question"], "options": q["options"]}
        for i, q in enumerate(qs)
    ]


@router.post("/answer")
def submit_answer(data: dict):
    session_id  = str(data.get("session_id", "")).strip()
    question_id = int(data.get("question_id") or 0)
    selected    = str(data.get("selected", "")).strip()

    if not session_id or not question_id or not selected:
        raise HTTPException(status_code=400, detail="Missing fields")

    qs = load_questions()
    if question_id < 1 or question_id > len(qs):
        raise HTTPException(status_code=404, detail="Question not found")

    question   = qs[question_id - 1]  # question_id is 1-based
    is_correct = selected.strip().lower() == question["answer"].strip().lower()

    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT is_correct FROM answers WHERE session_id=? AND question_id=?",
            (session_id, question_id),
        ).fetchone()
        if existing:
            return {
                "status":         "already_answered",
                "correct":        bool(existing["is_correct"]),
                "correct_answer": question["answer"],
            }
        conn.execute(
            "INSERT INTO answers (session_id, question_id, selected, is_correct) VALUES (?,?,?,?)",
            (session_id, question_id, selected, 1 if is_correct else 0),
        )
        conn.commit()
    finally:
        conn.close()

    return {"status": "ok", "correct": is_correct, "correct_answer": question["answer"]}


@router.get("/my-score")
def my_score(session_id: str):
    conn = get_connection()
    try:
        player = conn.execute(
            "SELECT name FROM players WHERE session_id=?", (session_id,)
        ).fetchone()
        if not player:
            return {"correct": 0, "answered": 0, "total_time_sec": 0}

        # Use JULIANDAY for time diff — avoids Python datetime parsing issues
        row = conn.execute("""
            SELECT
                COUNT(*)                   AS total,
                COALESCE(SUM(a.is_correct), 0) AS correct,
                ROUND(
                    (JULIANDAY(MAX(a.answered_at)) - JULIANDAY(p.joined_at)) * 86400, 1
                ) AS time_sec
            FROM answers a
            JOIN players p ON p.session_id = a.session_id
            WHERE a.session_id = ?
        """, (session_id,)).fetchone()
    finally:
        conn.close()

    time_sec = row["time_sec"]
    return {
        "correct":        int(row["correct"] or 0),
        "answered":       int(row["total"]   or 0),
        "total_time_sec": float(time_sec) if time_sec is not None else 0,
    }


@router.delete("/my-session")
def delete_my_session(session_id: str):
    """Wipe this player's data so they can start fresh."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM answers WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM players  WHERE session_id=?", (session_id,))
        conn.commit()
    finally:
        conn.close()
    return {"status": "cleared"}


@router.get("/debug-score")
def debug_score(session_id: str):
    qs = load_questions()
    conn = get_connection()
    try:
        player = conn.execute(
            "SELECT name FROM players WHERE session_id=?", (session_id,)
        ).fetchone()
        if not player:
            return {"error": "Player not found — click Play Again for a fresh session"}
        rows = conn.execute(
            "SELECT question_id, selected, is_correct FROM answers WHERE session_id=? ORDER BY id",
            (session_id,),
        ).fetchall()
    finally:
        conn.close()

    answers = []
    for r in rows:
        qid = r["question_id"]
        stored_answer = qs[qid - 1]["answer"] if 1 <= qid <= len(qs) else "?"
        answers.append({
            "qid":             qid,
            "stored_answer":   stored_answer,
            "player_selected": r["selected"],
            "is_correct_db":   r["is_correct"],
            "match":           r["selected"].strip().lower() == stored_answer.strip().lower(),
        })

    return {"player": player["name"], "total_answers": len(answers), "answers": answers}
