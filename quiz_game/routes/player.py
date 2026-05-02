from fastapi import APIRouter, HTTPException
import json, os, sys

TIMER_SEC = 10

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
    return [
        {"id": i + 1, "question": q["question"], "options": q["options"]}
        for i, q in enumerate(qs)
    ]


@router.get("/current-question")
def current_question():
    qs    = load_questions()
    total = len(qs)
    conn  = get_connection()
    try:
        # Atomic auto-advance: only fires once per question (WHERE guards concurrency)
        conn.execute("""
            UPDATE game_state SET
                current_question    = current_question + 1,
                question_started_at = CASE WHEN current_question + 1 <= :total
                                       THEN strftime('%Y-%m-%d %H:%M:%f', 'now') ELSE NULL END
            WHERE id = 1
              AND current_question BETWEEN 1 AND :total
              AND question_started_at IS NOT NULL
              AND (JULIANDAY('now') - JULIANDAY(question_started_at)) * 86400 >= :timer
        """, {"total": total, "timer": TIMER_SEC})
        conn.commit()

        state = conn.execute("""
            SELECT current_question, question_started_at, question_order,
                   (JULIANDAY('now') - JULIANDAY(question_started_at)) * 86400 AS elapsed_sec
            FROM game_state WHERE id=1
        """).fetchone()

        cq = state["current_question"] if state else 0

        if cq == 0:
            return {"status": "waiting", "question": None, "question_num": 0, "total": total}
        if cq > total:
            return {"status": "finished", "question": None, "question_num": cq, "total": total}

        order      = json.loads(state["question_order"]) if (state and state["question_order"]) else list(range(total))
        actual_idx = order[cq - 1]
        q          = qs[actual_idx]
        elapsed    = float(state["elapsed_sec"] or 0)
        time_left  = max(0, TIMER_SEC - int(elapsed))

        q_data = {"id": actual_idx + 1, "question": q["question"], "options": q["options"]}
        if q.get("image"):
            q_data["image"]    = q["image"]
            q_data["image_bg"] = q.get("image_bg", "#ffffff")
        if q.get("code"):
            q_data["code"] = q["code"]

        return {
            "status":         "active",
            "question_num":   cq,
            "total":          total,
            "question":       q_data,
            "time_remaining": time_left,
        }
    finally:
        conn.close()


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

    question   = qs[question_id - 1]
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
        # Works even if player record was deleted (e.g. after Reset All Data)
        row = conn.execute("""
            SELECT
                COUNT(*)                       AS total,
                COALESCE(SUM(is_correct), 0)   AS correct,
                ROUND(
                    (JULIANDAY(MAX(answered_at)) - JULIANDAY(MIN(answered_at))) * 86400, 1
                ) AS time_sec
            FROM answers
            WHERE session_id = ?
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
