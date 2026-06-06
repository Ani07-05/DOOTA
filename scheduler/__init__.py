import threading
import time


class ScanState:
    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict = {
            "running": False,
            "status": "idle",
            "scan_id": None,
            "progress": 0,
            "step": "",
            "processed": 0,
            "total": 0,
            "new_circulars": 0,
            "message": None,
        }

    def is_running(self) -> bool:
        with self._lock:
            return self._data["running"]

    def get_progress(self) -> dict:
        with self._lock:
            # Auto-clear if stuck running for > 15 minutes with no update
            if self._data["running"]:
                last = self._data.get("_last_update", time.time())
                if time.time() - last > 900:
                    self._data["running"] = False
                    self._data["status"] = "failed"
                    self._data["message"] = "Scan timed out"
            out = dict(self._data)
            out.pop("_last_update", None)
            return out

    def start(self, scan_id: int, total: int) -> None:
        with self._lock:
            self._data = {
                "running": True,
                "status": "running",
                "scan_id": scan_id,
                "progress": 0,
                "step": "Starting…",
                "processed": 0,
                "total": total,
                "new_circulars": 0,
                "message": None,
                "_last_update": time.time(),
            }

    def set_step(self, step: str, pct: int, index: int) -> None:
        with self._lock:
            self._data["step"] = step
            self._data["progress"] = pct
            self._data["processed"] = index
            self._data["_last_update"] = time.time()

    def add_circulars(self, count: int) -> None:
        with self._lock:
            self._data["new_circulars"] += count

    def finish(self, status: str, message: str = "") -> None:
        with self._lock:
            self._data["running"] = False
            self._data["status"] = status
            self._data["message"] = message
            if status == "completed":
                self._data["progress"] = 100
                self._data["step"] = "Complete"


scan_state = ScanState()
