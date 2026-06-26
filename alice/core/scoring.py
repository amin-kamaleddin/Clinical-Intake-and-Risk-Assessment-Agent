from typing import Optional

from core.state import AliceState


def calculate_phq9_total(state: AliceState) -> Optional[int]:
    """Sum phq9_q1..q9. Returns None until all nine items are answered."""
    scores = [state["phq9"].get(f"phq9_q{i}") for i in range(1, 10)]
    if any(score is None for score in scores):
        return None
    return sum(scores)


def calculate_gad7_total(state: AliceState) -> Optional[int]:
    """Sum gad7_q1..q7. Returns None until all seven items are answered."""
    scores = [state["gad7"].get(f"gad7_q{i}") for i in range(1, 8)]
    if any(score is None for score in scores):
        return None
    return sum(scores)
