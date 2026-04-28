import json
from pydantic import BaseModel
from typing import Optional


class PlayerRegister(BaseModel):
    name: str
    phone: str = ""


class PlayerOut(BaseModel):
    id: int
    name: str


class AnswerSubmit(BaseModel):
    player_id: int
    question_id: int
    selected: str


class AnswerResult(BaseModel):
    correct: bool
    correct_answer: str


class QuestionPublic(BaseModel):
    id: int
    question: str
    options: list[str]
    category: str
    index: int
    total: int

    @classmethod
    def from_row(cls, row, index: int, total: int) -> "QuestionPublic":
        return cls(
            id=row["id"],
            question=row["question"],
            options=json.loads(row["options"]),
            category=row["category"],
            index=index,
            total=total,
        )


class GameStateOut(BaseModel):
    status: str
    current_question_index: int
    question: Optional[QuestionPublic] = None
    players_registered: int
    players_answered: int


class LeaderboardEntry(BaseModel):
    rank: int
    player_id: int
    player_name: str
    correct: int
    total_questions: int
    avg_response_ms: Optional[int] = None
