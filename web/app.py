"""
Web 答题系统 — Flask 后端
提供题目列表、答案提交、评分等 API
"""

import json
import os
from pathlib import Path

from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).parent / "data"
_QUESTIONS: list[dict] = []


def _load_questions() -> list[dict]:
    """加载 questions.json 并返回题目列表"""
    path = _DATA_DIR / "questions.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 页面路由
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """答题首页"""
    return render_template("index.html", total=len(_QUESTIONS))


# ---------------------------------------------------------------------------
# API 路由
# ---------------------------------------------------------------------------

@app.route("/api/questions")
def api_questions():
    """返回题目列表（隐藏正确答案）"""
    safe = []
    for q in _QUESTIONS:
        safe.append({
            "id": q["id"],
            "type": q["type"],
            "stem": q["stem"],
            "options": q["options"],
        })
    return jsonify(safe)


@app.route("/api/submit", methods=["POST"])
def api_submit():
    """提交答案并评分"""
    data = request.get_json(force=True)
    answers: dict[str, str] = data.get("answers", {})  # {question_id: "A" or "A|答案分隔|C"}

    total = len(_QUESTIONS)
    correct = 0
    db_total = 0
    db_correct = 0
    web_total = 0
    web_correct = 0
    details = []

    for q in _QUESTIONS:
        qid = str(q["id"])
        user_answer = answers.get(qid, "").strip()
        correct_answer = q["correct_answer"]
        is_correct = _compare_answer(user_answer, correct_answer)
        source = q.get("source", "db")

        if source == "db":
            db_total += 1
            if is_correct:
                db_correct += 1
        else:
            web_total += 1
            if is_correct:
                web_correct += 1

        if is_correct:
            correct += 1

        details.append({
            "id": q["id"],
            "type": q["type"],
            "stem": q["stem"],
            "source": source,
            "user_answer": user_answer,
            "correct_answer": correct_answer,
            "is_correct": is_correct,
        })

    return jsonify({
        "total": total,
        "correct": correct,
        "score": round(correct / total * 100, 1) if total else 0,
        "db_total": db_total,
        "db_correct": db_correct,
        "db_rate": round(db_correct / db_total * 100, 1) if db_total else 0,
        "web_total": web_total,
        "web_correct": web_correct,
        "web_rate": round(web_correct / web_total * 100, 1) if web_total else 0,
        "details": details,
    })


@app.route("/api/result")
def api_result():
    """返回上次提交的评分结果（用于页面刷新后恢复）"""
    return jsonify({"message": "请先提交答案"}), 404


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _compare_answer(user_answer: str, correct_answer: str) -> bool:
    """比较用户答案和正确答案（支持多选分隔符）"""
    sep = "|答案分隔|"
    user_set = set(user_answer.split(sep)) if user_answer else set()
    correct_set = set(correct_answer.split(sep))
    return user_set == correct_set


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------

def create_app() -> Flask:
    """应用工厂"""
    global _QUESTIONS
    _QUESTIONS = _load_questions()
    return app


if __name__ == "__main__":
    create_app()
    app.run(host="127.0.0.1", port=5000, debug=False)
