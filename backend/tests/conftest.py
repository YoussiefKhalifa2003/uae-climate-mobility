"""Pytest config: force the offline synthetic sector + CPU backend for tests."""

import os

os.environ.setdefault("FORCE_SYNTHETIC", "true")
os.environ.setdefault("FORCE_CPU", "true")
os.environ.setdefault("USE_LIVE_DATA", "false")
