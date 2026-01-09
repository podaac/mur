#!/usr/bin/env python3
"""
MUR Data Viewer - Web Interface using Streamlit

A web-based interface for browsing and visualizing MUR SST processing data files.
Provides file browsing restricted to a base directory and interactive visualization
using matplotlib with Streamlit.

Usage:
    streamlit run web_viewer.py
    # or
    mur-web-viewer
"""

import streamlit as st
from pathlib import Path
import os
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm, LinearSegmentedColormap
from typing import Optional, List, Tuple

# Import from existing dataviewer modules
# Handle both relative imports (when imported as module) and absolute imports (when run by streamlit)
try:
    from .format_readers import read_file, DataFileReader
    from .dataviewer import compute_robust_stats, smart_downsample
except ImportError:
    # Running as standalone script via streamlit
    from format_readers import read_file, DataFileReader
    from dataviewer import compute_robust_stats, smart_downsample

# Configure matplotlib to use non-interactive backend for Streamlit
matplotlib.use('Agg')

# Page configuration
st.set_page_config(
    page_title="MUR Data Viewer",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded"
)


def get_base_directory() -> Path:
    """
    Get the base directory for file browsing.
    Can be set via environment variable BASE_DIR or defaults to current directory.
    """
    base_dir = os.environ.get('MUR_BASE_DIR', os.getcwd())
    return Path(base_dir).resolve()


def list_files_in_directory(directory: Path, pattern: str = "*") -> List[Path]:
    """
    List all files in the directory matching the pattern.

    Args:
        directory: Directory to search
        pattern: Glob pattern for files

    Returns:
        List of file paths
    """
    if not directory.exists() or not directory.is_dir():
        return []

    # Get all files matching pattern
    files = []
    try:
        for item in directory.glob(pattern):
            if item.is_file():
                files.append(item)
    except PermissionError:
        pass

    return sorted(files)


def list_subdirectories(directory: Path) -> List[Path]:
    """
    List all subdirectories in the given directory.

    Args:
        directory: Directory to search

    Returns:
        List of subdirectory paths
    """
    if not directory.exists() or not directory.is_dir():
        return []

    dirs = []
    try:
        for item in directory.iterdir():
            if item.is_dir():
                dirs.append(item)
    except PermissionError:
        pass

    return sorted(dirs)


def is_safe_path(base_dir: Path, requested_path: Path) -> bool:
    """
    Check if the requested path is within the base directory (prevent path traversal).

    Args:
        base_dir: Base directory (safe root)
        requested_path: Requested path to check

    Returns:
        True if path is safe, False otherwise
    """
    try:
        base_dir = base_dir.resolve()
        requested_path = requested_path.resolve()
        return str(requested_path).startswith(str(base_dir))
    except Exception:
        return False


def add_coastlines_to_ax(ax):
    """
    Add simple coastlines to a plot using Natural Earth data if available.

    Args:
        ax: Matplotlib axes object
    """
    try:
        import cartopy.io.shapereader as shpreader

        coastlines = shpreader.natural_earth(resolution='110m',
                                              category='physical',
                                              name='coastline')

        reader = shpreader.Reader(coastlines)
        for geometry in reader.geometries():
            if geometry.geom_type == 'LineString':
                coords = list(geometry.coords)
                lons = [c[0] for c in coords]
                lats = [c[1] for c in coords]
                ax.plot(lons, lats, 'k-', linewidth=0.5, alpha=0.5, zorder=10)
            elif geometry.geom_type == 'MultiLineString':
                for line in geometry.geoms:
                    coords = list(line.coords)
                    lons = [c[0] for c in coords]
                    lats = [c[1] for c in coords]
                    ax.plot(lons, lats, 'k-', linewidth=0.5, alpha=0.5, zorder=10)
    except (ImportError, Exception):
        pass


def create_point_data_plot(data: dict, format_type: str, filepath: Path,
                          use_density: bool = False) -> plt.Figure:
    """
    Create matplotlib figure for point data (bip, biq, bii, bic, bin).

    Args:
        data: Data dictionary from format reader
        format_type: File format type
        filepath: Path to file
        use_density: Whether to use density plotting

    Returns:
        Matplotlib figure object
    """
    num_points = data.get('N', len(data['sst']))

    # Check for empty data
    if num_points == 0:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, 'No data points in file',
                ha='center', va='center', fontsize=16)
        ax.axis('off')
        return fig

    # Filter invalid coordinates
    valid_mask = (
        (data['lon'] >= -180) & (data['lon'] <= 180) &
        (data['lat'] >= -90) & (data['lat'] <= 90)
    )
    num_invalid = np.sum(~valid_mask)

    if num_invalid > 0:
        data['lon'] = data['lon'][valid_mask]
        data['lat'] = data['lat'][valid_mask]
        data['sst'] = data['sst'][valid_mask]
        if 'hour' in data:
            data['hour'] = data['hour'][valid_mask]
        if 'weight' in data:
            data['weight'] = data['weight'][valid_mask]
        if 'bias' in data:
            data['bias'] = data['bias'][valid_mask]
        if 'rms' in data:
            data['rms'] = data['rms'][valid_mask]
        if 'platform_type' in data:
            data['platform_type'] = data['platform_type'][valid_mask]
        num_points = len(data['lon'])
        data['N'] = num_points

    # Determine rendering strategy
    DENSITY_THRESHOLD = 100000
    use_downsampling = False

    if num_points > DENSITY_THRESHOLD and not use_density:
        try:
            import mpl_scatter_density
            use_density = True
        except ImportError:
            use_downsampling = True

    # Prepare data
    if use_downsampling:
        lon_plot, lat_plot, sst_plot = smart_downsample(
            data['lon'], data['lat'], data['sst'], max_points=100000
        )
        if 'weight' in data:
            _, _, weight_plot = smart_downsample(
                data['lon'], data['lat'], data['weight'], max_points=100000
            )
        else:
            weight_plot = None
        if 'rms' in data:
            _, _, rms_plot = smart_downsample(
                data['lon'], data['lat'], data['rms'], max_points=100000
            )
        else:
            rms_plot = None
        if 'platform_type' in data:
            _, _, platform_plot = smart_downsample(
                data['lon'], data['lat'], data['platform_type'], max_points=100000
            )
        else:
            platform_plot = None
    else:
        lon_plot, lat_plot, sst_plot = data['lon'], data['lat'], data['sst']
        weight_plot = data.get('weight')
        rms_plot = data.get('rms')
        platform_plot = data.get('platform_type')

    # Compute robust colorbar limits
    robust_stats = compute_robust_stats(data['sst'])
    vmin_sst = robust_stats['median'] - 3 * robust_stats['robust_std']
    vmax_sst = robust_stats['median'] + 3 * robust_stats['robust_std']

    # Check if cartopy is available
    try:
        import cartopy.crs as ccrs
        has_cartopy = True
    except ImportError:
        has_cartopy = False

    # Create figure based on format
    if format_type == 'bii':
        # BII-specific layout: SST map, platform map, histogram
        if use_density:
            from matplotlib.colors import LinearSegmentedColormap
            white_viridis = LinearSegmentedColormap.from_list(
                'white_viridis', [
                    (0, '#ffffff'),
                    (1e-20, '#440053'),
                    (0.2, '#404388'),
                    (0.4, '#2a788e'),
                    (0.6, '#22a784'),
                    (0.8, '#7ad151'),
                    (1, '#fde725'),
                ], N=256)

            fig = plt.figure(figsize=(16, 10))
            ax1 = fig.add_subplot(2, 2, 1, projection='scatter_density')
            ax2 = fig.add_subplot(2, 2, 2)
            ax3 = fig.add_subplot(2, 1, 2)

            # SST density plot
            density1 = ax1.scatter_density(lon_plot, lat_plot, c=sst_plot,
                                          cmap='RdYlBu_r', dpi=72,
                                          vmin=vmin_sst, vmax=vmax_sst)
            ax1.set_xlabel('Longitude')
            ax1.set_ylabel('Latitude')
            ax1.set_title('SST Distribution (Mean)')
            ax1.set_aspect('equal', adjustable='box')
            ax1.grid(True, alpha=0.3)
            if has_cartopy:
                add_coastlines_to_ax(ax1)
            plt.colorbar(density1, ax=ax1, label='SST (°C)')

            # Platform type - convert to regular scatter
            platform_names = {
                0: 'Unknown', 1: 'Merchant Ship', 2: 'OSV (off station)',
                3: 'OSV (on station)', 4: 'Lightship', 5: 'Ship',
                6: 'Moored Buoy', 7: 'Drifting Buoy', 8: 'Ice Buoy',
                9: 'Ice Station', 10: 'Oceanographic', 11: 'MBT',
                12: 'XBT', 13: 'C-MAN'
            }
            if platform_plot is not None:
                unique_types = sorted(set(platform_plot.astype(int)))
                n_types = len(unique_types)
                tab10 = plt.colormaps.get_cmap('tab10')
                colors = [tab10(i % 10) for i in range(n_types)]
                cmap = ListedColormap(colors)
                bounds = [unique_types[0] - 0.5] + [t + 0.5 for t in unique_types]
                norm = BoundaryNorm(bounds, cmap.N)

                sc_platform = ax2.scatter(lon_plot, lat_plot, c=platform_plot,
                                         s=1, cmap=cmap, norm=norm, alpha=0.6)
                ax2.set_xlabel('Longitude')
                ax2.set_ylabel('Latitude')
                ax2.set_title('Platform Type Distribution')
                ax2.set_aspect('equal', adjustable='box')
                ax2.grid(True, alpha=0.3)
                if has_cartopy:
                    add_coastlines_to_ax(ax2)
                cbar = plt.colorbar(sc_platform, ax=ax2, label='Platform Type',
                                   ticks=unique_types)
                cbar.set_ticklabels([platform_names.get(t, f'Type {t}')
                                    for t in unique_types])
            else:
                ax2.axis('off')
        else:
            fig = plt.figure(figsize=(16, 10))
            ax1 = fig.add_subplot(2, 2, 1)
            ax2 = fig.add_subplot(2, 2, 2)
            ax3 = fig.add_subplot(2, 1, 2)

            # SST scatter
            sc1 = ax1.scatter(lon_plot, lat_plot, c=sst_plot, s=1,
                             cmap='RdYlBu_r', alpha=0.6,
                             vmin=vmin_sst, vmax=vmax_sst)
            ax1.set_xlabel('Longitude')
            ax1.set_ylabel('Latitude')
            ax1.set_title('SST Distribution')
            ax1.set_aspect('equal', adjustable='box')
            ax1.grid(True, alpha=0.3)
            if has_cartopy:
                add_coastlines_to_ax(ax1)
            plt.colorbar(sc1, ax=ax1, label='SST (°C)')

            # Platform type
            platform_names = {
                0: 'Unknown', 1: 'Merchant Ship', 2: 'OSV (off station)',
                3: 'OSV (on station)', 4: 'Lightship', 5: 'Ship',
                6: 'Moored Buoy', 7: 'Drifting Buoy', 8: 'Ice Buoy',
                9: 'Ice Station', 10: 'Oceanographic', 11: 'MBT',
                12: 'XBT', 13: 'C-MAN'
            }
            if platform_plot is not None:
                unique_types = sorted(set(platform_plot.astype(int)))
                n_types = len(unique_types)
                tab10 = plt.colormaps.get_cmap('tab10')
                colors = [tab10(i % 10) for i in range(n_types)]
                cmap = ListedColormap(colors)
                bounds = [unique_types[0] - 0.5] + [t + 0.5 for t in unique_types]
                norm = BoundaryNorm(bounds, cmap.N)

                sc2 = ax2.scatter(lon_plot, lat_plot, c=platform_plot, s=1,
                                 cmap=cmap, norm=norm, alpha=0.6)
                ax2.set_xlabel('Longitude')
                ax2.set_ylabel('Latitude')
                ax2.set_title('Platform Type Distribution')
                ax2.set_aspect('equal', adjustable='box')
                ax2.grid(True, alpha=0.3)
                if has_cartopy:
                    add_coastlines_to_ax(ax2)
                cbar = plt.colorbar(sc2, ax=ax2, label='Platform Type',
                                   ticks=unique_types)
                cbar.set_ticklabels([platform_names.get(t, f'Type {t}')
                                    for t in unique_types])
            else:
                ax2.axis('off')

        # Histogram (same for both)
        ax3.hist(data['sst'], bins=100, edgecolor='black', alpha=0.7)
        ax3.set_xlabel('SST (°C)')
        ax3.set_ylabel('Count (log scale)')
        ax3.set_title('SST Histogram')
        ax3.set_yscale('log')
        ax3.grid(True, alpha=0.3)

    else:
        # Standard 4-panel layout
        if use_density:
            from matplotlib.colors import LinearSegmentedColormap
            white_viridis = LinearSegmentedColormap.from_list(
                'white_viridis', [
                    (0, '#ffffff'),
                    (1e-20, '#440053'),
                    (0.2, '#404388'),
                    (0.4, '#2a788e'),
                    (0.6, '#22a784'),
                    (0.8, '#7ad151'),
                    (1, '#fde725'),
                ], N=256)

            fig = plt.figure(figsize=(15, 12))
            ax1 = fig.add_subplot(2, 2, 1, projection='scatter_density')
            ax2 = fig.add_subplot(2, 2, 2)
            ax3 = fig.add_subplot(2, 2, 3, projection='scatter_density',
                                 sharex=ax1, sharey=ax1)
            ax4 = fig.add_subplot(2, 2, 4, projection='scatter_density',
                                 sharex=ax1, sharey=ax1)

            # SST aggregated
            density1 = ax1.scatter_density(lon_plot, lat_plot, c=sst_plot,
                                          cmap='RdYlBu_r', dpi=72,
                                          vmin=vmin_sst, vmax=vmax_sst)
            ax1.set_xlabel('Longitude')
            ax1.set_ylabel('Latitude')
            ax1.set_title('SST Distribution (Mean)')
            ax1.set_aspect('equal', adjustable='box')
            ax1.grid(True, alpha=0.3)
            if has_cartopy:
                add_coastlines_to_ax(ax1)
            plt.colorbar(density1, ax=ax1, label='SST (°C)')

            # Coverage density
            density2 = ax3.scatter_density(lon_plot, lat_plot,
                                          cmap=white_viridis, dpi=72)
            ax3.set_xlabel('Longitude')
            ax3.set_ylabel('Latitude')
            ax3.set_title('Geographic Coverage (Density)')
            ax3.set_aspect('equal', adjustable='box')
            ax3.grid(True, alpha=0.3)
            if has_cartopy:
                add_coastlines_to_ax(ax3)
            plt.colorbar(density2, ax=ax3, label='Point Density')

            # Additional field
            if format_type in ['bip', 'biq'] and weight_plot is not None:
                density3 = ax4.scatter_density(lon_plot, lat_plot, c=weight_plot,
                                              cmap='viridis', dpi=72)
                ax4.set_xlabel('Longitude')
                ax4.set_ylabel('Latitude')
                ax4.set_title('Weight Distribution (Mean)')
                ax4.set_aspect('equal', adjustable='box')
                ax4.grid(True, alpha=0.3)
                if has_cartopy:
                    add_coastlines_to_ax(ax4)
                plt.colorbar(density3, ax=ax4, label='Weight')
            elif format_type in ['bic', 'bin'] and rms_plot is not None:
                density3 = ax4.scatter_density(lon_plot, lat_plot, c=rms_plot,
                                              cmap='hot_r', dpi=72)
                ax4.set_xlabel('Longitude')
                ax4.set_ylabel('Latitude')
                ax4.set_title('RMS Error Distribution (Mean)')
                ax4.set_aspect('equal', adjustable='box')
                ax4.grid(True, alpha=0.3)
                if has_cartopy:
                    add_coastlines_to_ax(ax4)
                plt.colorbar(density3, ax=ax4, label='RMS (°C)')
            else:
                ax4.axis('off')
        else:
            fig = plt.figure(figsize=(15, 12))
            ax1 = fig.add_subplot(2, 2, 1)
            ax2 = fig.add_subplot(2, 2, 2)
            ax3 = fig.add_subplot(2, 2, 3, sharex=ax1, sharey=ax1)
            ax4 = fig.add_subplot(2, 2, 4, sharex=ax1, sharey=ax1)

            # SST scatter
            sc1 = ax1.scatter(lon_plot, lat_plot, c=sst_plot, s=1,
                             cmap='RdYlBu_r', alpha=0.6,
                             vmin=vmin_sst, vmax=vmax_sst)
            ax1.set_xlabel('Longitude')
            ax1.set_ylabel('Latitude')
            ax1.set_title('SST Distribution')
            ax1.set_aspect('equal', adjustable='box')
            ax1.grid(True, alpha=0.3)
            if has_cartopy:
                add_coastlines_to_ax(ax1)
            plt.colorbar(sc1, ax=ax1, label='SST (°C)')

            # Coverage
            ax3.scatter(lon_plot, lat_plot, s=1, alpha=0.3)
            ax3.set_xlabel('Longitude')
            ax3.set_ylabel('Latitude')
            ax3.set_title('Geographic Coverage')
            ax3.set_aspect('equal', adjustable='box')
            ax3.grid(True, alpha=0.3)
            if has_cartopy:
                add_coastlines_to_ax(ax3)

            # Additional field
            if format_type in ['bip', 'biq'] and weight_plot is not None:
                sc3 = ax4.scatter(lon_plot, lat_plot, c=weight_plot, s=1,
                                 cmap='viridis', alpha=0.6)
                ax4.set_xlabel('Longitude')
                ax4.set_ylabel('Latitude')
                ax4.set_title('Weight Distribution')
                ax4.set_aspect('equal', adjustable='box')
                ax4.grid(True, alpha=0.3)
                if has_cartopy:
                    add_coastlines_to_ax(ax4)
                plt.colorbar(sc3, ax=ax4, label='Weight')
            elif format_type in ['bic', 'bin'] and rms_plot is not None:
                sc3 = ax4.scatter(lon_plot, lat_plot, c=rms_plot, s=1,
                                 cmap='hot_r', alpha=0.6)
                ax4.set_xlabel('Longitude')
                ax4.set_ylabel('Latitude')
                ax4.set_title('RMS Error Distribution')
                ax4.set_aspect('equal', adjustable='box')
                ax4.grid(True, alpha=0.3)
                if has_cartopy:
                    add_coastlines_to_ax(ax4)
                plt.colorbar(sc3, ax=ax4, label='RMS (°C)')
            else:
                ax4.axis('off')

        # Histogram
        ax2.hist(data['sst'], bins=100, edgecolor='black', alpha=0.7)
        ax2.set_xlabel('SST (°C)')
        ax2.set_ylabel('Count (log scale)')
        ax2.set_title('SST Histogram')
        ax2.set_yscale('log')
        ax2.grid(True, alpha=0.3)

    plt.suptitle(f'{filepath.name}\n{format_type.upper()}: {num_points:,} observations')
    plt.tight_layout()

    return fig


def create_grid_data_plot(data: dict, format_type: str, filepath: Path) -> plt.Figure:
    """
    Create matplotlib figure for grid data (gds, map).

    Args:
        data: Data dictionary from format reader
        format_type: File format type
        filepath: Path to file

    Returns:
        Matplotlib figure object
    """
    if format_type == 'gds':
        ii, jj = data['dimensions']

        # Check if cartopy is available
        try:
            import cartopy.crs as ccrs
            has_cartopy = True
        except ImportError:
            has_cartopy = False

        fig, axes = plt.subplots(1, 2, figsize=(15, 6), sharex=True, sharey=True)

        # Mask
        mask_labels = {
            1: 'Open sea', 2: 'Land', 3: 'Coast',
            5: 'Open lake', 7: 'Lake shore',
            9: 'Sea + ice', 11: 'Coast + ice',
            13: 'Lake + ice', 15: 'Complex shore'
        }

        unique_vals = sorted(np.unique(data['mask']))
        n_colors = len(unique_vals)
        tab10 = plt.colormaps.get_cmap('tab10')
        colors = [tab10(i / 10) for i in range(n_colors)]
        cmap = ListedColormap(colors)

        bounds = [unique_vals[0] - 0.5]
        for i in range(len(unique_vals) - 1):
            bounds.append((unique_vals[i] + unique_vals[i+1]) / 2)
        bounds.append(unique_vals[-1] + 0.5)
        norm = BoundaryNorm(bounds, cmap.N)

        im1 = axes[0].imshow(data['mask'].T, cmap=cmap, norm=norm,
                            aspect='equal', origin='lower', interpolation='none')
        axes[0].set_xlabel('Longitude Index')
        axes[0].set_ylabel('Latitude Index')
        axes[0].set_title('Land/Ice Mask')

        cbar1 = plt.colorbar(im1, ax=axes[0], label='Mask Value',
                            ticks=unique_vals)
        cbar1.set_ticklabels([mask_labels.get(v, str(v)) for v in unique_vals])

        # Ice concentration
        im2 = axes[1].imshow(data['icemap'].T, cmap='Blues',
                            vmin=-1, vmax=100,
                            aspect='equal', origin='lower', interpolation='none')
        axes[1].set_xlabel('Longitude Index')
        axes[1].set_ylabel('Latitude Index')
        axes[1].set_title('Ice Concentration (%)')
        plt.colorbar(im2, ax=axes[1], label='Ice %')

        plt.suptitle(f'{filepath.name}\n{format_type.upper()}: {ii}×{jj} grid')
        plt.tight_layout()

    elif format_type == 'map':
        nlon, nlat = data['dimensions']

        sst_valid = data['sst'][~np.isnan(data['sst'])]
        if len(sst_valid) == 0:
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.text(0.5, 0.5, 'No valid SST data',
                   ha='center', va='center', fontsize=16)
            ax.axis('off')
            return fig

        # Check if cartopy is available
        try:
            import cartopy.crs as ccrs
            has_cartopy = True
        except ImportError:
            has_cartopy = False

        fig, axes = plt.subplots(1, 2, figsize=(16, 6))

        # SST map
        im1 = axes[0].imshow(data['sst'].T, cmap='RdYlBu_r',
                            aspect='auto', origin='lower',
                            interpolation='nearest',
                            extent=[data['lon'].min(), data['lon'].max(),
                                   data['lat'].min(), data['lat'].max()])
        axes[0].set_xlabel('Longitude (degrees)')
        axes[0].set_ylabel('Latitude (degrees)')
        axes[0].set_title('SST Map (°C)')
        axes[0].grid(True, alpha=0.3)
        if has_cartopy:
            add_coastlines_to_ax(axes[0])
        plt.colorbar(im1, ax=axes[0], label='SST (°C)', shrink=0.8)

        # Histogram
        axes[1].hist(sst_valid.flatten(), bins=100, edgecolor='black', alpha=0.7)
        axes[1].set_xlabel('SST (°C)')
        axes[1].set_ylabel('Count')
        axes[1].set_title('SST Distribution')
        axes[1].grid(True, alpha=0.3)

        # Statistics
        stats_text = (
            f"Valid pixels: {len(sst_valid):,}\n"
            f"Mean: {sst_valid.mean():.2f} °C\n"
            f"Std: {sst_valid.std():.2f} °C\n"
            f"Min: {sst_valid.min():.2f} °C\n"
            f"Max: {sst_valid.max():.2f} °C"
        )
        axes[1].text(0.98, 0.98, stats_text,
                    transform=axes[1].transAxes,
                    verticalalignment='top',
                    horizontalalignment='right',
                    bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
                    fontsize=9, family='monospace')

        plt.suptitle(f'{filepath.name}\nMAP: {nlon}×{nlat} grid')
        plt.tight_layout()

    return fig


def create_coefficient_plot(data: dict, format_type: str, filepath: Path) -> plt.Figure:
    """
    Create matplotlib figure for coefficient data (csp, usp).

    Args:
        data: Data dictionary from format reader
        format_type: File format type
        filepath: Path to file

    Returns:
        Matplotlib figure object
    """
    coef = data['coefficients']
    scale = data.get('scale', 'unknown')

    # Take a slice through the middle for 4D arrays
    if coef.ndim == 4:
        slice_z = coef.shape[2] // 2
        slice_v = 0
        coef_slice = coef[:, :, slice_z, slice_v]
        slice_info = f"z={slice_z}, v={slice_v}"
    else:
        coef_slice = coef[:, :]
        slice_info = "2D"

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # 2D coefficient slice
    # Center colormap around zero for diverging visualization
    vmax = max(abs(coef_slice.min()), abs(coef_slice.max()))
    im1 = axes[0].imshow(coef_slice.T, cmap='RdBu_r',
                         aspect='equal', origin='lower',
                         vmin=-vmax, vmax=vmax)
    axes[0].set_xlabel('X index')
    axes[0].set_ylabel('Y index')
    axes[0].set_title(f'Coefficient Slice ({slice_info})')
    plt.colorbar(im1, ax=axes[0], label='Coefficient Value')

    # Histogram of all coefficients
    axes[1].hist(coef.flatten(), bins=100, edgecolor='black', alpha=0.7)
    axes[1].set_xlabel('Coefficient Value')
    axes[1].set_ylabel('Count')
    axes[1].set_title('Coefficient Distribution')
    axes[1].grid(True, alpha=0.3)
    axes[1].set_yscale('log')

    # Add vertical line at zero
    axes[1].axvline(x=0, color='r', linestyle='--', alpha=0.5, label='Zero')
    axes[1].legend()

    # Statistics text box
    stats_text = (
        f"Total: {coef.size:,}\n"
        f"Mean: {coef.mean():.4f}\n"
        f"Std: {coef.std():.4f}\n"
        f"Min: {coef.min():.4f}\n"
        f"Max: {coef.max():.4f}"
    )
    axes[1].text(0.98, 0.98, stats_text,
                 transform=axes[1].transAxes,
                 verticalalignment='top',
                 horizontalalignment='right',
                 bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
                 fontsize=9, family='monospace')

    type_label = "Coefficient" if format_type == 'csp' else "Uncertainty"
    plt.suptitle(f'{filepath.name}\n{type_label} File (L={scale}): {coef.shape}')
    plt.tight_layout()

    return fig


def create_interactive_point_plot(data: dict, format_type: str, filepath: Path):
    """
    Create interactive Plotly figure for point data with dynamic data loading.

    Uses Plotly's scattergl for hardware-accelerated rendering of large datasets.
    For very large datasets, uses density binning approach similar to mpl-scatter-density
    to show ALL data as aggregated values rather than downsampling.

    Args:
        data: Data dictionary from format reader
        format_type: File format type
        filepath: Path to file

    Returns:
        Plotly figure object
    """
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        raise ImportError("Plotly not installed. Install with: pip install plotly")

    num_points = data.get('N', len(data['sst']))

    if num_points == 0:
        # Empty figure with message
        fig = go.Figure()
        fig.add_annotation(
            text="No data points in file",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=20)
        )
        return fig

    # Filter invalid coordinates
    valid_mask = (
        (data['lon'] >= -180) & (data['lon'] <= 180) &
        (data['lat'] >= -90) & (data['lat'] <= 90)
    )
    num_invalid = np.sum(~valid_mask)

    if num_invalid > 0:
        data['lon'] = data['lon'][valid_mask]
        data['lat'] = data['lat'][valid_mask]
        data['sst'] = data['sst'][valid_mask]
        if 'weight' in data:
            data['weight'] = data['weight'][valid_mask]
        if 'platform_type' in data:
            data['platform_type'] = data['platform_type'][valid_mask]
        num_points = len(data['lon'])

    # Strategy: Use density binning for large datasets to show ALL data
    # This is similar to mpl-scatter-density but interactive
    USE_DENSITY_BINNING = num_points > 100000

    if USE_DENSITY_BINNING:
        # Create 2D histogram bins for aggregation
        # Use ~500x500 bins for good resolution and interactivity
        nbins = 400  # Adjustable based on data extent

        # Compute 2D histogram with mean SST values
        lon_bins = np.linspace(data['lon'].min(), data['lon'].max(), nbins)
        lat_bins = np.linspace(data['lat'].min(), data['lat'].max(), nbins)

        # Use numpy's 2D histogram with weights to get mean values
        sst_sum, _, _ = np.histogram2d(data['lon'], data['lat'],
                                        bins=[lon_bins, lat_bins],
                                        weights=data['sst'])
        counts, _, _ = np.histogram2d(data['lon'], data['lat'],
                                       bins=[lon_bins, lat_bins])

        # Compute mean SST per bin (avoid divide by zero)
        with np.errstate(divide='ignore', invalid='ignore'):
            sst_mean = sst_sum / counts
            sst_mean[counts == 0] = np.nan

        # Prepare grid coordinates for heatmap
        lon_centers = (lon_bins[:-1] + lon_bins[1:]) / 2
        lat_centers = (lat_bins[:-1] + lat_bins[1:]) / 2

        use_binning = True
        downsampled = False
    else:
        # For smaller datasets, use scatter plot
        lon_plot = data['lon']
        lat_plot = data['lat']
        sst_plot = data['sst']
        weight_plot = data.get('weight')
        platform_plot = data.get('platform_type')
        use_binning = False
        downsampled = False

    # Compute robust colorbar limits
    robust_stats = compute_robust_stats(data['sst'])
    vmin_sst = robust_stats['median'] - 3 * robust_stats['robust_std']
    vmax_sst = robust_stats['median'] + 3 * robust_stats['robust_std']

    # Create subplots based on whether we're using binning or scatter
    if use_binning:
        # Use heatmap for binned data - shows ALL data as mean values
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=('SST Distribution (Mean per bin)', 'SST Histogram',
                           'Point Density', 'Coverage Map'),
            specs=[[{'type': 'heatmap'}, {'type': 'histogram'}],
                   [{'type': 'heatmap'}, {'type': 'heatmap'}]],
            vertical_spacing=0.12,
            horizontal_spacing=0.10
        )

        # SST heatmap (mean values)
        fig.add_trace(
            go.Heatmap(
                x=lon_centers,
                y=lat_centers,
                z=sst_mean.T,
                colorscale='RdYlBu_r',
                zmin=vmin_sst,
                zmax=vmax_sst,
                colorbar=dict(title="SST (°C)", x=0.46, y=0.75, len=0.4),
                hovertemplate='Lon: %{x:.2f}<br>Lat: %{y:.2f}<br>Mean SST: %{z:.2f}°C<extra></extra>'
            ),
            row=1, col=1
        )

        # Histogram (still uses all original points)
        fig.add_trace(
            go.Histogram(
                x=data['sst'],
                nbinsx=100,
                name='SST Distribution',
                marker=dict(color='steelblue')
            ),
            row=1, col=2
        )

        # Density map (count of points per bin)
        fig.add_trace(
            go.Heatmap(
                x=lon_centers,
                y=lat_centers,
                z=counts.T,
                colorscale='Viridis',
                colorbar=dict(title="Point Count", x=1.0, y=0.75, len=0.4),
                hovertemplate='Lon: %{x:.2f}<br>Lat: %{y:.2f}<br>Points: %{z}<extra></extra>'
            ),
            row=2, col=1
        )

        # Coverage indicator (binary: has data / no data)
        coverage = (counts > 0).astype(float)
        coverage[coverage == 0] = np.nan
        fig.add_trace(
            go.Heatmap(
                x=lon_centers,
                y=lat_centers,
                z=coverage.T,
                colorscale=[[0, 'rgba(200,200,200,0.1)'], [1, 'rgba(100,150,200,0.8)']],
                showscale=False,
                hovertemplate='Lon: %{x:.2f}<br>Lat: %{y:.2f}<br>Coverage<extra></extra>'
            ),
            row=2, col=2
        )

        # Update axes labels
        fig.update_xaxes(title_text="Longitude", row=1, col=1)
        fig.update_yaxes(title_text="Latitude", row=1, col=1)
        fig.update_xaxes(title_text="Longitude", row=2, col=1)
        fig.update_yaxes(title_text="Latitude", row=2, col=1)
        fig.update_xaxes(title_text="Longitude", row=2, col=2)
        fig.update_yaxes(title_text="Latitude", row=2, col=2)

        fig.update_layout(
            title=dict(
                text=f"{filepath.name}<br><sub>{format_type.upper()}: {num_points:,} points "
                     f"(binned to {nbins}x{nbins} - ALL data shown as means)</sub>",
                x=0.5,
                xanchor='center'
            ),
            height=800,
            showlegend=False,
            hovermode='closest'
        )

    elif format_type == 'bii':
        # 3-panel layout for BII
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=('SST Distribution', 'Platform Types', 'SST Histogram', ''),
            specs=[[{'type': 'scattergl'}, {'type': 'scattergl'}],
                   [{'type': 'histogram', 'colspan': 2}, None]],
            vertical_spacing=0.12,
            horizontal_spacing=0.10
        )

        # SST scatter
        fig.add_trace(
            go.Scattergl(
                x=lon_plot, y=lat_plot,
                mode='markers',
                marker=dict(
                    color=sst_plot,
                    colorscale='RdYlBu_r',
                    cmin=vmin_sst,
                    cmax=vmax_sst,
                    size=3,
                    colorbar=dict(title="SST (°C)", x=0.46),
                    line=dict(width=0)
                ),
                text=[f"SST: {s:.2f}°C" for s in sst_plot[:1000]],  # Limit hover data
                hovertemplate='Lon: %{x:.2f}<br>Lat: %{y:.2f}<br>%{text}<extra></extra>',
                name='SST'
            ),
            row=1, col=1
        )

        # Platform types
        if platform_plot is not None:
            fig.add_trace(
                go.Scattergl(
                    x=lon_plot, y=lat_plot,
                    mode='markers',
                    marker=dict(
                        color=platform_plot,
                        colorscale='Viridis',
                        size=3,
                        colorbar=dict(title="Platform", x=1.0),
                        line=dict(width=0)
                    ),
                    name='Platform'
                ),
                row=1, col=2
            )

        # Histogram
        fig.add_trace(
            go.Histogram(
                x=data['sst'],
                nbinsx=100,
                name='SST Distribution',
                marker=dict(color='steelblue')
            ),
            row=2, col=1
        )

    else:
        # 4-panel layout for other formats
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=('SST Distribution', 'SST Histogram',
                           'Geographic Coverage', 'Weight/RMS Distribution'),
            specs=[[{'type': 'scattergl'}, {'type': 'histogram'}],
                   [{'type': 'scattergl'}, {'type': 'scattergl'}]],
            vertical_spacing=0.12,
            horizontal_spacing=0.10
        )

        # SST scatter
        fig.add_trace(
            go.Scattergl(
                x=lon_plot, y=lat_plot,
                mode='markers',
                marker=dict(
                    color=sst_plot,
                    colorscale='RdYlBu_r',
                    cmin=vmin_sst,
                    cmax=vmax_sst,
                    size=3,
                    colorbar=dict(title="SST (°C)", x=0.46, y=0.75, len=0.4),
                    line=dict(width=0)
                ),
                text=[f"SST: {s:.2f}°C" for s in sst_plot[:1000]],
                hovertemplate='Lon: %{x:.2f}<br>Lat: %{y:.2f}<br>%{text}<extra></extra>',
                name='SST'
            ),
            row=1, col=1
        )

        # Histogram
        fig.add_trace(
            go.Histogram(
                x=data['sst'],
                nbinsx=100,
                name='SST Distribution',
                marker=dict(color='steelblue')
            ),
            row=1, col=2
        )

        # Geographic coverage
        fig.add_trace(
            go.Scattergl(
                x=lon_plot, y=lat_plot,
                mode='markers',
                marker=dict(
                    color='rgba(100, 150, 200, 0.3)',
                    size=2,
                    line=dict(width=0)
                ),
                name='Coverage'
            ),
            row=2, col=1
        )

        # Weight or RMS
        if weight_plot is not None:
            fig.add_trace(
                go.Scattergl(
                    x=lon_plot, y=lat_plot,
                    mode='markers',
                    marker=dict(
                        color=weight_plot,
                        colorscale='Viridis',
                        size=3,
                        colorbar=dict(title="Weight", x=1.0, y=0.25, len=0.4),
                        line=dict(width=0)
                    ),
                    name='Weight'
                ),
                row=2, col=2
            )

    # Update layout
    fig.update_xaxes(title_text="Longitude", row=1, col=1)
    fig.update_yaxes(title_text="Latitude", row=1, col=1)
    fig.update_xaxes(title_text="Longitude", row=2, col=1)
    fig.update_yaxes(title_text="Latitude", row=2, col=1)

    fig.update_layout(
        title=dict(
            text=f"{filepath.name}<br><sub>{format_type.upper()}: {num_points:,} points"
                 f"{' (downsampled to ' + str(len(lon_plot)) + ')' if downsampled else ''}</sub>",
            x=0.5,
            xanchor='center'
        ),
        height=800,
        showlegend=False,
        hovermode='closest'
    )

    return fig


def display_file_info(data: dict, format_type: str, filepath: Path):
    """
    Display file information in Streamlit.

    Args:
        data: Data dictionary from format reader
        format_type: File format type
        filepath: Path to file
    """
    st.subheader("📋 File Information")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Format", format_type.upper())

    if format_type in ['bip', 'biq']:
        with col2:
            st.metric("Number of Points", f"{data['N']:,}")
        with col3:
            if data['N'] > 0:
                st.metric("SST Range", f"{data['sst'].min():.2f} - {data['sst'].max():.2f} °C")

        if data['N'] > 0:
            st.write("#### Statistics")

            robust_stats = compute_robust_stats(data['sst'])

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("SST Mean", f"{data['sst'].mean():.2f} °C")
            with col2:
                st.metric("SST Median", f"{robust_stats['median']:.2f} °C")
            with col3:
                st.metric("SST Std Dev", f"{data['sst'].std():.2f} °C")
            with col4:
                st.metric("Robust Std", f"{robust_stats['robust_std']:.2f} °C")

            st.write("#### Spatial Extent")
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Longitude:** {data['lon'].min():.4f}° to {data['lon'].max():.4f}°")
            with col2:
                st.write(f"**Latitude:** {data['lat'].min():.4f}° to {data['lat'].max():.4f}°")

    elif format_type == 'gds':
        ii, jj = data['dimensions']
        with col2:
            st.metric("Grid Dimensions", f"{ii} × {jj}")
        with col3:
            st.metric("Total Pixels", f"{ii*jj:,}")

        st.write("#### Mask Values")
        mask_unique = np.unique(data['mask'])
        mask_labels = {
            1: 'Open sea', 2: 'Land', 3: 'Coast',
            5: 'Open lake', 7: 'Lake shore',
            9: 'Sea + ice', 11: 'Coast + ice',
            13: 'Lake + ice', 15: 'Complex shore'
        }

        for val in mask_unique:
            count = np.sum(data['mask'] == val)
            pct = 100.0 * count / data['mask'].size
            label = mask_labels.get(val, f"Value {val}")
            st.write(f"**{label}:** {count:,} pixels ({pct:.2f}%)")

    elif format_type in ['bii', 'bic', 'bin']:
        with col2:
            st.metric("Number of Observations", f"{data['N']:,}")
        with col3:
            st.metric("Year/Day", f"{data['year']}/{data['day']}")

        if data['N'] > 0:
            st.write("#### Statistics")
            robust_stats = compute_robust_stats(data['sst'])

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("SST Mean", f"{data['sst'].mean():.2f} °C")
            with col2:
                st.metric("SST Median", f"{robust_stats['median']:.2f} °C")
            with col3:
                st.metric("SST Std Dev", f"{data['sst'].std():.2f} °C")
            with col4:
                st.metric("Outliers (>4σ)", f"{robust_stats['n_outliers_4sigma']:,}")

    elif format_type == 'map':
        nlon, nlat = data['dimensions']
        with col2:
            st.metric("Grid Dimensions", f"{nlon} × {nlat}")

        sst_valid = data['sst'][~np.isnan(data['sst'])]
        if len(sst_valid) > 0:
            with col3:
                st.metric("Valid Pixels", f"{len(sst_valid):,}")

            st.write("#### SST Statistics")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Mean", f"{sst_valid.mean():.2f} °C")
            with col2:
                st.metric("Std Dev", f"{sst_valid.std():.2f} °C")
            with col3:
                st.metric("Min", f"{sst_valid.min():.2f} °C")
            with col4:
                st.metric("Max", f"{sst_valid.max():.2f} °C")

    elif format_type in ['csp', 'usp']:
        coef = data['coefficients']
        scale = data.get('scale', 'unknown')
        with col2:
            st.metric("Scale Level", f"L={scale}")
        with col3:
            st.metric("Total Coefficients", f"{coef.size:,}")

        st.write("#### Grid Dimensions")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("mx", data['mx'])
        with col2:
            st.metric("my", data['my'])
        with col3:
            st.metric("mz", data['mz'])
        with col4:
            st.metric("nv", data['nv'])

        st.write(f"**Coefficient array shape:** {coef.shape}")

        st.write("#### Spatial Bounds")
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**X range:** [{data['xmin']:.4f}, {data['xmax']:.4f}]")
        with col2:
            st.write(f"**Y range:** [{data['ymin']:.4f}, {data['ymax']:.4f}]")

        st.write("#### Coefficient Statistics")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Min", f"{coef.min():.6f}")
        with col2:
            st.metric("Max", f"{coef.max():.6f}")
        with col3:
            st.metric("Mean", f"{coef.mean():.6f}")
        with col4:
            st.metric("Std Dev", f"{coef.std():.6f}")


def compare_files_data(data1: dict, data2: dict, format_type: str, tolerance: float = 1e-6) -> dict:
    """
    Compare two data dictionaries of the same format.

    Args:
        data1: First data dictionary
        data2: Second data dictionary
        format_type: File format type
        tolerance: Numerical tolerance for float comparisons

    Returns:
        Dictionary with comparison results
    """
    results = {
        'all_match': True,
        'comparisons': [],
        'stats': {}
    }

    if format_type in ['bip', 'biq', 'bic', 'bin']:
        # Compare point data
        n1 = data1.get('N', len(data1.get('sst', [])))
        n2 = data2.get('N', len(data2.get('sst', [])))

        if n1 != n2:
            results['comparisons'].append({
                'field': 'N (point count)',
                'match': False,
                'message': f"Different: {n1:,} vs {n2:,}"
            })
            results['all_match'] = False
        else:
            results['comparisons'].append({
                'field': 'N (point count)',
                'match': True,
                'message': f"Match: {n1:,}"
            })

        # Compare fields that exist in both
        fields_to_compare = ['lon', 'lat', 'sst', 'hour']
        if 'weight' in data1 and 'weight' in data2:
            fields_to_compare.append('weight')
        if 'rms' in data1 and 'rms' in data2:
            fields_to_compare.append('rms')
        if 'bias' in data1 and 'bias' in data2:
            fields_to_compare.append('bias')

        for field in fields_to_compare:
            if field not in data1 or field not in data2:
                continue

            arr1 = np.asarray(data1[field])
            arr2 = np.asarray(data2[field])

            if arr1.shape != arr2.shape:
                results['comparisons'].append({
                    'field': field,
                    'match': False,
                    'message': f"Different shapes: {arr1.shape} vs {arr2.shape}"
                })
                results['all_match'] = False
                continue

            # Handle NaN values
            valid_mask = ~(np.isnan(arr1) | np.isnan(arr2))
            if not np.any(valid_mask):
                results['comparisons'].append({
                    'field': field,
                    'match': True,
                    'message': "Both all NaN"
                })
                continue

            diff = arr1[valid_mask] - arr2[valid_mask]
            max_diff = np.max(np.abs(diff))
            mean_diff = np.mean(diff)
            std_diff = np.std(diff)

            if np.allclose(arr1, arr2, atol=tolerance, rtol=tolerance, equal_nan=True):
                results['comparisons'].append({
                    'field': field,
                    'match': True,
                    'message': f"Match (max diff: {max_diff:.2e})"
                })
            else:
                results['comparisons'].append({
                    'field': field,
                    'match': False,
                    'message': f"Differs: max={max_diff:.4f}, mean={mean_diff:.4f}, std={std_diff:.4f}"
                })
                results['all_match'] = False

            results['stats'][field] = {
                'max_diff': max_diff,
                'mean_diff': mean_diff,
                'std_diff': std_diff,
                'diff': diff if len(diff) < 100000 else None  # Only store if manageable size
            }

    elif format_type in ['gds', 'map']:
        # Compare grid data
        dim1 = data1.get('dimensions', data1.get('sst', np.array([])).shape)
        dim2 = data2.get('dimensions', data2.get('sst', np.array([])).shape)

        if dim1 != dim2:
            results['comparisons'].append({
                'field': 'dimensions',
                'match': False,
                'message': f"Different: {dim1} vs {dim2}"
            })
            results['all_match'] = False
        else:
            results['comparisons'].append({
                'field': 'dimensions',
                'match': True,
                'message': f"Match: {dim1}"
            })

        # Compare fields
        if format_type == 'gds':
            fields_to_compare = ['mask', 'lon', 'lat', 'icemap']
        else:  # map
            fields_to_compare = ['sst', 'lon', 'lat']

        for field in fields_to_compare:
            if field not in data1 or field not in data2:
                continue

            arr1 = np.asarray(data1[field])
            arr2 = np.asarray(data2[field])

            if arr1.shape != arr2.shape:
                results['comparisons'].append({
                    'field': field,
                    'match': False,
                    'message': f"Different shapes: {arr1.shape} vs {arr2.shape}"
                })
                results['all_match'] = False
                continue

            # Handle NaN values for float arrays
            if np.issubdtype(arr1.dtype, np.floating):
                valid_mask = ~(np.isnan(arr1) | np.isnan(arr2))
                if np.any(valid_mask):
                    diff = arr1[valid_mask] - arr2[valid_mask]
                    max_diff = np.max(np.abs(diff))
                    num_diff = np.sum(np.abs(diff) > tolerance)
                else:
                    max_diff = 0
                    num_diff = 0
            else:
                diff = arr1.astype(float) - arr2.astype(float)
                max_diff = np.max(np.abs(diff))
                num_diff = np.sum(arr1 != arr2)

            pct_diff = 100.0 * num_diff / arr1.size if arr1.size > 0 else 0

            if num_diff == 0:
                results['comparisons'].append({
                    'field': field,
                    'match': True,
                    'message': f"Match"
                })
            else:
                results['comparisons'].append({
                    'field': field,
                    'match': False,
                    'message': f"Differs: {num_diff:,} elements ({pct_diff:.4f}%), max diff: {max_diff}"
                })
                results['all_match'] = False

            results['stats'][field] = {
                'max_diff': max_diff,
                'num_diff': num_diff,
                'pct_diff': pct_diff
            }

    return results


def create_comparison_plot(data1: dict, data2: dict, format_type: str,
                           file1_name: str, file2_name: str) -> plt.Figure:
    """
    Create a comparison visualization showing both datasets and their difference.

    Args:
        data1: First data dictionary
        data2: Second data dictionary
        format_type: File format type
        file1_name: Name of first file
        file2_name: Name of second file

    Returns:
        Matplotlib figure
    """
    if format_type in ['bip', 'biq', 'bic', 'bin']:
        # Point data comparison
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))

        # SST scatter plots
        ax1 = axes[0, 0]
        valid1 = ~np.isnan(data1['sst'])
        sst1 = data1['sst'][valid1]
        if len(sst1) > 0:
            vmin = np.percentile(sst1, 1)
            vmax = np.percentile(sst1, 99)
            sc1 = ax1.scatter(data1['lon'][valid1], data1['lat'][valid1],
                              c=sst1, s=1, cmap='RdYlBu_r', vmin=vmin, vmax=vmax, alpha=0.7)
            plt.colorbar(sc1, ax=ax1, label='SST (K)')
        ax1.set_title(f"File 1: {file1_name}")
        ax1.set_xlabel('Longitude')
        ax1.set_ylabel('Latitude')

        ax2 = axes[0, 1]
        valid2 = ~np.isnan(data2['sst'])
        sst2 = data2['sst'][valid2]
        if len(sst2) > 0:
            sc2 = ax2.scatter(data2['lon'][valid2], data2['lat'][valid2],
                              c=sst2, s=1, cmap='RdYlBu_r', vmin=vmin, vmax=vmax, alpha=0.7)
            plt.colorbar(sc2, ax=ax2, label='SST (K)')
        ax2.set_title(f"File 2: {file2_name}")
        ax2.set_xlabel('Longitude')
        ax2.set_ylabel('Latitude')

        # SST difference histogram
        ax3 = axes[1, 0]
        n1, n2 = len(data1['sst']), len(data2['sst'])
        if n1 == n2:
            diff = data1['sst'] - data2['sst']
            valid_diff = diff[~np.isnan(diff)]
            if len(valid_diff) > 0:
                ax3.hist(valid_diff, bins=100, edgecolor='black', alpha=0.7)
                ax3.axvline(x=0, color='r', linestyle='--', label='Zero')
                ax3.set_xlabel('SST Difference (File1 - File2)')
                ax3.set_ylabel('Count')
                ax3.set_title(f'SST Difference Distribution\n'
                             f'Mean: {np.mean(valid_diff):.4f}, Std: {np.std(valid_diff):.4f}')
                ax3.legend()
        else:
            ax3.text(0.5, 0.5, f'Cannot compute difference:\nDifferent point counts\n({n1:,} vs {n2:,})',
                    ha='center', va='center', transform=ax3.transAxes)
            ax3.set_title('SST Difference')

        # SST 1:1 comparison scatter
        ax4 = axes[1, 1]
        if n1 == n2:
            valid_both = ~(np.isnan(data1['sst']) | np.isnan(data2['sst']))
            sst1_valid = data1['sst'][valid_both]
            sst2_valid = data2['sst'][valid_both]
            if len(sst1_valid) > 0:
                # Downsample if too many points
                if len(sst1_valid) > 10000:
                    idx = np.random.choice(len(sst1_valid), 10000, replace=False)
                    sst1_plot = sst1_valid[idx]
                    sst2_plot = sst2_valid[idx]
                else:
                    sst1_plot = sst1_valid
                    sst2_plot = sst2_valid

                ax4.scatter(sst1_plot, sst2_plot, s=1, alpha=0.3)
                # Add 1:1 line
                lims = [min(sst1_plot.min(), sst2_plot.min()),
                       max(sst1_plot.max(), sst2_plot.max())]
                ax4.plot(lims, lims, 'r--', label='1:1 line')
                ax4.set_xlabel(f'SST File 1 (K)')
                ax4.set_ylabel(f'SST File 2 (K)')
                ax4.set_title('SST Comparison (1:1)')
                ax4.legend()
                ax4.set_aspect('equal')
        else:
            ax4.text(0.5, 0.5, 'Cannot create 1:1 plot:\nDifferent point counts',
                    ha='center', va='center', transform=ax4.transAxes)
            ax4.set_title('SST 1:1 Comparison')

        plt.tight_layout()
        return fig

    elif format_type == 'map':
        # Grid data comparison
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))

        sst1 = data1['sst']
        sst2 = data2['sst']
        lon1 = data1['lon']
        lat1 = data1['lat']

        # Common colorbar limits
        valid1 = ~np.isnan(sst1)
        valid2 = ~np.isnan(sst2)
        all_valid = np.concatenate([sst1[valid1], sst2[valid2]])
        if len(all_valid) > 0:
            vmin = np.percentile(all_valid, 1)
            vmax = np.percentile(all_valid, 99)
        else:
            vmin, vmax = 270, 305

        ax1 = axes[0, 0]
        im1 = ax1.pcolormesh(lon1, lat1, sst1, cmap='RdYlBu_r', vmin=vmin, vmax=vmax)
        plt.colorbar(im1, ax=ax1, label='SST (K)')
        ax1.set_title(f"File 1: {file1_name}")

        ax2 = axes[0, 1]
        im2 = ax2.pcolormesh(lon1, lat1, sst2, cmap='RdYlBu_r', vmin=vmin, vmax=vmax)
        plt.colorbar(im2, ax=ax2, label='SST (K)')
        ax2.set_title(f"File 2: {file2_name}")

        # Difference map
        ax3 = axes[1, 0]
        if sst1.shape == sst2.shape:
            diff = sst1 - sst2
            diff_max = np.nanmax(np.abs(diff))
            im3 = ax3.pcolormesh(lon1, lat1, diff, cmap='RdBu_r',
                                 vmin=-diff_max, vmax=diff_max)
            plt.colorbar(im3, ax=ax3, label='Difference (K)')
            ax3.set_title(f'Difference (File1 - File2)\nMax: {diff_max:.4f}')
        else:
            ax3.text(0.5, 0.5, 'Cannot compute difference:\nDifferent grid sizes',
                    ha='center', va='center', transform=ax3.transAxes)

        # Histogram of differences
        ax4 = axes[1, 1]
        if sst1.shape == sst2.shape:
            diff_valid = diff[~np.isnan(diff)]
            if len(diff_valid) > 0:
                ax4.hist(diff_valid.flatten(), bins=100, edgecolor='black', alpha=0.7)
                ax4.axvline(x=0, color='r', linestyle='--')
                ax4.set_xlabel('Difference (K)')
                ax4.set_ylabel('Count')
                ax4.set_title(f'Difference Distribution\n'
                             f'Mean: {np.nanmean(diff):.4f}, Std: {np.nanstd(diff):.4f}')

        plt.tight_layout()
        return fig

    else:
        # Unsupported format
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, f'Comparison visualization not implemented for {format_type} format',
                ha='center', va='center', fontsize=14)
        ax.axis('off')
        return fig


def main():
    """Main Streamlit application."""

    # Title and description
    st.title("🌊 MUR Data Viewer")
    st.markdown("### Web-based interface for MUR SST processing data files")

    # Mode selector at the top
    mode = st.radio(
        "Mode:",
        ["📊 View Single File", "🔄 Compare Two Files"],
        horizontal=True
    )

    # Sidebar for file browsing
    st.sidebar.header("📁 File Browser")

    # Get base directory (don't display it)
    base_dir = get_base_directory()

    # Initialize session state
    if 'current_dir' not in st.session_state:
        st.session_state.current_dir = base_dir
    if 'selected_file' not in st.session_state:
        st.session_state.selected_file = None
    if 'should_visualize' not in st.session_state:
        st.session_state.should_visualize = False
    if 'compare_file1' not in st.session_state:
        st.session_state.compare_file1 = None
    if 'compare_file2' not in st.session_state:
        st.session_state.compare_file2 = None
    if 'should_compare' not in st.session_state:
        st.session_state.should_compare = False
    if 'reference_file' not in st.session_state:
        st.session_state.reference_file = None
    if 'reference_data' not in st.session_state:
        st.session_state.reference_data = None
    if 'reference_format' not in st.session_state:
        st.session_state.reference_format = None

    # Ensure current directory is safe
    if not is_safe_path(base_dir, st.session_state.current_dir):
        st.session_state.current_dir = base_dir

    current_dir = Path(st.session_state.current_dir)

    # Directory navigation
    rel_path = current_dir.relative_to(base_dir) if current_dir != base_dir else '/'
    st.sidebar.write(f"**Current:** `{rel_path}`")

    # Parent directory button
    if current_dir != base_dir:
        if st.sidebar.button("⬆️ Parent Directory"):
            parent = current_dir.parent
            if is_safe_path(base_dir, parent):
                st.session_state.current_dir = parent
                st.rerun()

    # List subdirectories
    subdirs = list_subdirectories(current_dir)
    if subdirs:
        st.sidebar.write("**Subdirectories:**")
        for subdir in subdirs:
            if st.sidebar.button(f"📁 {subdir.name}", key=f"dir_{subdir}"):
                if is_safe_path(base_dir, subdir):
                    st.session_state.current_dir = subdir
                    st.rerun()

    # File pattern selector
    st.sidebar.write("---")
    st.sidebar.write("**File Filter:**")

    supported_formats = {
        "All files": "*",
        "Point data (.bip, .biq, .bii, .bic, .bin)": "*.bi[pqic]",
        "Grid data (.gds, .map)": "*.{gds,map}",
        "NetCDF (.nc, .nc4)": "*.nc*",
        "Coefficients (.c*, .u*)": "*.[cu]*",
    }

    selected_filter = st.sidebar.selectbox(
        "Select file type:",
        list(supported_formats.keys())
    )

    pattern = supported_formats[selected_filter]

    # List files
    files = list_files_in_directory(current_dir, pattern)

    # Also check for compressed files
    if pattern != "*":
        gz_pattern = pattern + ".gz"
        files.extend(list_files_in_directory(current_dir, gz_pattern))
        files = sorted(set(files))

    if not files:
        st.warning("No files found in current directory with selected filter.")
        st.info("Use the sidebar file browser to navigate to MUR data files.")
        return

    # File search/filter
    st.sidebar.write(f"**Found {len(files)} file(s)**")
    search_term = st.sidebar.text_input(
        "🔍 Search files:",
        placeholder="Type to filter..."
    )

    # Filter files based on search term
    if search_term:
        filtered_files = [
            f for f in files if search_term.lower() in f.name.lower()
        ]
        st.sidebar.write(f"**Showing {len(filtered_files)} matching file(s)**")
    else:
        filtered_files = files

    if not filtered_files:
        st.sidebar.warning("No files match your search.")
        # Still show reference file status in compare mode even with no files
        if mode == "🔄 Compare Files" and st.session_state.reference_file:
            st.sidebar.write("---")
            ref_path = st.session_state.reference_file
            try:
                rel_path = ref_path.relative_to(base_dir)
            except ValueError:
                rel_path = ref_path.name
            st.sidebar.success(f"📌 **Reference:**\n`{rel_path}`")
            if st.sidebar.button(
                "🗑️ Clear Reference",
                use_container_width=True,
                key="clear_ref_no_files"
            ):
                st.session_state.reference_file = None
                st.session_state.reference_data = None
                st.session_state.reference_format = None
                st.session_state.should_compare = False
                st.rerun()
            st.info(
                f"📌 **Reference set:** `{rel_path}`\n\n"
                "Navigate to a folder with files to select comparison files."
            )
        return

    # =========== SINGLE FILE MODE ===========
    if mode == "📊 View Single File":
        # File selector
        selected_file = st.sidebar.selectbox(
            "Select a file:",
            filtered_files,
            format_func=lambda x: x.name,
            key="file_selector"
        )

        if selected_file:
            st.sidebar.write("---")

            # Visualization button (explicit action)
            st.sidebar.write("**Actions:**")
            viz_btn = st.sidebar.button(
                "📊 Visualize File",
                type="primary",
                use_container_width=True
            )
            if viz_btn:
                st.session_state.selected_file = selected_file
                st.session_state.should_visualize = True

            # Rendering options
            st.sidebar.write("---")
            st.sidebar.write("**Display Options:**")
            show_info = st.sidebar.checkbox("Show file info", value=True)

            # Plot type selector
            plot_type = st.sidebar.radio(
                "Plot type:",
                ["Matplotlib (Fast)", "Plotly (Interactive)"],
                help="Matplotlib is faster. Plotly allows zoom/pan."
            )
            use_plotly = plot_type.startswith("Plotly")

            # Only load and display if visualize button was clicked
            should_viz = st.session_state.should_visualize
            same_file = st.session_state.selected_file == selected_file
            if should_viz and same_file:
                try:
                    # Detect format
                    format_type = DataFileReader.detect_format(selected_file)

                    with st.spinner(f"Reading {format_type.upper()} file..."):
                        data = read_file(selected_file)

                    # Display info
                    if show_info:
                        display_file_info(data, format_type, selected_file)

                    # Display plot
                    st.write("---")
                    st.subheader("📊 Visualization")

                    with st.spinner("Creating visualization..."):
                        if format_type in ['bip', 'biq', 'bii', 'bic', 'bin']:
                            if use_plotly:
                                try:
                                    fig = create_interactive_point_plot(
                                        data, format_type, selected_file
                                    )
                                    st.plotly_chart(fig, use_container_width=True)
                                except Exception as e:
                                    st.error(f"Plotly failed: {e}")
                                    st.info("Falling back to Matplotlib...")
                                    fig = create_point_data_plot(
                                        data, format_type, selected_file
                                    )
                                    st.pyplot(fig)
                                    plt.close(fig)
                            else:
                                fig = create_point_data_plot(
                                    data, format_type, selected_file
                                )
                                st.pyplot(fig)
                                plt.close(fig)
                        elif format_type in ['gds', 'map']:
                            fig = create_grid_data_plot(
                                data, format_type, selected_file
                            )
                            st.pyplot(fig)
                            plt.close(fig)
                        elif format_type in ['csp', 'usp']:
                            fig = create_coefficient_plot(
                                data, format_type, selected_file
                            )
                            st.pyplot(fig)
                            plt.close(fig)
                        else:
                            st.info(
                                f"Visualization not implemented for "
                                f"{format_type} format."
                            )

                except Exception as e:
                    st.error(f"Error processing file: {e}")
                    import traceback
                    with st.expander("Show error details"):
                        st.code(traceback.format_exc())
            else:
                st.info("👆 Select a file and click **Visualize File**.")

    # =========== COMPARE MODE ===========
    else:
        # Show reference file status in sidebar
        st.sidebar.write("---")
        if st.session_state.reference_file:
            ref_path = st.session_state.reference_file
            try:
                ref_rel_path = ref_path.relative_to(base_dir)
            except ValueError:
                ref_rel_path = ref_path.name
            st.sidebar.success(f"📌 **Reference:**\n`{ref_rel_path}`")
            if st.sidebar.button(
                "🗑️ Clear Reference",
                use_container_width=True
            ):
                st.session_state.reference_file = None
                st.session_state.reference_data = None
                st.session_state.reference_format = None
                st.session_state.should_compare = False
                st.rerun()
        else:
            st.sidebar.info("📌 No reference file set")

        st.sidebar.write("---")
        st.sidebar.write("**Select file to compare:**")

        # File selector for comparison
        selected_file = st.sidebar.selectbox(
            "File:",
            filtered_files,
            format_func=lambda x: x.name,
            key="compare_file_selector"
        )

        st.sidebar.write("---")

        # Tolerance setting
        tolerance = st.sidebar.number_input(
            "Comparison tolerance:",
            min_value=1e-10,
            max_value=1.0,
            value=1e-6,
            format="%.2e",
            help="Numerical tolerance for float comparisons"
        )

        st.sidebar.write("---")
        st.sidebar.write("**Actions:**")

        # Set as Reference button
        set_ref_btn = st.sidebar.button(
            "📌 Set as Reference",
            use_container_width=True,
            help="Set the selected file as the reference for comparisons"
        )
        if set_ref_btn and selected_file:
            with st.spinner("Loading reference file..."):
                try:
                    ref_fmt = DataFileReader.detect_format(selected_file)
                    ref_data = read_file(selected_file)
                    st.session_state.reference_file = selected_file
                    st.session_state.reference_data = ref_data
                    st.session_state.reference_format = ref_fmt
                    st.session_state.should_compare = False
                    st.rerun()
                except Exception as e:
                    st.sidebar.error(f"Error loading reference: {e}")

        # Compare to Reference button (only enabled if reference is set)
        compare_btn = st.sidebar.button(
            "🔄 Compare to Reference",
            type="primary",
            use_container_width=True,
            disabled=st.session_state.reference_file is None
        )
        if compare_btn and selected_file:
            st.session_state.compare_file2 = selected_file
            st.session_state.should_compare = True

        # Main content area
        if st.session_state.reference_file is None:
            st.info(
                "👆 **Step 1:** Select a file in the sidebar and click "
                "**Set as Reference** to begin comparisons."
            )
        elif not st.session_state.should_compare:
            st.info(
                f"📌 **Reference set:** `{ref_rel_path}`\n\n"
                "👆 **Step 2:** Select another file and click "
                "**Compare to Reference** to see the comparison.\n\n"
                "You can compare multiple files to this reference without resetting."
            )
        else:
            # Perform comparison
            ref_file = st.session_state.reference_file
            cmp_file = st.session_state.compare_file2

            if ref_file == cmp_file:
                st.warning("The selected file is the same as the reference file.")
            else:
                try:
                    # Use cached reference data
                    ref_data = st.session_state.reference_data
                    ref_fmt = st.session_state.reference_format

                    # Detect format for comparison file
                    cmp_fmt = DataFileReader.detect_format(cmp_file)

                    if ref_fmt != cmp_fmt:
                        st.error(
                            f"Cannot compare different formats: "
                            f"{ref_fmt.upper()} (reference) vs "
                            f"{cmp_fmt.upper()} (comparison)"
                        )
                    else:
                        # Read comparison file
                        with st.spinner("Reading comparison file..."):
                            cmp_data = read_file(cmp_file)

                        # Display comparison results
                        st.subheader("🔄 Comparison Results")

                        # File info with relative paths
                        try:
                            cmp_rel_path = cmp_file.relative_to(base_dir)
                        except ValueError:
                            cmp_rel_path = cmp_file.name
                        col1, col2 = st.columns(2)
                        with col1:
                            st.write(f"**Reference:** `{ref_rel_path}`")
                        with col2:
                            st.write(f"**Comparison:** `{cmp_rel_path}`")

                        st.write(f"**Format:** {ref_fmt.upper()}")
                        st.write(f"**Tolerance:** {tolerance:.2e}")
                        st.write("---")

                        # Run comparison
                        results = compare_files_data(
                            ref_data, cmp_data, ref_fmt, tolerance
                        )

                        # Display results table
                        st.write("**Field Comparison:**")
                        for comp in results['comparisons']:
                            icon = "✅" if comp['match'] else "❌"
                            st.write(
                                f"{icon} **{comp['field']}**: {comp['message']}"
                            )

                        st.write("---")

                        # Summary
                        if results['all_match']:
                            st.success("🎉 All fields match within tolerance!")
                        else:
                            st.warning("❌ Some differences found.")

                        # Visualization
                        st.write("---")
                        st.subheader("📊 Comparison Visualization")

                        with st.spinner("Creating comparison plots..."):
                            fig = create_comparison_plot(
                                ref_data, cmp_data, ref_fmt,
                                ref_file.name, cmp_file.name
                            )
                            st.pyplot(fig)
                            plt.close(fig)

                except Exception as e:
                    st.error(f"Error comparing files: {e}")
                    import traceback
                    with st.expander("Show error details"):
                        st.code(traceback.format_exc())


if __name__ == '__main__':
    main()
