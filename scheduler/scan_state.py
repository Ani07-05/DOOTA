import threading
from dataclasses import asdict, dataclass, field


@dataclass
class ScanProgress:
    running: bool = False
    scan_id: int | None = None
    status: str = "idle"
    step: str = ""
    progress: int = 0
    processed: int = 0
    total: int = 0
    new_circulars: int = 0
    message: str = ""


_lock = threading.Lock()
_state = ScanProgress()


def get_progress() -> dict:
    with _lock:
        return asdict(_state)


def _update(**kwargs) -> None:
    with _lock:
        for key, value in kwargs.items():
            setattr(_state, key, value)


def start(scan_id: int, total_steps: int) -> None:
    _update(
        running=True,
        scan_id=scan_id,
        status="running",
        step="Starting scan...",
        progress=0,
        processed=0,
        total=total_steps,
        new_circulars=0,
        message="",
    )


def set_step(step: str, progress: int, processed: int | None = None) -> None:
    payload: dict = {"step": step, "progress": min(progress, 100)}
    if processed is not None:
        payload["processed"] = processed
    _update(**payload)


def add_circulars(count: int) -> None:
    with _lock:
        _state.new_circulars += count


def finish(status: str, message: str) -> None:
    with _lock:
        progress = 100 if status == "completed" else _state.progress
        step = "Done" if status == "completed" else _state.step
    _update(
        running=False,
        status=status,
        progress=progress,
        step=step,
        message=message,
    )


def is_running() -> bool:
    with _lock:
        return _state.running
