"""Per-stage timing for ingestion runs.

A trace groups stage timings for one import request via a context variable,
so sync endpoints running in threadpool threads still see the right trace.
Traces are kept in a bounded in-memory store and served by the traces
endpoints for monitoring.
"""
import threading
import time
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar

_trace: ContextVar = ContextVar("trace", default=None)

_lock = threading.Lock()
_traces: deque = deque(maxlen=200)


class Trace:
    def __init__(self, name: str):
        self.name = name
        self.started = time.perf_counter()
        self.meta: dict = {}
        self.spans: list[dict] = []

    @property
    def total_seconds(self) -> float:
        return round(time.perf_counter() - self.started, 3)

    def add(self, stage: str, seconds: float, meta: dict | None = None):
        entry = {"stage": stage, "seconds": round(seconds, 3)}
        if meta:
            entry.update(meta)
        self.spans.append(entry)

    def finish(self, status: str):
        with _lock:
            _traces.append({
                "name": self.name,
                "status": status,
                "total_seconds": self.total_seconds,
                "meta": self.meta,
                "spans": self.spans,
            })


def start_trace(name: str) -> Trace:
    trace = Trace(name)
    _trace.set(trace)
    return trace


def current() -> Trace | None:
    return _trace.get()


def set_meta(**kv):
    trace = _trace.get()
    if trace:
        trace.meta.update(kv)


def record(stage: str, seconds: float, **meta):
    trace = _trace.get()
    if trace:
        trace.add(stage, seconds, meta)


@contextmanager
def span(stage: str, **meta):
    start = time.perf_counter()
    try:
        yield
    except Exception as exc:
        record(stage, time.perf_counter() - start, error=type(exc).__name__, **meta)
        raise
    else:
        record(stage, time.perf_counter() - start, **meta)


def recent_traces(limit: int = 20) -> list:
    with _lock:
        return list(_traces)[-limit:]
