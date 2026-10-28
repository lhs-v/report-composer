"""One background queue for the writing aids: a job asks the provider once, the answer is checked by `aids.parse`,
and the result waits for the UI to fetch it.

A single worker thread runs the jobs one after another, so the model CLI is never asked twice at the same time. The
lock is held only to change the queue; it is released while the provider runs, so `get()`/`cancel()` never wait for a
model. Records live in memory only (the latest 200). An answer for the same kind, provider, model and prompt is
served from a small cache; a refused answer (a number that is not in the input) is never cached."""
from __future__ import annotations

import hashlib
import threading
import time
import uuid
from collections import OrderedDict, deque
from typing import Callable

from . import aids
from .llm import LlmError

MAX_RECORDS = 200
NO_PROVIDER = "LLM 공급자가 설정되지 않았습니다"


class _Job:
    def __init__(self, jid: str, kind: str, draft_id, node_id, built: dict):
        self.id, self.kind, self.draft_id, self.node_id = jid, kind, draft_id, node_id
        self.prompt, self.system, self.source, self.before = built["prompt"], built["system"], built["source"], built["before"]
        self.status = "queued"
        self.cached = False
        self.created = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.result: dict | None = None
        self.error: str | None = None
        self.cancel_flag = False

    def record(self) -> dict:
        return {"id": self.id, "kind": self.kind, "draft_id": self.draft_id, "node_id": self.node_id, "status": self.status,
                "cached": self.cached, "created": self.created, "result": dict(self.result) if self.result else None, "error": self.error}


def _primary(provider):
    return getattr(provider, "primary", provider)


def _ready(provider) -> bool:
    if provider is None:
        return False
    check = getattr(_primary(provider), "available", None)
    return bool(check()) if callable(check) else True


def _name(provider, via: str) -> str:
    """'claude:sonnet' for a CLI provider; a stand-in without a spec is called 'fake'."""
    chosen = _primary(provider) if via != "fallback" else getattr(provider, "fallback", None)
    spec = getattr(chosen, "spec", None)
    return f"{spec.provider}:{spec.resolved_model()}" if spec else "fake"


def _cache_key(kind: str, provider, prompt: str) -> str:
    spec = getattr(_primary(provider), "spec", None) if provider is not None else None
    parts = [kind, spec.provider if spec else "", spec.resolved_model() if spec else "", prompt]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


class JobQueue:
    def __init__(self, provider_factory: Callable[[], object], max_cache: int = 64):
        self._factory = provider_factory
        self._max_cache = max_cache
        self._cond = threading.Condition()
        self._pending: deque[_Job] = deque()
        self._jobs: OrderedDict[str, _Job] = OrderedDict()
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._worker: threading.Thread | None = None

    def ready(self) -> bool:
        try:
            return _ready(self._factory())
        except Exception:  # noqa: BLE001
            return False

    def submit(self, kind: str, draft: dict, node_id, style: str) -> dict:
        built = aids.build(kind, draft, node_id, style)                 # ValueError: the caller answers 400
        job = _Job("j-" + uuid.uuid4().hex[:10], kind, draft.get("id"), node_id, built)
        try:
            provider = self._factory()
        except Exception:  # noqa: BLE001 - a broken setting shows up as the job's failure, not as a crash here
            provider = None
        key = _cache_key(kind, provider, job.prompt)
        with self._cond:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                job.status, job.cached, job.result = "done", True, {**hit, "before": job.before, "value": _copy(hit["value"])}
            self._remember(job)
            if hit is None:
                self._pending.append(job)
                if self._worker is None:
                    self._worker = threading.Thread(target=self._loop, name="llm-jobs", daemon=True)
                    self._worker.start()
                self._cond.notify()
            return job.record()

    def get(self, job_id: str) -> dict | None:
        with self._cond:
            job = self._jobs.get(job_id)
            return job.record() if job else None

    def cancel(self, job_id: str) -> bool:
        """A queued job leaves the queue; a running one is flagged and its answer thrown away when it arrives."""
        with self._cond:
            job = self._jobs.get(job_id)
            if job is None or job.status not in ("queued", "running"):
                return False
            if job.status == "queued":
                try:
                    self._pending.remove(job)
                except ValueError:
                    pass
            job.cancel_flag, job.status = True, "cancelled"
            return True

    # ----- internals -----
    def _remember(self, job: _Job) -> None:
        self._jobs[job.id] = job
        if len(self._jobs) > MAX_RECORDS:
            for jid in [j.id for j in self._jobs.values() if j.status not in ("queued", "running")][:len(self._jobs) - MAX_RECORDS]:
                del self._jobs[jid]

    def _loop(self) -> None:
        while True:
            with self._cond:
                while not self._pending:
                    self._cond.wait()
                job = self._pending.popleft()
                if job.cancel_flag:
                    continue
                job.status = "running"
            try:
                result, error, key = self._run(job)
            except Exception as e:  # noqa: BLE001 - the worker must never die
                result, error, key = None, f"작업 중 예기치 않은 오류가 났습니다: {type(e).__name__}: {str(e)[:200]}", None
            with self._cond:
                if job.cancel_flag:                                    # cancelled while the model was answering: drop the answer
                    continue
                if result is not None:
                    job.status, job.result = "done", result
                    if key:
                        self._cache[key] = {**result, "value": _copy(result["value"])}
                        while len(self._cache) > self._max_cache:
                            self._cache.popitem(last=False)
                else:
                    job.status, job.error = "failed", error

    def _run(self, job: _Job) -> tuple[dict | None, str | None, str | None]:
        provider = self._factory()
        if provider is None:
            return None, NO_PROVIDER, None
        t0 = time.monotonic()
        try:
            answer = provider.complete(job.prompt, system=job.system)
        except LlmError as e:
            return None, str(e), None
        parsed = aids.parse(job.kind, answer, job.source)
        if not parsed["ok"]:
            return None, parsed["reason"], None
        via = getattr(provider, "last", "") or "primary"
        result = {"before": job.before, "value": parsed["value"], "provider": _name(provider, via), "via": via,
                  "ms": int((time.monotonic() - t0) * 1000)}
        return result, None, _cache_key(job.kind, provider, job.prompt)


def _copy(value):
    return list(value) if isinstance(value, list) else value
