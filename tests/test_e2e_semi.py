"""
E2E 测试：半自动模式 — 测试 VisionQuiz 半自动答题

使用方法：
1. 启动 Web 答题网站: python -m web.app
2. 浏览器打开 http://127.0.0.1:5000/ 并全屏
3. 确保 config.json 中 api_key 和 model 已配置
4. 运行: python -m pytest tests/test_e2e_semi.py -v -s

注意：此测试需要真实的 AI API key 和屏幕显示，不适合 CI 环境。
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def questions():
    path = ROOT / "web" / "data" / "questions.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class TestE2ESemiAuto:
    """半自动模式端到端测试"""

    def test_question_data_loads(self, questions):
        """题目数据正确加载"""
        assert len(questions) == 50

    def test_web_app_index_page(self):
        """Web 首页可访问"""
        try:
            from web.app import create_app
            app = create_app()
            with app.test_client() as client:
                resp = client.get("/")
                assert resp.status_code == 200
                assert b"\xe5\x9c\xa8\xe7\xba\xbf\xe7\xad\x94\xe9\xa2\x98" in resp.data  # "在线答题"
        except ImportError:
            pytest.skip("Flask 未安装")

    def test_web_app_navigation_works(self):
        """题目导航 API 正常"""
        try:
            from web.app import create_app
            app = create_app()
            with app.test_client() as client:
                resp = client.get("/api/questions")
                data = json.loads(resp.data)
                # Verify each question has required fields
                for q in data:
                    assert "id" in q
                    assert "type" in q
                    assert "stem" in q
                    assert "options" in q
                    # correct_answer should NOT be exposed
                    assert "correct_answer" not in q
                    assert "source" not in q
        except ImportError:
            pytest.skip("Flask 未安装")

    def test_multi_select_scoring(self):
        """多选题部分正确不得分"""
        try:
            from web.app import create_app
            app = create_app()
            with app.test_client() as client:
                # Get a multi-choice question
                resp = client.get("/api/questions")
                questions = json.loads(resp.data)
                multi_q = next(q for q in questions if q["type"] == "multi")

                # Load correct answer
                with open(ROOT / "web" / "data" / "questions.json", encoding="utf-8") as f:
                    full = json.load(f)
                full_q = next(q for q in full if q["id"] == multi_q["id"])

                # Submit with only one of multiple correct answers (should be wrong)
                correct_parts = full_q["correct_answer"].split("|答案分隔|")
                partial = correct_parts[0]  # only first option

                resp = client.post("/api/submit", json={"answers": {str(multi_q["id"]): partial}})
                result = json.loads(resp.data)
                assert result["correct"] < result["total"], "部分选择不应算全对"
        except ImportError:
            pytest.skip("Flask 未安装")


class TestSemiAutoIntegration:
    """
    半自动模式集成测试（需要真实环境）
    手动运行时取消 skip 标记
    """

    @pytest.mark.skip(reason="需要真实 AI API key 和屏幕显示，手动运行时移除此标记")
    def test_semi_auto_recognizes_web_questions(self):
        """
        半自动模式识别 Web 题目测试流程：
        1. 启动 Web 答题站 (python -m web.app)
        2. 浏览器全屏打开 http://127.0.0.1:5000/
        3. 运行 VisionQuiz 半自动模式
        4. 等待 HUD 显示识别结果
        5. 用户确认后检查标记流程

        预期：
        - 题库题（37 道）正确率 ≥ 95%
        - HUD 正确显示题目+答案
        - 用户确认流程无异常
        - pending_answer 超时自动标记正常
        """
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
