# Pipeline Input Inventory

**Status:** discovery — precedes the common explicit-args design
**Scope:** core processing pipeline only — `landice/`, `l2p/`, `iquam/`, `mrva/`, their wrappers/entrypoints, `run_mur_pipeline.py`, `run_mur_maap.py`, `config.json`/`config.example.json`. Excludes `dataviewer/`, analysis scripts under `utils/`, `run_web_viewer.py`, `mrva/src/fortran/`.

## Purpose

Before designing the "every input is an explicit named argument, Python resolves all paths" contract, we need a ground-truth inventory of every file each container actually touches today — dynamic (per-day) and semi-static (reference) — and exactly where in the code that path is currently constructed. This document is that inventory. It is descriptive only: no interface is proposed here.

Convention used below: **"live"** means the code path is actually reachable by the compiled container entry point; **"dead"** means it exists in the source tree but is not compiled/called by the container (found via grep, confirmed by checking the Dockerfile's `standaloneApplication(...)` entry point and call graph).

---

## IQUAM

**Compiled entry:** `iquam/src/*.m` → `buoyDataProcessing.m`
**Current entrypoint args:** `--work-dir` / `--log-dir` / `--output-dir` (named), or full legacy positional passthrough.

| Input | Kind | Current mechanism |
|---|---|---|
| iQuam buoy source data | dynamic, per-run | Runtime HTTP fetch from `sourceUrl` (`makedailyiquam.m:32`, default `https://www.star.nesdis.noaa.gov/pub/socd/sst/iquam/v2.10/`) — not a local file, a parameter with a hardcoded default. |

**Static-resource footprint: none found.** No `.mat`/`.gds`/grid/seasonal reference anywhere in `iquam/`.

**Finding:** iQuam is already almost fully compliant with "explicit named args, no hidden paths" — its only input is a URL default that could be exposed as `--source-url` for completeness, but it isn't a filesystem path problem at all. Smallest possible scope of the four.

---

## LANDICE

**Compiled entry:** `landice/src/landice_wrapper.m`
**Signature:** `landice_wrapper(input_dir, output_dir_p011, output_dir_p01, year_str, doy_str)`
**Current entrypoint args:** `--year` / `--doy` (named), or `YEAR DOY` positional. `input_dir`/`output_dir_p011`/`output_dir_p01` are **not exposed as flags at all** — hardcoded to `/input`, `/output/p011`, `/output/p01` inside `entrypoint.sh:build_command()`, fixed by volume mount.

| Input | Kind | Current mechanism |
|---|---|---|
| OSI-SAF ice concentration data (both hemispheres) | dynamic, per-day | Runtime fetch inside `readosisafice.m` (keyed by year/day/reprocessing-cutoff MJD) — not a locally-staged file path, analogous to iQuam's URL fetch. |
| `grids/maskGlob1km.gds` (p011) | static | `makeicefiles.m:70`: `append(input_dir, '/grids/maskGlob1km.gds')` |
| `mat/p011/saf2north.mat` | static | `makeicefiles.m:71` |
| `mat/p011/saf2south.mat` | static | `makeicefiles.m:72` |
| `grids/maskGLOBp01deg.gds` (p01) | static | `makeicefiles.m:86` |
| `mat/p01/saf2north.mat` | static | `makeicefiles.m:87` |
| `mat/p01/saf2south.mat` | static | `makeicefiles.m:88` |

All six static files are resolved by string-concatenating a single `input_dir` (today: the whole `static-resources/` root, per `config.json`'s `landice.input_dir: "testing/static-resources"`) — the exact "give me a directory and I'll figure out what's inside" pattern in scope for removal.

**Finding:** Cleanest non-trivial case. One wrapper, one helper function (`makeicefiles.m`), a fixed set of 6 static files (3 per resolution × 2 resolutions), no fan-in, no cross-day chaining, no dead/legacy hardcoded paths found. Good candidate for the first concrete design/implementation after the common pattern is agreed.

---

## L2P

**Compiled entry:** `l2p/src/l2p_wrapper.m` → calls `l2p2bic.m` directly
**Signature:** `l2p_wrapper(sensor, region, indir, bicdir, year_str, day_str, rewrite_str)`
**Current entrypoint args:** `--sensor --region --year --doy --rewrite` (named), or 5-arg positional. `indir`/`bicdir` are **not exposed as flags** — hardcoded to `/data/input`/`/data/output` in `entrypoint.sh:build_command()`.

| Input | Kind | Current mechanism |
|---|---|---|
| Pre-staged L2P granule `.nc` files | dynamic, per-day, variable count | `indir` — a directory of whatever granule files were staged there; L2P scans the directory rather than being told which files to read. Downloads happen out-of-band (cron/podaac-data-subscriber in production; `run_mur_maap.py`'s STAC search on MAAP). |

**Static-resource footprint: none found.**

**Dead code found:** `l2p2bic.m:232-233` has `if 0, ... bicfile=sprintf('/nas2/bic/%s/%04d/Global_%s_%04d_%03d.bic',...); ...` — an `if 0` block, permanently disabled in MATLAB, never executes. Confirmed dead; **no action needed.**

**Finding:** No semi-static dependencies at all. The only "hidden path" issue is the directory-scan convention for `indir` (variable-count granule fan-in) — the real design question here is how to pass a *list* of explicit granule file paths (repeated flag vs. manifest file vs. CWL `File[]`), not a static-resource problem. `bicdir` (single explicit output path) is trivial to expose.

---

## MRVA

**Compiled entry (confirmed via Dockerfile `standaloneApplication('mrva4com_container.m', ...)`):** `mrva/src/matlab/workflow/mrva4com_container.m`
**Signature:** `mrva4com_container(year, day, realtime, varargin)` — **zero path arguments of any kind.** Every directory is a hardcoded string literal inside the function body.
**Current entrypoint args:** `--year --doy --mode --sensors` (named), or 3-4 arg positional. No path flags exist.

**Important architectural finding:** `mrva4com.m` (the "core algorithm" file referenced in earlier investigation) is a **separate, parallel implementation that the container never calls.** Grep across `mrva/src/matlab/` for callers of `mrva4com(` / `mrva4com_container(` shows `mrva4com_container.m` is self-contained — it does not invoke `mrva4com.m`, and nothing invokes `mrva4com_container.m` from `mrva4com.m` either. `mrva4com.m`'s hardcoded `/nas2/landice/CylinderP01_edge.bip` (line 209), its calls to legacy `makeMUR25.m`/`makeSeasonal.m` (which hardcode `/nas/ftp/mur_sst/tmchin/...` paths), and its internal `bgfile`/`coefile` directory-scan are **all dead from the container's perspective.** They're a pre-containerization reference implementation living in the same tree, not code this effort needs to touch. (Flagging this for the user's decision under CLAUDE.md's "no reference-code edits" principle, applied here to a file that happens to sit inside `mur/` rather than `mur-internal/`.)

### Hardcoded roots (`mrva4com_container.m:69-95`)

```matlab
fortran_bin              = '/opt/mrva/bin';
bic_root                 = '/data/input/bic';
iquam_root                = '/data/input/iquam';
landice_p011_root        = '/data/input/landice-p011';
landice_p01_root         = '/data/input/landice-p01';
static_resources_root    = '/data/static-resources';
csp_basedir              = '/data/output/csp';
netcdf_dir               = '/data/output/netcdf';
bipdir                   = '/data/cache/bip';
mapdir                   = '/data/cache/mrva4map';
logdir                   = '/data/logs';
```

Plus `outgridfile = '/app/matlab/workflow/Global10km.out'` — a compile-time-baked path (used by the `spgrid` Fortran call), not runtime-configurable at all today.

### Static/semi-static files

| Input | Current mechanism |
|---|---|
| `landice/CylinderP01_edge.bip` (polar cap edge) | `mrva4com_container.m:301`: `sprintf('%s/landice/CylinderP01_edge.bip', static_resources_root)` |
| `grids/MUR25grid.gds` | `mrva4com_container.m:644` |
| `grids/maskGlob1km.gds` / `maskGLOBp01deg.gds` / `maskGlob8km.gds` | `csp2nc4a.m:195-227` (constructed from `grids_root`, itself hardcoded `/data/static-resources/grids` at `csp2nc4a.m:89`, independently of the root passed into `mrva4com_container.m`) |
| Seasonal climatology `seasonal/mur_###.nc` | `readSeasonal.m:17,20` — hardcodes its own `seasonal_root = '/data/static-resources/seasonal'`, **not derived from any passed-in `static_resources_root` at all** |
| Seasonal climatology (MUR25 variant) `seasonal25/mur_###.mat` | `makeMUR25_container.m:747-748`: `seasonaldir = sprintf('%s/seasonal25', static_resources_root); seasonalfile = sprintf('%s/mur_%03d.mat', seasonaldir, doy)` — **⚠ undocumented in `STATIC_DATA.md`**, which only lists `seasonal/mur_###.nc`. Needs confirmation: does `static-resources/seasonal25/*.mat` actually exist/get populated by `bundle_prod_static.sh`, or is this dead/unreachable because MUR25 generation is itself optional/conditional? |
| L4 GHRSST reference (`L4/GLOB/NCDC/AVHRR_OI/{year}/{doy}/*.bz2`) | `trimbip3a.m:6`: `L4_reference_root = '/data/static-resources/L4'` (hardcoded constant, not a passed parameter — but only used as a fallback when no prior-day coefficient exists) |

### Dynamic per-day / fan-in inputs

| Input | Kind | Current mechanism |
|---|---|---|
| BIC files, per sensor (`AMSR2R`, `MODISA`, `MODIST`, `AVMTAG`, `AVMTBG`), each across a `day_range` window | dynamic, variable count | `bic_root` hardcoded sensor-subdirectory table, `mrva4com_container.m:161-196`: `[bic_root, '/AMSR2R']` etc. — directory scan per sensor, not explicit file list. Easily 10-25 files per run. |
| iQuam buoy output | dynamic, per-day | `iquam_root` directory, output of the iQuam container |
| Landice output, both resolutions | dynamic, per-day | `landice_p011_root` / `landice_p01_root` directories — outputs of the landice container, consumed here as directory-scanned inputs (`csp2nc4a.m:195-221`: `[landice_p011_root, '/%04d/landice_%04d_%03d.gds.gz']` etc.) |
| Prior-day CSP coefficient (`coefile`) | dynamic, cross-day chaining | `mrva4com_container.m:325-352`: constructs `name = sprintf(['%s/%04d/', cspfmt], csp_basedir, y_ref, ...)` against the **previous day's** date and directory-scans `csp_basedir` for a matching `.c0N` file. This is the "prior CSP" gap identified in the earlier MAAP design pass — on MAAP there's no persistent shared disk across job invocations, so this must become an explicit `--prior-csp <href>` input, sourced from the previous day's job output rather than rediscovered by scanning. |

**Finding:** By far the largest and most tangled scope.
- No path arguments at all today — everything is hardcoded container-internal convention matched to Docker volume mounts.
- Static-resource touchpoints span **5 files**: `mrva4com_container.m`, `csp2nc4a.m`, `readSeasonal.m`, `makeMUR25_container.m`, `trimbip3a.m` — and at least two of them (`csp2nc4a.m`'s `grids_root`, `readSeasonal.m`'s `seasonal_root`) independently re-hardcode their own copy of `/data/static-resources/...` instead of receiving `static_resources_root` as a parameter, so today there isn't even a single source of truth to redirect — each file would need its own new parameter.
- One undocumented static file family (`seasonal25/*.mat`) needs confirmation before it can be added to the explicit-args contract.
- Variable-count fan-in (BIC files) needs a design decision (repeated flag / manifest file / CWL `File[]`) shared with L2P's granule-list problem.
- Prior-CSP cross-day chaining needs to become an explicit argument, wired through `run_mur_maap.py`'s per-day `run_day()`/`run()` loop.
- `mrva4com.m` (dead, unused by the container) is out of scope for this effort unless the user separately wants it cleaned up or deleted.

---

## Cross-cutting observations for the common design

1. **No single static-resources parameter today, even where one nominally exists.** `mrva4com_container.m` threads `static_resources_root` through to two callees (`polarcap`, `MUR25grid.gds`, and onward into `makeMUR25_container.m`), but `csp2nc4a.m` and `readSeasonal.m` each hardcode their own copy of the same root independently. Any design that just "adds a parameter for the directory" would still leave two files unparameterized; the fix has to reach every one of the 5 MRVA files listed above.
2. **Variable-count fan-in is a shared problem, not MRVA-only.** L2P's granule directory and MRVA's per-sensor BIC directories are the same shape of problem (N files, unknown count, resolved today by directory scan) and should get one shared answer in the common design, not two bespoke ones.
2. **Dead code exists at both ends of complexity.** `l2p2bic.m`'s `if 0` block and the entire unused `mrva4com.m`/`makeMUR25.m`/`makeSeasonal.m` family confirm that not every hardcoded `/nas...` path found by grep is a live problem — each finding above has been verified against the actual compiled entry point's call graph before being counted as in-scope.
3. **Prior-CSP chaining is MRVA-specific and already flagged from the earlier MAAP design pass** — it's a cross-day dependency, not a static resource, but it belongs in the same "every input is explicit" contract and should be designed alongside MRVA's other inputs rather than separately.
4. **Recommended build order**, smallest/cleanest to most tangled: **iquam → landice → l2p → mrva.** iquam is nearly free, landice is a clean template for the "static file set → explicit named args" pattern, l2p mainly needs the fan-in-list answer, and mrva needs everything (multi-file static parameterization, fan-in, prior-day chaining) and should go last so it can reuse whatever pattern the earlier three establish.

## Open items requiring a decision before/during the common design

- **Fan-in mechanism** for variable-count file lists (L2P granules; MRVA per-sensor BIC files): repeated `--input <path>` flags, a comma-separated list, or a manifest file passed as its own explicit argument. CWL supports `File[]` natively (see `MAAP_DEPLOYMENT_PLAN.html` §8.2), which is relevant prior art if OGC/CWL is the eventual target for all four containers.
- **`seasonal25/mur_###.mat`**: confirm whether this file family is actually present in the static-resources bundle / actively used, since it's undocumented in `STATIC_DATA.md` and not covered by `bundle_prod_static.sh` as currently understood.
- **`mrva4com.m` and friends (dead code)**: confirm with the user whether to leave untouched (out of scope) or flag for a separate cleanup/removal task — not blocking, since it's unreachable from the container either way.
