"""
主引擎模块 —— 后台循环线程，整合截图→识别→展示→点击完整流程
"""

import threading
import logging
import os
from typing import Optional, Callable

from core import config
from core.cache import CacheDB
from core.matcher import QuestionMatcher
from core.ai_client import AIClient
from core.recognizer import Recognizer, RecognizeResult
from core.clicker import AutoClicker
from core import screenshot as ss

logger = logging.getLogger(__name__)


class EngineMode:
    SEMI_AUTO = "semi"   # 半自动：只显示答案，用户手动点击
    FULL_AUTO = "full"   # 全自动：自动点击选项


class EngineState:
    IDLE = "idle"
    RUNNING = "running"
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

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # 快照：mark_current_answered 使用固定 phash，避免与 _last_phash 竞态
        self._last_phash: str = ""
        self._last_phash_lock = threading.Lock()

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
        if self._state == EngineState.RUNNING:
            return
        self._stop_event.clear()
        self._init_components()
        self._state = EngineState.RUNNING
        self._thread = threading.Thread(target=self._loop, daemon=True, name="EngineLoop")
        self._thread.start()
        logger.info("引擎已启动（模式: %s）", self._mode)
        self._notify_status("运行中")

    def stop(self):
        """
        停止引擎。
        先设置停止事件，等待线程退出后再清理资源，避免线程仍在运行时关闭数据库连接。
        """
        self._stop_event.set()
        self._state = EngineState.STOPPED
        if self._thread and self._thread.is_alive():
            # 等待线程实际退出，超时后记录警告但继续清理
            self._thread.join(timeout=35)  # 略大于 AI 最大超时(30s)
            if self._thread.is_alive():
                logger.warning("引擎线程未能在超时内停止，强制清理资源")
        self._thread = None
        self._cleanup()
        logger.info("引擎已停止")
        self._notify_status("已停止")

    @property
    def is_running(self) -> bool:
        return self._state == EngineState.RUNNING

    # ------------------------------------------------------------------
    # 内部初始化
    # ------------------------------------------------------------------

    def _init_components(self):
        cfg = self._cfg
        expire_days = cfg.get("cache_expire_days", 7)

        # 缓存
        self._cache = CacheDB()
        self._cache.init_db(expire_days)

        # 题库匹配器
        self._matcher = None
        if self._db_path and os.path.isfile(self._db_path):
            try:
                self._matcher = QuestionMatcher(self._db_path)
                logger.info("题库已加载: %s", self._db_path)
            except Exception as e:
                logger.warning("题库加载失败: %s", e)

        # AI 客户端
        self._ai = None
        api_key = cfg.get("api_key", "").strip()
        model = cfg.get("model", "").strip()
        if api_key and model:
            self._ai = AIClient(
                api_key=api_key,
                api_base_url=cfg.get("api_base_url", "https://api.openai.com/v1"),
                model=model,
                timeout=cfg.get("timeout", 30),
            )

        # 识别器
        self._recognizer = Recognizer(
            cache=self._cache,
            matcher=self._matcher,
            ai_client=self._ai,
            similarity_threshold=cfg.get("similarity_threshold", 0.8),
        )

        # 自动点击器（仅全自动模式；分辨率由主线程通过 screen_size 传入，不在此处创建 tk.Tk()）
        if self._mode == EngineMode.FULL_AUTO:
            sw, sh = self._screen_size
            self._clicker = AutoClicker(self._recognizer, sw, sh)

    def _cleanup(self):
        if self._cache:
            self._cache.close()
            self._cache = None

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    def _loop(self):
        interval = self._cfg.get("screenshot_interval", 2)

        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.exception("引擎循环异常: %s", e)
                self._notify_error(f"运行异常: {e}")

            # 等待下一个截图周期，支持快速响应停止信号
            self._stop_event.wait(timeout=interval)

    def _tick(self):
        # 截图
        img = ss.capture_screen()

        # pHash（计算一次，传递给 recognizer 避免重复计算）
        phash_str = ss.compute_phash(img)

        # pHash 去重：画面未变化则跳过
        with self._last_phash_lock:
            if phash_str == self._last_phash:
                return
            self._last_phash = phash_str

        # 检查 pHash 缓存（已答过，直接跳过）
        if self._cache:
            cached = self._cache.get_by_phash(phash_str)
            if cached and cached.get("answered"):
                return  # 已答过，跳过

        # 识别（将 phash_str 传入，避免 recognizer 内部重复计算）
        result = self._recognizer.recognize(img, phash_str=phash_str)
        if result is None:
            self._notify_error("识别失败：所有策略均未能给出答案")
            return

        # 通知 UI 展示结果
        self._notify_result(result)

        # 全自动模式：执行点击
        if self._mode == EngineMode.FULL_AUTO and self._clicker:
            success = self._clicker.execute(img, result.answer)
            if success and self._cache and result.question_hash:
                self._cache.mark_answered(result.question_hash)
            elif not success:
                self._notify_error("自动点击失败，请手动操作")

        # 半自动模式：answered 由用户确认后外部调用 mark_current_answered()

    # ------------------------------------------------------------------
    # 回调通知
    # ------------------------------------------------------------------

    def _notify_result(self, result: RecognizeResult):
        if self._on_result:
            try:
                self._on_result(result)
            except Exception as e:
                logger.error("on_result 回调异常: %s", e)

    def _notify_error(self, msg: str):
        if self._on_error:
            try:
                self._on_error(msg)
            except Exception as e:
                logger.error("on_error 回调异常: %s", e)

    def _notify_status(self, status: str):
        if self._on_status:
            try:
                self._on_status(status)
            except Exception as e:
                logger.error("on_status 回调异常: %s", e)

    # ------------------------------------------------------------------
    # 外部接口（半自动模式使用）
    # ------------------------------------------------------------------

    def mark_current_answered(self):
        """
        半自动模式下，用户手动选择答案后调用此方法标记当前题目已完成。
        使用加锁读取 _last_phash 快照，避免与引擎线程竞态。
        """
        with self._last_phash_lock:
            phash_snapshot = self._last_phash

        if self._cache and phash_snapshot:
            cached = self._cache.get_by_phash(phash_snapshot)
            if cached and cached.get("question_hash"):
                self._cache.mark_answered(cached["question_hash"])

    def switch_db(self, db_path: str):
        """切换题库（运行时热切换，线程安全）。"""
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
