# Running on MAAP

This document describes the current state of running the MUR SST pipeline on NASA's MAAP platform, what's actually implemented versus stubbed, and the real submission mechanism confirmed against MAAP's own source and documentation — as distinct from the aspirational OGC/CWL framing in [MAAP_DEPLOYMENT_PLAN.html](MAAP_DEPLOYMENT_PLAN.html).

**Read this before assuming anything here executes today: it doesn't, end to end.** `run_mur_maap.py`'s decision logic is real and tested; the code that would actually talk to MAAP is a stub. See §2.

## 1. What "running on MAAP" means for this pipeline

Each of the four processing containers (`landice`, `l2p`, `iquam`, `mrva`) is meant to run as a MAAP DPS (Data Processing System) job — the same container image used for local Docker execution (`run_mur_pipeline.py`), invoked instead through MAAP's job-submission mechanism, with `run_mur_maap.py`'s `MAAPOrchestrator` in place of `run_mur_pipeline.py`'s `MUROrchestrator`.

The two orchestrators share the same decision logic on purpose (processing window, NRT/REA mode) — see `MAAPOrchestrator.calculate_processing_window()`/`is_nrt_mode()` in `run_mur_maap.py`, which mirror `MUROrchestrator`'s methods in `run_mur_pipeline.py`. What differs is how each one actually gets a container running: `run_mur_pipeline.py` shells out to `docker run`; `run_mur_maap.py` is meant to call MAAP's job-submission API instead.

## 2. Current state — what's real, what's a stub

`run_mur_maap.py` is a skeleton, by design (see its own module docstring). Concretely:

**Real and tested** (`tests/test_run_mur_maap.py`, 20 tests, all against a `FakeMAAPClient`):
- `MAAPOrchestrator.calculate_processing_window()` / `is_nrt_mode()` — the same NRT/REA window math as the local orchestrator
- `MAAPOrchestrator.run_day()` — per-day job sequencing: submits landice + iquam + per-sensor L2P jobs, waits for them, builds and publishes the L2P granules and MRVA sensor-inputs manifests, submits MRVA, waits, and publishes
- BIC cache-skip logic (don't resubmit an L2P job if a fresh-enough BIC already exists)
- The explicit-args resolution for landice (`resolve_landice_static_hrefs`), iquam (submitting `mode`/`reference_date`/`buoy_day_range`/`stability_latency` alongside `year`/`doy`), and mrva (`resolve_mrva_static_hrefs` plus landice-output hrefs via `get_job_output` against the same-run landice job)
- The manifest mechanism itself (§5): `build_l2p_manifest_from_hrefs` and the MRVA sensor-inputs manifest builder, both exercised against `FakeMAAPClient.write_manifest`

**Stubs — every method on `MAAPClient` raises `NotImplementedError`:**
- `stac_search`, `object_exists`, `list_objects` — no real STAC/S3 querying
- `write_manifest` — no real S3 write of manifest JSON
- `submit_job`, `wait_all`, `get_job_output` — no real job submission or polling
- `publish_stac_item` — no real STAC publish of the final product

**Nothing executes on MAAP today.** `MAAPOrchestrator.run()`/`run_day()` can be exercised right now only against the fake client in tests — never against a real MAAP endpoint. Getting from here to an actual MAAP run means implementing `MAAPClient`'s methods against `maap-py`, `pystac-client`, and `boto3` — that work hasn't started.

## 3. The real MAAP submission mechanism (confirmed from source, not docs prose)

`MAAP_DEPLOYMENT_PLAN.html` frames this pipeline's MAAP target as "OGC Application Packages (CWL + Docker)." That framing describes where MAAP is *headed* (`docs.maap-project.org/en/ogc/`), not what's deployable today — that branch isn't public yet. What's actually confirmed, by reading `maap-py`'s source directly (`maap/dps/DpsHelper.py`, `execute.xml`, `execute_inputs.xml`) rather than relying on docs:

- **`maap.submitJob()` builds an OGC WPS 2.0 Execute XML request**, not a CWL/OGC-API-Processes JSON body. Algorithms are registered the classic way (`algorithm_config.yml` + `maap.register_algorithm_from_yaml_file()`), matching real MAAP-Project example repos (`example-dps-stac-from-cog`).
- **Every named input becomes exactly one `<wps:LiteralValue>`** — a single scalar string, built from a plain Python dict (`kwargs`), which can't hold duplicate keys. **There is no repeated-flag or array-input mechanism at the transport level.** A container that needs a variable-count list of files (see §5) cannot receive it as N separate arguments in one job submission.
- **DPS jobs have direct S3 read access at runtime.** Confirmed via a real production MAAP algorithm (`example-dps-stac-from-cog`) that passes a raw `s3://...` path as a plain string parameter and reads it directly (via `rio`/GDAL) — no special per-job credential handling beyond the default AWS region.
- **DPS controls the output location, not the caller.** A job's local `output/` folder gets auto-uploaded to a DPS-managed path (`dps_output/<ALGO_ID>/<ALGO_VERSION>/<IDENTIFIER>/...`, with DPS layering its own date/time organization even when the caller sets `IDENTIFIER`). There is no way to predict a job's output href from a naming convention — it has to be retrieved via `job.outputs` / `get_job_output()` after the job completes, or (for outputs from a *previous* process's job, where the job_id was never retained) via a durable catalog. See §6.

This matters directly for the design below: it's why fan-in has to be a manifest file (§5), and why cross-run output lookups need a catalog rather than a predictable S3 path (§6).

## 4. The explicit-args contract, container by container

Per `docs/superpowers/specs/2026-07-27-explicit-input-contract-design.md` (the common design) and `docs/superpowers/specs/2026-07-27-pipeline-input-inventory.md` (the original per-container audit):

| Container | Status | Static/date inputs | Fan-in inputs |
|---|---|---|---|
| **landice** | ✅ Converted | 6 explicit static files (`--landmask-p01-file`, etc.) + `--year`/`--doy`, named-args only | None |
| **iquam** | ✅ Converted | `--year`/`--doy`/`--mode`/`--reference-date` + 5 more, named-args only, no internal date computation | None |
| **l2p** | ✅ Converted | No static files; `--sensor`/`--region`/`--year`/`--doy`/`--rewrite`, named-args only | Yes — `--granules-manifest` (§5) |
| **mrva** | ✅ Converted | 3 static files + 3 per-day landice-output files, all explicit named flags; `--year`/`--doy`/`--mode`/`--sensors` | Yes — `--sensor-inputs-manifest` (§5, BIC + iQuam unified) |

All four containers now share the same named-flag interface, working identically whether the caller is `run_mur_pipeline.py` (values are local bind-mounted paths) or `run_mur_maap.py` (values are S3 hrefs, once `MAAPClient` is real) — see the design doc's §6 for the local-vs-MAAP split of responsibilities. MRVA's compiled entry point (`mrva4com_container.m`) receives its many resolved values via one generated JSON config file rather than individual positional MATLAB parameters — purely an internal `entrypoint.sh`-to-binary handoff detail; the container's own CLI is unaffected.

## 5. Fan-in: the manifest-file mechanism (implemented)

Because WPS 2.0 Execute only supports one scalar value per named input (§3), a variable-count input (L2P's granules, MRVA's BIC + iQuam files) can't be N repeated flags on real MAAP — it's a single flag pointing at a manifest file:

```json
{
  "files": [
    { "path": "s3://podaac-bucket/mur/bic/AMSR2R/2026/216.bic", "sensor": "AMSR2R", "relative_path": "AMSR2R/2026/Global_AMSR2R_2026_216.bic.gz" },
    { "path": "s3://podaac-bucket/mur/bic/MODISA/2026/218.bic", "sensor": "MODISA", "relative_path": "MODISA/2026/Global_MODISA_2026_218.bic.gz" }
  ]
}
```

One schema, reused by every fan-in consumer — a single `--<name>-manifest <href>` flag; `common/bin/localize.sh`'s `localize_manifest` function fetches the manifest itself, then materializes every listed entry into a fresh scratch directory (`relative_path` if present, else `basename(path)`) before MATLAB runs — the container's own scan/lookup logic (`l2p2bic.m`'s sensor-pattern-priority `dir()`, `mrva4com_container.m`'s per-sensor directory construction) needs **no changes at all**, since it operates on that materialized directory exactly as it did on a bind-mounted one. Locally, `run_mur_pipeline.py` writes the same-schema manifest into a temp file and bind-mounts it plus the source directories; on MAAP, `run_mur_maap.py` writes it to S3 via `MAAPClient.write_manifest` (still a stub) and passes the href.

**Manifests are scoped per run, not cumulative** — generated fresh for the one day/window a given invocation needs (from whatever Python already knows: a STAC search result, a download log, a same-run job output), never an ever-growing file. See the design doc §3 for the full reasoning, including why the manifest itself is also worth *publishing* to STAC (§6) so a later standalone replay doesn't need to reconstruct it (not implemented yet — see §6).

## 6. Cross-run output discovery (why MRVA needs more than explicit args)

Within one `run_day()` call, a job's output href is retrievable directly via `get_job_output(job_id, name)` — the orchestrator still holds the `job_id` it just got back from `submit_job()`, and this is how landice's per-day outputs and this run's fresh L2P jobs' BIC outputs feed into MRVA's flags/manifest today. That breaks down across process boundaries: a *different* invocation of `run_mur_maap.py` (yesterday's cron run, or a standalone replay of one stage) has no `job_id` to query, and DPS's output path isn't predictable (§3) — so there's no way to reconstruct "where did that file land" from a naming convention.

The design (§5 of the common design doc) is to register each intermediate artifact — and the manifest that bundled them for a given day — as a STAC item when it's produced, and search STAC instead of guessing a path or a job_id when a later run needs to find something that already exists. Two specific gaps remain because of this:
- **Skipped L2P jobs** (a fresh-enough BIC already exists, per `object_exists`) fall back to a deterministic `bic_prefix` string rather than a real catalog lookup — works today because Python controls that S3 key convention directly, but is the same kind of naming-convention reliance §3 warns against for DPS-controlled paths specifically.
- **MRVA's prior-day coefficient** (`--prior-csp-file`) is left unset entirely rather than guessed — `run_mur_maap.py`'s `run_day()` omits it, which is a real, unclosed gap (`mrva4com_container.m` falls back to bootstrapping from L4 whenever it's absent, so this doesn't break anything, it just means MRVA always bootstraps on MAAP today instead of chaining from the previous day).

**Not implemented yet** — scoped into its own STAC-cataloging design pass, since MRVA (and L2P's cache-skip) are the only places that actually need cross-run lookup (landice and iquam are always resubmitted fresh every day).

## 7. What's needed to actually run something on MAAP

In rough dependency order:

1. **Implement `MAAPClient`'s methods** against real SDKs: `stac_search`/`object_exists`/`list_objects`/`write_manifest` via `pystac-client`/`boto3`, `submit_job`/`wait_all`/`get_job_output` via `maap-py`, `publish_stac_item` via the STAC Transaction API.
2. **Register each container as a MAAP algorithm** (`algorithm_config.yml` + `maap.register_algorithm_from_yaml_file()`) — all four named-flag interfaces are ready for this now.
3. **Implement the STAC-cataloging piece** (§6) to close the prior-CSP and cross-run BIC-reuse gaps.
4. **Confirm landice's real output names** (`landice_ice_p011`, `landice_grid_p01`, `landice_icefiles_p011` — used by `run_mur_maap.py`'s `get_job_output` calls for MRVA's landice-output flags) against a real registered landice algorithm; these aren't confirmed against any actual DPS output-naming convention yet, and `landice_icefiles_p011` specifically isn't confirmed to be a real landice output file at all (flagged the same way in `run_mur_pipeline.py`'s `resolve_mrva_landice_inputs`).
5. **Confirm the DPS output-staging behavior in practice** (§3's `dps_output/...` path) against a real registered algorithm, since this document's description of it is inferred from docs and one real CWL example, not yet exercised against this pipeline's own algorithms.

## 8. Exercising what exists today

Even though nothing runs on real MAAP yet, the real, tested decision logic can be exercised directly:

```bash
uv run pytest tests/test_run_mur_maap.py -v
```

This runs `MAAPOrchestrator.run()`/`run_day()` against `FakeMAAPClient` (a fake that just records what would have been submitted) — useful for confirming the per-day job sequencing, NRT/REA window math, and BIC skip-logic without needing any real MAAP access. It's the same pattern used throughout `run_mur_maap.py`'s test suite; see `tests/test_run_mur_maap.py`'s `FakeMAAPClient` class for the fake's shape if you're extending it.

## Related documentation

- [MAAP_DEPLOYMENT_PLAN.html](MAAP_DEPLOYMENT_PLAN.html) — the original migration plan; accurate on architecture and phasing, but its OGC/CWL framing describes where MAAP is headed, not what's deployable today (§3 above)
- [`docs/superpowers/specs/2026-07-27-explicit-input-contract-design.md`](../docs/superpowers/specs/2026-07-27-explicit-input-contract-design.md) — the common explicit-args/manifest/STAC design referenced throughout this document
- [`docs/superpowers/specs/2026-07-27-pipeline-input-inventory.md`](../docs/superpowers/specs/2026-07-27-pipeline-input-inventory.md) — the original per-container audit that motivated the design
- [STATIC_DATA.md](STATIC_DATA.md) — where landice's six static files come from
- [landice/README.md](../landice/README.md), [iquam/README.md](../iquam/README.md) — the two containers already converted to the explicit-args contract
