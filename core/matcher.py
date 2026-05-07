"""
题库匹配器

支持两种数据库 schema：
  - questdb(id, quest, answer)  — 建工题库等自定义 schema
  - questions(id, question, answer) — VisionQuiz 自建题库

使用关键词预过滤 + SequenceMatcher 精确匹配，13K 题库 ~0.02s/题。
"""

import difflib
import logging
import re
import sqlite3

logger = logging.getLogger(__name__)

# 支持的 schema 列表（优先级从高到低）
_SCHEMAS = [
    ("questdb", "quest", "answer"),
    ("questions", "question", "answer"),
]


def _extract_keywords(text: str, min_len: int = 2, max_ngram: int = 4) -> set[str]:
    """提取文本中的关键词（连续中文片段 + 数字/字母）。

    对于长度 > max_ngram 的中文片段，额外生成长度 2~max_ngram 的滑动窗口子串，
    以保证无标点 OCR 文本能与数据库中标点分隔的关键词交集。
    """
    tokens = re.findall(r'[一-鿿]{2,}|[a-zA-Z0-9]+', text)
    kws: set[str] = set()
    for t in tokens:
        if len(t) >= min_len:
            kws.add(t)
            # 对长中文片段生成滑动窗口子串
            if len(t) > max_ngram and all('一' <= c <= '鿿' for c in t):
                for w in range(2, max_ngram + 1):
                    for i in range(len(t) - w + 1):
                        kws.add(t[i:i + w])
    return kws


class QuestionMatcher:
    """题库匹配器：关键词预过滤 + SequenceMatcher 精确匹配。"""

    def __init__(self, db_path: str):
        self._questions: list[dict] = []
        self._keyword_index: dict[str, list[int]] = {}
        self.reload(db_path)

    def reload(self, db_path: str):
        self._questions = []
        self._keyword_index = {}
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            # 自动检测 schema
            table, q_col, a_col = self._detect_schema(conn)
            logger.info("题库 schema: %s(%s, %s)", table, q_col, a_col)

            cursor = conn.execute(f"SELECT {q_col}, {a_col} FROM {table}")
            for idx, row in enumerate(cursor):
                question = row[q_col] or ""
                answer = row[a_col] or ""
                kws = _extract_keywords(question)
                self._questions.append({
                    "question": question,
                    "answer": answer,
                    "keywords": kws,
                    "length": len(question),
                })
                # 构建关键词索引
                for kw in kws:
                    self._keyword_index.setdefault(kw, []).append(idx)

            logger.info("题库已加载: %d 道题, %d 个关键词", len(self._questions), len(self._keyword_index))
        finally:
            conn.close()

    def _detect_schema(self, conn: sqlite3.Connection) -> tuple[str, str, str]:
        """自动检测数据库表和列名。"""
        # 获取所有表名
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}

        for table, q_col, a_col in _SCHEMAS:
            if table in tables:
                # 验证列名存在
                columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                if q_col in columns and a_col in columns:
                    return table, q_col, a_col

        # 兜底：尝试第一个表的前两列
        if tables:
            table = next(iter(tables))
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            if len(columns) >= 2:
                logger.warning("未识别 schema，使用 %s 的前两列: %s, %s", table, columns[0], columns[1])
                return table, columns[0], columns[1]

        raise ValueError(f"无法从数据库中识别题目表，已有表: {tables}")

    def find_best(self, query: str, threshold: float = 0.55) -> dict | None:
        """在题库中查找最匹配的题目。

        1. 关键词索引获取初始候选集
        2. 关键词重叠度过滤（≥ 0.2）
        3. 长度过滤（比例 0.3~3.0）
        4. SequenceMatcher 精确匹配
        """
        if not self._questions:
            return None

        query_keywords = _extract_keywords(query)
        query_len = len(query)

        # 通过关键词索引获取初始候选集
        candidate_indices: set[int] = set()
        if query_keywords:
            for kw in query_keywords:
                if kw in self._keyword_index:
                    candidate_indices.update(self._keyword_index[kw])

            # 关键词交集过少时，扩大候选集（降级为全量扫描）
            if len(candidate_indices) < 5:
                candidate_indices = set(range(len(self._questions)))
        else:
            candidate_indices = set(range(len(self._questions)))

        best_score = 0.0
        best_idx = -1
        candidates_examined = 0

        for idx in candidate_indices:
            item = self._questions[idx]
            bquest = item["question"]
            q_len = item["length"]

            # 长度过滤
            if q_len > 0 and query_len > 0:
                ratio = query_len / q_len
                if ratio < 0.3 or ratio > 3.0:
                    continue

            # 关键词重叠度过滤（宽松：仅排除完全无交集的候选）
            if query_keywords:
                bquest_kw = item.get("keywords")
                if bquest_kw is None:
                    bquest_kw = _extract_keywords(bquest)
                if not (query_keywords & bquest_kw):
                    continue

            candidates_examined += 1
            score = difflib.SequenceMatcher(None, query, bquest).ratio()
            if score > best_score:
                best_score = score
                best_idx = idx
                if best_score >= 0.95:
                    break

        if best_idx >= 0 and best_score >= threshold:
            item = self._questions[best_idx]
            logger.debug("题库匹配: score=%.2f, 检查 %d/%d 题",
                         best_score, candidates_examined, len(candidate_indices))
            return {
                "question": item["question"],
                "answer": item["answer"],
                "score": best_score,
            }

        return None

    @property
    def question_count(self) -> int:
        return len(self._questions)
