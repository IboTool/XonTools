"""E9c's closed forms: docs/geometry_closed_forms.md, the code that mirrors it, and the builder at small levels."""
import re
from pathlib import Path

import numpy as np
import pytest

from xon.config import XonConfig
from xon.experiments import REGISTRY_V1_2
from xon.geometry import CLOSED_FORM_GEOMETRIES, closed_form, max_level, structure_rows

DOC = Path(__file__).resolve().parents[1] / "docs" / "geometry_closed_forms.md"
CFG = XonConfig()
KEYS = ("cells", "vertices", "edges", "diameter")


def doc_tables() -> dict[str, dict[int, dict[str, int]]]:
    """{geometry: {L: {cells, vertices, edges, diameter}}} from the tables under the machine-read marker."""
    text = DOC.read_text(encoding="utf-8").split("machine-read by tests/test_closed_forms.py", 1)[1]
    text = text.split("\n## ", 1)[0]
    tables, name = {}, None
    for line in text.splitlines():
        head = re.match(r"\*\*(\w+)\*\*", line)
        if head:
            name = head[1]
            tables[name] = {}
            continue
        cells = [c.strip().replace(",", "") for c in line.strip().strip("|").split("|")]
        if name and len(cells) == 5 and all(c.isdigit() for c in cells):
            tables[name][int(cells[0])] = dict(zip(KEYS, map(int, cells[1:])))
    return tables


def test_doc_tables_equal_the_code_forms():
    tables = doc_tables()
    assert set(tables) == set(CLOSED_FORM_GEOMETRIES)
    for name, rows in tables.items():
        assert sorted(rows) == list(range(len(rows))), name
        for level, values in rows.items():
            assert closed_form(name, level, 4) == values, (name, level)


def test_doc_levels_are_the_registered_ones():
    registered = REGISTRY_V1_2["E9c"].thresholds["exact"]
    assert registered["max_n"] == CFG.e9c_retry_max_n
    for name, rows in doc_tables().items():
        top = max_level(name, CFG, CFG.e9c_retry_max_n)
        assert max(rows) == top and registered["levels"][name] == f"0-{top}", name


def test_the_forms_are_integers():
    for L in range(16):
        assert (44 * 8 ** L + 56 * 3 ** L + 40) % 35 == 0 and (12 * 8 ** L + 8 * 3 ** L) % 5 == 0
        assert (3 ** (L + 1) + 3) % 2 == 0
        for p in range(3, 9):
            assert p * (p ** (L + 1) - 1) % 2 == 0
    assert closed_form("lattice", 2) is None


@pytest.mark.parametrize("name", CLOSED_FORM_GEOMETRIES)
def test_builder_matches_the_forms_at_small_levels(name):
    rows = structure_rows(name, CFG, range(max_level(name, CFG, 2000) + 1))
    for r in rows:
        assert all(r["matches"].values()) and r["cells"] == r["closed_form"]["cells"], (name, r["level"])
        assert r["symmetry_generators"] == 2 and r["orbits"] <= r["vertices"]
    assert np.isnan(rows[0]["ratio_vertices"]) and all(np.isfinite(r["ratio_vertices"]) for r in rows[1:])


def test_ratio_sequences():
    gasket = structure_rows("gasket", CFG, range(6))
    carpet = structure_rows("carpet", CFG, range(4))
    # D doubles (gasket) or triples (carpet) exactly, so counting cells gives the dimension at every level
    assert all(r["ratio_cells"] == pytest.approx(np.log(3) / np.log(2)) for r in gasket[1:])
    assert all(r["ratio_cells"] == pytest.approx(np.log(8) / np.log(3)) for r in carpet[1:])
    ratios = [r["ratio_vertices"] for r in gasket[1:]]
    assert ratios == sorted(ratios) and ratios[-1] < np.log(3) / np.log(2)
