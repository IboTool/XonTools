"""Launcher of the A1 rev. 2.2 full development pass (CHANGELOG_EXPERIMENTS.md, the 2026-09-25 full-pass entry). Keeps
the machine awake while it runs, starts `python scripts/run_rev22_dev.py --budget <N> --iteration 0 --out <OUT>` with
recording off, and reruns the same command, budget recomputed, only after a failure where no response arrived:
anthropic.APIConnectionError (which includes APITimeoutError) or an anthropic.APIStatusError with a 5xx status; at most
5 reruns. Before each start it waits until the API's name resolves and its port accepts a connection, for at most 60
minutes. Anything else stops. The child inherits this process's environment, so the API key must already be set there."""
import ctypes
import json
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "results" / "a1-rev22-full-run.log"
OUT = "results/a1-rev22-full-20260925-124414"
CAP = 45_000_000
MAX_RERUNS = 5
HOST, PORT = "api.anthropic.com", 443
NETWORK_WAIT_S, NETWORK_POLL_S = 3600, 30
ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
FINAL = re.compile(r"^(anthropic\.\w+): (.*)$")
PROGRESS = re.compile(r"^(\S+) \((\d+)/180, rev\. 2\.2\): ")


def note(msg: str) -> None:
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[launcher {datetime.now().astimezone().isoformat(timespec='seconds')}] {msg}\n")


def a1_spent() -> int:
    rows = [json.loads(x) for x in (ROOT / "cache" / "llm" / "log.jsonl").read_text("utf-8").splitlines()]
    return sum(r.get("input_tokens", 0) + r.get("output_tokens", 0) for r in rows if r.get("source") == "api")


def network_up() -> bool:
    try:
        socket.getaddrinfo(HOST, PORT)
        with socket.create_connection((HOST, PORT), timeout=10):
            return True
    except OSError:
        return False


def wait_for_network() -> bool:
    t0 = time.time()
    while not network_up():
        if time.time() - t0 > NETWORK_WAIT_S:
            return False
        time.sleep(NETWORK_POLL_S)
    if time.time() - t0 > 1:
        note(f"network back after {time.time() - t0:.0f} s")
    return True


def no_response(lines: list[str]) -> str | None:
    """The final exception, if it is one the rerun rule covers; None otherwise."""
    last = next((x for x in reversed(lines) if x.strip() and not x.startswith("[launcher")), "")
    m = FINAL.match(last.strip())
    if not m:
        return None
    name, text = m.groups()
    if name in ("anthropic.APIConnectionError", "anthropic.APITimeoutError"):
        return last.strip()
    status = re.match(r"Error code: (\d{3})", text)
    if status and status.group(1).startswith("5"):
        return last.strip()
    return None


def main() -> int:
    awake = ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    note(f"SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED): {'set' if awake else 'FAILED'}")
    env = {k: v for k, v in os.environ.items() if k != "XON_LLM_RECORD"} | {"PYTHONIOENCODING": "utf-8"}
    try:
        for attempt in range(MAX_RERUNS + 1):
            if not wait_for_network():
                note(f"{HOST} unreachable for {NETWORK_WAIT_S} s: stopping for a report")
                return 1
            budget = CAP - a1_spent()
            note(f"start {'resume' if attempt == 0 else f'automatic rerun {attempt} of {MAX_RERUNS}'}: "
                 f"--budget {budget}")
            t0 = time.time()
            lines = []
            proc = subprocess.Popen([sys.executable, "-u", "scripts/run_rev22_dev.py", "--budget", str(budget),
                                     "--iteration", "0", "--out", OUT],
                                    cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    encoding="utf-8", errors="replace")
            with open(LOG, "a", encoding="utf-8") as f:
                for line in proc.stdout:
                    f.write(line)
                    f.flush()
                    lines.append(line.rstrip("\n"))
            code = proc.wait()
            done = [m for m in map(PROGRESS.match, lines) if m]
            where = f"after {done[-1].group(1)} ({done[-1].group(2)}/180)" if done else "before the first document"
            note(f"exit {code} after {time.time() - t0:.0f} s, stopped {where}")
            if code == 0:
                note("finished")
                return 0
            reason = no_response(lines) if code == 1 else None
            if reason is None:
                note("not a failure the rerun rule covers: stopping for a report")
                return code
            if attempt == MAX_RERUNS:
                note(f"{reason}: a sixth failure, stopping for a report")
                return code
            note(f"{reason}: no response arrived; rerunning once the network is up, at least 60 s from now")
            time.sleep(60)
    finally:
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        note("SetThreadExecutionState cleared")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
