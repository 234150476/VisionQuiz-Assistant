"""
缓存模块 —— 基于 SQLite + 内存双层缓存
"""

import sqlite3
import datetime
import threading
from typing import Optional

import imagehash

from core import config


class CacheDB:
    """
    SQLite 持久化缓存 + 运行时内存缓存。

    内存缓存结构：
        _mem_by_qhash  : { question_hash -> row_dict }
        _mem_phash_list: [ row_dict, ... ]  （按插入顺序，用于汉明距离遍历）

    所有公共方法均通过 _lock 保证线程安全。
    """

    _CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS cache (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            question_hash   TEXT UNIQUE NOT NULL,
            phash           TEXT,
            answer          TEXT,
            source          TEXT,
            answered        INTEGER DEFAULT 0,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """

    def __init__(self):
        db_path = config.get_cache_db_path()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute(self._CREATE_TABLE_SQL)
        self._conn.commit()

        self._lock = threading.Lock()

        # 内存缓存
        self._mem_by_qhash: dict = {}       # question_hash -> row dict
        self._mem_phash_list: list = []     # 所有含 phash 的记录列表（与 _mem_by_qhash 共享同一 dict 对象）

        self._load_to_memory()

    # ------------------------------------------------------------------
    # 内部：内存加载
    # ------------------------------------------------------------------

    def _load_to_memory(self):
        """将数据库全量记录加载到内存缓存（初始化时调用，无需加锁）。"""
        cursor = self._conn.execute(
            "SELECT id, question_hash, phash, answer, source, answered, created_at, updated_at FROM cache"
        )
        rows = cursor.fetchall()
        for row in rows:
            d = dict(row)
            self._mem_by_qhash[d["question_hash"]] = d
            if d.get("phash"):
                self._mem_phash_list.append(d)

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def init_db(self, expire_days: int) -> None:
        """
        启动时清理过期记录。
        删除 created_at 早于 expire_days 天的记录，并同步更新内存缓存。
        """
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=expire_days)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            cursor = self._conn.execute(
                "SELECT question_hash FROM cache WHERE created_at < ?", (cutoff_str,)
            )
            expired_hashes = {row["question_hash"] for row in cursor.fetchall()}

            if expired_hashes:
                self._conn.execute(
                    "DELETE FROM cache WHERE created_at < ?", (cutoff_str,)
                )
                self._conn.commit()

                # 同步内存缓存
                for qhash in expired_hashes:
                    self._mem_by_qhash.pop(qhash, None)
                self._mem_phash_list = [
                    r for r in self._mem_phash_list
                    if r["question_hash"] not in expired_hashes
                ]

    def get_by_phash(
        self, phash_str: str, hamming_threshold: int = 8
    ) -> Optional[dict]:
        """
        遍历内存中所有含 phash 的记录，用 imagehash 计算汉明距离。
        返回距离最小且不超过阈值的记录 dict，否则返回 None。
        """
        if not phash_str:
            return None

        try:
            query_hash = imagehash.hex_to_hash(phash_str)
        except Exception:
            return None

        with self._lock:
            if not self._mem_phash_list:
                return None

            best_record = None
            best_distance = hamming_threshold + 1

            for record in self._mem_phash_list:
                stored_phash_str = record.get("phash")
                if not stored_phash_str:
                    continue
                try:
                    stored_hash = imagehash.hex_to_hash(stored_phash_str)
                    distance = query_hash - stored_hash
                except Exception:
                    continue

                if distance < best_distance:
                    best_distance = distance
                    best_record = record

            if best_distance <= hamming_threshold and best_record is not None:
                return dict(best_record)
            return None

    def get_by_question_hash(self, qhash: str) -> Optional[dict]:
        """
        按 question_hash 精确查询。
        优先走内存缓存，未命中时查数据库。
        返回 dict 或 None。
        """
        with self._lock:
            # 优先内存
            if qhash in self._mem_by_qhash:
                return dict(self._mem_by_qhash[qhash])

            # 回退到数据库
            cursor = self._conn.execute(
                "SELECT * FROM cache WHERE question_hash = ?", (qhash,)
            )
            row = cursor.fetchone()
            if row:
                d = dict(row)
                # 写入内存缓存（去重检查：phash 列表中避免重复追加）
                self._mem_by_qhash[d["question_hash"]] = d
                if d.get("phash") and not any(
                    r["question_hash"] == d["question_hash"] for r in self._mem_phash_list
                ):
                    self._mem_phash_list.append(d)
                return dict(d)
            return None

    def insert(
        self,
        question_hash: str,
        phash: Optional[str],
        answer: str,
        source: str,
    ) -> None:
        """
        插入新记录。若 question_hash 已存在则忽略（IGNORE）。
        同步更新内存缓存。
        """
        with self._lock:
            if question_hash in self._mem_by_qhash:
                # 记录已存在：若传入了新的 phash 且原记录无 phash，则补写
                existing = self._mem_by_qhash[question_hash]
                if phash and not existing.get("phash"):
                    # 更新数据库
                    self._conn.execute(
                        "UPDATE cache SET phash = ? WHERE question_hash = ?",
                        (phash, question_hash),
                    )
                    self._conn.commit()
                    # 同步内存
                    existing["phash"] = phash
                    if not any(r["question_hash"] == question_hash for r in self._mem_phash_list):
                        self._mem_phash_list.append(existing)
                return

            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO cache (question_hash, phash, answer, source)
                VALUES (?, ?, ?, ?)
                """,
                (question_hash, phash, answer, source),
            )
            self._conn.commit()

            now_str = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            record = {
                "id": cursor.lastrowid,
                "question_hash": question_hash,
                "phash": phash,
                "answer": answer,
                "source": source,
                "answered": 0,
                "created_at": now_str,
                "updated_at": now_str,
            }
            self._mem_by_qhash[question_hash] = record
            if phash:
                self._mem_phash_list.append(record)

    def mark_answered(self, question_hash: str) -> None:
        """
        将指定记录的 answered 置为 1，并更新 updated_at。
        同步更新内存缓存（_mem_phash_list 中的对象与 _mem_by_qhash 共享引用，直接修改生效）。
        """
        now_str = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            self._conn.execute(
                """
                UPDATE cache
                SET answered = 1, updated_at = ?
                WHERE question_hash = ?
                """,
                (now_str, question_hash),
            )
            self._conn.commit()

            # 同步内存：_mem_by_qhash 与 _mem_phash_list 中存的是同一个 dict 对象
            # （仅当记录通过 insert() 写入时成立；通过 _load_to_memory 加载的也是同一对象）
            # 对于通过 DB 回退路径加载的记录，两处可能是不同对象，需同时更新
            if question_hash in self._mem_by_qhash:
                self._mem_by_qhash[question_hash]["answered"] = 1
                self._mem_by_qhash[question_hash]["updated_at"] = now_str
            # 同步 phash 列表（处理对象不同引用的情况）
            for record in self._mem_phash_list:
                if record.get("question_hash") == question_hash:
                    record["answered"] = 1
                    record["updated_at"] = now_str

    def update_phash(self, question_hash: str, phash: str) -> None:
        """
        为已存在的记录补写 phash 字段（当记录原本无 phash 时调用）。
        同步更新内存缓存，使该记录加入 _mem_phash_list 参与快速匹配。
        """
        if not question_hash or not phash:
            return
        with self._lock:
            if question_hash not in self._mem_by_qhash:
                return  # 记录不存在，无需更新
            record = self._mem_by_qhash[question_hash]
            if record.get("phash"):
                return  # 已有 phash，无需覆盖
            # 更新数据库
            self._conn.execute(
                "UPDATE cache SET phash = ? WHERE question_hash = ?",
                (phash, question_hash),
            )
            self._conn.commit()
            # 同步内存
            record["phash"] = phash
            # 加入 phash 列表（避免重复）
            if not any(r["question_hash"] == question_hash for r in self._mem_phash_list):
                self._mem_phash_list.append(record)

    def close(self) -> None:
        """关闭数据库连接。"""
        with self._lock:
            self._conn.close()
