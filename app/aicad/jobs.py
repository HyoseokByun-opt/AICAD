"""Background jobs with a log, live AI output and a Stop that acts at once.

The browser polls /api/jobs/<id> with the offsets it has already seen and
receives only what is new. One AI job runs at a time; quick jobs (a rebuild
after a parameter change) run beside it.
"""
from __future__ import annotations

import threading
import time
import traceback
import uuid

JOBS: dict[str, "Job"] = {}
_ai_lock = threading.Lock()


class Stopped(Exception):
    pass


class Job:
    def __init__(self, kind: str, project_id: str | None, ai: bool):
        self.id = uuid.uuid4().hex[:10]
        self.kind, self.project_id, self.ai = kind, project_id, ai
        self.state = "queued"           # queued | running | done | failed | stopped
        self.stage, self.progress = "", 0.0
        self.logs: list[dict] = []
        self.stream: list[list] = []    # [kind, text] pieces of the AI answer
        self.stream_len = 0
        self.result: dict = {}
        self.error = ""
        self.stop = threading.Event()
        self.created, self.finished = time.time(), None

    # ------------------------------------------------------------ reporting
    def log(self, msg: str, level: str = "info"):
        self.logs.append({"t": round(time.time() - self.created, 1), "level": level, "msg": msg})

    def set(self, stage: str | None = None, progress: float | None = None):
        if stage is not None:
            self.stage = stage
            self.log(stage, "stage")
        if progress is not None:
            self.progress = max(self.progress, min(1.0, progress))

    def token(self, kind: str, text: str):
        if self.stream and self.stream[-1][0] == kind and len(self.stream[-1][1]) < 2000:
            self.stream[-1][1] += text
        else:
            self.stream.append([kind, text])
        self.stream_len += len(text)

    def stream_mark(self, title: str):
        self.stream.append(["mark", title])

    def check(self):
        if self.stop.is_set():
            raise Stopped()

    def snapshot(self, log_from=0, stream_from=0) -> dict:
        # stream pieces may grow in place: resend the last one the client has
        sf = max(0, stream_from - 1)
        return {"id": self.id, "kind": self.kind, "project": self.project_id, "state": self.state,
                "stage": self.stage, "progress": round(self.progress, 3), "error": self.error,
                "logs": self.logs[log_from:], "log_n": len(self.logs),
                "stream": self.stream[sf:], "stream_from": sf, "stream_n": len(self.stream),
                "result": self.result if self.state in ("done", "failed", "stopped") else {},
                "elapsed": round((self.finished or time.time()) - self.created, 1)}


def busy_ai():
    for j in JOBS.values():
        if j.ai and j.state in ("queued", "running"):
            return j
    return None


def start(kind: str, project_id: str | None, fn, ai: bool = True, **kw) -> Job:
    job = Job(kind, project_id, ai)
    JOBS[job.id] = job

    def run():
        lock = _ai_lock if ai else None
        if lock:
            lock.acquire()
        try:
            if job.stop.is_set():
                raise Stopped()
            job.state = "running"
            fn(job, project_id, **kw)
            job.state = "done"
            job.progress = 1.0
        except Stopped:
            job.state = "stopped"
            job.log("Stopped by the user.", "warn")
        except Exception as e:  # noqa: BLE001
            job.state = "failed"
            job.error = f"{type(e).__name__}: {e}"
            job.log(job.error, "error")
            job.log(traceback.format_exc()[-2000:], "debug")
        finally:
            job.finished = time.time()
            if lock:
                lock.release()
    threading.Thread(target=run, daemon=True, name=f"job-{kind}").start()
    # keep the list short
    if len(JOBS) > 60:
        for k in sorted(JOBS, key=lambda k: JOBS[k].created)[:20]:
            if JOBS[k].state not in ("queued", "running"):
                JOBS.pop(k, None)
    return job
