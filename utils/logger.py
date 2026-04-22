import sys
from datetime import datetime


class PipelineLogger:
    RESET  = "\033[0m"
    COLOURS = {
        "INFO":    "\033[36m",
        "SUCCESS": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR":   "\033[31m",
        "DEBUG":   "\033[90m",
        "ALERT":   "\033[35m",
    }

    def __init__(self, name: str = "pipeline"):
        self.name = name

    def _log(self, level: str, message: str):
        colour = self.COLOURS.get(level, "")
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"{colour}[{ts}] [{level}] [{self.name}] {message}{self.RESET}")

    def info(self, msg):    self._log("INFO", msg)
    def success(self, msg): self._log("SUCCESS", msg)
    def warning(self, msg): self._log("WARNING", msg)
    def error(self, msg):   self._log("ERROR", msg)
    def debug(self, msg):   self._log("DEBUG", msg)
    def alert(self, msg):   self._log("ALERT", msg)

    def section(self, title: str):
        print(f"\n{'='*60}\n  {title}\n{'='*60}")


logger = PipelineLogger()
