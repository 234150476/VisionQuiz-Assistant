import sqlite3
import time
import unittest
from unittest.mock import MagicMock, patch

import imagehash
from PIL import Image

from core.engine import Engine, EngineMode, EngineState
from core.recognizer import RecognizeResult
from ui.error_mapper import UIErrorMapper


class EngineTests(unittest.TestCase):
    def make_cfg(self):
        return {
            "cache_expire_days": 7,
            "api_key": "key",
            "api_base_url": "https://example.com/v1",
            "model": "gpt-test",
            "timeout": 3,
            "similarity_threshold": 0.8,
            "screenshot_interval": 0.01,
        }

    def test_start_initializes_components_and_updates_state(self):
        mock_cache = MagicMock()
        mock_ai = MagicMock()
        mock_recognizer = MagicMock()
        mock_thread = MagicMock()

        with patch("core.engine.CacheDB", return_value=mock_cache), patch(
            "core.engine.AIClient", return_value=mock_ai
        ), patch("core.engine.Recognizer", return_value=mock_recognizer), patch(
            "core.engine.threading.Thread", return_value=mock_thread
        ):
            engine = Engine(self.make_cfg(), mode=EngineMode.SEMI_AUTO)
            on_status = MagicMock()
            engine.set_callbacks(on_status=on_status)
            engine.start()

        mock_cache.init_db.assert_called_once_with(7)
        mock_thread.start.assert_called_once()
        self.assertTrue(engine.is_running)
        self.assertEqual(engine._state, EngineState.RUNNING)
        on_status.assert_called_with("运行中")

    def test_start_rolls_back_initialized_components_on_failure(self):
        mock_cache = MagicMock()
        mock_ai = MagicMock()

        with patch("core.engine.CacheDB", return_value=mock_cache), patch(
            "core.engine.AIClient", return_value=mock_ai
        ), patch("core.engine.Recognizer", side_effect=RuntimeError("boom")):
            engine = Engine(self.make_cfg(), mode=EngineMode.SEMI_AUTO)
            with self.assertRaises(RuntimeError):
                engine.start()

        mock_ai.close.assert_called_once()
        mock_cache.close.assert_called_once()
        self.assertFalse(engine.is_running)
        self.assertEqual(engine._state, EngineState.IDLE)

    def test_stop_uses_five_second_join_budget(self):
        engine = Engine(self.make_cfg(), mode=EngineMode.SEMI_AUTO)
        engine._state = EngineState.RUNNING
        engine._ai = MagicMock()
        engine._cache = MagicMock()
        engine._thread = MagicMock()
        engine._thread.is_alive.side_effect = [True, False]
        on_status = MagicMock()
        engine.set_callbacks(on_status=on_status)

        engine.stop()

        self.assertTrue(engine._stop_event.is_set())
        self.assertEqual(engine._state, EngineState.IDLE)
        on_status.assert_called_with("已停止")

    def test_stop_closes_ai_and_cache_and_joins_thread(self):
        engine = Engine(self.make_cfg(), mode=EngineMode.SEMI_AUTO)
        mock_ai = MagicMock()
        mock_cache = MagicMock()
        mock_thread = MagicMock()
        mock_thread.is_alive.side_effect = [True, False]
        engine._state = EngineState.RUNNING
        engine._ai = mock_ai
        engine._cache = mock_cache
        engine._thread = mock_thread

        engine.stop()

        mock_ai.close.assert_called_once()
        mock_thread.join.assert_called_once_with(timeout=5)
        mock_cache.close.assert_called_once()

    def test_tick_updates_last_snapshot_and_notifies_result(self):
        engine = Engine(self.make_cfg(), mode=EngineMode.SEMI_AUTO)
        result = RecognizeResult()
        result.answer = "A"
        result.question_hash = "q-1"
        on_result = MagicMock()
        engine.set_callbacks(on_result=on_result)
        engine._tick_capture = MagicMock(return_value=Image.new("RGB", (10, 10)))
        valid_hex = "a0a0a0a0a0a0a0a0"
        engine._tick_hash = MagicMock(return_value=(valid_hex, "hint"))
        engine._tick_recognize = MagicMock(return_value=result)
        engine._tick_click = MagicMock(return_value=True)

        engine._tick()

        self.assertEqual(str(engine._last_phash), valid_hex)
        self.assertEqual(engine._last_phash_str, valid_hex)
        self.assertEqual(engine._last_result_qhash, "q-1")
        on_result.assert_called_once_with(result)
        engine._tick_click.assert_called_once()

    def test_tick_recognize_reports_error_on_exception(self):
        engine = Engine(self.make_cfg(), mode=EngineMode.SEMI_AUTO)
        engine._recognizer = MagicMock()
        engine._recognizer.recognize.side_effect = RuntimeError("boom")
        on_error = MagicMock()
        engine.set_callbacks(on_error=on_error)

        result = engine._tick_recognize(Image.new("RGB", (10, 10)), "phash")

        self.assertIsNone(result)
        on_error.assert_called_once()

    def test_mark_current_answered_uses_question_hash_fallback(self):
        engine = Engine(self.make_cfg(), mode=EngineMode.SEMI_AUTO)
        engine._cache = MagicMock()
        engine._cache.get_by_phash.return_value = None
        engine._last_phash_str = "phash"
        engine._last_result_qhash = "q-1"

        engine.mark_current_answered()

        engine._cache.mark_answered.assert_called_once_with("q-1")

    def test_similar_screen_detected_as_duplicate(self):
        """Hamming 距离 ≤ 8 的两张图片 hash 应判定为重复画面。"""
        engine = Engine(self.make_cfg(), mode=EngineMode.SEMI_AUTO)
        engine._cache = MagicMock()
        engine._cache.get_by_phash.return_value = None

        # 创建两张仅差 2 bit 的 hash
        hash_a = imagehash.hex_to_hash("a0a0a0a0a0a0a0a0")
        # 翻转 2 bit
        hash_b = imagehash.hex_to_hash("a0a0a0a0a0a0a0a2")
        distance = hash_a - hash_b
        self.assertLessEqual(distance, 8)

        engine._last_phash = hash_a

        # Mock compute_phash 返回 hash_b 的字符串形式
        with patch("core.engine.ss.compute_phash", return_value=str(hash_b)):
            with patch("core.engine.ss.compute_question_hash", return_value="hint"):
                img = Image.new("RGB", (10, 10))
                result = engine._tick_hash(img)

        # Hamming 距离 ≤ 8 → 判定为重复，返回 None
        self.assertIsNone(result)

    def test_different_screen_not_detected_as_duplicate(self):
        """Hamming 距离 > 8 的两张图片 hash 应判定为不同画面。"""
        engine = Engine(self.make_cfg(), mode=EngineMode.SEMI_AUTO)
        engine._cache = MagicMock()
        engine._cache.get_by_phash.return_value = None

        hash_a = imagehash.hex_to_hash("0000000000000000")
        hash_b = imagehash.hex_to_hash("ffffffffffffffff")
        distance = hash_a - hash_b
        self.assertGreater(distance, 8)

        engine._last_phash = hash_a

        with patch("core.engine.ss.compute_phash", return_value=str(hash_b)):
            with patch("core.engine.ss.compute_question_hash", return_value="hint"):
                img = Image.new("RGB", (10, 10))
                result = engine._tick_hash(img)

        # Hamming 距离 > 8 → 不同画面，返回非 None
        self.assertIsNotNone(result)

    def test_recognition_timeout_skips_round(self):
        """识别调用超时后应返回 None 而非阻塞。"""
        cfg = self.make_cfg()
        cfg["recognition_timeout"] = 1  # 1 秒超时
        engine = Engine(cfg, mode=EngineMode.SEMI_AUTO)
        engine._recognition_timeout = 1
        on_error = MagicMock()
        engine.set_callbacks(on_error=on_error)
        engine._recognizer = MagicMock()

        # 模拟识别器耗时 60 秒
        def slow_recognize(img, phash_str=""):
            time.sleep(60)
            return RecognizeResult()

        engine._recognizer.recognize.side_effect = slow_recognize

        img = Image.new("RGB", (10, 10))
        result = engine._tick_recognize(img, "phash")

        self.assertIsNone(result)
        on_error.assert_called()

    def test_semi_auto_does_not_auto_mark(self):
        """半自动模式下识别后不应立即标记 answered。"""
        cfg = self.make_cfg()
        cfg["auto_mark_timeout"] = 10
        engine = Engine(cfg, mode=EngineMode.SEMI_AUTO)
        engine._cache = MagicMock()
        result = RecognizeResult()
        result.answer = "A"
        result.question_hash = "q-semi"
        engine._tick_capture = MagicMock(return_value=Image.new("RGB", (10, 10)))
        valid_hex = "a0a0a0a0a0a0a0a0"
        engine._tick_hash = MagicMock(return_value=(valid_hex, "hint"))
        engine._tick_recognize = MagicMock(return_value=result)
        engine._tick_click = MagicMock(return_value=True)

        engine._tick()

        # 半自动模式：不应调用 mark_answered
        engine._cache.mark_answered.assert_not_called()
        # 应设置 pending_answer
        self.assertIsNotNone(engine._pending_answer)
        self.assertEqual(engine._pending_answer["question_hash"], "q-semi")

    def test_semi_auto_mark_after_user_confirm(self):
        """半自动模式下用户手动确认后应标记 answered。"""
        cfg = self.make_cfg()
        engine = Engine(cfg, mode=EngineMode.SEMI_AUTO)
        engine._cache = MagicMock()
        engine._cache.get_by_phash.return_value = None
        engine._last_phash_str = "phash"
        engine._last_result_qhash = "q-confirm"
        engine._pending_answer = {"question_hash": "q-confirm", "time": time.monotonic()}

        engine.mark_current_answered()

        engine._cache.mark_answered.assert_called_once_with("q-confirm")
        self.assertIsNone(engine._pending_answer)

    def test_semi_auto_auto_mark_after_timeout(self):
        """半自动模式下超时后应自动标记 answered。"""
        cfg = self.make_cfg()
        cfg["auto_mark_timeout"] = 1  # 1 秒超时
        engine = Engine(cfg, mode=EngineMode.SEMI_AUTO)
        engine._cache = MagicMock()
        # 设置一个已超时的 pending_answer
        engine._pending_answer = {
            "question_hash": "q-timeout",
            "time": time.monotonic() - 5,  # 5 秒前
        }
        engine._tick_capture = MagicMock(return_value=None)  # 不继续识别

        engine._tick()

        engine._cache.mark_answered.assert_called_once_with("q-timeout")
        self.assertIsNone(engine._pending_answer)

    def test_switch_db_updates_recognizer_matcher(self):
        engine = Engine(self.make_cfg(), mode=EngineMode.SEMI_AUTO)
        engine._recognizer = MagicMock()
        matcher = object()

        with patch("core.engine.os.path.isfile", return_value=True), patch(
            "core.engine.QuestionMatcher", return_value=matcher
        ):
            engine.switch_db("questions.db")

        engine._recognizer.set_matcher.assert_called_once_with(matcher)

    def test_notify_error_isolates_callback_exception(self):
        engine = Engine(self.make_cfg(), mode=EngineMode.SEMI_AUTO)

        def broken_callback(_msg):
            raise RuntimeError("callback boom")

        engine.set_callbacks(on_error=broken_callback)
        engine._notify_error("msg")


class UIErrorMapperTests(unittest.TestCase):
    def test_translate_connection_error(self):
        user_msg, severity = UIErrorMapper.translate(ConnectionError("network"))

        self.assertEqual(severity, "error")
        self.assertEqual(user_msg, "AI 服务连接失败，请检查网络和 API Key")

    def test_translate_database_error(self):
        user_msg, severity = UIErrorMapper.translate(sqlite3.DatabaseError("broken db"))

        self.assertEqual(severity, "error")
        self.assertEqual(user_msg, "题库数据损坏，请重新导入")

    def test_translate_timeout_error(self):
        user_msg, severity = UIErrorMapper.translate(TimeoutError("slow"))

        self.assertEqual(severity, "error")
        self.assertEqual(user_msg, "请求超时，请稍后重试")

    def test_translate_engine_runtime_message(self):
        user_msg, severity = UIErrorMapper.translate("自动点击失败，请手动操作")

        self.assertEqual(severity, "error")
        self.assertEqual(user_msg, "自动点击失败，请手动完成当前题目")


if __name__ == "__main__":
    unittest.main()
