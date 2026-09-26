"""JSON / CSV / PNG export with run metadata (§4 Export).

Everything goes to ``<out>/<timestamp>_<seed>/``: params.json (full config, seed, code version),
traces.csv, spectrum.csv, depth_energy.csv, experiments.json, optional report tables such as
e9_report.csv, and one image per figure (PNG through kaleido; HTML when kaleido cannot render,
recorded in params.json).
"""
from __future__ import annotations

import csv
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from . import __version__


def git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent,
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def code_version() -> dict[str, Any]:
    return {"xon_version": __version__, "git_commit": git_commit()}


def to_jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return to_jsonable(obj.tolist())
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return f if np.isfinite(f) else None
    if isinstance(obj, complex):
        return {"re": obj.real, "im": obj.imag}
    return obj


def write_json(path: Path, obj: Any) -> Path:
    path.write_text(json.dumps(to_jsonable(obj), indent=2), encoding="utf-8")
    return path


def make_run_dir(out: str | Path = "results", seed: int = 0) -> Path:
    base = Path(out) / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{seed}"
    path, i = base, 1
    while path.exists():
        path = base.with_name(f"{base.name}-{i}")
        i += 1
    path.mkdir(parents=True)
    return path


def write_params(run_dir: Path, cfg, extra: dict | None = None) -> Path:
    return write_json(run_dir / "params.json", {
        "seed": cfg.seed, "code_version": code_version(), "created": datetime.now().isoformat(timespec="seconds"),
        "config": cfg.to_dict(), **(extra or {})})


def write_traces_csv(run_dir: Path, traces: list[dict], growth_steps: list[int] | None = None) -> Path | None:
    if not traces:
        return None
    keys = list(dict.fromkeys(k for row in traces for k in row))
    growth = set(growth_steps or [])
    path = run_dir / "traces.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(keys + ["growth_event"])
        for row in traces:
            w.writerow([row.get(k, "") for k in keys] + [int(row.get("step", -1) in growth)])
    return path


def write_spectrum_csv(run_dir: Path, spec, p: np.ndarray | None = None) -> Path:
    path = run_dir / "spectrum.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["k", "lambda", "omega", "ipr"] + (["p"] if p is not None else []))
        for i in range(spec.k_used):
            row = [i + 1, spec.lam[i], spec.omega[i], spec.ipr[i]]
            w.writerow(row + ([p[i]] if p is not None else []))
    return path


def write_depth_energy_csv(run_dir: Path, E: np.ndarray) -> Path:
    path = run_dir / "depth_energy.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["depth", "E"])
        for d, e in enumerate(E):
            w.writerow([d, e])
    return path


def write_figures(run_dir: Path, figures: dict[str, Any]) -> dict[str, Any]:
    """PNG via kaleido; on any failure fall back to self-contained-directory HTML and say so."""
    if not figures:
        return {"format": None, "files": []}
    fig_dir = run_dir / "figures"
    fig_dir.mkdir(exist_ok=True)
    names = list(figures)
    try:
        import plotly.io as pio
        paths = [fig_dir / f"{n}.png" for n in names]
        if hasattr(pio, "write_images"):
            pio.write_images([figures[n] for n in names], paths)
        else:
            for n, p in zip(names, paths):
                figures[n].write_image(p)
        return {"format": "png", "files": [str(p.relative_to(run_dir)) for p in paths]}
    except Exception as exc:  # kaleido missing or no browser available
        files = []
        for n in names:
            p = fig_dir / f"{n}.html"
            figures[n].write_html(p, include_plotlyjs="directory")
            files.append(str(p.relative_to(run_dir)))
        note = f"PNG export unavailable ({type(exc).__name__}: {str(exc).splitlines()[0][:200]}); wrote HTML instead."
        (fig_dir / "README.txt").write_text(note + "\n", encoding="utf-8")
        return {"format": "html", "files": files, "note": note}


def write_table_csv(path: Path, rows: list[dict]) -> Path:
    """Rows of equal keys as a CSV with a header line."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return path


def export_run(out: str | Path, cfg, *, spec=None, p: np.ndarray | None = None, traces: list[dict] | None = None,
               growth_steps: list[int] | None = None, depth_energy: np.ndarray | None = None,
               experiments: list | None = None, figures: dict | None = None,
               extra: dict | None = None, tables: dict[str, list[dict]] | None = None) -> tuple[Path, dict]:
    """Write every available artifact; returns (run directory, figure-export info).

    ``tables`` maps a name to rows written as <name>.csv (e.g. the E9 report).
    """
    run_dir = make_run_dir(out, cfg.seed)
    if traces:
        write_traces_csv(run_dir, traces, growth_steps)
    if spec is not None:
        write_spectrum_csv(run_dir, spec, p)
    if depth_energy is not None:
        write_depth_energy_csv(run_dir, depth_energy)
    if experiments:
        write_json(run_dir / "experiments.json", [r.to_json() for r in experiments])
    for name, rows in (tables or {}).items():
        if rows:
            write_table_csv(run_dir / f"{name}.csv", rows)
    fig_info = write_figures(run_dir, figures or {})
    write_params(run_dir, cfg, {**(extra or {}), "figures": fig_info})
    return run_dir, fig_info
