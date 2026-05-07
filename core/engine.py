"""
主引擎模块 —— 后台循环线程，整合截图→识别→展示→点击完整流程
"""

import threading
import logging
import os
import time
from typing import Optional, Callable

import imagehash

from core.cache import CacheDB
from core.matcher import QuestionMatcher
from core.ai_client import AIClient
from core.recognizer import Recognizer, RecognizeResult
from core.clicker import AutoClicker, ElementClicker
from core.element_provider import ElementProvider, QuestionElement
from core.answer_normalizer import normalize_bank_answer
from core import screenshot as ss

logger = logging.getLogger(__name__)


class EngineMode:
    SEMI_AUTO = "semi"   # 半自动：只显示答案，用户手动点击
    FULL_AUTO = "full"   # 全自动：自动点击选项


class EngineState:
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"


class Engine:
    """
    答题引擎：后台轮询截图，识别题目，通知 UI，按模式决定是否自动点击。

    使用方式：
        engine = Engine(cfg, db_path=..., mode=EngineMode.SEMI_AUTO, screen_size=(w, h))
        engine.set_callbacks(on_result=..., on_error=..., on_status=...)
        engine.start()
        ...
        engine.stop()

    注意：screen_size 必须在主线程（tkinter 线程）中获取后传入，
    不可在引擎内部调用 tk.Tk() 获取分辨率。
    """

    def __init__(
        self,
        cfg: dict,
        db_path: Optional[str] = None,
        mode: str = EngineMode.SEMI_AUTO,
        screen_size: tuple[int, int] = (1920, 1080),
    ):
        self._cfg = cfg
        self._db_path = db_path
        self._mode = mode
        self._screen_size = screen_size  # (width, height) 由主线程传入
        self._state_lock = threading.Lock()
        self._state = EngineState.IDLE

        # 回调函数（由 UI 注册）
        self._on_result: Optional[Callable[[RecognizeResult], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
        self._on_status: Optional[Callable[[str], None]] = None

        # 核心组件（start() 时初始化）
        self._cache: Optional[CacheDB] = None
        self._matcher: Optional[QuestionMatcher] = None
        self._ai: Optional[AIClient] = None
        self._recognizer: Optional[Recognizer] = None
        self._clicker: Optional[AutoClicker] = None
        self._provider: Optional[ElementProvider] = None
        self._element_clicker: Optional[ElementClicker] = None
        self._last_question_hash: str = ""  # 元素模式去重用

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # pHash Hamming 距离阈值（≤ threshold 判定为同屏）
        self._phash_threshold: int = cfg.get("phash_threshold", 8)
        # 识别调用超时（秒）
        self._recognition_timeout: int = cfg.get("recognition_timeout", 45)

        # 快照：mark_current_answered 使用固定 phash/qhash，避免与 _last_phash 竞态
        self._last_phash: Optional[imagehash.ImageHash] = None  # ImageHash 对象（Hamming 距离比较）
        self._last_phash_str: str = ""  # 字符串形式（仅用于日志）
        self._last_result_qhash: str = ""   # 最后一次识别成功的 question_hash（兜底用）
        self._last_phash_lock = threading.Lock()

        # 半自动模式：pending_answer 机制（等待用户手动标记或超时自动标记）
        self._pending_answer: Optional[dict] = None
        self._auto_mark_timeout: int = cfg.get("auto_mark_timeout", 10)

    # ------------------------------------------------------------------
    # 回调注册
    # ------------------------------------------------------------------

    def set_callbacks(
        self,
        on_result: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        on_status: Optional[Callable] = None,
    ):
        self._on_result = on_result
        self._on_error = on_error
        self._on_status = on_status

    # ------------------------------------------------------------------
    # 启动 / 停止
    # ------------------------------------------------------------------

    def start(self):
        with self._state_lock:
            if self._state != EngineState.IDLE:
                return
            self._state = EngineState.STARTING

        self._stop_event.clear()
        try:
            cache, matcher, ai_client, recognizer, clicker = self._init_components()
        except Exception:
            with self._state_lock:
                self._state = EngineState.IDLE
            raise

        self._cache = cache
        self._matcher = matcher
        self._ai = ai_client
        self._recognizer = recognizer
        self._clicker = clicker
        self._thread = threading.Thread(target=self._loop, daemon=True, name="EngineLoop")
        self._thread.start()
        with self._state_lock:
            self._state = EngineState.RUNNING
        logger.info("引擎已启动（模式: %s）", self._mode)
        self._notify_status("运行中")

    def stop(self):
        """
        停止引擎。
        先关闭外部 I/O，再设置停止事件，等待线程退出后清理资源。
        """
        with self._state_lock:
            if self._state in (EngineState.IDLE, EngineState.STOPPED):
                return
            if self._state == EngineState.STOPPING:
                return
            self._state = EngineState.STOPPING
            thread = self._thread
            ai_client = self._ai

        ai_closed = False
        try:
            if ai_client is not None:
                ai_client.close()
                ai_closed = True
        except Exception:
            logger.exception("关闭 AI 客户端失败")
        else:
            if ai_closed and self._ai is ai_client:
                self._ai = None

        self._stop_event.set()
        if thread and thread.is_alive():
            thread.join(timeout=5)
            if thread.is_alive():
                logger.warning("Thread did not exit within 5s")

        self._thread = None
        self._cleanup()
        with self._state_lock:
            self._state = EngineState.IDLE
        logger.info("引擎已停止")
        self._notify_status("已停止")

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return self._state == EngineState.RUNNING

    # ------------------------------------------------------------------
    # 内部初始化
    # ------------------------------------------------------------------

    def _init_components(self):
        cfg = self._cfg
        expire_days = cfg.get("cache_expire_days", 7)
        initialized = []

        try:
            # 缓存
            cache = CacheDB()
            initialized.append(cache)
            cache.init_db(expire_days)

            # 题库匹配器
            matcher = None
            if self._db_path and os.path.isfile(self._db_path):
                try:
                    matcher = QuestionMatcher(self._db_path)
                    logger.info("题库已加载: %s", self._db_path)
                except Exception as e:
                    logger.warning("题库加载失败: %s", e)

            # AI 客户端
            ai_client = None
            api_key = cfg.get("api_key", "").strip()
            model = cfg.get("model", "").strip()
            if api_key and model:
                ai_client = AIClient(
                    api_key=api_key,
                    api_base_url=cfg.get("api_base_url", "https://api.openai.com/v1"),
                    model=model,
                    timeout=cfg.get("timeout", 30),
                )
                initialized.append(ai_client)

            # 识别器
            recognizer = Recognizer(
                cache=cache,
                matcher=matcher,
                ai_client=ai_client,
                similarity_threshold=cfg.get("similarity_threshold", 0.55),
            )

            # 自动点击器（仅全自动模式；分辨率由主线程通过 screen_size 传入，不在此处创建 tk.Tk()）
            clicker = None
            if self._mode == EngineMode.FULL_AUTO:
                sw, sh = self._screen_size
                clicker = AutoClicker(recognizer, sw, sh)

            # P7: ElementProvider 初始化
            input_mode = cfg.get("input_mode", "screenshot")
            if input_mode == "browser":
                from core.browser_provider import BrowserElementProvider
                self._provider = BrowserElementProvider(
                    debug_port=cfg.get("browser_debug_port", 9222),
                    selector_config=cfg.get("browser_selector_config", ""),
                )
                if not self._provider.connect():
                    logger.warning("浏览器 Provider 连接失败，降级到截图模式")
                    self._provider = None
                else:
                    logger.info("浏览器模式已激活: %s", self._provider.name)
            elif input_mode == "windows":
                from core.windows_provider import WindowsElementProvider
                self._provider = WindowsElementProvider(
                    target_title=cfg.get("windows_target_title", ""),
                )
                if not self._provider.connect():
                    logger.warning("桌面程序 Provider 连接失败，降级到截图模式")
                    self._provider = None
                else:
                    logger.info("桌面程序模式已激活: %s", self._provider.name)

            # 元素模式下的点击器
            if self._provider and self._mode == EngineMode.FULL_AUTO:
                self._element_clicker = ElementClicker(self._provider)
            elif self._provider:
                # 半自动元素模式不需要 clicker
                pass

            return cache, matcher, ai_client, recognizer, clicker
        except Exception:
            self._cleanup_initialized(initialized)
            raise

    def _cleanup_initialized(self, initialized) -> None:
        for component in reversed(initialized):
            close = getattr(component, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.exception("初始化失败后的组件回收异常")

    def _cleanup(self):
        if self._ai:
            try:
                self._ai.close()
            except Exception:
                logger.exception("关闭 AI 客户端失败")
            self._ai = None

        if self._cache:
            try:
                self._cache.close()
            except Exception:
                logger.exception("关闭缓存失败")
            self._cache = None

        if self._provider:
            try:
                self._provider.close()
            except Exception:
                logger.exception("关闭 ElementProvider 失败")
            self._provider = None

        self._matcher = None
        self._recognizer = None
        self._clicker = None
        self._element_clicker = None

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    def _loop(self):
        interval = self._cfg.get("screenshot_interval", 2)

        while not self._stop_event.is_set():
            try:
                if self._provider:
                    self._tick_provider()
                else:
                    self._tick()
            except Exception as e:
                logger.exception("引擎循环异常: %s", e)
                self._notify_error(f"运行异常: {e}")

            # 等待下一个截图周期，支持快速响应停止信号
            self._stop_event.wait(timeout=interval)

    def _tick_capture(self):
        try:
            img = ss.capture_screen()
            if img is None:
                logger.info("截图失败，跳过本轮")
                return None
            return img
        except Exception as exc:
            logger.exception("截图阶段异常: %s", exc)
            self._notify_error(f"截图异常: {exc}")
            return None

    def _tick_hash(self, img):
        try:
            phash_str = ss.compute_phash(img)
            question_hash_hint = ss.compute_question_hash(phash_str) if phash_str else ""

            if phash_str:
                phash_obj = imagehash.hex_to_hash(phash_str)
            else:
                phash_obj = None

            with self._last_phash_lock:
                if phash_obj is not None and self._last_phash is not None:
                    distance = phash_obj - self._last_phash
                    if distance <= self._phash_threshold:
                        return None

            if self._cache and phash_str:
                cached = self._cache.get_by_phash(phash_str)
                if cached and cached.get("answered"):
                    with self._last_phash_lock:
                        self._last_phash = phash_obj
                        self._last_phash_str = phash_str
                    return None

            return phash_str, question_hash_hint
        except Exception as exc:
            logger.exception("哈希阶段异常: %s", exc)
            return "", ""

    def _tick_recognize(self, img, phash_str: str):
        try:
            if self._recognizer is None:
                self._notify_error("识别器未初始化")
                return None

            # 带超时保护的识别调用：防止 AI 调用长时间阻塞引擎循环
            result_box: list = [None]
            error_box: list = [None]

            def _do_recognize():
                try:
                    result_box[0] = self._recognizer.recognize(img, phash_str=phash_str)
                except Exception as exc:
                    error_box[0] = exc

            worker = threading.Thread(target=_do_recognize, daemon=True, name="RecognizeWorker")
            worker.start()
            worker.join(timeout=self._recognition_timeout)

            if worker.is_alive():
                # 超时：引擎继续运行，不阻塞
                logger.warning("识别超时 (%.1fs)，跳过本轮", self._recognition_timeout)
                self._notify_error(f"识别超时 ({self._recognition_timeout}s)，已跳过")
                return None

            if error_box[0] is not None:
                raise error_box[0]

            result = result_box[0]
            if result is None or not isinstance(result.answer, str) or not result.answer.strip():
                self._notify_error("识别失败：所有策略均未能给出答案")
                return None
            return result
        except Exception as exc:
            logger.exception("识别阶段异常: %s", exc)
            self._notify_error(f"识别异常: {exc}")
            return None

    def _tick_click(self, img, result: RecognizeResult) -> bool:
        try:
            if self._mode != EngineMode.FULL_AUTO or self._clicker is None:
                return True
            # 将截图尺寸附加到 result，供 clicker 坐标转换使用
            img_w, img_h = img.size
            result._img_w = img_w
            result._img_h = img_h
            success = self._clicker.dispatch_answer(result)
            if success:
                if self._cache and result.question_hash:
                    self._cache.mark_answered(result.question_hash)
                return True
            self._notify_error("自动点击失败，请手动操作")
            return False
        except Exception as exc:
            logger.exception("点击阶段异常: %s", exc)
            self._notify_error(f"自动点击异常: {exc}")
            return False

    def _normalize_bank_result(self, img, ocr_text: str, result: "RecognizeResult") -> "RecognizeResult":
        """题库命中后补调 Prompt A 获取选项坐标并归一化答案。

        当题库匹配成功但缺少选项坐标时，调用 AI 的 Prompt A 仅获取选项位置，
        然后将题库答案文本映射为选项字母（如 "D: xxx" → "D"）。
        """
        # 已有选项坐标时直接归一化
        if result.options:
            result.answer = normalize_bank_answer(
                result.answer, result.options, result.question_type
            )
            return result

        # 无选项坐标：调用 Prompt A 获取
        if self._ai and img is not None:
            try:
                img_input = ocr_text.strip() if ocr_text.strip() else "（请直接读取截图内容）"
                prompt_a = self._ai.answer_with_image(img_input, img)
                if prompt_a:
                    result.question_type = result.question_type or prompt_a.question_type
                    result.options = [
                        {"text": o.text, "x": o.x, "y": o.y, "letter": chr(ord("A") + i)}
                        for i, o in enumerate(prompt_a.options)
                    ]
                    result.input_targets = [
                        {"placeholder": t.placeholder, "x": t.x, "y": t.y}
                        for t in prompt_a.input_targets
                    ]
                    result.recognition_source = "vision"
                    logger.debug("Prompt A 获取选项成功: %d 个选项", len(result.options))
            except Exception as exc:
                logger.warning("Prompt A 获取选项失败: %s", exc)

        # 归一化答案
        if result.options:
            result.answer = normalize_bank_answer(
                result.answer, result.options, result.question_type
            )
        else:
            # Prompt A 也失败，仅做纯字母提取
            result.answer = normalize_bank_answer(
                result.answer, [], result.question_type
            )

        result.answer_source = "bank"
        return result

    def _tick(self):
        # 半自动模式：检查 pending_answer 是否超时需要自动标记
        if self._pending_answer and self._cache:
            elapsed = time.monotonic() - self._pending_answer["time"]
            if elapsed >= self._auto_mark_timeout:
                qhash = self._pending_answer["question_hash"]
                self._pending_answer = None
                if qhash:
                    self._cache.mark_answered(qhash)
                    logger.info("半自动模式超时 (%.0fs)，已自动标记 answered: %s", elapsed, qhash)

        img = self._tick_capture()
        if img is None:
            return

        hash_result = self._tick_hash(img)
        if hash_result is None:
            return
        phash_str, _ = hash_result

        result = self._tick_recognize(img, phash_str)
        if result is None:
            return

        # 题库命中时：补调 Prompt A 获取选项坐标 + 归一化答案
        if result.source == "bank" and not result.options:
            result = self._normalize_bank_result(img, result.question_text, result)

        with self._last_phash_lock:
            if phash_str:
                self._last_phash = imagehash.hex_to_hash(phash_str)
                self._last_phash_str = phash_str
            self._last_result_qhash = result.question_hash

        self._notify_result(result)
        self._tick_click(img, result)

        if self._mode == EngineMode.SEMI_AUTO:
            # 半自动模式：不立即标记 answered，等待用户手动确认或超时自动标记
            self._pending_answer = {
                "question_hash": result.question_hash,
                "time": time.monotonic(),
            }
        else:
            # 全自动模式：立即标记 answered
            if self._cache and result.question_hash:
                self._cache.mark_answered(result.question_hash)

    def _tick_provider(self):
        """元素模式的主循环分支：通过 Provider 直接读取元素。"""
        # 半自动 pending_answer 超时检查（与截图模式共享）
        if self._pending_answer and self._cache:
            elapsed = time.monotonic() - self._pending_answer["time"]
            if elapsed >= self._auto_mark_timeout:
                qhash = self._pending_answer["question_hash"]
                self._pending_answer = None
                if qhash:
                    self._cache.mark_answered(qhash)
                    logger.info("半自动模式超时 (%.0fs)，已自动标记 answered: %s", elapsed, qhash)

        # 读取题目元素
        question_elem = self._provider.get_question_elements()
        if question_elem is None:
            return

        # 元素级去重（用 raw_hash 替代 pHash）
        qhash = question_elem.raw_hash
        if qhash == self._last_question_hash:
            return

        # 题库匹配
        result = None
        if self._matcher and question_elem.question_text.strip():
            try:
                bank_hit = self._matcher.find_best(
                    question_elem.question_text.strip(),
                    self._cfg.get("similarity_threshold", 0.55),
                )
                if bank_hit:
                    result = RecognizeResult()
                    result.question_text = question_elem.question_text
                    result.answer = bank_hit["answer"]
                    result.source = "bank"
                    result.question_hash = qhash
                    result.score = bank_hit["score"]
                    result.question_type = question_elem.question_type
                    result.answer_source = "bank"
                    # 附加 element_ref 到 options
                    result.options = [
                        {"text": o.text, "element_ref": o.element_ref, "index": o.index}
                        for o in question_elem.options
                    ]
                    # 归一化题库答案为选项字母
                    result.answer = normalize_bank_answer(
                        result.answer, result.options, result.question_type
                    )
            except Exception as exc:
                logger.warning("题库匹配失败: %s", exc)

        # AI 文本回答（仅 Prompt B）
        if result is None and self._ai:
            try:
                prompt_b = self._ai.answer_with_text(question_elem.question_text)
                if prompt_b and prompt_b.answer.strip():
                    result = RecognizeResult()
                    result.question_text = question_elem.question_text
                    result.answer = prompt_b.answer.strip()
                    result.source = "ai"
                    result.question_hash = qhash
                    result.question_type = question_elem.question_type
                    result.confidence = prompt_b.confidence
                    result.answer_source = prompt_b.answer_source
                    result.options = [
                        {"text": o.text, "element_ref": o.element_ref, "index": o.index}
                        for o in question_elem.options
                    ]
                    result.input_targets = [
                        {"placeholder": t.placeholder, "element_ref": t.element_ref}
                        for t in question_elem.input_targets
                    ]
            except Exception as exc:
                logger.warning("AI 文本回答失败: %s", exc)

        if result is None:
            self._notify_error("元素模式识别失败：题库和 AI 均无结果")
            return

        self._last_question_hash = qhash
        self._notify_result(result)

        # 点击操作
        if self._mode == EngineMode.FULL_AUTO and self._element_clicker:
            success = self._element_clicker.dispatch_answer(result, question_elem)
            if success:
                if self._cache and result.question_hash:
                    self._cache.mark_answered(result.question_hash)
            else:
                self._notify_error("元素模式自动点击失败")
        elif self._mode == EngineMode.SEMI_AUTO:
            self._pending_answer = {
                "question_hash": result.question_hash,
                "time": time.monotonic(),
            }
        else:
            if self._cache and result.question_hash:
                self._cache.mark_answered(result.question_hash)

    # ------------------------------------------------------------------
    # 回调通知
    # ------------------------------------------------------------------

    def _emit_callback(self, callback: Optional[Callable], *args):
        if callback:
            try:
                callback(*args)
            except Exception:
                logger.exception("callback error")

    def _notify_result(self, result: RecognizeResult):
        self._emit_callback(self._on_result, result)

    def _notify_error(self, msg: str):
        self._emit_callback(self._on_error, msg)

    def _notify_status(self, status: str):
        self._emit_callback(self._on_status, status)

    # ------------------------------------------------------------------
    # 外部接口（半自动模式使用）
    # ------------------------------------------------------------------

    def mark_current_answered(self):
        """
        半自动模式下，用户手动选择答案后调用此方法标记当前题目已完成。
        优先通过 pHash 查找缓存记录；若 pHash 尚未写入缓存（如题目通过 question_hash
        命中缓存但 phash 补写还未完成），则直接使用最后一次识别结果的 question_hash 兜底。
        """
        # 清除 pending_answer（用户已手动确认）
        self._pending_answer = None

        with self._last_phash_lock:
            phash_snapshot = self._last_phash_str
            qhash_snapshot = self._last_result_qhash

        if not self._cache:
            return

        # 优先通过 pHash 查找
        if phash_snapshot:
            cached = self._cache.get_by_phash(phash_snapshot)
            if cached and cached.get("question_hash"):
                self._cache.mark_answered(cached["question_hash"])
                return

        # 兜底：直接用最后一次识别结果的 question_hash
        if qhash_snapshot:
            self._cache.mark_answered(qhash_snapshot)

    def switch_db(self, db_path: str):
        """切换题库（仅限启动前，运行中禁止切换）。"""
        if self._state == EngineState.RUNNING:
            logger.warning("运行中不允许切换题库")
            return False
        self._db_path = db_path
        if os.path.isfile(db_path):
            try:
                new_matcher = QuestionMatcher(db_path)
                self._matcher = new_matcher
                if self._recognizer:
                    self._recognizer.set_matcher(new_matcher)
                logger.info("题库已切换: %s", db_path)
            except Exception as e:
                logger.warning("题库切换失败: %s", e)
