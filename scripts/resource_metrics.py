"""Read-only sampling. Reports host FFmpeg count (including unrelated processes)."""
import threading
import psutil
from pathlib import Path


class Sampler:
    def __init__(self, pid_directory=None):
        self.samples = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.pid_directory = Path(pid_directory) if pid_directory else None

    def __enter__(self):
        psutil.cpu_percent()
        self.thread.start()
        return self

    def _run(self):
        while not self.stop.is_set():
            count = rss = 0
            denied = 0
            if self.pid_directory:
                processes = []
                for marker in self.pid_directory.glob("ffmpeg_*.pid"):
                    try:
                        processes.append(psutil.Process(int(marker.read_text())))
                    except (ValueError, OSError, psutil.NoSuchProcess):
                        pass
            else:
                processes = psutil.process_iter()
            for process in processes:
                try:
                    if process.name().lower() in {"ffmpeg", "ffmpeg.exe"}:
                        count += 1
                        rss += process.memory_info().rss
                except psutil.AccessDenied:
                    denied += 1
                except psutil.NoSuchProcess:
                    pass
            memory, swap = psutil.virtual_memory(), psutil.swap_memory()
            self.samples.append({"ffmpeg_count": count, "ffmpeg_rss_mb": rss / 2**20,
                                 "cpu_percent": psutil.cpu_percent(), "host_used_mb": memory.used / 2**20,
                                 "available_mb": memory.available / 2**20, "swap_used_mb": swap.used / 2**20,
                                 "access_denied": denied})
            self.stop.wait(0.2)

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join()

    def summary(self):
        if not self.samples:
            return {}
        return {"samples": len(self.samples), "peak_host_ffmpeg_count": max(s["ffmpeg_count"] for s in self.samples),
                "process_scope": "benchmark child PIDs" if self.pid_directory else "entire host",
                "process_visibility_restricted": any(s["access_denied"] for s in self.samples),
                "peak_ffmpeg_rss_mb": max(s["ffmpeg_rss_mb"] for s in self.samples),
                "average_cpu_percent": sum(s["cpu_percent"] for s in self.samples) / len(self.samples),
                "peak_cpu_percent": max(s["cpu_percent"] for s in self.samples),
                "peak_host_used_mb": max(s["host_used_mb"] for s in self.samples),
                "minimum_available_mb": min(s["available_mb"] for s in self.samples),
                "peak_swap_used_mb": max(s["swap_used_mb"] for s in self.samples)}
