# Installation Guide - MUR Web Viewer

## Quick Start

### 1. Install the package with web viewer support

From the `mur/` directory:

```bash
cd /Users/jleach/Documents/Development/MUR/mur
pip install -e .
```

This installs:
- Core dependencies (numpy, matplotlib, etc.)
- Streamlit for the web interface
- All dataviewer components

### 2. Verify installation

```bash
# Check that the command is available
which mur-web-viewer

# Test the import
python -c "import streamlit; print('Streamlit version:', streamlit.__version__)"
```

### 3. Run the web viewer

```bash
# Set your data directory (optional)
export MUR_BASE_DIR=/path/to/your/data

# Launch the web viewer
mur-web-viewer
```

The app will open automatically in your browser at `http://localhost:8501`.

## Detailed Installation

### Prerequisites

- Python 3.10 or higher
- pip package manager

### Optional Dependencies

For enhanced functionality:

```bash
# For coastline overlays (recommended)
pip install cartopy

# For optimal large dataset rendering (highly recommended)
pip install mpl-scatter-density
```

### Installing Streamlit Only

If you already have the core dataviewer installed and just want to add the web interface:

```bash
pip install streamlit>=1.28.0
```

### Development Installation

For development, install with dev dependencies:

```bash
cd /Users/jleach/Documents/Development/MUR/mur
pip install -e ".[dev]"
```

## Testing the Installation

### Test 1: Import Check

```bash
python << 'EOF'
import streamlit
from dataviewer import web_viewer
from dataviewer.format_readers import DataFileReader
print("✅ All imports successful")
print(f"   Streamlit version: {streamlit.__version__}")
EOF
```

### Test 2: Run with Sample Data

If you have sample MUR data:

```bash
export MUR_BASE_DIR=/path/to/sample/data
mur-web-viewer
```

### Test 3: Check Entry Point

```bash
# Verify the script was installed
pip show -f mur-processing | grep mur-web-viewer
```

## Troubleshooting

### Issue: "Module not found: streamlit"

**Solution**: Install streamlit explicitly:
```bash
pip install streamlit
```

### Issue: "Command not found: mur-web-viewer"

**Solution**: Reinstall the package:
```bash
cd /Users/jleach/Documents/Development/MUR/mur
pip install -e . --force-reinstall
```

Then verify:
```bash
which mur-web-viewer
```

### Issue: "Port 8501 already in use"

**Solution**: Either:
1. Stop the existing Streamlit process
2. Use a different port:
   ```bash
   streamlit run dataviewer/web_viewer.py --server.port 8502
   ```

### Issue: matplotlib backend errors

**Solution**: The web viewer uses the `Agg` backend automatically. If you see errors:

```bash
export MPLBACKEND=Agg
mur-web-viewer
```

### Issue: Permission denied accessing files

**Solution**: Ensure the base directory is readable:

```bash
# Check permissions
ls -la $MUR_BASE_DIR

# If needed, update permissions
chmod -R +r /path/to/data
```

## Docker Installation (Alternative)

If you prefer to run in a container:

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
RUN pip install -e .

# Copy dataviewer code
COPY dataviewer/ dataviewer/

# Expose Streamlit port
EXPOSE 8501

# Set environment variable for data location
ENV MUR_BASE_DIR=/data

# Run the web viewer
CMD ["streamlit", "run", "dataviewer/web_viewer.py", \
     "--server.address", "0.0.0.0", \
     "--server.port", "8501"]
```

Build and run:

```bash
docker build -t mur-web-viewer .
docker run -p 8501:8501 -v /path/to/data:/data mur-web-viewer
```

## Verification Checklist

After installation, verify:

- [ ] `pip list | grep mur-processing` shows the package
- [ ] `pip list | grep streamlit` shows streamlit>=1.28.0
- [ ] `which mur-web-viewer` returns a path
- [ ] `mur-web-viewer --help` works (Note: Streamlit will ignore --help, but the command should be recognized)
- [ ] Opening http://localhost:8501 shows the web interface

## Next Steps

Once installed, see:
- [WEB_VIEWER_README.md](WEB_VIEWER_README.md) - Usage guide
- [ARCHITECTURE.md](ARCHITECTURE.md) - Technical details
- [../README.md](../README.md) - General MUR documentation
