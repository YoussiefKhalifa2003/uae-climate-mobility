"""Lightweight disk cache for geo + raster artifacts.

Keeps OSM downloads and precomputed rasters on disk so reloads are instant.
Keys are derived from semantic inputs (place + params) rather than time.
"""

from __future__ import annotations

import hashlib
import json
import logging
import pickle
from pathlib import Path
from typing import Any, Callable

import numpy as np

from app.config import CACHE_DIR

logger = logging.getLogger(__name__)


def _key(namespace: str, params: dict[str, Any]) -> str:
    blob = json.dumps(params, sort_keys=True, default=str).encode()
    digest = hashlib.sha1(blob).hexdigest()[:16]
    return f"{namespace}_{digest}"


def _path(namespace: str, params: dict[str, Any], ext: str) -> Path:
    return CACHE_DIR / f"{_key(namespace, params)}.{ext}"


def cached_pickle(namespace: str, params: dict[str, Any], builder: Callable[[], Any]) -> Any:
    """Return a pickled object from cache, building + storing it on a miss."""
    path = _path(namespace, params, "pkl")
    if path.exists():
        try:
            with path.open("rb") as fh:
                logger.info("cache hit: %s", path.name)
                return pickle.load(fh)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache read failed (%s); rebuilding.", exc)
    obj = builder()
    try:
        with path.open("wb") as fh:
            pickle.dump(obj, fh, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cache write failed: %s", exc)
    return obj


def cached_npz(namespace: str, params: dict[str, Any], builder: Callable[[], dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
    """Cache a dict of NumPy arrays as a compressed .npz."""
    path = _path(namespace, params, "npz")
    if path.exists():
        try:
            with np.load(path, allow_pickle=False) as data:
                logger.info("raster cache hit: %s", path.name)
                return {k: data[k] for k in data.files}
        except Exception as exc:  # noqa: BLE001
            logger.warning("npz read failed (%s); rebuilding.", exc)
    arrays = builder()
    try:
        np.savez_compressed(path, **arrays)
    except Exception as exc:  # noqa: BLE001
        logger.warning("npz write failed: %s", exc)
    return arrays


def clear_cache() -> int:
    count = 0
    for f in CACHE_DIR.glob("*"):
        try:
            f.unlink()
            count += 1
        except OSError:
            pass
    return count
