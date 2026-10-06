# MUR Input Collection Utilities

Scripts for collecting MRVA input files for a given analysis day into a zip archive, useful for comparing production vs containerized pipeline inputs.

## Scripts

### bundle_prod_static.sh

Bundles the **semi-static** reference files (grid masks, OSI-SAF transform
matrices, seasonal climatology, polar-cap edge) from the production tree
into a single gzip'd tar archive. The resulting `.tar.gz` untars into a
top-level `static-resources/` directory that matches the layout in
[static input data](https://podaac.github.io/mur/static-data.html) and the defaults in
`config.example.json`.

Run on the production host (or anywhere `/home/tmchin`, `/nas2` etc. are
mounted):

```bash
# Default output path: ./static-resources_YYYYMMDD.tar.gz
./bundle_prod_static.sh

# Explicit output path
./bundle_prod_static.sh /tmp/static-resources.tar.gz

# Override source roots if your install differs from the defaults
GRIDS_DIR=/alt/grids ICE_DIR=/alt/ice \
SEASONAL_DIR=/alt/seasonal POLARCAP_FILE=/alt/CylinderP01_edge.bip \
    ./bundle_prod_static.sh
```

To install on the pipeline host (defaults assume the pipeline config's
`./testing/static-resources` path):

```bash
tar -xzf static-resources_YYYYMMDD.tar.gz -C mur/testing/
```

### measure_static_sizes.py

Reports exact on-disk sizes of every static/semi-static reference file the
containerized pipeline touches, split into what's irreducible (no generator
exists), what's regeneratable at build time from much smaller inputs (the
`saf2north.mat`/`saf2south.mat` pairs and `CylinderP01_edge.bip` — see
`landice/data_creation/`), and what's optional/unconfirmed (dead code paths,
undocumented file families). Run this **before** deciding how to bundle
static data for distribution — it's the answer to "how big is this, and can
any of it be generated from smaller source files."

Two ways to point it at your data:

- **`--root` / `STATIC_RESOURCES_ROOT`** — a single static-resources root
  laid out per [static input data](https://podaac.github.io/mur/static-data.html)
  (`root/{grids,mat,seasonal,landice}/...`). This is what `config.json`'s
  `landice.static_resources_dir` / `mrva.static_resources_dir` points at —
  use it on the **engineering/container test host**, where static data
  lives under one root (e.g. `/data3/jleach/mur/testing/static-resources`)
  rather than scattered across separate NAS paths.
- **Individual source-root env vars** — same variables as
  `bundle_prod_static.sh` (`GRIDS_DIR`, `ICE_DIR`, `SEASONAL_DIR`,
  `POLARCAP_FILE`), plus `L4_DIR` and `SEASONAL25_DIR` for the two
  optional/unconfirmed file families. Use these on the **production/ops
  host**, where files are scattered across `/home/tmchin/grids`,
  `/home/tmchin/ice`, etc. with no single common root. Any of these set
  explicitly always override whatever `--root` derives, so the two can be
  mixed (a root plus one override).

If you don't know the static-resources root on your engineering host, find
it with `find /data3 /data1 -maxdepth 4 \( -iname static-resources -o -iname maskGLOBp01deg.gds \) 2>/dev/null`.

```bash
# Engineering host: point at the single static-resources root
python utils/measure_static_sizes.py --root /data3/jleach/mur/testing/static-resources --json static_sizes.json

# Production/ops host: no root, defaults to the scattered production paths
python utils/measure_static_sizes.py --json static_sizes.json

# Dry run against the local test fixtures (no prod/engineering mounts needed):
python utils/measure_static_sizes.py --root landice/tests/in
```

### collect_prod_inputs.py

Collects input files from the **production** system. Paths and sensor parameters are derived from `mur-internal/cyc4/nrtMRVA.py` and `mrva4com.m`.

Run this on the production server where `/nas2/`, `/nas4/`, etc. are mounted.

```bash
# List all files needed for an analysis day (no zip created)
python collect_prod_inputs.py --date 2026-03-29 --list-only

# Create a zip using DOY instead of date
python collect_prod_inputs.py --doy 88 --year 2026

# Specify output path
python collect_prod_inputs.py --date 2026-03-29 -o /tmp/prod_088.zip

# Bundle today's REA inputs (analysis day = run_date - 4)
python collect_prod_inputs.py --rea --run-date 2026-06-01

# Bundle today's NRT inputs (analysis day = run_date - 1)
python collect_prod_inputs.py --run-date 2026-06-01
```

### collect_container_inputs.py

Collects input files from the **containerized** pipeline. Reads paths and sensor parameters from the pipeline's JSON config file.

Run this on the container test server where the pipeline output directories exist.

```bash
# List files (resolve config paths relative to base-dir)
python collect_container_inputs.py -c config.json --date 2026-03-29 \
    --base-dir /data3/jleach --list-only

# Create a zip
python collect_container_inputs.py -c config.json --doy 88 --year 2026 \
    --base-dir /data3/jleach

# Specify output path
python collect_container_inputs.py -c config.json --date 2026-03-29 \
    --base-dir /data3/jleach -o /tmp/container_088.zip

# REA bundle keyed off a run date
python collect_container_inputs.py -c config.json --rea --run-date 2026-06-01 \
    --base-dir /data3/jleach
```

### REA vs NRT mode

Both scripts accept a run-mode flag (`--mode {nrt,rea}`, or the `--rea` shorthand)
and an optional `--run-date YYYY-MM-DD` alternative to `--date`/`--doy`. The mode
does **not** change which file paths are read — REA and NRT pull from the same
production trees (`/nas2/bic`, `/nas2/iquam`, `/nas/ftp/.../landice`,
`/nas4/cyc4out`) with the same sensor list and day-range windows.

What `--mode` actually controls:

- **Latency** when `--run-date` is given. Analysis date is derived as
  `run_date - latency_days(mode)`; latencies match
  `mur-internal/cyc4/nrtMRVA.py:38-40` (`NRT_LATENCY_DAYS=1`,
  `REA_LATENCY_DAYS=4`). With `--date`/`--doy`, the mode does not affect the
  analysis day.
- **Labeling.** The default output zip is named
  `prod_{mode}_inputs_{YEAR}_{DOY}.zip` /
  `container_{mode}_inputs_{YEAR}_{DOY}.zip`, the banner prints `Run mode: NRT`
  or `Run mode: REA`, and a top-level `manifest.json` is written into every zip
  recording `mode`, `analysis_date`, `analysis_doy`, `latency_days`, `run_date`
  (if used), and `source` (`prod` or `container`).

## What Gets Collected

For a given analysis day, both scripts collect:

| Data Type | DOY Range | Source |
|-----------|-----------|--------|
| Land/Ice (p011 + p01) | Analysis DOY only | OSI-SAF derived masks |
| iQUAM (buoy) | DOY +/- 3 | NOAA iQUAM |
| BIC (per sensor) | DOY +/- 2 | L2P satellite data |
| MRVA coefficients | Previous day | Prior MRVA run output (.c00-.c11, .u06-.u08) |

The container script can optionally collect **raw L2P .nc granule files** with `--include-l2p` (off by default as this can be thousands of files).

## Zip Structure

Both scripts use a common internal zip layout for easy comparison:

```
bic/AMSR2R/2026/Global_AMSR2R_2026_088.bic.gz
bic/MODISA/2026/Global_MODISA_2026_088.bic.gz
iquam/2026/Global_IQUAM0_2026_088.bii
landice-p011/2026/landice_2026_088.gds.gz
landice-p01/2026/landiceP01_2026_088.gds.gz
csp/2026/2026032809_MRVA4_Global.c06
l2p/AMSR2R/2026/088/*.nc          (container --include-l2p only)
```

## Finding analysis days where prod/container input granules match

Late-arriving L2P granules cause prod and container to ingest different
inputs on the same analysis day, which makes apples-to-apples output
comparisons impossible. To sweep many days cheaply and find ones where
the two pipelines agreed:

### scan_prod_l2plists.py / scan_container_l2plists.py

These produce a compact JSON ledger of the granule basenames recorded in
each `L2Plist_*.txt` file across a DOY range. No data is copied — only
the small text files are read.

```bash
# On the prod host
python utils/scan_prod_l2plists.py --start-doy 100 --end-doy 160 --year 2026 \
    -o prod_l2plist_scan_2026.json

# On the container host
python utils/scan_container_l2plists.py -c containerized-mur/config.container.json \
    --base-dir /home/jleach --start-doy 100 --end-doy 160 --year 2026 \
    -o container_l2plist_scan_2026.json
```

### find_matching_days.py

Ranks candidate analysis days by total granule mismatch (only-prod +
only-cont) across all sensors and the +/-dayrange window:

```bash
python utils/find_matching_days.py \
    --prod prod_l2plist_scan_2026.json \
    --container container_l2plist_scan_2026.json \
    --top 20 --json ranking.json
```

A day with `mismatch=0` means both pipelines saw the same L2P granule set
for every sensor across DOY +/-2 — that's a good candidate for a clean
output comparison. By default sensors that are missing on one side are
excluded from the comparison; pass `--include-missing` to penalise them
instead.

## L2P download orphan capture (`l2p_capture.py`)

Proves, in real time, how many L2P granules the **hourly incremental** download
misses and the **daily deep-sync** later recovers. Because the deep-sync writes
only files that are *missing* on disk, the files it writes each day are exactly
the orphans the incremental runs failed to fetch (see `L2P_orphan_report.html`
for the mechanism).

It works by recording, after each download run, every `.nc` file whose mtime is
newer than a run-start marker — i.e. exactly what that run just wrote — into an
append-only daily JSONL ledger. The two cron wrappers already call it:

- `run_l2p_download_cron.sh` → `record --run-type incremental` (per sensor)
- `run_l2p_deepsync_cron.sh` → `record --run-type deepsync --sensor ALL`, then
  emits a rolling `report`

Manual use:

```bash
# After a run, capture what was written (marker = file touched at run start)
python utils/l2p_capture.py record --config config.prod.json --sensor MODIST \
    --run-type incremental --marker /tmp/.runstart \
    --ledger-dir "$MUR_LOG_DIR/l2p_ledger" --log-watermarks

# --sensor ALL reads l2p.active_sensors from the config (used by deep-sync)
python utils/l2p_capture.py record --config config.prod.json --sensor ALL \
    --run-type deepsync --marker /tmp/.runstart \
    --ledger-dir "$MUR_LOG_DIR/l2p_ledger"

# Summarise the trailing window: incremental vs deep-sync (orphan) counts,
# orphan rate, and the recovered granules grouped by observation day
python utils/l2p_capture.py report --ledger-dir "$MUR_LOG_DIR/l2p_ledger" \
    --days 9 --json /tmp/orphans.json
```

A granule whose **first** capture in the window is a deep-sync run is a proven
orphan. The ledger lives under `${MUR_LEDGER_DIR:-$MUR_LOG_DIR/l2p_ledger}` as
`downloads_YYYYMMDD.jsonl`; the deep-sync also writes
`l2p_orphan_summary_YYYYMMDD.{log,json}` to `$MUR_LOG_DIR`.

### Cron schedule

```cron
# Hourly incremental download (mirrors prod mur_cron timing), now ledger-logged
0  * * * * /bin/bash ~/containerized-mur/run_l2p_download_cron.sh AMSR2R_FINAL
10 * * * * /bin/bash ~/containerized-mur/run_l2p_download_cron.sh AMSR2R_RT
20 * * * * /bin/bash ~/containerized-mur/run_l2p_download_cron.sh AVMTBG
30 * * * * /bin/bash ~/containerized-mur/run_l2p_download_cron.sh MODISA
40 * * * * /bin/bash ~/containerized-mur/run_l2p_download_cron.sh MODIST

# Daily deep-sync (catch-up) BEFORE MRVA — records orphans + writes the summary
0  4 * * * /bin/bash ~/containerized-mur/run_l2p_deepsync_cron.sh 9
```

The deep-sync wrapper emits the orphan report itself, so no separate report cron
is needed. To watch the running miss-rate:

```bash
cat "$MUR_LOG_DIR"/l2p_orphan_summary_$(date +%Y%m%d).log
```
