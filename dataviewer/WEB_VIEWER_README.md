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

## Interface Guide

### Sidebar (Left)

- **Base Directory**: Shows the configured base directory
- **Current Directory**: Displays the current browsing location
- **Navigation**:
  - "⬆️ Parent Directory" button to go up one level
  - Click folder names to navigate into subdirectories
- **File Filter**: Dropdown to filter by file type
- **File Selector**: Dropdown to select a specific file
- **Display Options**:
  - "Show file info": Toggle file statistics
  - "Show visualization": Toggle plots

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

## Example Workflow

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
