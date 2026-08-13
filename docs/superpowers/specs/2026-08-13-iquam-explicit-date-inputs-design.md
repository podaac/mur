# iquam Explicit Date/Input Contract — Design

**Status:** design, pending user review
**Scope:** `iquam/buoyDataProcessing.m`, `iquam/bin/entrypoint.sh`, `run_mur_pipeline.py`'s `run_iquam()`. No other container is in scope. `run_mur_maap.py`'s iquam job submission is touched only to correct its existing stub to match the real contract (it currently submits `{"year": year, "doy": doy}`, which doesn't match iquam's real args at all today).
**Builds on:** `docs/superpowers/specs/2026-07-27-explicit-input-contract-design.md` (the shared explicit-args contract) and the landice implementation (`docs/superpowers/plans/2026-07-27-landice-explicit-inputs.md`) as precedent for named-flags-only entrypoints.

## 1. Purpose

The explicit-input-contract work so far (landice) was about file *paths*. This task is about a different but related hidden input: **iquam decides what date to process, and what mode (NRT/REA) it's in, by itself** — via `now()` or a `MUR_SIMULATED_DATE` environment variable read inside the compiled MATLAB executable — rather than being told explicitly by the caller. Every other container in this pipeline (landice, l2p, mrva) already receives its target date as an explicit `--year`/`--doy` CLI argument; iquam is the outlier.

## 2. Current behavior (confirmed by reading `buoyDataProcessing.m` in full)

`buoyDataProcessing.m` independently reimplements the same processing-window calculation `run_mur_pipeline.py`'s `MUROrchestrator` already performs in Python — identical default latencies (`nrtLatency=1`, `reaLatency=4`, `scanLatency=9` match `NRT_LATENCY`/`REA_LATENCY`/`SCAN_LATENCY` exactly). It determines "today" via `getenv('MUR_SIMULATED_DATE')` or `now()`, computes a `day0..day2` window from that, then **loops over every single day in that entire window itself**, deciding NRT-vs-REA per day, and — within each day — loops over `±buoyDayRange` offsets, checking file existence and deciding rewrite-vs-skip per offset day, before calling `makedailyiquam(year, doy, rewrite, outputDir, sourceUrl)`.

Meanwhile, `run_mur_pipeline.py`'s own `run()` loop already iterates `day0..day2` and calls `run_iquam()` once per specific `process_date`. So today, **every one of those per-day container invocations reprocesses the entire rolling window again from scratch**, redundantly with Python's own iteration — the outer window loop inside MATLAB duplicates work Python has already done. `makedailyiquam.m` itself, by contrast, is already fully explicit: `makedailyiquam(year, doy, rewrite, outputDir, sourceUrl)` — no internal date logic at all.

## 3. New design

**Remove entirely:** the outer `year0:year2` / `d0:d2` double loop, the window-bound computation (`nrtEndDatenum`, `reaEndDatenum`, `scanStartDatenum` and their derived `year0/day0/year1/day1/year2/day2`), `nrtLatency`/`reaLatency`/`scanLatency` (only existed to compute that window), `simulatedToday` and the `getenv('MUR_SIMULATED_DATE')`/`now()` fallback chain.

**Keep, now explicit inputs:** the inner `for dt = -buoyDayRange:buoyDayRange` loop, the "skip future dates" check, and the per-offset rewrite/stability decision — these now read from parameters instead of internally-computed values.

**New `buoyDataProcessing.m` signature:**

```matlab
function buoyDataProcessing(year, doy, mode, referenceToday, ...
                            workDir, logDir, outputDir, sourceUrl, ...
                            buoyDayRange, buoyStabilityLatency, ...
                            sourceUrl, enableREA, testing, ...
                            reaAggregationWindow, reaOutputDir)
```

- `year`, `doy`: the one target day to process (replaces the outer loop entirely).
- `mode`: `'nrt'` or `'rea'` string, replacing the internally-derived `realtime` flag (`dayOrdinal > day1Ordinal`). Computed by Python's existing `is_nrt_mode()` and passed straight through — matches `mrva`'s `--mode` convention exactly.
- `referenceToday`: `'YYYY-MM-DD'`, replaces `simulatedToday`/`now()`/env var as the *only* source of "what day is it" — used for the "skip future dates" check and the `daysOld`/stability comparison in the inner loop. No longer optional; always supplied.
- `workDir`, `logDir`, `outputDir`, `buoyDayRange`, `buoyStabilityLatency`, `sourceUrl`, `enableREA`, `testing`, `reaAggregationWindow`, `reaOutputDir`: unchanged in meaning, already explicit today, kept as-is.

**Ordering note:** `sourceUrl` moves to *after* `buoyDayRange`/`buoyStabilityLatency` in the parameter list (it was between `outputDir` and `buoyDayRange` before). This isn't cosmetic — compiled MATLAB executables receive positional arguments, and a caller can only supply a *prefix* of the parameter list before letting the rest default; it can't skip an un-exposed middle parameter to reach a later one it does want to set. Since the entrypoint exposes `buoyDayRange`/`buoyStabilityLatency` as flags but not `sourceUrl`, `sourceUrl` has to move past them so the entrypoint can supply exactly nine positional values (through `stability-latency`) and stop, letting `sourceUrl` onward default naturally — without the entrypoint needing to hardcode a duplicate copy of MATLAB's default URL just to "skip over" it positionally.

**Inner-loop logic changes minimally:** `todayDatenum` is now `datenum(referenceToday, 'yyyy-mm-dd')` (always — no branching on whether a simulated date was supplied). `realtime` is now `strcmpi(mode, 'nrt')` instead of the `dayOrdinal > day1Ordinal` comparison. Everything else in the inner loop (the `±buoyDayRange` iteration, `adjustDoy`, the "skip future" check, the rewrite/stability decision, the `makedailyiquam` call, the REA-aggregation-stub branch gated on `enableREA && ~realtime`) is unchanged, just now driven by parameters instead of internally-derived state.

## 4. Container entrypoint (`iquam/bin/entrypoint.sh`)

Drop the legacy positional passthrough entirely (matches landice's precedent). New required named flags: `--year`, `--doy`, `--mode`, `--reference-date`, `--work-dir`, `--log-dir`, `--output-dir`, `--buoy-day-range`, `--stability-latency`. `--source-url` stays un-exposed (MATLAB-side default), per the earlier decision to keep that out of scope. `mode` validated to be exactly `nrt` or `rea` (same validation pattern already used for mrva's `--mode`). `reference-date` validated as `YYYY-MM-DD`.

`enableREA`/`testing`/`reaAggregationWindow`/`reaOutputDir` are not exposed as new flags — they're pre-existing MATLAB defaults unrelated to the date-input problem this design addresses, and REA aggregation itself remains an unimplemented stub. Out of scope for this task.

## 5. Python changes

**`run_mur_pipeline.py`'s `run_iquam()`:** replaces the three bare positional args (`/tmp/makebic`, logs dir, output dir) and the `-e MUR_SIMULATED_DATE=...` env var mechanism with the nine named flags above. `reference_today` comes from `self.get_reference_today()` (already exists, already used elsewhere in the class). `mode` comes from `"nrt" if is_nrt else "rea"` — `is_nrt` is already a parameter `run_iquam()` receives; no new decision logic needed, just wiring already-computed values into explicit args instead of an env var.

**`run_mur_maap.py`'s iquam submission:** today's stub submits `{"year": year, "doy": doy}` for iquam — this has never matched iquam's real contract (which took neither of those as CLI args before this design). This task corrects it to include the same set of explicit values (`year`, `doy`, `mode`, `reference_date`, `buoy_day_range`, `stability_latency`) that `run_mur_pipeline.py` now passes, making the stub accurate for the first time. `work_dir`/`log_dir`/`output_dir` are container-internal/DPS-staged paths on MAAP (not something the orchestrator resolves to an href, per the design doc's established local-vs-MAAP asymmetry) — left as fixed container-side defaults, not added to the submitted args dict.

## 6. Testing

Same TDD approach as landice: `iquam/tests/test_entrypoint.sh` (new, mirrors the landice/mrva pattern) covers argument parsing, validation, and `build_command` output. Python-side changes get unit tests following the existing patterns in `tests/test_run_mur_pipeline.py` and `tests/test_run_mur_maap.py`.

**MATLAB (`buoyDataProcessing.m`) changes cannot be compiled or run in this environment** — same caveat as landice's `.m` changes. This is a larger, more structural MATLAB edit than landice's (removing a whole loop and several parameters, not just three path-construction lines), so the implementer should be especially careful re-reading the full modified file, and the commit must be flagged unverified exactly as landice's were.

## 7. Out of scope

- `--source-url` as an explicit flag (decided earlier, out of scope).
- REA aggregation (`refbii2biq`) — remains an unimplemented stub, unaffected by this change.
- The `l2p`/`mrva` containers — neither has this "compute today internally" problem; confirmed by reading their entrypoints (both already receive `--year`/`--doy` explicitly and don't call `now()` or read date-related env vars internally). MRVA's *separate*, already-identified prior-CSP problem (computing "yesterday's" date internally to scan for a coefficient file) is a different category of issue — relative-to-a-given-date arithmetic, not "what day is it" — and remains tracked for MRVA's own future design pass.
