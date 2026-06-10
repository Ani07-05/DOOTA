import logging
from scheduler import scan_state

_WATCHED = ("scheduler", "scrapers", "summarizer")
_fmt = logging.Formatter("%(levelname)-8s %(name)s: %(message)s")


class ScanLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if not any(record.name.startswith(p) for p in _WATCHED):
            return
        try:
            scan_state.push_log(_fmt.format(record))
        except Exception:
            pass
