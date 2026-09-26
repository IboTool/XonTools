# XON A5 — Sheaf-Diffusion Language Model (Proof of Concept, Local Learning)

> **Instruction to the implementing agent (Cursor):** Optional package `xon/lm/` (`pip install -e .[lm]`; requires PyTorch for the baselines and the backprop ablation). Nothing in earlier stages imports it. **Gate:** start A5 only after A3's LC1 and LC3 have passed; A5 reuses A3's local learning rules at larger scale, and if locality fails on the small task there is no reason to expect it to work here. A5 uses A1's consistency engine for evaluation. Experiments LM1–LM5 are pre-registered.

---

## 0. Decisions already made

| Decision | Choice |
|---|---|
| Dataset | TinyStories (Eldan & Li 2023), HuggingFace `roneneldan/TinyStories`, streamed and subset by token budget |
| Tokenizer | Byte-level BPE, 4,096 vocab, trained on the training split (`tokenizers`) |
| Models | **SH-EP**: sheaf-diffusion model trained by equilibrium propagation (primary; local). **SH-BP**: the same model trained by backprop through settling (ablation). **MD**: masked-diffusion transformer (control). **AR**: autoregressive transformer (reference) |
| Matching | Parameter counts within ±5%; same training tokens; SH-EP, SH-BP, and MD share the same masked-diffusion objective |
| Devices | Auto-detected: CUDA/ROCm, MPS, DirectML, CPU; override with `XON_DEVICE`. SH-EP's core runs in NumPy or PyTorch-without-autograd, so it has no double-backward requirement |
| Presets | `smoke` (~0.5M params, any CPU), `laptop-cpu` (~2M), `gpu-8gb` (~10M), `gpu-24gb` (~40M), `cloud` (~100M). Same code, different config |

---

## 1. Purpose

A language model built from the project's architecture: generation as relaxation toward consistency, observed words clamped, a multi-scale hierarchy, and **local learning** instead of backpropagation. Two hypotheses carry over from earlier work, plus one new one:

- **H1 (coherence):** at matched loss, SH-EP's stories contradict themselves less than MD's.
- **H2 (built-in uncertainty):** SH-EP's residual energy after settling predicts which stories contain contradictions.
- **H3 (locality at scale):** SH-EP reaches loss within a stated margin of SH-BP, so local learning remains viable beyond the small A3 task.

Expectations stated up front: SH-EP will likely be slower and worse on raw loss than MD. The proof of concept succeeds if any hypothesis holds at matched loss, and it is informative if none do.

---

## 2. Model

### 2.1 Graph over a sequence
- **Token nodes** 0..L−1: **clamped** to their token embedding if the token is known; **free** if masked.
- **Hierarchy:** chunk nodes over windows of w tokens (default 8), section nodes over windows of w chunks, up to one document node (all free latents).
- **Static edges:** `seq` (neighbors within each level) and `up` (child ↔ parent).
- **Dynamic edges** (`sim`): at each settling step, each token node connects to its top-k (default 8) other token nodes by cosine similarity of current states, with softmax weights. No learned query/key projections, so learning stays local.

### 2.2 Maps and energy
Stalk dimension d (preset). Per edge type τ, restriction maps `F_head^τ, F_tail^τ` (diagonal + rank-16), shared across edges of that type. Token embedding matrix `E` (vocab × d) is also a learned local parameter. Energy:
```
E(x) = Σ_e w_e ‖F_head^τ x_u − F_tail^τ x_v‖² + Σ_i φ(x_i) + (α/2) Σ_free ‖x_i‖²
```
with φ a small per-node potential (two-layer MLP applied pointwise; its parameters update locally from each node's own state), α = 0.1.

### 2.3 Settling, readout, cost
- Settle free nodes by `x ← x − η ∇_x E` for T steps (T_train 8, T_eval 16).
- Readout at a masked token node: logits = x_i · Eᵀ.
- **Cost** C = cross-entropy on masked positions, weighted by 1/t (masked-diffusion objective with mask rate t ~ U(0.02, 1)).

### 2.4 Learning
- **SH-EP (primary):** free phase: settle minimizing E. Nudged phase: settle minimizing E + β·C (β = 0.05). Update every parameter θ by −(1/β)(∂E/∂θ at nudged − ∂E/∂θ at free) (Scellier & Bengio 2017). Every term is local to an edge or a node. Symmetric nudging (±β) as an option for lower-bias gradients.
- **SH-BP (ablation):** same model, same C, gradients by autograd through the unrolled free phase.
- Collapse prevention as in A3 (map norm rescaling).

### 2.5 Generation
Iterative unmasking over S steps (default 32), committing the highest-confidence predictions each step and settling with warm starts. Returns tokens, final total energy, and per-token energy.

---

## 3. Baselines
- **MD:** bidirectional transformer denoiser with a timestep embedding, same objective.
- **AR:** small GPT (pre-LN, rotary positions, tied embeddings), next-token objective. Reference only; its NLL is not compared numerically with the diffusion models.

---

## 4. Evaluation

- 3 seeds per model per preset; checkpoints every 5% of the token budget. **Matched-loss comparisons** use the SH and MD checkpoints whose shared masked-diffusion validation loss is closest (within ±2%); otherwise final checkpoints, stated.
- 500 fixed validation prompts (first sentences); 200-token continuations (temperature 0.8, top-p 0.95).
- **Coherence measures:** A1's consistency engine per story (conflict and balanced flag; budget-capped subsample of 200 per model per seed); a free rule-based **entity check** (gendered-name introductions vs later pronouns where the character is the sole antecedent; attribute flips for a small closed set), with unit tests; **fluency controls** (distinct-2/3, repetition rate, length).

| ID | Name | Pass criterion |
|---|---|---|
| **LM1** | Learns at all (gate) | SH-EP final validation loss < unigram baseline by ≥ 30% relative, and 10 inspected samples are grammatical-looking. If it fails, stop |
| **LM2** | Coherence (H1) | At matched loss, SH-EP's checker contradiction rate and entity-inconsistency rate both lower than MD's (bootstrap 95% CI of the difference excluding zero, pooled over seeds), with fluency controls within 10% of MD |
| **LM3** | Energy as uncertainty (H2) | AUROC of SH-EP final energy for checker-flagged contradiction ≥ 0.60 and ≥ MD mean-token-entropy AUROC + 0.05 |
| **LM4** | Settling depth | Reported: contradiction rate and energy vs T_eval ∈ {4, 8, 16, 32} |
| **LM5** | Locality at scale (H3) | SH-EP validation loss within 10% (relative) of SH-BP at equal tokens |

---

## 5. Hardware
Always run `xon-lm estimate --preset <name>` first: it reports the device found, parameter counts, measured throughput, projected wall-clock time, and peak memory. On a Ryzen 7 7735HS with 16 GB RAM, `smoke` and `laptop-cpu` run on CPU. The RX 7700S on Windows may or may not be usable (AMD's PyTorch-on-Windows support is a preview); `estimate` decides. Larger presets run unchanged on a borrowed GPU or a cloud notebook.

---

## 6. UI: LM tab
Training monitor (loss curves for all four models, throughput, ETA); **Generate** with SH stories rendered with per-token energy as background color, so dissonant spans are visible; **Compare** (same prompt, four models, each annotated with checker and entity results); results tables and export.

---

## 7. Implementation order
1. Config presets, device detection, `estimate`.
2. Data: streaming, tokenizer, packing, cached shards.
3. MD and AR; train `smoke`.
4. SH model: graph, energy, settling, readout; monotone-settling and clamping unit tests.
5. SH-EP learning with locality test; SH-BP ablation; train `smoke`.
6. Generation; entity check with tests; evaluation LM1–LM5 (dry-run fixtures for the checker).
7. LM tab; README (Section 8).

---

## 8. What the results mean
- **LM1 + LM5 passing:** a language model can be trained with local, equilibrium-propagation learning on this architecture at small scale, without backpropagation. That is the core of "distinct from standard neural networks" and is worth reporting even if LM2 and LM3 fail.
- **LM2 or LM3 passing:** the architecture's inductive biases (settling, clamped evidence, hierarchy) buy measurable coherence or self-assessment. That justifies a larger run on better hardware; it says nothing about large-scale performance.
- **LM5 failing:** locality does not survive the jump in scale here, and the architecture would need backprop to compete, which removes one of its distinguishing features.

---

## References
- Eldan, R., & Li, Y. (2023). TinyStories: How small can language models be and still speak coherent English? *arXiv*:2305.07759.
- Scellier, B., & Bengio, Y. (2017). Equilibrium propagation. *Frontiers in Computational Neuroscience*, 11, 24.
- Sahoo, S. S., et al. (2024). Simple and effective masked diffusion language models. *NeurIPS 2024*.
