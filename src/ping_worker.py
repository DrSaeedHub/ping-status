"""Run ping -c <count> -i <interval_sec> <target> and parse output."""
import re
import subprocess
from dataclasses import dataclass
from typing import Optional

from src.error_reporting import send_error


@dataclass
class PingResult:
    """Parsed ping result."""
    target: str
    count: int
    interval_sec: float
    transmitted: int
    received: int
    loss_pct: float
    rtt_min_ms: Optional[float] = None
    rtt_avg_ms: Optional[float] = None
    rtt_max_ms: Optional[float] = None
    rtt_mdev_ms: Optional[float] = None
    raw_summary: str = ""
    error: Optional[str] = None


# Linux ping summary line: "rtt min/avg/max/mdev = 1.234/5.678/9.012/2.345 ms"
_RTT_RE = re.compile(
    r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms",
    re.IGNORECASE,
)
# "X packets transmitted, Y received, Z% packet loss"
_STATS_RE = re.compile(
    r"(\d+) packets? transmitted, (\d+) (?:received|received)",
    re.IGNORECASE,
)
_LOSS_RE = re.compile(r"(\d+(?:\.\d+)?)% packet loss", re.IGNORECASE)


def run_ping(target: str, count: int, interval_sec: float) -> PingResult:
    """
    Run ping -c <count> -i <interval_sec> <target> and return parsed result.
    On Linux, interval < 0.2 may require root.
    """
    cmd = ["ping", "-c", str(count), "-i", str(interval_sec), target]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=count * interval_sec + 60,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as e:
        send_error(e, "ping_worker: run_ping TimeoutExpired")
        return PingResult(
            target=target,
            count=count,
            interval_sec=interval_sec,
            transmitted=count,
            received=0,
            loss_pct=100.0,
            error="Ping timed out",
        )
    except FileNotFoundError as e:
        send_error(e, "ping_worker: run_ping FileNotFoundError")
        return PingResult(
            target=target,
            count=count,
            interval_sec=interval_sec,
            transmitted=0,
            received=0,
            loss_pct=100.0,
            error="ping command not found",
        )
    except Exception as e:
        send_error(e, "ping_worker: run_ping")
        return PingResult(
            target=target,
            count=count,
            interval_sec=interval_sec,
            transmitted=0,
            received=0,
            loss_pct=100.0,
            error=str(e),
        )

    return _parse_ping_output(target, count, interval_sec, stdout, stderr)


def _parse_ping_output(
    target: str,
    count: int,
    interval_sec: float,
    stdout: str,
    stderr: str,
) -> PingResult:
    transmitted = count
    received = 0
    loss_pct = 100.0
    rtt_min = rtt_avg = rtt_max = rtt_mdev = None
    raw_summary = ""

    # Packet stats: "3 packets transmitted, 3 received, 0% packet loss"
    stats_match = _STATS_RE.search(stdout)
    if stats_match:
        transmitted = int(stats_match.group(1))
        received = int(stats_match.group(2))
    loss_match = _LOSS_RE.search(stdout)
    if loss_match:
        loss_pct = float(loss_match.group(1))
    elif transmitted > 0:
        loss_pct = 100.0 * (1 - received / transmitted)

    # RTT line
    rtt_match = _RTT_RE.search(stdout)
    if rtt_match:
        rtt_min = float(rtt_match.group(1))
        rtt_avg = float(rtt_match.group(2))
        rtt_max = float(rtt_match.group(3))
        rtt_mdev = float(rtt_match.group(4))
        raw_summary = rtt_match.group(0)

    # Fallback: use last line as raw summary if no RTT parsed
    if not raw_summary and stdout.strip():
        lines = [l.strip() for l in stdout.strip().splitlines() if l.strip()]
        if lines:
            raw_summary = lines[-1]

    return PingResult(
        target=target,
        count=count,
        interval_sec=interval_sec,
        transmitted=transmitted,
        received=received,
        loss_pct=loss_pct,
        rtt_min_ms=rtt_min,
        rtt_avg_ms=rtt_avg,
        rtt_max_ms=rtt_max,
        rtt_mdev_ms=rtt_mdev,
        raw_summary=raw_summary,
        error=stderr.strip() or None if stderr else None,
    )


def format_report(job_name: str, result: PingResult) -> str:
    """Format a detailed report string for Telegram."""
    lines = [
        f"Ping report: {job_name}",
        f"Target: {result.target}",
        f"Count: {result.count} (interval {result.interval_sec}s)",
        f"Transmitted: {result.transmitted}, Received: {result.received}",
        f"Packet loss: {result.loss_pct:.1f}%",
    ]
    if result.rtt_min_ms is not None and result.rtt_avg_ms is not None and result.rtt_max_ms is not None:
        lines.append(f"RTT min/avg/max: {result.rtt_min_ms:.2f}/{result.rtt_avg_ms:.2f}/{result.rtt_max_ms:.2f} ms")
    if result.raw_summary:
        lines.append(result.raw_summary)
    if result.error:
        lines.append(f"Note: {result.error}")
    return "\n".join(lines)
