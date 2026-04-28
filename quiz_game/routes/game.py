from fastapi import APIRouter

from database import get_connection
from models import GameStateOut, LeaderboardEntry, QuestionPublic

router = APIRouter(prefix="/game", tags=["game"])


@router.get("/state", response_model=GameStateOut)
def game_state():
    with get_connection() as conn:
        gs = conn.execute("SELECT * FROM game_state WHERE id=1").fetchone()
        questions = conn.execute("SELECT * FROM questions ORDER BY order_num").fetchall()
        total = len(questions)
        idx = gs["current_question_index"]
        status = gs["status"]

        players_registered = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
        players_answered = 0
        question = None

        if status == "active" and 0 <= idx < total:
            q_row = questions[idx]
            players_answered = conn.execute(
                "SELECT COUNT(*) FROM answers WHERE question_id=?", (q_row["id"],)
            ).fetchone()[0]
            question = QuestionPublic.from_row(q_row, idx, total)

    return GameStateOut(
        status=status,
        current_question_index=idx,
        question=question,
        players_registered=players_registered,
        players_answered=players_answered,
    )


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
def leaderboard():
    with get_connection() as conn:
        total_questions = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        rows = conn.execute("""
            SELECT
                p.id   AS player_id,
                p.name AS player_name,
                COUNT(CASE WHEN a.is_correct = 1 THEN 1 END) AS correct,
                AVG(CASE WHEN a.is_correct = 1 THEN a.response_time_ms END) AS avg_ms
            FROM players p
            LEFT JOIN answers a ON a.player_id = p.id
            GROUP BY p.id, p.name
            ORDER BY correct DESC, avg_ms ASC NULLS LAST
        """).fetchall()

    return [
        LeaderboardEntry(
            rank=i + 1,
            player_id=r["player_id"],
            player_name=r["player_name"],
            correct=r["correct"] or 0,
            total_questions=total_questions,
            avg_response_ms=int(r["avg_ms"]) if r["avg_ms"] else None,
        )
        for i, r in enumerate(rows)
    ]
