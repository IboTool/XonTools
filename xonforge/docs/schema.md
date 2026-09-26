# Schema

The skeleton format (`XONFORGE_SPEC.md` §5.1; `xonforge/skeleton/schema.py`) and the document format (§6, §11;
`xonforge/render/schema.py`), then the export format (`xonforge/corpus/export.py`) and the fingerprint manifests of
the leak test (`xonforge/corpus/leak.py`).

A **base** holds one world's variants, which quotas and splits keep together: `base_id`, `consistent` (the consistent
twin), `planted` (one or more planted variants) and `trap_only` (in v0, a `binary_parity` base's `arity_control` trap
variant, when it is asked for; otherwise none). All variants share the base's id, seed,
genre, entities, attributes, arity fact and premise status, and a fact and its counterpart have the same id in every
variant.

A **skeleton** is one variant:

| field | contents |
|---|---|
| `base_id`, `seed`, `genre` | the base, its seed, and the genre it records |
| `variant` | `consistent`, `planted` or `trap_only` |
| `entities` | `id`, `name`, `pronoun`, `aliases` |
| `attributes` | `key`, `kind` (`ordinal`, `categorical`, `quantity`, `time` or `location`), `arity` (the number of values, when a fact states it), `unit` |
| `facts` | `id`, `kind` (`relation`, `value`, `event` or `premise`), `subject`, `attribute`, `relation`, `object`, `value`, `negated`, `time`, `role`, `depends`, `scope`, `unit` |
| `plant` | `type`, `facts` (its ids) and `params`; only in a planted variant |
| `traps` | `type`, `facts`, `naive` (the reading and the facts it would flag) and `resolving` (facts a correct reading uses); only on a trap-only variant |
| `difficulty` | the knobs the skeleton sets: `cycle_length`, `entities`, `attributes`, `distractor_density`, `same_attribute_distractors` |
| `arity_fact` | the id of the fact stating the planted attribute's number of values (`binary_parity`), or none |
| `premise_status` | `premise` or `not_premise` (`direct_negation`), or none |

`relation` and `negated` are added to §5.1's fact. A relation fact names its `relation`: `greater` (the subject is
above the object on an ordinal attribute, or inside the object when the attribute is a location), `same` or
`different`. A value fact names its `value`, and `negated` marks one stated as false. A premise without a subject
states its categorical attribute's number of values, a whole number of at least 2, in `value`; at most one fact
states it per attribute, and the attribute's `arity` repeats it.

Step 8 adds `role`, `depends`, `scope` and `unit` to a fact. `role` says what a v1 fact is doing (a clock, a
quotation, a belief, a roster). `depends` lists other fact ids; a constraint applies only when every one of them is
present. `scope` lists the entities a roster names. `unit` is `km`, `miles` or `hours` when the number needs one. An
event may name an `object` without being a relation. Entity ids stay unique; display names may repeat, for
`coreference_trap` and `same_name`. A trap's `resolving` facts are skeleton facts. A trap is recorded only on a
trap-only variant.

`arity_fact` and `premise_status` are added to §5.1's skeleton, for the user's step 2 decisions. The arity fact is
recorded apart from the plant's facts and is in both variants; the solver requires it in the planted variant's only
minimal contradiction. The premise status is the same in both variants.

A planted variant's `params` hold the planted attribute (`attribute`), the plant's entities in order (`entities`),
the ids of the facts that differ from the consistent twin (`differs_from_twin`) and the seed that chose that change
(`twin_seed`). `binary_parity` adds the number of "different" relations (`differences`), and `direct_negation` the ids
of the claim and its negation (`negated_claim`, `negation`). `Skeleton.digest()` is the SHA-256 of the skeleton's
canonical JSON.

## Documents

A renderer replies with a **rendering**: `text`, and `spans`, one entry per fact with the fact's id (`fact`) and the
whole sentence that states it, copied character for character (`span`).

A **document** is one rendered variant, kept outside the repository until the split assigns it:

| field | contents |
|---|---|
| `doc_id`, `base_id`, `variant` | the document (`<base_id>-<variant>`), its base, and its variant |
| `skeleton_digest` | the SHA-256 of the skeleton it renders |
| `mode` | the mode of the run that made it (`xonforge/modes.py`): `record`, or `pipeline_test`, whose documents never enter a sealed or judged split or a corpus of record |
| `renderer` | `entry` (the registry entry), `provider`, `model`, `params`, `thinking`, `prompt_version` |
| `rules` | `words` (150 to 3,000), `explicitness` (`stated` or `paraphrased`), `lexical_variety` (`low`, `medium` or `high`), `min_spacing`, `retry_cap` |
| `status` | `rendered`, or `failed` when the last attempt still failed its checks |
| `text`, `spans` | the last readable reply's document and its fact→span map (fact id to sentence) |
| `attempts` | per attempt: `number`, `request` (the first 16 digits of its cache key), `source` (`api` or `cache`), `failed` (the checks quoted back), `error` (a provider error that counted as an attempt) |
| `flags` | for human review: every attempt used, or the checks still failing |
| `review_problems` | a human reviewer's problems that a re-rendering was asked to fix: `problem`, and optionally `fact` and `sentence` |
| `measured` | §5.4's measurements: `words` (whitespace-separated), `sentences`, `plant_distance` (the words between the first and the last planted sentence), `min_spacing` (the fewest other sentences between two planted sentences) |
| `scans` | per deterministic scan (§7.2): `scan`, `result` (`clean`, `hits`, `not_applicable`, or `not_run` while a planted sentence is not a whole sentence), `trusted` (the scan caught every canary registered for it, and one is), `uncovered` (the skeleton's attributes the scan has no pattern for) |

## Export

The corpus is licensed under CC BY 4.0, and its "not for training" notice is a request, not a term of the license.
Nothing is exported with a document whose renderer's provider has no logged check of its terms on publishing its
outputs as a dataset (`xonforge/config/terms.yaml`). Each split has a canary string of its own. Each split's folder
holds `<split>.jsonl`, a record per document; `<split>.skeletons.jsonl`, its skeletons, each with the split's canary
string (`canary`); and a `README.md` and a `LICENSE.txt`, each with the license, the notice and the canary strings of
the folder's splits, and no other split's. The development and calibration splits go to `data/xonforge/<version>/`,
the sealed test split to `XONFORGE_SEALED_DIR/<version>/`, and the judged split to `XONFORGE_JUDGED_DIR/<version>/`.
Which base goes to which split: stratified by plant type × difficulty level, seeded within each stratum, 50 / 15 / 35
for development, calibration and test by default (`xonforge/corpus/splits.py`).

A corpus and all its records have one mode. A pipeline test has only development and calibration splits, which go to
`data/xonforge/pipeline_test/<version>/`, and its README and datasheet say that it is not a corpus of record. A
sealed split's manifest is not written while any document line in its folder is not labelled `record`. A record:

| field | contents |
|---|---|
| `doc_id`, `base_id`, `variant`, `genre` | as in the document and its skeleton |
| `mode` | as in the document |
| `text`, `spans` | the document and its fact→span map |
| `plant`, `traps`, `arity_fact`, `premise_status` | as in the skeleton |
| `difficulty` | `set`: the skeleton's knobs with the rules' `words`, `explicitness` and `lexical_variety`; `measured`: the document's measurements |
| `renderer`, `flags`, `scans` | as in the document |
| `reviewers` | the reviewers who read the document |
| `decisions` | the human decisions on the document: `decision`, `reason`, `reviewer`, `time` |
| `hashes` | `skeleton` (the skeleton's digest) and `text` (the text's SHA-256) |
| `canary` | the split's canary string |

The sealed test split's folder also holds `MANIFEST.json` (`xon_common/manifest.py`): `version` (1), `files` (each
file's path, relative and with forward slashes, mapped to its SHA-256), `canary`, and `manifest_hash`, the SHA-256 of
the canonical JSON of the rest. `SEALED.md` records each sealed version's manifest hash, date, file count and the
SHA-256 of the split's canary string, never the string. An encrypted copy of a file, if made, is `<file>.enc` in a
folder beside the sealed one: the line `XONFORGE-ENC1`, a 16-byte scrypt salt, a 12-byte nonce, then the AES-256-GCM
ciphertext and tag.

## Fingerprint manifests

For the leak test (`xonforge/corpus/leak.py`), sealing a split writes
`data/xonforge/fingerprints/<version>-<split>.json` into the repository: `version`, `split`, `k` (8),
`canary_sha256`, and `documents`, each with `doc_id`, `text_sha256`
(the SHA-256 of its normalized text) and `ngrams` (the 16-hex-digit BLAKE2b hashes of its normalized word 8-grams,
leaving out those in the prompts and in its own skeleton statements). Normalized: NFKC, case folded, punctuation and
quotes stripped, whitespace collapsed. It holds no text.
