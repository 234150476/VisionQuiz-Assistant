import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "benchmark: opt-in live model benchmark tests")
