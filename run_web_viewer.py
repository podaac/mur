#!/usr/bin/env python3
"""
CLI wrapper to launch the MUR web viewer using Streamlit.

This script is the entry point for the `mur-web-viewer` command.
It simply runs: streamlit run dataviewer/web_viewer.py
"""

import sys
import os
import subprocess
from pathlib import Path


def main():
    """Launch Streamlit with the web viewer."""
    # Get the mur directory
    mur_dir = Path(__file__).parent.resolve()
    web_viewer_path = mur_dir / 'dataviewer' / 'web_viewer.py'

    if not web_viewer_path.exists():
        print(f"Error: Could not find web_viewer.py at {web_viewer_path}")
        sys.exit(1)

    # Set default base directory to ./testing if not already set
    if 'MUR_BASE_DIR' not in os.environ:
        default_base = mur_dir / 'testing'
        os.environ['MUR_BASE_DIR'] = str(default_base)
        print(f"Using default base directory: {default_base}")

    # Build the streamlit command
    cmd = ['streamlit', 'run', str(web_viewer_path)]

    # Add any additional arguments passed to this script
    if len(sys.argv) > 1:
        cmd.append('--')
        cmd.extend(sys.argv[1:])

    # Change to mur directory so relative imports work
    os.chdir(mur_dir)

    # Execute streamlit
    try:
        sys.exit(subprocess.call(cmd))
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        sys.exit(0)
    except FileNotFoundError:
        print("Error: streamlit command not found. Install with: pip install streamlit")
        sys.exit(1)


if __name__ == '__main__':
    main()
