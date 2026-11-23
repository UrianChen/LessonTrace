"""Celery 工作进程。只开一个进程（--concurrency=1），任务排队执行。"""
from celery import Celery

from .config import get_settings
from .db import SessionLocal
from .pipeline.stages import NEXT, STAGES, run_stage

MAX_RETRIES = 3                      # 阶段内出错自动重试 3 次
RETRY_DELAYS = (30, 120, 480)        # 间隔逐次加长（秒）

celery = Celery("lessontrace", broker=get_settings().redis_url)
celery.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, broker_connection_retry_on_startup=True)


@celery.task(bind=True, name="lessontrace.stage", max_retries=MAX_RETRIES)
def stage_task(self, lesson_id: int, stage: str):
    from . import queue

    db = SessionLocal()
    try:
        outcome = run_stage(db, lesson_id, stage, final_attempt=self.request.retries >= MAX_RETRIES)
    finally:
        db.close()
    if outcome == "retry":
        raise self.retry(countdown=RETRY_DELAYS[self.request.retries])
    if outcome == "done" and NEXT[stage] in STAGES:
        queue.dispatch(lesson_id, NEXT[stage])
    return outcome
