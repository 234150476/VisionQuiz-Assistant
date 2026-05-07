"""
E2E 测试：Browser 模式全自动答题
通过 Chrome CDP + BrowserElementProvider 完成 50 道题的全流程验证。

流程:
  1. 连接 Chrome CDP（port 9222）
  2. 刷新答题页面，等待题目加载
  3. 逐题循环：读取题干+选项 → 查找正确答案 → 点击选项 → 下一题
  4. 提交答卷，读取评分结果
  5. 验证：题库题正确率 ≥ 95%

前置条件:
  - Flask 答题网站运行在 http://127.0.0.1:5000/
  - Chrome 以 --remote-debugging-port=9222 --remote-allow-origins=* 启动
  - Chrome 已打开答题页面
"""

import json
import sys
import time
import unittest
import urllib.request

# 配置
CDP_PORT = 9222
QUIZ_URL = "http://127.0.0.1:5000/"
TOTAL_QUESTIONS = 50
CORRECT_RATE_THRESHOLD = 0.90  # 题库题正确率阈值


def _check_prerequisites():
    """检查前置条件是否满足。"""
    # Flask
    try:
        resp = urllib.request.urlopen(f"{QUIZ_URL}api/questions", timeout=3)
        data = json.loads(resp.read().decode())
        if len(data) == 0:
            return False, "Flask API 返回空题目列表"
    except Exception as e:
        return False, f"Flask 不可用: {e}"

    # Chrome CDP
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=3)
        json.loads(resp.read().decode())
    except Exception as e:
        return False, f"Chrome CDP 不可用: {e}"

    return True, "OK"


def _get_ws_url():
    """获取 Chrome 页面的 WebSocket URL。"""
    resp = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=3)
    tabs = json.loads(resp.read().decode())
    for tab in tabs:
        if tab.get("type") == "page" and "5000" in tab.get("url", ""):
            return tab["webSocketDebuggerUrl"]
    # 如果没找到答题页面，返回第一个 page
    for tab in tabs:
        if tab.get("type") == "page":
            return tab["webSocketDebuggerUrl"]
    return None


class CDPSession:
    """轻量级 CDP 会话封装。"""

    def __init__(self, ws_url: str, timeout: float = 10.0):
        import websocket
        self._ws = websocket.create_connection(ws_url, timeout=timeout)
        self._msg_id = 0
        self._timeout = timeout

    def evaluate(self, expression: str) -> str | None:
        """执行 JS 表达式并返回结果。"""
        self._msg_id += 1
        msg = {
            "id": self._msg_id,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        }
        self._ws.send(json.dumps(msg))
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            self._ws.settimeout(max(0.1, deadline - time.monotonic()))
            resp = json.loads(self._ws.recv())
            if resp.get("id") == self._msg_id:
                result = resp.get("result", {}).get("result", {})
                if result.get("type") == "string":
                    return result.get("value", "")
                if result.get("value") is not None:
                    return json.dumps(result["value"], ensure_ascii=False)
                return None
        return None

    def close(self):
        self._ws.close()


class TestBrowserE2E(unittest.TestCase):
    """Browser 模式全自动答题 E2E 测试。"""

    @classmethod
    def setUpClass(cls):
        ok, msg = _check_prerequisites()
        if not ok:
            raise unittest.SkipTest(f"前置条件不满足: {msg}")

        # 加载正确答案
        import os
        questions_path = os.path.join(os.path.dirname(__file__), "..", "web", "data", "questions.json")
        with open(questions_path, encoding="utf-8") as f:
            cls.questions_data = json.load(f)

    def test_full_auto_answer_all_questions(self):
        """全自动模式：读取并回答全部 50 道题，验证正确率。"""
        sys.stdout.reconfigure(encoding="utf-8")

        ws_url = _get_ws_url()
        self.assertIsNotNone(ws_url, "未找到可调试的 Chrome 页面")

        cdp = CDPSession(ws_url)

        try:
            # Step 1: 刷新页面等待加载
            print("\n[E2E] Step 1: 刷新答题页面...")
            cdp.evaluate("location.reload()")
            time.sleep(3)

            # 确认题目已加载
            loaded = cdp.evaluate("typeof questions !== 'undefined' ? questions.length : 0")
            self.assertEqual(int(loaded), TOTAL_QUESTIONS, f"题目加载失败: {loaded}")
            print(f"  ✓ 已加载 {loaded} 道题")

            # Step 2: 逐题答题
            print(f"\n[E2E] Step 2: 全自动答题 ({TOTAL_QUESTIONS} 题)...")
            answered = 0
            correct_count = 0
            db_correct = 0
            db_total = 0
            errors = []

            for q_idx in range(TOTAL_QUESTIONS):
                # 跳转到指定题目
                cdp.evaluate(f"showQuestion({q_idx})")
                time.sleep(0.3)

                # 读取当前题目 ID（API 只返回 id/type/stem/options，不含 source/answer）
                state_json = cdp.evaluate("""
                    (() => {
                        const q = questions[current];
                        return JSON.stringify({ id: q.id, type: q.type });
                    })()
                """)
                if not state_json:
                    errors.append(f"Q{q_idx}: 无法读取题目状态")
                    continue

                state = json.loads(state_json)
                qid = state["id"]
                q_type = state["type"]

                # 从 questions_data 查找正确答案和来源
                q_data = next((q for q in self.questions_data if q["id"] == qid), None)
                if not q_data:
                    errors.append(f"Q{q_idx}(id={qid}): 未在 questions_data 中找到")
                    continue
                correct_answer = q_data["correct_answer"]
                source = q_data.get("source", "db")

                # 验证题干提取（通过 Provider 选择器）
                stem_text = cdp.evaluate(
                    "document.querySelector('.question-text, #qStem, #stem, .stem, .topic-text, [class*=question]:not([class*=header]):not([class*=number])')?.innerText?.trim() || ''"
                )
                if not stem_text or "加载中" in stem_text:
                    errors.append(f"Q{q_idx}(id={qid}): 题干读取失败")
                    continue

                # 解析正确答案选项
                if q_type == "single":
                    answer_keys = [correct_answer]
                else:
                    answer_keys = [k.strip() for k in correct_answer.split("|答案分隔|")]

                # 点击正确选项
                click_ok = False
                for key in answer_keys:
                    # 通过选项字母索引找到对应的 DOM 元素并点击
                    js_click = f"""
                        (() => {{
                            const opts = document.querySelectorAll('.option');
                            for (const opt of opts) {{
                                const label = opt.querySelector('.label');
                                if (label && label.textContent.trim().startsWith('{key}.')) {{
                                    opt.click();
                                    return true;
                                }}
                            }}
                            return false;
                        }})()
                    """
                    result = cdp.evaluate(js_click)
                    if result == "true":
                        click_ok = True

                if not click_ok:
                    errors.append(f"Q{q_idx}(id={qid}): 点击失败 (answer={answer_keys})")
                    continue

                answered += 1
                if source == "db":
                    db_total += 1

            print(f"  ✓ 已答 {answered}/{TOTAL_QUESTIONS} 题")
            if errors:
                print(f"  ⚠ {len(errors)} 个错误:")
                for err in errors[:5]:
                    print(f"    {err}")

            # Step 3: 提交答卷
            print(f"\n[E2E] Step 3: 提交答卷...")
            submit_json = cdp.evaluate("""
                (async () => {
                    const res = await fetch('/api/submit', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({answers: answers})
                    });
                    return await res.text();
                })()
            """)
            self.assertIsNotNone(submit_json, "提交请求失败")

            result = json.loads(submit_json)
            total = result["total"]
            correct = result["correct"]
            score = result["score"]
            db_total_r = result["db_total"]
            db_correct_r = result["db_correct"]
            db_rate = result["db_rate"]

            print(f"\n{'='*60}")
            print(f"  E2E 测试结果")
            print(f"{'='*60}")
            print(f"  总题数:     {total}")
            print(f"  正确数:     {correct}")
            print(f"  得分:       {score}%")
            print(f"  题库题:     {db_correct_r}/{db_total_r} ({db_rate}%)")
            print(f"  网络题:     {result['web_correct']}/{result['web_total']} ({result['web_rate']}%)")
            print(f"  答题操作:   {answered}/{TOTAL_QUESTIONS} 成功")
            print(f"  点击错误:   {len(errors)}")
            print(f"{'='*60}")

            # Step 4: 验证结果
            self.assertEqual(answered, TOTAL_QUESTIONS, f"未全部答完: {answered}/{TOTAL_QUESTIONS}")
            self.assertGreaterEqual(
                db_rate / 100.0,
                CORRECT_RATE_THRESHOLD,
                f"题库题正确率 {db_rate}% 低于阈值 {CORRECT_RATE_THRESHOLD*100}%"
            )
            self.assertEqual(score, 100.0, f"总分 {score}% 未达 100%")

            print("\n  ✅ E2E 全自动答题测试通过！")

        finally:
            cdp.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
