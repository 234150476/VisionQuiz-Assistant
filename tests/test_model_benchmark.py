"""
模型基准测试 —— opt-in 模型对比测试，默认跳过。

运行方式:
  BENCHMARK_API_KEY=your-key python -m pytest tests/test_model_benchmark.py -v --run-benchmark

需要环境变量:
  BENCHMARK_API_KEY  — 模型 API Key（必填）
  BENCHMARK_BASE_URL — API Base URL（可选，默认使用预设值）
"""

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from core.ai_client import AIClient, PromptAResult, ProviderProfile
from core.config import MODEL_PRESETS

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "benchmark"

_needs_api_key = pytest.mark.skipif(
    not os.environ.get("BENCHMARK_API_KEY"),
    reason="BENCHMARK_API_KEY not set — skipping live benchmark",
)


def _load_corpus():
    """加载基准测试题集：[(screenshot_path, expected_dict)]。"""
    corpus = []
    for i in range(1, 100):
        img_path = FIXTURES_DIR / f"screenshot-{i}.png"
        json_path = FIXTURES_DIR / f"expected-{i}.json"
        if not img_path.exists() or not json_path.exists():
            break
        with open(json_path, "r", encoding="utf-8") as f:
            expected = json.load(f)
        corpus.append((str(img_path), expected))
    return corpus


def _vision_presets():
    """返回支持视觉的预设 key 列表。"""
    return [
        k for k, v in MODEL_PRESETS.items()
        if v.get("supports_vision", False)
    ]


@_needs_api_key
@pytest.mark.benchmark
class TestModelBenchmark:
    """模型基准对比测试。"""

    def _make_client(self, preset_key: str) -> AIClient:
        """根据预设创建 AIClient。"""
        preset = MODEL_PRESETS[preset_key]
        api_key = os.environ["BENCHMARK_API_KEY"]
        base_url = os.environ.get("BENCHMARK_BASE_URL", preset["base_url"])
        profile = ProviderProfile(
            base_url=base_url,
            model=preset["model"],
            supports_vision=preset["supports_vision"],
            image_transport=preset.get("image_transport", "inline_base64"),
            extra_body=preset.get("extra_body"),
        )
        return AIClient(api_key, base_url, preset["model"], timeout=30, profile=profile)

    @pytest.mark.parametrize("preset_key", _vision_presets(), ids=lambda k: MODEL_PRESETS[k]["display_name"])
    def test_benchmark_preset(self, preset_key):
        """逐预设运行基准测试，记录准确率和延迟。"""
        corpus = _load_corpus()
        if not corpus:
            pytest.skip("No benchmark fixtures found in tests/fixtures/benchmark/")

        client = self._make_client(preset_key)
        results = []

        for img_path, expected in corpus:
            img = Image.open(img_path)
            start = time.monotonic()
            try:
                result = client.answer_with_image(expected.get("question", ""), img)
                latency_ms = (time.monotonic() - start) * 1000
                parse_success = isinstance(result, PromptAResult)
                results.append({
                    "parse_success": parse_success,
                    "latency_ms": round(latency_ms, 1),
                    "question_type": result.question_type if parse_success else None,
                })
            except Exception as exc:
                latency_ms = (time.monotonic() - start) * 1000
                results.append({
                    "parse_success": False,
                    "latency_ms": round(latency_ms, 1),
                    "error": str(exc),
                })
            time.sleep(1)  # rate limit protection

        total = len(results)
        success = sum(1 for r in results if r["parse_success"])
        avg_latency = sum(r["latency_ms"] for r in results) / total if total else 0

        # 输出报告
        print(f"\n{'='*50}")
        print(f"  Benchmark: {MODEL_PRESETS[preset_key]['display_name']}")
        print(f"  Preset:    {preset_key}")
        print(f"  Model:     {MODEL_PRESETS[preset_key]['model']}")
        print(f"  Corpus:    {total} items")
        print(f"  Success:   {success}/{total} ({100*success/total:.0f}%)")
        print(f"  Avg Latency: {avg_latency:.0f}ms")
        print(f"{'='*50}")

        # 至少能完成解析（不强制准确率，因为截图是占位图）
        assert total > 0, "Benchmark corpus is empty"

    def test_benchmark_comparison_report(self):
        """所有视觉预设的横向对比报告。"""
        corpus = _load_corpus()
        if not corpus:
            pytest.skip("No benchmark fixtures found")

        presets = _vision_presets()
        report = []

        for preset_key in presets:
            client = self._make_client(preset_key)
            results = []
            for img_path, expected in corpus:
                img = Image.open(img_path)
                start = time.monotonic()
                try:
                    result = client.answer_with_image(expected.get("question", ""), img)
                    latency_ms = (time.monotonic() - start) * 1000
                    results.append({
                        "success": isinstance(result, PromptAResult),
                        "latency_ms": latency_ms,
                    })
                except Exception:
                    latency_ms = (time.monotonic() - start) * 1000
                    results.append({"success": False, "latency_ms": latency_ms})
                time.sleep(1)

            total = len(results)
            success = sum(1 for r in results if r["success"])
            avg_latency = sum(r["latency_ms"] for r in results) / total if total else 0
            report.append({
                "preset": preset_key,
                "display": MODEL_PRESETS[preset_key]["display_name"],
                "success": success,
                "total": total,
                "avg_latency_ms": round(avg_latency, 0),
            })

        # 输出对比表
        print(f"\n{'='*70}")
        print(f"  {'Model':<30} {'Success':>10} {'Latency':>12}")
        print(f"  {'-'*30} {'-'*10} {'-'*12}")
        for r in report:
            print(f"  {r['display']:<30} {r['success']}/{r['total']:>7} {r['avg_latency_ms']:>9.0f}ms")
        print(f"{'='*70}")

        assert len(report) > 0
