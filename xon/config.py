"""Every tunable constant of XON SIM lives here.

Experiment *thresholds* are deliberately NOT here: they are pre-registered constants in
``xon/experiments.py`` so that they cannot be tuned from the UI. The available growth rules and
dynamics are the keys of the registries ``xon.growth.RULES`` and ``xon.dynamics.DYNAMICS``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from typing import Any

DRIVES = ("noise", "tone", "probe", "none")
OSC_DRIVES = ("noise", "probe", "none")     # stuart_landau and oscillator have no tone drive
OMEGA_MODES = ("identical", "by_depth", "random")
COHERENCE_FACTORS = ("consonance", "spectral_concentration", "phase_order")
INTEGRATORS = ("auto", "modal", "rk4")
CANONICAL_BASES = ("localized", "raw")
METRIC_SCOPES = ("all", "frontier")

# --- A1 consistency engine: model strings live only here (XON_A1_CONSISTENCY.md §0) ---------------------------------
# claude-sonnet-5 is the model for runs of record. Haiku 4.5 is a cheap option, not for runs of record: its announced
# retirement would make results unreproducible against the live API.
LLM_MODELS = ("claude-sonnet-5", "claude-haiku-4-5-20251001", "claude-opus-5-5", "claude-fable-5-1")
# From the Claude docs, 2026-09-23. sampling: accepts non-default temperature / top_p / top_k (the others reject them
# with an error). thinking_default: what the model does when the request has no thinking field. thinking_can_disable:
# accepts thinking {type: disabled}. thinking_adaptive: accepts thinking {type: adaptive} (Claude docs, adaptive and
# extended thinking, 2026-09-25: Haiku 4.5 has extended thinking only and rejects it).
LLM_CAPABILITIES = {
    "claude-sonnet-5": {"sampling": False, "thinking_default": "adaptive", "thinking_can_disable": True,
                        "thinking_adaptive": True},
    "claude-haiku-4-5-20251001": {"sampling": True, "thinking_default": "off", "thinking_can_disable": True,
                                  "thinking_adaptive": False},
    "claude-opus-5-5": {"sampling": False, "thinking_default": "adaptive", "thinking_can_disable": False,
                        "thinking_adaptive": True},
    "claude-fable-5-1": {"sampling": False, "thinking_default": "adaptive", "thinking_can_disable": False,
                         "thinking_adaptive": True},
}
# USD per million (input, output) tokens; thinking is billed as output. Copied from the Claude pricing page on
# 2026-09-23 and needing verification against the current page. Used only for the sidebar's running estimate.
LLM_PRICES_USD_PER_MTOK = {
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-fable-5-1": (10.0, 50.0),
}
# Multipliers on the input price (Claude docs, prompt caching and batch processing, 2026-09-25): a 5-minute cache write
# costs 1.25x, a cache read 0.1x (0.05x on Opus 5.5); the Message Batches API charges 50% of every price.
LLM_CACHE_WRITE_MULT = 1.25
LLM_CACHE_READ_MULT = {"claude-opus-5-5": 0.05}
LLM_CACHE_READ_MULT_DEFAULT = 0.1
LLM_BATCH_PRICE_MULT = 0.5

# A1 engine versions (XON_A1_REV2_2_PRECISION.md §2). Rev. 2.1 is the run of record's engine and replays it exactly.
ENGINE_VERSIONS = ("2.1", "2.2")
THRESHOLD_METHODS = ("engine", "minimal", "pairwise")
RELATION_THRESHOLD_V2_1 = 0.5       # every clause and the pairwise baseline (entity_consistency.CONFIDENCE_MIN)
# §6: rev. 2.2's relation-confidence threshold per method, selected by the fixed rule on the final development pass
# and frozen with the engine. None until then, when rev. 2.2 uses rev. 2.1's threshold.
RELATION_THRESHOLD_V2_2 = {"engine": None, "minimal": None, "pairwise": None}
# §7.5: the rev. 2.2 development iteration this code implements (CHANGELOG). Iteration 0's single entity call is in
# the git history before iteration 1; its saved statements are still read by entity_consistency.build_entity_graph_v22.
REV22_ITERATION = 1


def relation_threshold(method: str, engine_version: str) -> float:
    """The relation-confidence threshold of a method (THRESHOLD_METHODS) under an engine version; it applies to every
    clause of the method."""
    if engine_version not in ENGINE_VERSIONS:
        raise ValueError(f"unknown engine version {engine_version!r}; expected one of {ENGINE_VERSIONS}")
    if method not in THRESHOLD_METHODS:
        raise ValueError(f"unknown method {method!r}; expected one of {THRESHOLD_METHODS}")
    value = RELATION_THRESHOLD_V2_2[method] if engine_version == "2.2" else None
    return RELATION_THRESHOLD_V2_1 if value is None else float(value)


@dataclass
class XonConfig:
    # --- reproducibility -------------------------------------------------------------
    seed: int = 0

    # --- graph / growth (§3.1, §3.2) ---------------------------------------------------
    growth_rule: str = "gasket"
    simplex_dim: int = 2            # 2 = gasket, 3 = tetrix, ...
    target_level: int = 5           # UI "grow to" target
    max_vertices: int = 200_000     # growth refuses to exceed this
    refine_threshold: float = 1.5   # adaptive: refine cells with mean |a|^2 > threshold * global mean
    refine_floor: float = 0.05      # adaptive: also refine this random fraction of leaf cells
    branch: int = 3                 # tree: children per frontier vertex
    lattice_side: int = 20          # lattice: side x side grid
    sierpinski_p: int = 4           # sierpinski_p: corners p; level L is S(p, L + 1) with p^(L+1) vertices
    merge_tol: float = 1e-9         # rounded-coordinate key resolution for vertex merging

    # --- spectrum (§3.5) ---------------------------------------------------------------
    dense_max: int = 3000           # dense eigh up to this many vertices, eigsh above
    k_modes: int = 64               # modes requested from eigsh in sparse mode
    degeneracy_tol: float = 1e-6    # degeneracy metrics: eigenvalues closer than this are one level
    eig_merge_rtol: float = 1e-8    # numerically equal eigenvalues (gap <= 1e-10 + rtol * lambda) are averaged and
                                    # get a canonical basis. Relative, and far below degeneracy_tol, because the low
                                    # gasket spectrum shrinks ~5x per level: distinct levels are 9e-7 apart at level 7
    canonical_basis: str = "localized"  # basis inside degenerate eigenspaces ("localized" | "raw")
    localize_max_iter: int = 300

    # --- dynamics (§3.3, §6.2; V1.1 §2) --------------------------------------------------
    dynamics: str = "wave"
    c: float = 1.0
    dt: float = 0.05
    dt_auto: bool = True            # cap dt so that (fastest rate bound) * dt <= dt_safety
    dt_safety: float = 0.45
    # wave (V1.1 §2.1): Rayleigh damping alpha I + beta L, mode k decays at alpha + beta lambda_k
    alpha: float = 0.02
    beta: float = 0.05
    sink: bool = False              # optional depth sink Gamma_sink (refused if sink_gamma > 0.1 beta lambda_2)
    sink_gamma: float = 0.01        # gamma_s on vertices with depth <= d_max - sink_depth
    sink_depth: int = 2             # D_sink
    # wave_v1 (V1 §3.3): gamma(d) = gamma0 + gamma1 ((d_max - d) / d_max)^p
    gamma0: float = 0.05            # damping at the frontier (newest vertices)
    gamma1: float = 1.0             # extra damping at the oldest vertices
    damping_p: float = 1.0          # exponent p in gamma(d)
    drive: str = "noise"
    drive_amp: float = 1.0          # wave / wave_v1 noise and tone amplitude
    drive_mode: int = 2             # 1-based mode index for drive="tone" (1 = fundamental)
    tone_resonant: bool = True      # tone phase follows mode k's own rotation exp(-i c^2 lambda_k t)
    init_amp: float = 1.0           # initial state: complex Gaussian with this rms amplitude
    integrator: str = "auto"        # auto = modal when N <= dense_max, else RK4
    probe_vertex: int = 0
    probe_amp: float = 5.0
    # natural frequencies omega_i (stuart_landau, oscillator)
    omega_mode: str = "by_depth"    # identical | by_depth | random
    omega0: float = 1.0
    delta_omega: float = 1.0        # by_depth: omega_i = omega0 + delta_omega * depth_i / d_max
    omega_sigma: float = 0.2        # random: omega_i = omega0 + omega_sigma * N(0, 1), fixed per vertex
    # stuart_landau (V1.1 §2.2)
    sl_mu: float = 1.0
    sl_alpha: float = 0.0
    sl_beta: float = 0.02
    sl_sigma: float = 0.05          # noise drive amplitude at the frontier
    mu_dt_max: float = 0.09         # dt cap keeps mu * dt < 0.1
    # oscillator (V1.1 §2.3): Kuramoto / oscillator Ising machine
    osc_K: float = 1.0
    osc_Ks: float = 0.0             # sub-harmonic locking K_s (E6 and the MaxCut demo anneal it instead)
    osc_sigma: float = 0.0          # phase noise: at the frontier when drive = "noise", else at every vertex
    osc_Ks_max: float = 1.0         # E6: K_s ramps from 0 to this over osc_anneal_steps
    osc_noise: float = 0.05         # E6: phase noise at every vertex

    # --- metrics (§3.4) ----------------------------------------------------------------
    harmonicity_coherence: str = "consonance"
    freq_scale: float = 250.0       # omega -> audio-like Hz for the Plomp-Levelt curve
    roughness_eps: float = 1e-10    # only pairs with p_j p_k > eps contribute to roughness
    ipr_factor: float = 5.0         # mode is localized if ipr > ipr_factor / N
    frontier_window: int = 1        # "frontier" for frontier metrics = depth >= d_max - window
    rp_t_min: int = 5               # spectral-dimension fit window (return probability)
    rp_t_max: int = 60
    rp_probes: int = 64             # Hutchinson probes when N > dense_max
    n_clusters: int = 3             # V1.1: k-means clusters on the low eigenspace (constant + degenerate lambda_2)
    cluster_restarts: int = 20
    cluster_window: int = 200       # W: steps of cluster phase history behind n_clusters_eff
    cluster_drift_max: float = 1.0  # clusters whose phases drift apart by less than this (rad) over the window
                                    # share a frequency: Delta = cluster_drift_max / (W dt)
    k_gap_max: int = 10             # k_gap = argmax lambda_{k+1} / lambda_k over 2 <= k <= k_gap_max
    # geometry metrics (V1.2 §4)
    plateau_multiplicity: int = 3   # degenerate_fraction / plateau_persistence: levels of multiplicity >= this
    mass_uniform_centers: int = 200 # mass_dimension: centers drawn uniformly from all vertices (E9c_v2) ...
    mass_centers: int = 30          # ... or at least R_max from the outer boundary (centers="deep", E9c_v1)
    mass_eligible_frac: float = 0.1 # R_max = the boundary distance that this fraction of the vertices reach
    mass_fit_from: float = 0.25     # fit log M vs log r over r in [mass_fit_from * R_max, R_max]
    walk_walkers: int = 1000        # walk_dimension: lazy walkers, split evenly over walk_starts start vertices
    walk_starts: int = 50
    walk_t_min: int = 10            # MSD fit window: from this many lazy steps ...
    walk_saturation: float = 0.25   # ... until the MSD reaches this fraction of its saturation value
    walk_max_steps: int = 400_000   # ... or this many lazy steps, whichever comes first

    # --- UI / sandbox ------------------------------------------------------------------
    fps: float = 5.0
    steps_per_frame: int = 5
    step_n: int = 50                # N for the "Step xN" button
    auto_grow_every: int = 0        # sandbox: grow one level every this many steps, up to target_level (0 = off)
    metrics_scope: str = "all"      # sandbox traces over "all" vertices or the "frontier"
    max_display_vertices: int = 5000
    max_display_edges: int = 20000

    # --- experiment protocols (§5). Thresholds live in experiments.py. ------------------
    e1_levels: tuple[int, ...] = (3, 4, 5)
    e1_resample: int = 200
    e2_level: int = 5
    e3_level: int = 6               # E3_v1
    e3_steps: int = 2000            # E3_v1: T; E[d] is averaged over the second half
    e3_tree_depth: int = 6          # E3_v1
    e3_tree_branch: int = 3
    e3_start_level: int = 3         # E3: grow from this level ...
    e3_end_level: int = 7           # ... to this one
    e3_grow_every: int = 200        # E3: G
    e3_alpha: float = 0.005
    e3_beta: float = 0.05
    e3_phase_draws: int = 4         # E3: random-phase injections averaged per layer
    e3_fit_k: int = 4               # E3: fit R(k) over k = 1..e3_fit_k
    e4_start_level: int = 2
    e4_end_level: int = 5
    e4_grow_every: int = 500        # G
    e4_seeds: int = 5
    e4_sigma: float = 0.05          # E4b / E4c: noise drive at the frontier
    e5_level: int = 4
    e5_stalk_dim: int = 2
    e5_examples: int = 50
    e5_clamp_frac: float = 0.3
    e5_learn_steps: int = 500
    e5_learn_eta: float = 0.1
    e5_diffuse_steps: int = 5000
    e5_diffuse_eta: float = 0.2
    e6_n: int = 40
    e6_seeds: int = 10
    e6_steps: int = 2000
    osc_anneal_steps: int = 1500    # K_s ramps from 0 to osc_Ks_max over this many steps
    e7_dims: tuple[int, ...] = (2, 3, 4)
    e7_target_n: int = 8000
    e8_level: int = 5
    e8_steps: int = 2000            # E8_v1: T per phase. E8: length of the driven phase 2
    e8_collapse_times: float = 1.0  # E8: phase 1 lasts this many predicted global-collapse times 1/(2 beta lambda_2)
    # E9 (V1.2 §5): cross-geometry predictions
    e9_geometries: tuple[str, ...] = ("gasket", "vicsek", "sierpinski_p", "carpet", "lattice", "tree")
    e9_band: tuple[int, int] = (500, 3000)      # E9a / E9b: the level whose N lies in this band
    e9c_max_n: int = 50_000         # E9c: d_w and d_s at the largest level with N <= this ...
    e9c_retry_max_n: int = 400_000  # ... rerun once at the next level if N <= this; exact counts up to this N
    e9c_trend_from_level: int = 4   # E9c: vicsek's mass-radius d_f from this level up to the largest N <= retry
    e9c_trend_centers: int = 200    # ... with this many deep and this many uniform centers per level
    e9_sierpinski_p: int = 4        # E9 runs S(p, n) with this p
    e9_tree_branch: int = 3
    e9_rp_window: tuple[int, int] = (10, 1000)  # E9c: return-probability fit window for d_s

    # --- A1 consistency engine (XON_A1_CONSISTENCY.md). Its protocol constants live in xon/llm. ---------------------
    llm_model: str = "claude-sonnet-5"
    llm_budget_tokens: int = 500_000    # per session: a call that could take the total past this raises BudgetExceeded
    llm_world_knowledge: bool = False   # relation scoring may use world knowledge (off: the text's own consistency)
    llm_temperature: float = 0.0        # sent only to models that accept sampling parameters (LLM_CAPABILITIES)
    llm_chars_per_token: float = 2.5    # input-token estimate for the budget check (the current tokenizer's average)
    llm_retries: int = 3                # on transport failures only: 429, 5xx, timeouts, lost connections
    llm_backoff_s: float = 2.0          # the first retry waits this long, doubling each time
    llm_engine_version: str = "2.1"     # ENGINE_VERSIONS; the Consistency view offers both and defaults to 2.2
    llm_concurrency: int = 8            # rev. 2.2: relation calls of one document in flight at once
    # max_tokens per call type; it covers thinking plus output
    llm_max_tokens_extract: int = 8192
    llm_max_tokens_pairs: int = 4096
    llm_max_tokens_relate: int = 4096
    llm_max_tokens_relate_single: int = 1024    # rev. 2.2: one pair per call
    llm_max_tokens_entities: int = 8192
    # rev. 2.2's inventory, relations and coverage calls, with adaptive thinking; the SDK refuses a non-streaming call
    # whose max_tokens implies more than ten minutes (above 21,333)
    llm_max_tokens_entity_steps: int = 16000
    llm_max_tokens_direct: int = 16000  # LLM-direct baseline with adaptive thinking
    llm_max_tokens_direct_no_thinking: int = 4096

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in d.items()}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "XonConfig":
        known = {f.name: f for f in fields(cls)}
        kw = {}
        for k, v in d.items():
            if k not in known:
                continue
            default = getattr(cls(), k)
            kw[k] = tuple(v) if isinstance(default, tuple) else v
        return cls(**kw)

    def replace(self, **changes: Any) -> "XonConfig":
        return replace(self, **changes)


DEFAULT = XonConfig()
