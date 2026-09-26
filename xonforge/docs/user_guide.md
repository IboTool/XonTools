# XonForge user guide

The dashboard is `xonforge/app/dashboard.py`. On Windows, `run_xonforge.bat` (next to `run_xon.bat`) starts it.
It does not import the consistency engine. A key is shown as present or missing, never as its value. Nothing on
the Run page sends a call.

## Configure

Target size, the mix (`TYPE:LEVEL:COUNT`), the spacing and retry constants, how many reviewers read each document,
and the development, calibration and test proportions. Edits stay in the session. The dashboard does not write
`xonforge/config/defaults.yaml`, and it does not set the token caps.

## Providers

The startup check: each registry entry, whether its key is present or missing, its price and its caps. The terms
checklist is `xonforge/config/terms.yaml`. No test call is sent.

## Run

Shows whether the selected run configuration may start. Estimate prices the mix with no call, the same way
`python -m xonforge estimate` does. Start, Pause and Resume change only a paused flag and say that no call was sent.
A live run is `python -m xonforge run NAME --bases TYPE:LEVEL:COUNT` after `run-check` passes, which it does not
while a token cap is unset.

## Review queue

The queue for a run, when `XONFORGE_CACHE_DIR` is set to a directory outside the repository. Accept, Regenerate or
Discard records a reason on the hash-chained decision log. If the cache directory is not set, the page says so and
stops.

## Quality

Whether each scan's canaries were caught, and how many queue items the run has.

## Corpus

A datasheet preview for an empty pipeline-test corpus, and the refusal the export code gives when a pipeline test
is aimed at the sealed split. Pipeline-test documents are not split or sealed.

## Logs

Verifies the decision log when the cache directory is set, and reports the refusal when it is not.
