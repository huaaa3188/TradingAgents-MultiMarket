from __future__ import annotations

import functools
import os
import re
import sys
from typing import Callable

from diskcache import Cache

from .config import get_config


_UNINITIALIZED_CACHE = object()
_CACHES: dict[str, object] = {}
_NAMESPACE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def get_disk_cache(namespace: str):
    """Return the lazily initialized DiskCache for a dataflow namespace."""
    _validate_namespace(namespace)
    active_cache = _CACHES.get(namespace, _UNINITIALIZED_CACHE)
    if active_cache is _UNINITIALIZED_CACHE:
        cache_dir = os.path.join(get_config()["data_cache_dir"], namespace)
        try:
            active_cache = Cache(cache_dir)
        except Exception as exc:  # noqa: BLE001 - cache failures must not block data fetches
            print(f"[Warning] Failed to initialize DiskCache at {cache_dir}: {exc}", file=sys.stderr)
            active_cache = None
        _CACHES[namespace] = active_cache
    return active_cache


def set_disk_cache(namespace: str, cache_obj) -> None:
    """Inject a cache object for tests or controlled runtime overrides."""
    _validate_namespace(namespace)
    _CACHES[namespace] = cache_obj


def clear_disk_cache(namespace: str | None = None) -> None:
    """Forget cached Cache instances so future calls re-read current config."""
    if namespace is not None:
        _validate_namespace(namespace)
        cache_obj = _CACHES.pop(namespace, None)
        _close_cache(cache_obj)
        return

    cache_objects = list(_CACHES.values())
    _CACHES.clear()
    for cache_obj in cache_objects:
        _close_cache(cache_obj)


def disk_cache(namespace: str, expire: int = 14400) -> Callable:
    """Decorate dataflow fetchers with a shared fail-open DiskCache layer."""
    _validate_namespace(namespace)

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not get_config().get("enable_data_cache", True):
                return func(*args, **kwargs)

            active_cache = get_disk_cache(namespace)
            if active_cache is None:
                return func(*args, **kwargs)

            key = _cache_key(func, args, kwargs)
            try:
                cached_val = active_cache.get(key)
                if cached_val is not None:
                    return cached_val
            except Exception as exc:  # noqa: BLE001 - fall through to live fetch
                print(f"[Warning] DiskCache read failure for {func.__name__}: {exc}", file=sys.stderr)

            val = func(*args, **kwargs)

            try:
                active_cache.set(key, val, expire=expire)
            except Exception as exc:  # noqa: BLE001 - fetched data is still usable
                print(f"[Warning] DiskCache write failure for {func.__name__}: {exc}", file=sys.stderr)
            return val

        return wrapper

    return decorator


def _cache_key(func, args, kwargs) -> str:
    return f"disk:{func.__name__}:{args}:{sorted(kwargs.items())}"


def _validate_namespace(namespace: str) -> None:
    if not namespace or not _NAMESPACE_RE.fullmatch(namespace):
        raise ValueError(f"Invalid dataflow cache namespace: {namespace!r}")


def _close_cache(cache_obj) -> None:
    close = getattr(cache_obj, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass
