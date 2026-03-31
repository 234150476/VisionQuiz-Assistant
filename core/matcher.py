import difflib
import sqlite3


class QuestionMatcher:
    def __init__(self, db_path: str):
        self._questions: list[dict] = []
        self.reload(db_path)

    def reload(self, db_path: str):
        self._questions = []
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute("SELECT question, answer FROM questions")
            for row in cursor:
                self._questions.append({
                    "question": row["question"],
                    "answer": row["answer"],
                })
        finally:
            conn.close()

    def find_best(self, query: str, threshold: float = 0.8) -> dict | None:
        best_score = -1.0
        best_match = None

        for item in self._questions:
            score = difflib.SequenceMatcher(None, query, item["question"]).ratio()
            if score > best_score:
                best_score = score
                best_match = item
                if best_score == 1.0:
                    break

        if best_match is not None and best_score >= threshold:
            return {
                "question": best_match["question"],
                "answer": best_match["answer"],
                "score": best_score,
            }

        return None
