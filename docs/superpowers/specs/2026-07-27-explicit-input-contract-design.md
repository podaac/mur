# Explicit Input Contract — Common Design

**Status:** design, pending user review
**Scope:** core processing pipeline only — `landice/`, `l2p/`, `iquam/`, `mrva/`, their wrappers/entrypoints, `run_mur_pipeline.py`, `run_mur_maap.py`, `config.json`/`config.example.json`. Excludes `dataviewer/`, analysis scripts under `utils/`, `run_web_viewer.py`, `mrva/src/fortran/`.
**Precedes:** per-container implementation plans, starting with landice (see build order, §11). Builds on the findings in `docs/superpowers/specs/2026-07-27-pipeline-input-inventory.md`.

## 1. Purpose

Today every container resolves most of its own file paths internally — directory scans, hardcoded `/data/...` conventions, sensor-subdirectory tables. This document is the shared design all four containers and both orchestrators (`run_mur_pipeline.py` for local Docker, `run_mur_maap.py` for MAAP) will follow so that:

- Every input a container needs, static or dynamic, singular or variable-count, arrives as an **explicit named argument** resolved entirely by Python.
- No container-side code constructs a path from a directory root, scans a directory to discover what's in it, or infers identity (sensor, date) by parsing a path string.
- The same container image and entrypoint logic run **unchanged** in both the local-Docker and MAAP environments — only how Python *discovers* and *supplies* argument values differs.

## 2. The shared contract

**Named args only.** Positional-argument mode is dropped entirely from all four entrypoints (`landice/bin/entrypoint.sh`, `l2p/bin/entrypoint.sh`, `iquam/bin/entrypoint.sh`, `mrva/bin/entrypoint.sh`) — named flags become the only accepted form.

Every input is one of two shapes:

- **A direct value flag** — `--<name>-file <path-or-href>` — for anything that resolves to exactly one file (a static grid mask, a seasonal climatology file for a given day, a single dynamic per-day output from another container).
- **A manifest flag** — `--<name>-manifest <path-or-href>` — for anything that's a variable, unbounded count of files (L2P's staged granules, MRVA's per-sensor BIC fan-in across a day-range window).

Flag names are domain-specific (`--landmask-file`, `--bic-manifest`), not generic (`--input-file-1`), so the flag itself documents what it is without needing to read the resolution code.

**Python is the only place path/href logic lives.** `run_mur_pipeline.py` and `run_mur_maap.py` each know the `static-resources/` layout (`documentation/STATIC_DATA.md`) and the per-day/per-sensor naming conventions, and are responsible for computing every flag's value before invoking the container. The bash entrypoint and MATLAB wrapper receive a string and open it — no `fullfile`/`sprintf`-built paths, no `dir()`/directory listing, on the container side, ever.

## 3. Manifest file format

One schema, reused everywhere a variable-count input is needed:

```json
{
  "files": [
    { "path": "s3://podaac-bucket/mur/bic/AMSR2R/2026/216.bic", "sensor": "AMSR2R" },
    { "path": "s3://podaac-bucket/mur/bic/AMSR2R/2026/217.bic", "sensor": "AMSR2R" },
    { "path": "s3://podaac-bucket/mur/bic/MODISA/2026/218.bic", "sensor": "MODISA" }
  ]
}
```

- Every entry has `path`. Extra fields are added only where a consumer genuinely needs grouping that the path string shouldn't have to be parsed to recover — e.g. `sensor` on BIC manifest entries, because `mrva4com_container.m`'s per-sensor table needs that grouping and re-deriving it from the path would just reintroduce a hidden convention. L2P's granule manifest uses the same schema with `path`-only entries (sensor/day are already separate scalar flags on that container).
- JSON specifically: trivial in Python (`json.dump`/`json.load`) and MATLAB (`jsondecode`, built in), consistent with the project's existing `config.json`.
- One parser, reused by every manifest consumer — no bespoke per-container manifest format.

### Manifest construction is environment-specific; the manifest itself isn't

The schema is identical in both environments. What differs is how Python discovers the file list to put in it:

- **L2P granules, on MAAP:** `run_mur_maap.py`'s existing `stac_search()` call already finds the granule hrefs — that result becomes the manifest's `files` list, written to S3, instead of today's stub behavior of passing a raw Python list as a `submit_job` arg (which the WPS scalar-only inputs finding, §6, rules out anyway).
- **L2P granules, locally:** `run_mur_pipeline.py`'s existing `run_l2p_download_incremental` already knows exactly what it downloaded — that becomes the manifest's `files` list, using local paths.
- **MRVA's BIC fan-in:** built from whichever files are relevant for the sensor×day-range window — some produced by L2P jobs submitted *this run* (known via their job outputs, §7), some reused from a past run (resolved via the cross-run cataloging mechanism, §7).

The container-side contract never changes based on which of these produced the list: read a manifest, open every listed entry.

### Manifests are scoped per run, not cumulative

A manifest is generated fresh for one specific invocation and covers exactly the window that invocation needs — it is never a persistent, ever-growing file that later runs append to. Concretely: L2P's manifest is generated for one sensor's one target "day," bounded to that sensor's stable-latency window (`config.json`'s per-sensor `stable`/`day_range`), regenerated from scratch each time L2P runs for that day — it doesn't accumulate history from prior days' runs. The same applies to MRVA's BIC manifest: bounded to the day-range window relevant to that MRVA run, not a running list of every BIC file ever produced. (The STAC catalog in §5 is intentionally the opposite of this — a durable, growing record over time — but that's a separate artifact from the ephemeral, per-invocation manifest file itself. That said, "scoped, fresh per invocation" and "worth persisting for later lookup" aren't in tension — see §5's discussion of publishing the manifest itself as a STAC item for replay.)

## 4. Localization: getting bytes onto local disk before MATLAB runs

MATLAB's compiled runtime reads `.gds`/`.mat`/`.bip`/`.bic`/`.nc` via ordinary local `fopen`/`load`/netCDF calls — none of it understands `s3://` URIs natively. So an `s3://` value, whether a direct flag or a manifest entry, has to become a local file before the MATLAB executable is invoked.

Critically, **this can't happen in Python** the way it might for local Docker (where `run_mur_pipeline.py` just bind-mounts a real local path). On MAAP, the orchestrator (`run_mur_maap.py`) is a separate control-plane process — it is not co-located with the DPS worker container that actually runs the algorithm (§7). So the fetch has to happen *inside* the container, at the start of `entrypoint.sh`, uniformly for all four containers:

- For each direct-value flag: if the value looks like `s3://...`, fetch it to a local scratch path and substitute the local path before calling the MATLAB executable. If it's already a local path (the local-Docker case, or an in-mount path), pass it through unchanged.
- For each manifest: read the manifest, fetch every `s3://` entry to local scratch, and hand MATLAB a **rewritten, all-local manifest** (or an already-localized list) — so the MATLAB-side manifest parser only ever sees local paths and never has to know about S3 at all, in either environment.

This localization step is shared, boilerplate logic (a small helper sourced by all four `entrypoint.sh` scripts), not something each container reimplements.

## 5. Cross-job output discovery — why this is harder than it looks on MAAP

A "run" (`MAAPOrchestrator.run_day()`) is a purely client-side Python loop — it has no runtime existence on MAAP's side. It submits several genuinely separate jobs (landice, iquam, one L2P job per sensor×day, one MRVA job), each on its own isolated worker container. **No job ever shares a filesystem with any other job** — not with jobs submitted a moment ago, not with jobs from last week. That's universal and it is not, by itself, the thing that makes discovery hard: every job's output goes through the exact same DPS-controlled staging path (`dps_output/<ALGO_ID>/<ALGO_VERSION>/<IDENTIFIER>/...`) regardless of when it ran.

The actual fork is narrower than "storage sharing": it's **whether this orchestrator process still holds that job's `job_id` in memory.**

1. **This process just submitted the job** (its `job_id` is sitting in a local Python variable from earlier in the same `run()` call). `maap-py`'s real `DPSJob.outputs` / `get_job_output(job_id, output_name)` can query that specific job directly and get its actual href back. This works purely because we still have the handle to ask with — not because anything about storage differs. The existing `run_mur_maap.py` skeleton is already shaped this way (`get_job_output(mrva_job, "netcdf")`).
2. **A different process invocation submitted the job** — yesterday's cron run, or whenever a still-valid, reused BIC file was originally generated — and that process has already exited. Its `job_id` was never persisted anywhere this process can read. There is no handle left to query with, so `get_job_output()` is unusable here regardless of storage — we've simply lost the one thing that API call needs. And critically, we can't fall back to guessing a path either: confirmed by checking MAAP's actual DPS output handling, **we don't get to choose the output bucket/prefix** — DPS decides it (with its own date/time organization layered in even when we choose `IDENTIFIER` ourselves) — so a naming-convention guess like today's stub (`bic_prefix = f"mur/bic/{sensor}/{year}/{doy}.bic.gz"`) is not a real, reliable href.

For case 2, we resolve this by **registering each intermediate artifact as a STAC item when its producing job completes**, and searching STAC instead of trying to reconstruct a `job_id` or guess a path when checking whether a reusable file exists — reusing the `stac_search`/`publish_stac_item`-shaped primitives already stubbed in `MAAPClient`, rather than inventing a bespoke index. This applies specifically to:
   - L2P's BIC output, since it has a stability/skip-cache mechanism (`test_run_day_skips_l2p_when_bic_cached_and_not_due_for_rewrite`).
   - MRVA's prior-day coefficient, when day N and day N+1 aren't processed inside the same continuous `run()` call (e.g. separate cron-triggered invocations of `run_mur_maap.py` rather than one long-lived process spanning the whole window).

   Landice's and iQuam's outputs do **not** need this — both are resubmitted fresh every day with no skip/cache logic in the current design, so their `job_id` is always available in-process (always case 1).

### Publishing the manifest itself, for replay without a job_id

Per-file STAC registration (above) answers "does this individual file already exist" — the question the routine daily skip/cache logic needs. It doesn't answer a different, equally real question: **rerunning a single stage standalone for a past date**, with no job_id available anywhere and no interest in re-deriving anything. E.g. replaying MRVA alone for `2026-08-06` months later, for debugging or a reprocess.

For that, the **manifest itself** (§3) is published as its own STAC item, tagged by `process_date`, once it's built — not just passed inline to the one invocation that needed it. A standalone replay does a single STAC search ("the BIC manifest for day 218, 2026") and gets back the href of the exact manifest that was built from whatever L2P/iquam/landice actually produced when that day originally ran — no job_id needed, no re-deriving which sensors/files were involved. This applies to any manifest worth replaying against later (MRVA's BIC manifest at minimum); it does not change the per-file registration above, which still exists for the finer-grained skip-decision — the two serve different questions and both are needed.

This does not conflict with "manifests are scoped per run, not cumulative" (§3): each manifest is still a fresh, immutable snapshot generated for one specific day, never appended to — publishing it just means that snapshot is also saved somewhere searchable afterward, rather than existing only as a value passed inline to one invocation.

**A note on confidence:** the `en/ogc/` docs (MAAP's not-yet-public OGC/CWL direction) don't have an output-handling section yet, so this can't be confirmed against documentation. A real, working CWL Application Package found in a MAAP-Project repo (`ogc-app-pack-generator`) shows the same underlying shape — `outputBinding: {glob: ./output*}` — a container writes to a local folder and something else stages it, with no caller-predictable final href either way. This is standard CWL semantics, not something the OGC migration looks designed to change, so the STAC-cataloging approach is a reasonable bet to remain valid there too — but this is inferred from one example, not confirmed by MAAP documentation, and should be revisited if/when that path is public.

## 6. Local vs. MAAP: what's identical, what legitimately differs

| | Local Docker | MAAP |
|---|---|---|
| Container-facing contract (flags, manifest schema) | Identical | Identical |
| Manifest *construction* source | Directory enumeration / download tracking (Python already knows what it wrote) | STAC search (granules) / job outputs (same-run) / STAC catalog (cross-run) |
| Localization step | No-op (values are already local mounted paths) | Real S3 fetch, inside the container |
| Cross-job output discovery | Not needed — `run_mur_pipeline.py` owns every volume mount and always knows every path deterministically; no DPS-style redirection exists locally | Needed — see §5 |

No local STAC mirror is planned. It would buy mechanism-symmetry across environments, but it's real infrastructure (a STAC API + backing store) solving a problem — unpredictable output location — that doesn't exist locally. This is one place the two environments differ under the hood while the container contract stays the same.

## 7. Real MAAP submission mechanism (why fan-in can't be a repeated flag)

Confirmed directly from `maap-py` source (`maap/dps/DpsHelper.py`, `execute.xml`, `execute_inputs.xml`), not just docs prose: `maap.submitJob()` builds an **OGC WPS 2.0 Execute XML** request, not a CWL/OGC-API-Processes JSON body. Every named input becomes exactly one `<wps:Input id="name"><wps:LiteralValue>` element, built from a plain Python dict — which can't hold duplicate keys. There is no repeated-flag or native array mechanism at the transport level today. This is why manifest files (§3), not repeated flags, are the only viable fan-in mechanism for anything that must run on real MAAP right now.

Separately, DPS jobs do have direct S3 read access at runtime — demonstrated by a real production MAAP algorithm (`example-dps-stac-from-cog`) that passes a raw `s3://` path as a literal string and reads it directly via `rio`/GDAL, no special per-job credential handling beyond the default AWS region. This is what makes container-side localization (§4) feasible.

## 8. Required vs. optional inputs

Several static/dynamic inputs are legitimately optional today (STATIC_DATA.md's own conditional table): the MUR25 grid file, the seasonal25 climatology, the L4 bootstrap reference, and MRVA's prior-day coefficient (absent on a true first run). The contract:

- **Required flags**: entrypoint fails fast with a clear error if missing or unfetchable. No silent fallback to an old hardcoded path.
- **Optional flags**: entrypoint accepts their absence as a valid, meaningful state (e.g. `--prior-csp-file` omitted ⇒ bootstrap-from-L4 path; `--mur25-grid-file` omitted ⇒ skip MUR25 generation, matching existing documented behavior). Absence is not an error; a value that's present but unreadable/unfetchable is.

Which specific flags on which container are required vs. optional is decided per-container in each container's own implementation pass (§11), not exhaustively enumerated here.

## 9. Error handling

- Validate all required flags are present and non-empty during argument parsing (before any MATLAB invocation), matching the existing pattern in `mrva/tests/test_entrypoint.sh`.
- After localization (§4), verify every resolved local path actually exists before invoking MATLAB — fail with a message naming the flag and the source value (path or href), not a generic MATLAB file-not-found error surfaced later.
- Manifest files that fail to parse, or list entries that fail to fetch, are hard failures — no partial-run/skip-missing-entry behavior.

## 10. Testing approach

Per the project's TDD practice: entrypoint argument-parsing changes get bash unit tests in the same style as `mrva/tests/test_entrypoint.sh` (source the script, call `parse_args`/`build_command` directly, assert on parsed fields and constructed commands) — written first, watched to fail, then made to pass. Python-side path/manifest-resolution logic in `run_mur_pipeline.py`/`run_mur_maap.py` gets unit tests against fakes, following the existing `FakeMAAPClient` pattern in `tests/test_run_mur_maap.py`. Manifest read/write gets a round-trip test (Python writes, a small MATLAB or Python-side reader confirms it parses back to the same entries).

**MATLAB source changes cannot be compiled or run end-to-end in this environment** (no MATLAB compiler/license server reachable here) — per earlier agreement, `.m` files are edited now and rebuilt/verified elsewhere; any MATLAB-side change in each implementation pass will be flagged explicitly as unverified until that happens.

## 11. Recommended build order

Smallest/cleanest to most tangled, so each step establishes pattern for the next: **iquam → landice → l2p → mrva.**

- **iquam**: no static-resource files at all; already parameterized (`--work-dir`/`--log-dir`/`--output-dir`); only needs positional mode dropped, and optionally `--source-url` exposed for full compliance.
- **landice**: clean, self-contained template case (§12 worked example) — one wrapper, one helper, 6 static files, no fan-in, no cross-day chaining.
- **l2p**: no static-resource dependencies; the main work is the granule manifest (§3) and dropping positional mode; `l2p2bic.m`'s `/nas2/bic/...` reference is confirmed dead (`if 0` block) and needs no change.
- **mrva**: gets its own dedicated design pass once the pattern above is proven — static-resource touchpoints span 5 live files, output discovery needs the STAC-cataloging piece (§5, §7), and the BIC manifest needs to merge same-run job outputs with cross-run catalog lookups.

## 12. Worked example: landice

Concrete illustration of the pattern, since landice is next up for implementation.

**Today:**
```
landice_wrapper(input_dir, output_dir_p011, output_dir_p01, year_str, doy_str)
# input_dir = static-resources root; makeicefiles.m builds:
#   append(input_dir, '/grids/maskGlob1km.gds')       (p011)
#   append(input_dir, '/mat/p011/saf2north')
#   append(input_dir, '/mat/p011/saf2south')
#   append(input_dir, '/grids/maskGLOBp01deg.gds')     (p01)
#   append(input_dir, '/mat/p01/saf2north')
#   append(input_dir, '/mat/p01/saf2south')
```
`entrypoint.sh` accepts only `--year`/`--doy`; `input_dir`/output dirs are hardcoded to `/input`, `/output/p011`, `/output/p01`.

**Proposed:**
```
landice_wrapper(landmask_p011, gridindex_north_p011, gridindex_south_p011, ...
                landmask_p01, gridindex_north_p01, gridindex_south_p01, ...
                output_dir_p011, output_dir_p01, year_str, doy_str)
```
`entrypoint.sh` gains six new required flags: `--landmask-p011-file`, `--gridindex-north-p011-file`, `--gridindex-south-p011-file`, `--landmask-p01-file`, `--gridindex-north-p01-file`, `--gridindex-south-p01-file`. Output directories stay directories (outputs are produced, not discovered — no scan-and-collect problem on the output side), though each output file's *name* stays convention-based inside that directory since landice's own outputs are always exactly two well-known files per resolution. When MRVA later consumes landice's output, it does so via its own explicit single-file flags (resolved through `job.outputs`/local path lookup, §5/§6) — not by scanning landice's output directory itself; that's MRVA's own future design pass, not something this redesign of landice's *inputs* needs to solve.

`run_mur_pipeline.py`/`run_mur_maap.py` each construct these six values from the known `static-resources/` layout (`STATIC_DATA.md`) and pass them explicitly — no `input_dir` argument survives.

## 13. Open items carried forward

- **`seasonal25/mur_###.mat`** (referenced by `makeMUR25_container.m`): undocumented in `STATIC_DATA.md`; confirm whether this file family is actually populated before it's added to MRVA's explicit-args contract.
- **`mrva4com.m` and its legacy callees** (`makeMUR25.m`, `makeSeasonal.m`): confirmed dead code, unreachable from the compiled container entry point (`mrva4com_container.m`). Out of scope for this effort; flag separately if the user wants them removed as cleanup.
- **`MAAP_DEPLOYMENT_PLAN.html`'s CWL/OGC API Processes framing**: doesn't match the real, current MAAP submission mechanism (WPS 2.0 XML via classic `algorithm_config.yml` + `submitJob()`). Left as-is per the user's direction — it's forward-looking to where MAAP is headed, not a description of what to build against today. Worth a documentation pass later, not blocking.
- **STAC intermediate-artifact cataloging** (§5): the specific collection(s)/item schema for registering L2P BIC outputs and MRVA coefficient outputs is deferred to MRVA's own dedicated design pass, since it's load-bearing there but not for iquam/landice/l2p in isolation.
- **Exact per-flag inventories for l2p and mrva** are intentionally not enumerated exhaustively in this document — each gets its own implementation-level design pass per the build order (§11), applying the pattern established here.
