import os
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core import config as config_module
from core.cache import CacheDB


class CacheDBTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tempdir.name, "cache.db")
        self.config_patcher = patch(
            "core.cache.config.get_cache_db_path", return_value=self.db_path
        )
        self.config_patcher.start()

    def tearDown(self):
        self.config_patcher.stop()
        self.tempdir.cleanup()

    def test_insert_refreshes_memory_from_database_truth(self):
        seed_conn = sqlite3.connect(self.db_path)
        seed_conn.execute(
            """
            CREATE TABLE cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_hash TEXT UNIQUE NOT NULL,
                phash TEXT,
                answer TEXT,
                source TEXT,
                answered INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        seed_conn.execute(
            """
            INSERT INTO cache (question_hash, phash, answer, source)
            VALUES (?, ?, ?, ?)
            """,
            ("q-1", "old-phash", "db-answer", "seed"),
        )
        seed_conn.commit()
        seed_conn.close()

        cache = CacheDB()
        cache._mem_by_qhash.clear()
        cache._mem_phash_list.clear()

        cache.insert("q-1", "new-phash", "wrong-answer", "runtime")

        row = cache.get_by_question_hash("q-1")
        self.assertIsNotNone(row)
        self.assertEqual(row["answer"], "db-answer")
        self.assertEqual(row["phash"], "old-phash")
        cache.close()

    def test_write_with_rollback_keeps_connection_usable(self):
        cache = CacheDB()

        with self.assertRaises(sqlite3.OperationalError):
            cache._write_with_rollback("INSERT INTO missing_table VALUES (1)")

        cache.insert("q-2", "phash", "answer", "test")
        row = cache.get_by_question_hash("q-2")

        self.assertEqual(row["answer"], "answer")
        cache.close()

    def test_close_is_idempotent_and_public_methods_raise_after_close(self):
        cache = CacheDB()

        cache.close()
        cache.close()

        with self.assertRaises(RuntimeError):
            cache.get_by_question_hash("q-3")

    def test_init_failure_closes_connection_before_reraise(self):
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = [None, sqlite3.OperationalError("boom")]

        with patch("core.cache.sqlite3.connect", return_value=mock_conn):
            with self.assertRaises(sqlite3.OperationalError):
                CacheDB()

        mock_conn.close.assert_called_once()


class ConfigTests(unittest.TestCase):
    def test_load_config_flags_corrupt_json_and_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config_path = os.path.join(tempdir, "config.json")
            with open(config_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("{bad json")

            with patch("core.config.get_base_dir", return_value=tempdir):
                cfg = config_module.load_config()

            self.assertTrue(config_module.was_last_load_corrupt())
            self.assertEqual(cfg["api_base_url"], config_module.CONFIG_DEFAULTS["api_base_url"])

    def test_save_config_returns_false_on_oserror_without_raise(self):
        with patch("builtins.open", side_effect=OSError("denied")):
            result = config_module.save_config({"provider": "openai"})

        self.assertFalse(result)

    def test_save_config_can_reraise_oserror(self):
        with patch("builtins.open", side_effect=OSError("denied")):
            with self.assertRaises(OSError):
                config_module.save_config({"provider": "openai"}, raise_on_error=True)


if __name__ == "__main__":
    unittest.main()
