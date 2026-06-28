"""Compute backend abstraction (GPU via CuPy, CPU fallback via NumPy).

Import ``xp`` from here instead of importing numpy/cupy directly. The module
auto-detects CuPy + a working CUDA device (your RTX 4080 Super) and otherwise
transparently falls back to NumPy so the platform always runs.
"""

from __future__ import annotations

import logging

import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

_GPU_AVAILABLE = False
_DEVICE_NAME = "CPU (NumPy)"
xp = np  # default backend

if not settings.force_cpu:
    try:
        import cupy as _cp  # type: ignore

        # Touch the device to confirm a usable CUDA runtime.
        _cp.cuda.runtime.getDeviceCount()
        _dev = _cp.cuda.runtime.getDeviceProperties(0)
        _DEVICE_NAME = _dev["name"].decode() if isinstance(_dev["name"], bytes) else str(_dev["name"])
        xp = _cp  # type: ignore
        _GPU_AVAILABLE = True
        logger.info("GPU compute enabled: %s", _DEVICE_NAME)
    except Exception as exc:  # noqa: BLE001 - any failure means fall back
        logger.warning("CuPy/CUDA unavailable (%s); using NumPy CPU backend.", exc)


def gpu_available() -> bool:
    return _GPU_AVAILABLE


def device_name() -> str:
    return _DEVICE_NAME


def to_cpu(array):
    """Return a NumPy array regardless of the active backend."""
    if _GPU_AVAILABLE and isinstance(array, xp.ndarray):  # type: ignore[attr-defined]
        return xp.asnumpy(array)  # type: ignore[attr-defined]
    return np.asarray(array)


def to_device(array):
    """Move a host array onto the active compute device."""
    return xp.asarray(array)


def backend_info() -> dict:
    return {
        "gpu": _GPU_AVAILABLE,
        "device": _DEVICE_NAME,
        "backend": "cupy" if _GPU_AVAILABLE else "numpy",
    }
