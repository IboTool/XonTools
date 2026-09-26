"""Launcher of the A1 L1 run of record (CHANGELOG_EXPERIMENTS.md, A1 item 22). Keeps the machine awake while it runs,
starts `python scripts/run_consistency_eval.py --budget <N>` with XON_LLM_RECORD=1 for the child only, and reruns the
same command, budget recomputed, only after a failure where no response arrived: anthropic.APIConnectionError (which
includes APITimeoutError) or an anthropic.APIStatusError with a 5xx status; at most 5 reruns. Anything else stops.
The child inherits this process's environment, so the API key must already be set there."""
import ctypes
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "results" / "a1-l1-run-of-record.log"
CAP = 15_000_000
MAX_RERUNS = 5
ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
FINAL = re.compile(r"^(anthropic\.\w+): (.*)$")
PROGRESS = re.compile(r"^(\S+) \((\d+)/180\): ")


def note(msg: str) -> None:
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[launcher {datetime.now().astimezone().isoformat(timespec='seconds')}] {msg}\n")


def a1_spent() -> int:
    rows = [json.loads(x) for x in (ROOT / "cache" / "llm" / "log.jsonl").read_text("utf-8").splitlines()]
    return sum(r.get("input_tokens", 0) + r.get("output_tokens", 0) for r in rows if r.get("source") == "api")


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
    env = dict(os.environ, XON_LLM_RECORD="1", PYTHONIOENCODING="utf-8")
    try:
        for attempt in range(MAX_RERUNS + 1):
            budget = CAP - a1_spent()
            note(f"start {'resume' if attempt == 0 else f'automatic rerun {attempt} of {MAX_RERUNS}'}: "
                 f"--budget {budget}")
            t0 = time.time()
            lines = []
            proc = subprocess.Popen([sys.executable, "-u", "scripts/run_consistency_eval.py", "--budget", str(budget)],
                                    cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    encoding="utf-8", errors="replace")
            with open(LOG, "a", encoding="utf-8") as f:
                for line in proc.stdout:
                    f.write(line)
                    f.flush()
                    lines.append(line.rstrip("\n"))
            code = proc.wait()
            done = [PROGRESS.match(x) for x in lines]
            done = [m for m in done if m]
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
            note(f"{reason}: no response arrived; rerunning in 60 s")
            time.sleep(60)
    finally:
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        note("SetThreadExecutionState cleared")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
