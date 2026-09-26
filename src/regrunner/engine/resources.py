"""What the computer was going through during a run: ``resources.jsonl`` in the run folder, one line every ``measure.sample_s``.

The scarce resource on a work laptop is memory, not processor: a test waiting inside a page keeps its page (and its memory) open, and once
the laptop starts swapping every test slows down at once.  So each sample records free memory, swap / page-file use, the memory of the
browsers this run started (the whole process tree under the runner), processor use, how many tests were running - and how late the
runner's own event loop ran (every test shares one loop: a blocked loop freezes them all).

No new dependency: the numbers are read from what the operating system offers (``/proc`` on Linux, ``vm_stat`` / ``sysctl`` / ``ps`` on a
Mac, the Win32 API on Windows).  If ``psutil`` happens to be installed it is used instead.  A number that cannot be read is ``null``; the
sampler never fails a run.  Nothing here reads a page, a URL or anything a test typed.

The browsers' memory is the sum of the processes' resident memory (working set on Windows): pages shared between processes count more than
once, so it is an upper bound - good for comparing runs on the same computer, not an exact figure.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

MB = 1024 * 1024

try:                                                    # optional: used when present, never required
    import psutil                                       # type: ignore
except Exception:                                       # pragma: no cover - depends on the computer
    psutil = None


# -- the computer and the runner ------------------------------------------------------------------------------
_version_cache: dict[str, str] = {}


def runner_version() -> str:
    """A hash of the runner's own source files (``src-<12 hex>``): the work computer gets files copied, not a git checkout, so the files
    themselves say which version ran.  The same files give the same version on any computer."""
    if "v" not in _version_cache:
        root = Path(__file__).resolve().parents[1]
        digest = hashlib.sha1()
        for path in sorted(root.rglob("*")):
            if path.suffix in (".py", ".js", ".css", ".html") and "__pycache__" not in path.parts:
                try:
                    digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0" + path.read_bytes().replace(b"\r\n", b"\n"))
                except OSError:
                    continue
        _version_cache["v"] = "src-" + digest.hexdigest()[:12]
    return _version_cache["v"]


def machine_info() -> dict[str, Any]:
    """The computer a run ran on (for comparing runs): system, processors, memory, Python, runner version.  No user or host names."""
    info: dict[str, Any] = {"os": platform.system(), "os_version": platform.release(), "machine": platform.machine(),
                            "cpus": os.cpu_count(), "python": platform.python_version(), "runner_version": runner_version()}
    try:
        info["ram_mb"] = int((read_memory().get("total") or 0) / MB) or None
    except Exception:
        info["ram_mb"] = None
    if psutil is not None:
        info["psutil"] = True
    return info


# -- one sample -----------------------------------------------------------------------------------------------
def read_memory() -> dict[str, float | None]:
    """{total, available, swap_used} in bytes (None where it cannot be read)."""
    if psutil is not None:
        vm, sw = psutil.virtual_memory(), psutil.swap_memory()
        return {"total": float(vm.total), "available": float(vm.available), "swap_used": float(sw.used)}
    system = platform.system()
    if system == "Linux":
        values: dict[str, float] = {}
        with open("/proc/meminfo", encoding="ascii") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                values[key] = float(rest.split()[0]) * 1024
        return {"total": values.get("MemTotal"), "available": values.get("MemAvailable", values.get("MemFree")),
                "swap_used": (values.get("SwapTotal", 0.0) - values.get("SwapFree", 0.0)) if "SwapTotal" in values else None}
    if system == "Windows":
        return _win_memory()
    if system == "Darwin":
        return _mac_memory()
    return {"total": None, "available": None, "swap_used": None}


def _mac_memory() -> dict[str, float | None]:
    total = float(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=3).stdout.strip() or 0) or None
    out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=3).stdout
    page = 4096.0
    pages: dict[str, float] = {}
    for line in out.splitlines():
        if "page size of" in line:
            page = float(line.split("page size of")[1].split()[0])
        elif ":" in line:
            key, _, value = line.partition(":")
            try:
                pages[key.strip()] = float(value.strip().rstrip("."))
            except ValueError:
                pass
    available = sum(pages.get(k, 0.0) for k in ("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable")) * page or None
    swap = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True, timeout=3).stdout
    used = None
    if "used =" in swap:
        raw = swap.split("used =")[1].split()[0]
        scale = {"K": 1024.0, "M": MB, "G": MB * 1024.0}.get(raw[-1:], 1.0)
        used = float(raw.rstrip("KMG")) * scale
    return {"total": total, "available": available, "swap_used": used}


def _win_memory() -> dict[str, float | None]:
    import ctypes
    from ctypes import wintypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return {"total": None, "available": None, "swap_used": None}
    committed = float(status.ullTotalPageFile - status.ullAvailPageFile)             # memory promised to programs (RAM + page file)
    in_ram = float(status.ullTotalPhys - status.ullAvailPhys)
    return {"total": float(status.ullTotalPhys), "available": float(status.ullAvailPhys), "swap_used": max(0.0, committed - in_ram)}


class CpuMeter:
    """Processor use (% of all cores) since the previous reading."""

    def __init__(self):
        self._last: tuple[float, float] | None = None
        if psutil is not None:
            psutil.cpu_percent(None)                    # (the first reading is always 0: prime it)

    def read(self) -> float | None:
        if psutil is not None:
            return float(psutil.cpu_percent(None))
        if platform.system() == "Darwin":                  # (ps gives a recent average per process: already a rate)
            out = subprocess.run(["ps", "-A", "-o", "%cpu="], capture_output=True, text=True, timeout=3).stdout
            total = sum(float(x) for x in out.split() if x.replace(".", "", 1).isdigit())
            return round(min(100.0, total / max(1, os.cpu_count() or 1)), 1)
        now = self._times()
        if now is None:
            return None
        last, self._last = self._last, now
        if last is None:
            return None
        busy, total = now[0] - last[0], now[1] - last[1]
        return round(100.0 * busy / total, 1) if total > 0 else None

    @staticmethod
    def _times() -> tuple[float, float] | None:
        """(busy, total) processor time counters."""
        system = platform.system()
        if system == "Linux":
            with open("/proc/stat", encoding="ascii") as fh:
                fields = [float(x) for x in fh.readline().split()[1:]]
            idle = fields[3] + (fields[4] if len(fields) > 4 else 0.0)
            return sum(fields) - idle, sum(fields)
        if system == "Windows":
            import ctypes
            from ctypes import wintypes
            idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
            if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
                return None
            as_int = lambda ft: (ft.dwHighDateTime << 32) | ft.dwLowDateTime
            total = float(as_int(kernel) + as_int(user))                             # (kernel time includes idle time)
            return total - as_int(idle), total
        return None


def tree_memory(root_pid: int | None = None) -> tuple[float | None, int]:
    """(resident memory in bytes, number of processes) of every process started under ``root_pid`` (this runner: the browser driver and
    every browser it launched), not counting the runner itself."""
    root = root_pid or os.getpid()
    if psutil is not None:
        total, count = 0.0, 0
        for child in psutil.Process(root).children(recursive=True):
            try:
                total += float(child.memory_info().rss)
                count += 1
            except Exception:
                continue
        return total, count
    system = platform.system()
    if system == "Linux":
        parents: dict[int, int] = {}
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/stat", encoding="ascii", errors="replace") as fh:
                    parents[int(entry)] = int(fh.read().rsplit(")", 1)[1].split()[1])
            except (OSError, IndexError, ValueError):
                continue
        page = os.sysconf("SC_PAGE_SIZE")
        total, count = 0.0, 0
        for pid in _descendants(root, parents):
            try:
                with open(f"/proc/{pid}/statm", encoding="ascii") as fh:
                    total += float(fh.read().split()[1]) * page
                count += 1
            except (OSError, IndexError, ValueError):
                continue
        return total, count
    if system == "Darwin":
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,rss="], capture_output=True, text=True, timeout=3).stdout
        parents, rss = {}, {}
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 3 and all(p.isdigit() for p in parts):
                parents[int(parts[0])], rss[int(parts[0])] = int(parts[1]), float(parts[2]) * 1024
        found = _descendants(root, parents)
        return sum(rss.get(p, 0.0) for p in found), len(found)
    if system == "Windows":
        return _win_tree_memory(root)
    return None, 0


def _descendants(root: int, parents: dict[int, int]) -> list[int]:
    children: dict[int, list[int]] = {}
    for pid, ppid in parents.items():
        children.setdefault(ppid, []).append(pid)
    found, todo = [], list(children.get(root, []))
    while todo:
        pid = todo.pop()
        if pid in found or pid == root:
            continue
        found.append(pid)
        todo.extend(children.get(pid, []))
    return found


def _win_tree_memory(root: int) -> tuple[float | None, int]:
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    kernel32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.argtypes = kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)                     # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:                          # INVALID_HANDLE_VALUE
        return None, 0
    parents: dict[int, int] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    total, count = 0.0, 0
    for pid in _descendants(root, parents):
        handle = kernel32.OpenProcess(0x1000 | 0x0010, False, pid)                  # PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ
        if not handle:
            continue
        try:
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                total += float(counters.WorkingSetSize)
                count += 1
        finally:
            kernel32.CloseHandle(handle)
    return total, count


def _safe(read, default):
    try:
        return read()
    except Exception:
        return default


def read_sample(cpu: CpuMeter) -> dict[str, Any]:
    """One reading of the computer (blocking: run it off the event loop)."""
    memory = _safe(read_memory, {})
    browsers_bytes, processes = _safe(tree_memory, (None, 0))
    mb = lambda v: None if v is None else round(v / MB)
    return {"cpu_pct": _safe(cpu.read, None), "mem_free_mb": mb(memory.get("available")), "mem_total_mb": mb(memory.get("total")),
            "swap_used_mb": mb(memory.get("swap_used")), "browsers_mb": mb(browsers_bytes), "processes": processes}


# -- the sampler --------------------------------------------------------------------------------------------------
class LoopLag:
    """How late the event loop runs: a 100 ms heartbeat that notes how much later than asked it woke up."""

    BEAT_S = 0.1

    def __init__(self):
        self.worst = 0.0
        self.late_total = 0.0

    async def run(self) -> None:
        while True:
            t0 = time.monotonic()
            await asyncio.sleep(self.BEAT_S)
            late = time.monotonic() - t0 - self.BEAT_S
            if late > 0:
                self.worst = max(self.worst, late)
                if late > 0.05:
                    self.late_total += late

    def take(self) -> tuple[float, float]:
        worst, total = self.worst, self.late_total
        self.worst = self.late_total = 0.0
        return worst, total


class ResourceSampler:
    """Every ``interval_s``: one line in the ``resources.jsonl`` of every run that is going (``sinks()``), with ``counts()`` (tests running,
    workers...) added.  Started and cancelled by the engine."""

    def __init__(self, interval_s: float, sinks: Callable[[], list[Path]], counts: Callable[[], dict[str, Any]]):
        self.interval_s = max(0.5, float(interval_s))
        self.sinks, self.counts = sinks, counts

    async def run(self) -> None:
        cpu = CpuMeter()
        lag = LoopLag()
        beat = asyncio.ensure_future(lag.run())
        try:
            await asyncio.to_thread(_safe, cpu.read, None)             # (primes the processor counters)
            while True:
                await asyncio.sleep(self.interval_s)
                sample = await asyncio.to_thread(read_sample, cpu)
                worst, late_total = lag.take()
                line = {"at": _now_iso(), "t": round(time.time(), 1), **sample, "loop_lag_ms": int(worst * 1000),
                        "loop_late_ms": int(late_total * 1000), **_safe(self.counts, {})}
                text = json.dumps(line) + "\n"
                for run_dir in _safe(self.sinks, []):
                    try:
                        with (run_dir / "resources.jsonl").open("a", encoding="utf-8") as fh:
                            fh.write(text)
                    except OSError:
                        pass
        finally:
            beat.cancel()


def _now_iso() -> str:
    from ..events import now_iso
    return now_iso()


def read_resources(path: Path) -> list[dict[str, Any]]:
    """The samples of a run (``resources.jsonl``), skipping a line cut short."""
    samples: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    samples.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return samples


def summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """The peaks a person compares runs by: least free memory, most swap, the browsers' most memory, most processor, worst loop lag."""
    if not samples:
        return {}

    def pick(key: str, fn):
        values = [s[key] for s in samples if isinstance(s.get(key), (int, float))]
        return fn(values) if values else None
    return {"samples": len(samples), "min_mem_free_mb": pick("mem_free_mb", min), "max_swap_used_mb": pick("swap_used_mb", max),
            "max_browsers_mb": pick("browsers_mb", max), "max_cpu_pct": pick("cpu_pct", max), "max_loop_lag_ms": pick("loop_lag_ms", max),
            "max_tests_running": pick("tests_running", max), "mem_total_mb": pick("mem_total_mb", max)}


if __name__ == "__main__":                                  # quick check on a computer: python -m regrunner.engine.resources
    meter = CpuMeter()
    meter.read()
    time.sleep(1)
    print(json.dumps({"machine": machine_info(), "sample": read_sample(meter)}, indent=2))
    sys.exit(0)
