# MUR Data Viewer - Web Interface

A web-based interface for browsing and visualizing MUR SST processing data files using Streamlit.

## Features

- **Secure File Browsing**: Navigate directories and select files within a configurable base directory
- **Interactive Visualization**: Uses matplotlib for high-quality plots with full support for:
  - Large point datasets (>10M points) via `mpl-scatter-density`
  - Smart downsampling with outlier preservation
  - Multiple visualization panels showing different data aspects
- **File Format Support**: All formats supported by the CLI viewer:
  - Point data: `.bip`, `.biq`, `.bii`, `.bic`, `.bin`
  - Grid data: `.gds`, `.map`
  - NetCDF: `.nc`, `.nc4`
  - Coefficients: `.c*`, `.u*`
- **Real-time Statistics**: File information and statistics displayed alongside visualizations
- **Configurable Data Sources**: Runs come from the local filesystem *or* MAAP's
  STAC catalog, and Compare mode measures them against the operational MUR L4
  product at PO.DAAC by default — no local copy of the reference required
  (see [Data Sources](#data-sources))

## Installation

Install the web viewer dependencies:

```bash
cd /path/to/mur
pip install -e .
```

This will install Streamlit and all required dependencies.

## Usage

### Basic Usage

Run the web viewer from the `dataviewer/` directory so that Streamlit picks up the
`.streamlit/config.toml` configuration:

```bash
cd /path/to/mur/dataviewer

# Set the base directory for file browsing
export MUR_BASE_DIR=/path/to/mur/data

# Run the viewer
streamlit run web_viewer.py
```

The app will open in your default web browser at `http://localhost:8501`.

### Setting Base Directory

The `MUR_BASE_DIR` environment variable controls which directory tree is available
for browsing. This **must** be set before launching the viewer:

```bash
# Set base directory to MUR data location
export MUR_BASE_DIR=/path/to/mur/data
streamlit run web_viewer.py

# Or inline
MUR_BASE_DIR=/nas4/mur/data streamlit run web_viewer.py
```

This ensures users can only browse files within the specified directory tree (security feature to prevent path traversal).

### Password Protection

The app requires a password before any content is rendered. The password is stored
in `.streamlit/secrets.toml` (git-ignored):

```toml
app_password = "your-secure-password"
```

If the file is missing or the `app_password` key is absent, the app runs without
a password prompt. To enable password protection, create the file and set the value.

### SSL / HTTPS

To serve over HTTPS, place your certificate and key files in the `ssl/` directory:

```text
dataviewer/
  ssl/
    cert.pem   # SSL certificate (or fullchain)
    key.pem    # SSL private key
```

Then uncomment the SSL lines in `.streamlit/config.toml`:

```toml
sslCertFile = "ssl/cert.pem"
sslKeyFile = "ssl/key.pem"
address = "0.0.0.0"
enableCORS = true
```

When SSL is enabled the server binds to `0.0.0.0` and is accessible at
`https://<hostname>:8501`. Without the cert/key files, it binds to `127.0.0.1`
only (use an SSH tunnel for remote access).

To generate a self-signed certificate for development:

```bash
openssl req -x509 -newkey rsa:4096 -keyout ssl/key.pem -out ssl/cert.pem \
  -days 365 -nodes -subj '/CN=localhost'
```

### Advanced Usage

#### Custom Port

```bash
streamlit run web_viewer.py --server.port 8080
```

#### Production Deployment

For production, enable SSL (see above) and run headless:

```bash
streamlit run web_viewer.py --server.headless true
```

## Data Sources

The viewer originally browsed one directory and compared two files you picked by
hand. That only works while both sides of a comparison are on the machine running
Streamlit — which stops being true the moment the pipeline runs on MAAP, and was
never true of the thing most worth comparing against: the operational MUR L4
product published at PO.DAAC.

Three things are now configured independently:

| Setting | Meaning | Values | Default |
|---|---|---|---|
| `run_source` | where the granule you are inspecting comes from | `local`, `maap` | `local` |
| `reference_source` | what Compare mode measures it against | `public`, `local`, `maap` | `public` |
| `cache_dir` | where remote granules are materialized | any path | `~/.cache/mur-viewer/granules` |

### Why `public` is the default reference

The public product is the same product this pipeline reproduces. A difference
against it is a statement about the run; a difference between two files that
happened to be on disk is a statement about nothing in particular. Compare mode
therefore resolves the reference automatically from the **run's own analysis
date** — there is no path to select. The difference is reported as
**run − reference**.

The manual pick survives as an explicit override (**Set as Reference** in the
sidebar) for the run-vs-run case, such as comparing a container run against a
production run of the same day.

### Configuration

Environment variables beat a config file, which beats the defaults. The file is
what you check in or bake into an image; the environment is what whoever
launches the viewer overrides.

```bash
# Local runs, compared against the public product (the default)
export MUR_BASE_DIR=/data3/testing/output
mur-web-viewer

# MAAP runs, compared against the public product
export MUR_VIEWER_RUN_SOURCE=maap
export MUR_VIEWER_MAAP_WORKSPACE_ROOT=s3://maap-ops-workspace/yourname
mur-web-viewer

# Container run vs production run, both local
export MUR_VIEWER_REFERENCE_SOURCE=local
```

Every setting, and where it comes from:

| Environment variable | Config key | Notes |
|---|---|---|
| `MUR_VIEWER_RUN_SOURCE` | `run_source` | `local` or `maap` |
| `MUR_BASE_DIR`, `MUR_VIEWER_BASE_DIR` | `base_dir` | local browser root; the namespaced spelling wins if both are set |
| `MUR_VIEWER_REFERENCE_SOURCE` | `reference_source` | `public`, `local` or `maap` |
| `MUR_VIEWER_PUBLIC_COLLECTION` | `public_collection` | CMR short name; default `MUR-JPL-L4-GLOB-v4.1` |
| `MUR_VIEWER_MAAP_STAC_URL` | `maap_stac_url` | STAC API root |
| `MUR_VIEWER_MAAP_COLLECTION` | `maap_collection` | default `mur-l4-sst`, matching `mur_maap/stac.py` |
| `MUR_VIEWER_MAAP_WORKSPACE_ROOT` | `maap_workspace_root` | `s3://bucket/prefix`; enables the bucket fallback below |
| `MUR_VIEWER_MAAP_STAC_TOKEN`, `MAAP_PGT` | `maap_stac_token` | bearer token for the STAC API |
| `MUR_VIEWER_CACHE_DIR` | `cache_dir` | download cache |
| `MUR_VIEWER_MAX_DOWNLOAD_MB` | `max_download_mb` | per-granule ceiling; default 2048 |
| `MUR_VIEWER_CONFIG` | — | path to the config file itself |

Copy `viewer.example.json` to `viewer.json` next to `run_web_viewer.py`, or point
`MUR_VIEWER_CONFIG` at it. Pointing `MUR_VIEWER_CONFIG` at a *pipeline* config
(`config.maap.json`) also works: the viewer reads `maap.workspace_root` out of it
rather than needing a second copy.

Everything is also adjustable at runtime under **Data Sources** in the sidebar,
which shows a readiness line per source (`✅` / `⚠️` with the reason).

### How MAAP runs are discovered

Two routes, tried in order:

1. **STAC API** — a `POST /search` against `maap_stac_url` for
   `maap_collection`, over plain HTTP. (No `pystac-client` dependency for one
   request.)
2. **Workspace bucket** — the deterministic item keys the pipeline already
   writes, at `mur/stac/items/<year>/<doy><mode>.json`
   (`mur_maap/paths.stac_item_key`). This route works *today*, before any STAC
   endpoint exists to point at, because it reads files we know we wrote at keys
   we chose. Needs `s3fs`.

A day produced first as NRT and later reprocessed as REA appears as two
granules, labelled `[NRT]` and `[REA]`; an unqualified date lookup prefers the
reanalysis.

### Credentials

- **PO.DAAC**: searching CMR needs nothing. *Downloading* needs an Earthdata
  login — a `machine urs.earthdata.nasa.gov` entry in `~/.netrc`, or
  `EARTHDATA_USERNAME` / `EARTHDATA_PASSWORD`. The viewer says so at the moment
  a download is actually wanted rather than up front.
- **MAAP**: `MAAP_PGT` is picked up automatically, so a MAAP JupyterHub session
  needs no extra configuration. S3 reads use the default credential chain.

### The download cache

Every reader downstream opens a local path, so a remote granule is downloaded
once and reused. MUR L4 is ~700 MB/day, so:

- comparisons are gated behind an explicit **Compare** button — nothing is
  fetched because you changed a colour scale;
- downloads stage through a scratch directory, so an interrupted transfer does
  not leave a short file under the name the cache looks for;
- a cached file whose size does not match is re-fetched rather than handed back;
- the cache is namespaced by source, because our output and PO.DAAC's share a
  filename by convention and would otherwise overwrite each other;
- `max_download_mb` refuses an oversized granule before any transfer starts.

Size and location are shown under **Data Sources**, with a button to clear it.

## Interface Guide

### Sidebar (Left)

- **Mode**: "View File" or "Compare Files"
- **Data Sources**: run source, reference source, the settings each one needs,
  a readiness line per source, and the download cache
- **Display Options**:
  - "Show file info": Toggle file statistics
  - Plot type: Matplotlib (fast) or Plotly (interactive zoom/pan)
- **Comparison settings** (Compare mode): tolerance, difference colour range
  and number of colour levels
- **Run selection**, which depends on the run source:
  - *local* — directory navigation and a file selector, as before
  - *maap* — a date range and a granule list; a STAC catalog has no tree to
    walk, only dates to ask about

### Main Panel (Right)

- **File Information**: Displays file metadata and statistics
  - Format type
  - Number of points/pixels
  - Statistical summaries (mean, median, std dev, etc.)
  - Spatial extent
- **Visualization**: Interactive matplotlib plots
  - Point data: Multiple panels showing SST, coverage, and auxiliary fields
  - Grid data: Mask and ice concentration maps
  - Histograms and statistical overlays

## Matplotlib in Streamlit

The web viewer uses Streamlit's excellent matplotlib integration:

- **Automatic Rendering**: `st.pyplot()` renders matplotlib figures directly in the browser
- **Non-Interactive Backend**: Uses `Agg` backend (optimized for web display)
- **Efficient Handling**: Figures are properly closed after rendering to prevent memory leaks
- **Full Feature Support**: All matplotlib features work including:
  - Custom colormaps
  - Multiple subplots
  - Shared axes
  - Colorbars and annotations
  - `mpl-scatter-density` for large datasets

### Performance Tips

For large datasets:

1. **mpl-scatter-density is supported**: Install it for optimal performance:
   ```bash
   pip install mpl-scatter-density
   ```

2. **Smart downsampling**: If `mpl-scatter-density` is not available, the app automatically downsamples to 100k points while preserving outliers

3. **Caching**: Streamlit's caching can be added to `read_file()` calls for faster repeated access

## Example Workflow: viewing a file

1. **Start the app**:
   ```bash
   export MUR_BASE_DIR=/nas4/mur/processing/2024/001
   mur-web-viewer
   ```

2. **Navigate** to your data directory using the sidebar

3. **Select a file type** filter (e.g., "Point data (.bip, .biq, .bii, .bic, .bin)")

4. **Choose a file** from the dropdown

5. **View** the file information and visualizations in the main panel

6. **Interact** with the plots:
   - Plots are static (PNG) but can be downloaded via right-click
   - Use the file selector to quickly compare different files
   - Toggle info/plots on/off for focused viewing

## Example Workflow: comparing a run against the public product

1. **Start the app** pointed at your output tree:
   ```bash
   export MUR_BASE_DIR=/data3/testing/output
   mur-web-viewer
   ```

2. **Switch to "Compare Files"** in the sidebar.

3. **Select a run** — the L4 granule you produced.

4. The **reference resolves itself**: the PO.DAAC granule for that same
   analysis date, named in the main panel. Nothing to browse to.

5. **Press Compare**. Both granules are materialized locally (the public one is
   downloaded once and cached, with a progress bar) and the full-resolution
   difference runs.

6. **Read the result**: per-field match/mismatch, a difference-tail table over
   every valid pixel, the worst pixel and its location, and the difference map.
   With Plotly selected, box-select on the map re-renders that region at full
   resolution.

To compare two of your own runs instead — a container run against a production
run of the same day — either set `reference_source` to `local`, or select the
other file and press **Set as Reference**.

## Troubleshooting

### Port Already in Use

If you see "Port 8501 is already in use":

```bash
# Use a different port
streamlit run dataviewer/web_viewer.py --server.port 8502
```

### Cannot Access Remote Server

Check firewall settings and ensure the port is open:

```bash
# On the server
sudo ufw allow 8501

# Test connectivity
curl http://your-server-ip:8501
```

### Memory Issues with Large Files

If processing very large files (>100M points):

1. Ensure `mpl-scatter-density` is installed
2. Increase system memory limits
3. Consider preprocessing data to smaller regions

### Import Errors

If you see import errors:

```bash
# Reinstall with all dependencies
cd /path/to/mur
pip install -e . --force-reinstall
```

## Architecture Notes

The web viewer reuses the core dataviewer modules:

- **`format_readers.py`**: File format detection and reading
- **`dataviewer.py`**: Statistics computation and downsampling utilities
- **`web_viewer.py`**: Streamlit interface and matplotlib figure generation

This ensures consistency between CLI and web interfaces while maintaining a clean separation of concerns.

## Security Considerations

1. **Path Traversal Protection**: The `is_safe_path()` function prevents users from accessing files outside the base directory

2. **Environment Variable Configuration**: Base directory is configured via environment variable, not user input

3. **Read-Only**: The interface only reads files, never writes

4. **Network Access**: By default, Streamlit only binds to localhost. Use caution when enabling remote access.

## Comparison: CLI vs Web Viewer

| Feature | CLI (`mur-viewer`) | Web (`mur-web-viewer`) |
|---------|-------------------|------------------------|
| File browsing | Manual path entry | Interactive navigation |
| Visualization | Desktop window (TkAgg/Qt) | Browser-based (static PNG) |
| Multi-file comparison | Multiple commands | Quick dropdown switching |
| Scripting | Excellent | Limited |
| Remote access | Requires X forwarding | Native web support |
| Batch processing | Excellent | Not designed for this |
| Interactivity | Full (zoom, pan) | View-only |

## Future Enhancements

Potential improvements:

- [ ] Add Plotly for interactive web plots (zoom, pan, hover)
- [ ] File comparison mode (side-by-side)
- [ ] Export visualizations (PNG, SVG, PDF)
- [ ] Caching for faster repeated file access
- [ ] Thumbnail previews in file browser
- [ ] Multi-file animation/time series
- [ ] Custom color scale controls
- [ ] Spatial subsetting interface

## License

Same as MUR processing codebase.
