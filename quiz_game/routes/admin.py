import csv, io, json, os, sys, traceback
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from database import get_connection

router = APIRouter(prefix="/admin", tags=["admin"])


def _make_qr_png(url: str) -> bytes:
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M
    qr = qrcode.QRCode(version=1, error_correction=ERROR_CORRECT_M,
                       box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1e293b", back_color="white")
    buf = io.BytesIO()
    img.save(buf)
    buf.seek(0)
    return buf.read()


@router.get("/server-info")
def server_info(request: Request):
    # base_url works correctly both locally and when deployed behind HTTPS
    player_url = str(request.base_url)
    return {"player_url": player_url}


@router.get("/qr")
def serve_qr(request: Request):
    player_url = str(request.base_url)
    png = _make_qr_png(player_url)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


def load_questions():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../data/questions.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def compute_leaderboard():
    total_q = len(load_questions())
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT
                p.name,
                p.phone,
                COUNT(a.id)                        AS answered,
                COALESCE(SUM(a.is_correct), 0)     AS correct,
                ROUND(
                    (JULIANDAY(MAX(a.answered_at)) - JULIANDAY(p.joined_at)) * 86400,
                    1
                )                                  AS time_sec
            FROM players p
            LEFT JOIN answers a ON a.session_id = p.session_id
            GROUP BY p.session_id, p.name, p.phone, p.joined_at
        """).fetchall()
    finally:
        conn.close()

    results = []
    for r in rows:
        r        = dict(r)
        correct  = int(r["correct"]  or 0)
        answered = int(r["answered"] or 0)
        time_sec = r["time_sec"]  # None when player has no answers

        results.append({
            "name":            r["name"],
            "phone":           r["phone"] or "—",
            "correct":         correct,
            "total_questions": total_q,
            "answered":        answered,
            "time_taken_sec":  float(time_sec) if time_sec is not None else None,
            "finished":        answered >= total_q,
        })

    results.sort(key=lambda x: (
        -x["correct"],
        x["time_taken_sec"] if x["time_taken_sec"] is not None else 999999,
    ))

    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(results):
        r["rank"]  = i + 1
        r["medal"] = medals[i] if i < 3 else str(i + 1)

    return results


@router.get("/leaderboard")
def leaderboard():
    try:
        return compute_leaderboard()
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.get("/players")
def all_players():
    try:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT name, phone, joined_at FROM players ORDER BY joined_at"
            ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.get("/answers/all")
def all_answers():
    try:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT session_id, question_id, selected, is_correct, answered_at "
                "FROM answers ORDER BY answered_at"
            ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.get("/winner")
def get_winner():
    results = compute_leaderboard()
    if not results:
        return {"message": "No players yet"}
    w = results[0]
    return {
        "winner":     w["name"],
        "phone":      w["phone"],
        "score":      f"{w['correct']}/{w['total_questions']}",
        "time_taken": f"{w['time_taken_sec']}s" if w["time_taken_sec"] is not None else "N/A",
        "rank":       1,
    }


@router.get("/export/csv")
def export_csv():
    results = compute_leaderboard()
    output  = io.StringIO()
    writer  = csv.writer(output)
    writer.writerow(["Rank", "Medal", "Name", "Phone", "Correct", "Total", "Time(sec)", "Finished"])
    for r in results:
        writer.writerow([
            r["rank"], r["medal"], r["name"], r["phone"],
            r["correct"], r["total_questions"],
            r["time_taken_sec"] if r["time_taken_sec"] is not None else "N/A",
            r["finished"],
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=quiz_results.csv"},
    )


@router.get("/game-state")
def admin_game_state():
    """Current question index + live answer count — polled by admin UI."""
    try:
        conn = get_connection()
        try:
            state  = conn.execute(
                "SELECT current_question, question_started_at FROM game_state WHERE id=1"
            ).fetchone()
            qs     = load_questions()
            cq     = state["current_question"] if state else 0
            total  = len(qs)

            answers_now = 0
            q_text      = None
            q_answer    = None
            if 1 <= cq <= total:
                row = conn.execute(
                    "SELECT COUNT(DISTINCT session_id) AS cnt FROM answers WHERE question_id=?",
                    (cq,)
                ).fetchone()
                answers_now = row["cnt"] if row else 0
                q_text   = qs[cq - 1]["question"]
                q_answer = qs[cq - 1]["answer"]

            player_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM players"
            ).fetchone()["cnt"]
        finally:
            conn.close()

        return {
            "current_question":    cq,
            "total_questions":     total,
            "status":              "waiting" if cq == 0 else ("finished" if cq > total else "active"),
            "answers_for_current": answers_now,
            "player_count":        player_count,
            "current_question_text":   q_text,
            "current_correct_answer":  q_answer,
            "question_started_at": state["question_started_at"] if state else None,
        }
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.post("/next-question")
def advance_question():
    """Advance to the next question (or past the last to signal finish)."""
    try:
        conn = get_connection()
        try:
            state  = conn.execute(
                "SELECT current_question FROM game_state WHERE id=1"
            ).fetchone()
            next_q = (state["current_question"] if state else 0) + 1
            conn.execute("""
                INSERT INTO game_state (id, current_question, question_started_at)
                VALUES (1, ?, strftime('%Y-%m-%d %H:%M:%f', 'now'))
                ON CONFLICT(id) DO UPDATE SET
                    current_question    = excluded.current_question,
                    question_started_at = excluded.question_started_at
            """, (next_q,))
            conn.commit()
            total = len(load_questions())
        finally:
            conn.close()
        return {
            "current_question": next_q,
            "total_questions":  total,
            "status":           "finished" if next_q > total else "active",
        }
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.post("/reset-game")
def reset_game():
    """Reset game to waiting state and wipe answers so players can play again.
    Player registrations are preserved — players don't need to re-enter their name."""
    try:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM answers")
            conn.execute("""
                INSERT INTO game_state (id, current_question, question_started_at)
                VALUES (1, 0, NULL)
                ON CONFLICT(id) DO UPDATE SET current_question=0, question_started_at=NULL
            """)
            conn.commit()
        finally:
            conn.close()
        return {"status": "reset", "message": "Game reset — answers cleared, players kept"}
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.delete("/reset-all")
def reset_all():
    """Wipe ALL data including players — use for a completely fresh event."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM answers")
        conn.execute("DELETE FROM players")
        conn.execute("""
            INSERT INTO game_state (id, current_question, question_started_at)
            VALUES (1, 0, NULL)
            ON CONFLICT(id) DO UPDATE SET current_question=0, question_started_at=NULL
        """)
        conn.commit()
    finally:
        conn.close()
    return {"status": "cleared", "message": "All player data deleted"}
