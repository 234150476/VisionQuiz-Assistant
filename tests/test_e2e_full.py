"""
E2E 测试：全自动模式 — 测试 VisionQuiz 全自动答题

使用方法：
1. 启动 Web 答题网站: python -m web.app
2. 浏览器打开 http://127.0.0.1:5000/ 并全屏
3. 确保 config.json 中 api_key 和 model 已配置
4. 运行: python -m pytest tests/test_e2e_full.py -v -s

注意：此测试需要真实的 AI API key 和屏幕显示，不适合 CI 环境。
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def questions():
    """加载题目数据"""
    path = ROOT / "web" / "data" / "questions.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def db_questions(questions):
    """题库来源题目"""
    return [q for q in questions if q["source"] == "db"]


@pytest.fixture(scope="module")
def web_questions(questions):
    """网络来源题目"""
    return [q for q in questions if q["source"] == "web"]


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------

class TestE2EFullAuto:
    """全自动模式端到端测试"""

    def test_question_dataset_integrity(self, questions):
        """验证题目数据集完整性"""
        assert len(questions) == 50, f"期望 50 题，实际 {len(questions)}"

        singles = [q for q in questions if q["type"] == "single"]
        multis = [q for q in questions if q["type"] == "multi"]
        assert len(singles) >= 25, f"单选题不足 25 道: {len(singles)}"
        assert len(multis) >= 10, f"多选题不足 10 道: {len(multis)}"

    def test_db_questions_count(self, db_questions):
        """验证题库题目数量"""
        assert len(db_questions) == 37, f"期望 37 道题库题，实际 {len(db_questions)}"

    def test_web_questions_count(self, web_questions):
        """验证网络题目数量"""
        assert len(web_questions) == 13, f"期望 13 道网络题，实际 {len(web_questions)}"

    def test_all_questions_have_options(self, questions):
        """验证所有题目都有选项"""
        for q in questions:
            assert "options" in q, f"题目 {q['id']} 缺少 options"
            assert len(q["options"]) >= 2, f"题目 {q['id']} 选项不足 2 个"

    def test_all_questions_have_correct_answer(self, questions):
        """验证所有题目都有正确答案"""
        for q in questions:
            assert "correct_answer" in q, f"题目 {q['id']} 缺少 correct_answer"
            assert q["correct_answer"].strip(), f"题目 {q['id']} 答案为空"

    def test_multi_choice_answers_valid(self, questions):
        """验证多选题答案格式正确"""
        multis = [q for q in questions if q["type"] == "multi"]
        for q in multis:
            answer = q["correct_answer"]
            parts = answer.split("|答案分隔|")
            assert len(parts) >= 2, f"多选题 {q['id']} 答案选项不足 2 个: {answer}"
            for part in parts:
                assert part in q["options"], f"多选题 {q['id']} 答案 {part} 不在选项中"

    def test_single_choice_answers_valid(self, questions):
        """验证单选题答案格式正确"""
        singles = [q for q in questions if q["type"] == "single"]
        for q in singles:
            answer = q["correct_answer"]
            assert answer in q["options"], f"单选题 {q['id']} 答案 {answer} 不在选项中"

    def test_stems_unique(self, questions):
        """验证题干不重复"""
        stems = [q["stem"] for q in questions]
        assert len(stems) == len(set(stems)), "存在重复题干"

    def test_stems_minimum_length(self, questions):
        """验证题干最小长度（至少 10 字符）"""
        for q in questions:
            assert len(q["stem"]) >= 10, f"题目 {q['id']} 题干过短: {q['stem']}"

    def test_web_app_api_returns_50_questions(self):
        """验证 Web API 返回 50 道题"""
        try:
            from web.app import create_app
            app = create_app()
            with app.test_client() as client:
                resp = client.get("/api/questions")
                data = json.loads(resp.data)
                assert len(data) == 50, f"API 返回 {len(data)} 题"
        except ImportError:
            pytest.skip("Flask 未安装")

    def test_web_app_submit_correct_answers(self, questions):
        """验证 Web API 全部正确答案提交得 100%"""
        try:
            from web.app import create_app
            app = create_app()
            with app.test_client() as client:
                correct = {str(q["id"]): q["correct_answer"] for q in questions}
                resp = client.post("/api/submit", json={"answers": correct})
                result = json.loads(resp.data)
                assert result["score"] == 100.0, f"期望 100%，实际 {result['score']}%"
                assert result["db_rate"] == 100.0, f"题库题正确率 {result['db_rate']}%"
        except ImportError:
            pytest.skip("Flask 未安装")

    def test_web_app_submit_empty_answers(self, questions):
        """验证 Web API 空答案提交得 0%"""
        try:
            from web.app import create_app
            app = create_app()
            with app.test_client() as client:
                resp = client.post("/api/submit", json={"answers": {}})
                result = json.loads(resp.data)
                assert result["score"] == 0.0, f"期望 0%，实际 {result['score']}%"
        except ImportError:
            pytest.skip("Flask 未安装")


class TestFullAutoIntegration:
    """
    全自动模式集成测试（需要真实环境）
    手动运行时取消 skip 标记
    """

    @pytest.mark.skip(reason="需要真实 AI API key 和屏幕显示，手动运行时移除此标记")
    def test_full_auto_recognizes_web_questions(self):
        """
        全自动模式识别 Web 题目测试流程：
        1. 启动 Web 答题站 (python -m web.app)
        2. 浏览器全屏打开 http://127.0.0.1:5000/
        3. 运行 VisionQuiz 全自动模式
        4. 等待引擎完成全部 50 题
        5. 检查答题结果

        预期：
        - 题库题（37 道）正确率 ≥ 95%（至少 35/37）
        - 网络题（13 道）识别率正常
        - 无崩溃、无超时卡死
        """
        pass  # 由手动测试执行


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
