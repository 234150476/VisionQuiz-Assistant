import sqlite3
import openpyxl
from datetime import datetime


class QuestionDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_table()

    def _create_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL UNIQUE,
                answer TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    def import_from_excel(self, excel_path: str) -> tuple[int, int]:
        wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
        try:
            ws = wb.active

            existing = set()
            cursor = self.conn.execute("SELECT question FROM questions")
            for row in cursor:
                existing.add(row[0])

            success = 0
            skipped = 0
            rows = iter(ws.iter_rows(values_only=True))
            next(rows, None)  # 跳过表头

            for row in rows:
                if not row or len(row) < 2:
                    skipped += 1
                    continue

                question = row[0]
                answer = row[1]

                if question is None or answer is None:
                    skipped += 1
                    continue

                question = str(question).strip()
                answer = str(answer).strip()

                if not question or not answer:
                    skipped += 1
                    continue

                if question in existing:
                    skipped += 1
                    continue

                self.conn.execute(
                    "INSERT OR IGNORE INTO questions (question, answer) VALUES (?, ?)",
                    (question, answer)
                )
                existing.add(question)
                success += 1

            self.conn.commit()
        finally:
            wb.close()
        return success, skipped

    def get_all(self, page: int, page_size: int = 50) -> tuple[list[dict], int]:
        total = self.count()
        offset = (page - 1) * page_size
        cursor = self.conn.execute(
            "SELECT id, question, answer, created_at FROM questions ORDER BY id ASC LIMIT ? OFFSET ?",
            (page_size, offset)
        )
        rows = cursor.fetchall()
        result = [
            {
                "id": row["id"],
                "question": row["question"],
                "answer": row["answer"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
        return result, total

    def count(self) -> int:
        cursor = self.conn.execute("SELECT COUNT(*) FROM questions")
        return cursor.fetchone()[0]

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None
