"""把阶段任务放进队列。API 和工作进程都从这里触发下一阶段。"""
from .config import get_settings


def dispatch(lesson_id: int, stage: str):
    from .worker import stage_task

    limit = getattr(get_settings(), f"timeout_{stage}")
    stage_task.apply_async(args=[lesson_id, stage], soft_time_limit=limit, time_limit=limit + 120)
