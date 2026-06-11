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
    from .dataviewer import (compute_robust_stats, smart_downsample,
                             slice_to_bounds, block_mean_resample,
                             nearest_resample)
except ImportError:
    # Running as standalone script via streamlit
    from format_readers import read_file, DataFileReader
    from dataviewer import (compute_robust_stats, smart_downsample,
                            slice_to_bounds, block_mean_resample,
                            nearest_resample)

# Note: streamlit-file-browser component doesn't work in sidebar, so we use native widgets

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


def create_netcdf_plot(data: dict, filepath: Path) -> plt.Figure:
    """
    Create matplotlib figure for NetCDF MUR GHRSST data.

    Args:
        data: Data dictionary from NetCDFReader
        filepath: Path to file

    Returns:
        Matplotlib figure object
    """
    variables = data['variables']
    dimensions = data['dimensions']

    # Check if this is a MUR GHRSST file
    is_mur_ghrsst = 'analysed_sst' in variables

    if not is_mur_ghrsst:
        # Generic NetCDF - show what we can
        fig, ax = plt.subplots(figsize=(10, 6))
        info_text = "NetCDF file (non-GHRSST format)\n\nVariables:\n"
        for var_name in list(variables.keys())[:10]:
            var = variables[var_name]
            shape = var['data'].shape if hasattr(var['data'], 'shape') else 'scalar'
            info_text += f"  - {var_name}: {shape}\n"
        if len(variables) > 10:
            info_text += f"  ... and {len(variables) - 10} more\n"
        info_text += f"\nDimensions: {dimensions}"
        ax.text(0.1, 0.5, info_text, fontsize=12, family='monospace',
                verticalalignment='center')
        ax.axis('off')
        plt.suptitle(f'{filepath.name}\nNetCDF file')
        return fig

    # Extract key variables for MUR GHRSST
    sst_var = variables['analysed_sst']
    lon = variables['lon']['data'][:]
    lat = variables['lat']['data'][:]
    # NOTE: netCDF4 auto-applies scale_factor and add_offset when reading
    # So sst_data is already in Kelvin (NOT raw int16 values)
    sst_data = sst_var['data'][0, :, :] if sst_var['data'].ndim == 3 \
        else sst_var['data'][:, :]

    # Data is already in Kelvin, just convert to Celsius
    # DO NOT apply scale_factor/add_offset again - causes double-scaling bug!
    sst_celsius = sst_data - 273.15

    # netCDF4 auto-masking handles fill values, but ensure masked array
    if not isinstance(sst_celsius, np.ma.MaskedArray):
        fill_value = sst_var['attributes'].get('_FillValue', -32768)
        scale = sst_var['attributes'].get('scale_factor', 1.0)
        offset = sst_var['attributes'].get('add_offset', 0.0)
        scaled_fill = fill_value * scale + offset - 273.15
        sst_celsius = np.ma.masked_where(
            np.isclose(sst_celsius, scaled_fill), sst_celsius)

    # Get mask if available
    mask = None
    if 'mask' in variables:
        mask_var = variables['mask']
        mask = mask_var['data'][0, :, :] if mask_var['data'].ndim == 3 else mask_var['data'][:, :]

    # Determine subsampling for large grids (MUR is 36000x17999)
    max_display = 2000  # Smaller for web display
    subsample = max(1, max(len(lon), len(lat)) // max_display)

    if subsample > 1:
        lon_plot = lon[::subsample]
        lat_plot = lat[::subsample]
        sst_plot = sst_celsius[::subsample, ::subsample]
        if mask is not None:
            mask_plot = mask[::subsample, ::subsample]
    else:
        lon_plot = lon
        lat_plot = lat
        sst_plot = sst_celsius
        mask_plot = mask if mask is not None else None

    # Check if cartopy is available
    try:
        import cartopy.crs as ccrs  # noqa: F401
        has_cartopy = True
    except ImportError:
        has_cartopy = False

    # Fixed color scale for MUR SST (0 to 32°C)
    sst_valid = sst_plot[~sst_plot.mask] if hasattr(sst_plot, 'mask') else sst_plot[~np.isnan(sst_plot)]
    vmin, vmax = 0, 32

    # Create figure with 2 rows:
    # Row 1: Large SST map (full width)
    # Row 2: Histogram and mask side-by-side
    has_mask = mask is not None

    # Use constrained_layout for GridSpec compatibility (avoids tight_layout issues)
    fig = plt.figure(figsize=(20, 14), constrained_layout=True)

    # Use GridSpec for flexible layout
    # Row 1: SST map takes 60% height
    # Row 2: Histogram and mask take 40% height
    gs = fig.add_gridspec(2, 2, height_ratios=[1.5, 1])

    # SST map - spans full width of top row
    ax1 = fig.add_subplot(gs[0, :])

    # Note: NetCDF data is in (lat, lon) order, pcolormesh expects C(lat, lon)
    im1 = ax1.pcolormesh(lon_plot, lat_plot, sst_plot,
                         cmap='RdYlBu_r', vmin=vmin, vmax=vmax,
                         shading='nearest')
    ax1.set_xlabel('Longitude (degrees)', fontsize=11)
    ax1.set_ylabel('Latitude (degrees)', fontsize=11)
    ax1.set_title('MUR SST Analysis (°C)', fontsize=14, fontweight='bold')
    ax1.set_aspect('equal', adjustable='box')
    ax1.grid(True, alpha=0.3)
    if has_cartopy:
        add_coastlines_to_ax(ax1)
    plt.colorbar(im1, ax=ax1, label='SST (°C)', shrink=0.6, pad=0.02)

    # SST histogram - bottom left
    ax2 = fig.add_subplot(gs[1, 0])
    if len(sst_valid) > 0:
        ax2.hist(sst_valid.flatten(), bins=100, edgecolor='black', alpha=0.7)
        ax2.set_xlabel('SST (°C)')
        ax2.set_ylabel('Count')
        ax2.set_title('SST Distribution')
        ax2.grid(True, alpha=0.3)

        # Add statistics
        stats_text = (
            f"Valid pixels: {len(sst_valid):,}\n"
            f"Mean: {sst_valid.mean():.2f} °C\n"
            f"Std: {sst_valid.std():.2f} °C\n"
            f"Min: {sst_valid.min():.2f} °C\n"
            f"Max: {sst_valid.max():.2f} °C"
        )
        ax2.text(0.98, 0.98, stats_text,
                transform=ax2.transAxes,
                verticalalignment='top',
                horizontalalignment='right',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
                fontsize=9, family='monospace')

    # Mask display - bottom right (if available)
    if has_mask:
        ax3 = fig.add_subplot(gs[1, 1])

        # Create discrete colormap for mask
        mask_labels = {
            1: 'Open sea', 2: 'Land', 3: 'Coast',
            5: 'Open lake', 9: 'Sea+ice', 11: 'Coast+ice',
            13: 'Lake+ice', 15: 'Complex'
        }
        # Filter out fill values (-128) and get unique valid values
        mask_flat = mask_plot.flatten()
        valid_mask = mask_flat[mask_flat >= 0]
        if len(valid_mask) > 0:
            unique_vals = sorted(set(valid_mask.astype(int)))
            n_colors = len(unique_vals)
            tab10 = plt.colormaps.get_cmap('tab10')
            colors = [tab10(i / 10) for i in range(n_colors)]
            cmap_mask = ListedColormap(colors)
            bounds = [unique_vals[0] - 0.5] + [v + 0.5 for v in unique_vals]
            norm = BoundaryNorm(bounds, cmap_mask.N)

            # Mask out invalid values for display
            mask_display = np.ma.masked_where(mask_plot < 0, mask_plot)
            im3 = ax3.pcolormesh(lon_plot, lat_plot, mask_display,
                                cmap=cmap_mask, norm=norm, shading='nearest')
            ax3.set_xlabel('Longitude (degrees)')
            ax3.set_ylabel('Latitude (degrees)')
            ax3.set_title('Land/Sea/Ice Mask')
            ax3.set_aspect('equal', adjustable='box')
            ax3.grid(True, alpha=0.3)

            cbar3 = plt.colorbar(im3, ax=ax3, label='Surface Type',
                                ticks=unique_vals, shrink=0.8)
            cbar3.set_ticklabels([mask_labels.get(v, str(v)) for v in unique_vals])
        else:
            ax3.text(0.5, 0.5, 'No valid mask data', ha='center', va='center')
            ax3.axis('off')

    title_str = data['attributes'].get('title', 'MUR SST L4 Analysis')
    resolution = f"{len(lon)}×{len(lat)}"
    if subsample > 1:
        resolution += f" (displayed at {len(lon_plot)}×{len(lat_plot)})"

    plt.suptitle(f'{filepath.name}\n{title_str}\nResolution: {resolution}')
    # Note: No tight_layout needed - using constrained_layout=True in figure creation

    return fig


@st.cache_resource(show_spinner=False)
def _read_file_cached(filepath_str: str, mtime: float) -> dict:
    """
    Cache the raw read of a (potentially multi-GB) file by path + mtime.

    Box-select reruns trigger a full script rerun, so without caching the
    NetCDF grid would be re-read from disk on every zoom. ``cache_resource``
    stores the dict by reference (no pickling copy), keyed on mtime so edits
    invalidate it.
    """
    return read_file(Path(filepath_str))


@st.cache_resource(show_spinner=False)
def load_netcdf_fields(filepath_str: str, mtime: float):
    """
    Load and cache the full-resolution fields needed for MUR GHRSST plotting.

    Returns a compact dict (lon, lat, sst_celsius as float32 with NaN fills,
    mask or None, plus metadata) so on-the-fly view-aware resampling can slice
    the in-memory grid cheaply. Returns None for non-GHRSST NetCDF files.

    Centralizes the K->C conversion and fill-value handling that previously
    lived inline in create_interactive_netcdf_plot.
    """
    data = _read_file_cached(filepath_str, mtime)
    variables = data['variables']
    if 'analysed_sst' not in variables:
        return None

    sst_var = variables['analysed_sst']
    lon = np.asarray(variables['lon']['data'][:])
    lat = np.asarray(variables['lat']['data'][:])

    # NOTE: netCDF4 auto-applies scale_factor/add_offset, so this is Kelvin.
    sst_data = sst_var['data'][0, :, :] if sst_var['data'].ndim == 3 \
        else sst_var['data'][:, :]
    # Already Kelvin -> Celsius. DO NOT re-apply scale/offset (double-scaling bug).
    sst_celsius = sst_data - 273.15

    if isinstance(sst_celsius, np.ma.MaskedArray):
        sst_celsius = sst_celsius.filled(np.nan)
    else:
        fill_value = sst_var['attributes'].get('_FillValue', -32768)
        scale = sst_var['attributes'].get('scale_factor', 1.0)
        offset = sst_var['attributes'].get('add_offset', 0.0)
        scaled_fill = fill_value * scale + offset - 273.15
        sst_celsius = np.where(np.isclose(sst_celsius, scaled_fill),
                               np.nan, sst_celsius)
    # float32 halves the resident footprint of the full grid (~5GB -> ~1.3GB).
    sst_celsius = np.ascontiguousarray(sst_celsius, dtype=np.float32)

    mask = None
    if 'mask' in variables:
        mask_var = variables['mask']
        mask = mask_var['data'][0, :, :] if mask_var['data'].ndim == 3 \
            else mask_var['data'][:, :]
        if isinstance(mask, np.ma.MaskedArray):
            mask = mask.filled(-1)
        mask = np.asarray(mask)

    return {
        'lon': lon,
        'lat': lat,
        'sst_celsius': sst_celsius,
        'mask': mask,
        'title': data['attributes'].get('title', 'MUR SST L4 Analysis'),
        'full_shape': (len(lat), len(lon)),  # (n_lat, n_lon)
    }


def create_interactive_netcdf_plot(fields: dict, filepath: Path,
                                   view_bounds: Optional[tuple] = None):
    """
    Create interactive Plotly figures for MUR GHRSST data, resampling the
    currently-viewed region from full resolution on the fly.

    The full-resolution grid (from load_netcdf_fields) is sliced to
    ``view_bounds`` and then area-mean resampled to ~1500 px. Zooming into a
    smaller region therefore reveals more detail, down to native pixels once
    the region fits in the output grid.

    Args:
        fields: compact dict from load_netcdf_fields()
        filepath: path to the file (for titles)
        view_bounds: (lon_min, lon_max, lat_min, lat_max), or None for global

    Returns:
        (fig_main, fig_aux): the selection-enabled SST map, and the
        histogram + mask companion figure.
    """
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        raise ImportError("Plotly not installed. Install with: pip install plotly")

    lon_full = fields['lon']
    lat_full = fields['lat']
    sst_full = fields['sst_celsius']
    mask_full = fields['mask']
    target = 1500
    vmin, vmax = 0, 32

    # Slice the full-resolution grid to the region being viewed.
    lon_slice, lat_slice = slice_to_bounds(lon_full, lat_full, view_bounds)
    lon = lon_full[lon_slice]
    lat = lat_full[lat_slice]
    sst_region = sst_full[lat_slice, lon_slice]

    # Area-mean resample the region to ~target px (native pixels when factor==1).
    sst_plot, lon_plot, lat_plot, factor = block_mean_resample(
        sst_region, lon, lat, target=target)

    # ----- Main SST figure (box-select enabled) -----
    fig_main = go.Figure()
    fig_main.add_trace(go.Heatmap(
        z=sst_plot, x=lon_plot, y=lat_plot,
        colorscale='RdYlBu_r', zmin=vmin, zmax=vmax,
        colorbar=dict(title="SST (°C)"),
        hovertemplate="Lon: %{x:.3f}<br>Lat: %{y:.3f}<br>SST: %{z:.2f}°C<extra></extra>"
    ))

    full_ny, full_nx = fields['full_shape']
    disp = f"{len(lon_plot)}×{len(lat_plot)}"
    detail = "native resolution" if factor == 1 else f"÷{factor} of full"
    if view_bounds is None:
        region = "Full globe"
    else:
        region = (f"Lon [{float(np.nanmin(lon_plot)):.2f}, {float(np.nanmax(lon_plot)):.2f}], "
                  f"Lat [{float(np.nanmin(lat_plot)):.2f}, {float(np.nanmax(lat_plot)):.2f}]")
    fig_main.update_layout(
        title=(f"{filepath.name}<br><sup>{fields['title']} | {region} | "
               f"full {full_nx}×{full_ny}, displayed {disp} ({detail})</sup>"),
        height=650,
        dragmode='select',
        showlegend=False,
    )
    fig_main.update_xaxes(title_text="Longitude")
    fig_main.update_yaxes(title_text="Latitude", scaleanchor="x")

    # ----- Companion figure: histogram (visible region) + mask -----
    # Sample the sliced full-res region for the histogram/stats so the work is
    # bounded regardless of zoom (a global view's region can be ~650M cells).
    flat = sst_region.ravel()
    if flat.size > 2_000_000:
        idx = np.random.randint(0, flat.size, size=2_000_000)
        flat = flat[idx]
    sst_valid = flat[~np.isnan(flat)]

    has_mask = mask_full is not None
    if has_mask:
        mask_region = mask_full[lat_slice, lon_slice]
        mask_plot = nearest_resample(mask_region, factor)
        fig_aux = make_subplots(
            rows=1, cols=2,
            subplot_titles=["SST Distribution (visible region)", "Land/Sea/Ice Mask"],
            specs=[[{"type": "histogram"}, {"type": "heatmap"}]],
            horizontal_spacing=0.12,
            column_widths=[0.45, 0.55],
        )
    else:
        fig_aux = make_subplots(
            rows=1, cols=1,
            subplot_titles=["SST Distribution (visible region)"],
            specs=[[{"type": "histogram"}]],
        )

    if len(sst_valid) > 0:
        hist_data = (np.random.choice(sst_valid, 100000, replace=False)
                     if len(sst_valid) > 100000 else sst_valid)
        fig_aux.add_trace(
            go.Histogram(
                x=hist_data, nbinsx=100, marker_color='steelblue', opacity=0.7,
                hovertemplate="SST: %{x:.1f}°C<br>Count: %{y}<extra></extra>"
            ),
            row=1, col=1
        )

    if has_mask:
        mask_display = np.where(mask_plot < 0, np.nan, mask_plot)
        fig_aux.add_trace(
            go.Heatmap(
                z=mask_display, x=lon_plot, y=lat_plot,
                colorscale='Viridis',
                colorbar=dict(
                    title="Mask",
                    tickvals=[1, 2, 3, 5, 9],
                    ticktext=['Sea', 'Land', 'Coast', 'Lake', 'Ice']
                ),
                hovertemplate=("Lon: %{x:.2f}<br>Lat: %{y:.2f}<br>"
                               "Mask: %{z}<extra></extra>")
            ),
            row=1, col=2
        )

    fig_aux.update_layout(height=380, showlegend=False)
    fig_aux.update_xaxes(title_text="SST (°C)", row=1, col=1)
    fig_aux.update_yaxes(title_text="Count", row=1, col=1)
    if has_mask:
        fig_aux.update_xaxes(title_text="Longitude", row=1, col=2)
        fig_aux.update_yaxes(title_text="Latitude", row=1, col=2)

    if len(sst_valid) > 0:
        stats_text = (
            f"Valid pixels (sampled): {len(sst_valid):,}<br>"
            f"Mean: {sst_valid.mean():.2f}°C<br>"
            f"Std: {sst_valid.std():.2f}°C<br>"
            f"Range: [{sst_valid.min():.2f}, {sst_valid.max():.2f}]°C"
        )
        fig_aux.add_annotation(
            text=stats_text,
            xref="x domain", yref="y domain",
            x=0.98, y=0.98, showarrow=False,
            font=dict(size=10, family="monospace"), align="right",
            bgcolor="rgba(255,255,255,0.8)", bordercolor="gray", borderwidth=1
        )

    return fig_main, fig_aux


def _extract_box_bounds(event) -> Optional[tuple]:
    """
    Pull (lon_min, lon_max, lat_min, lat_max) from a Streamlit Plotly
    box-selection event, or None if there is no box selection.
    """
    try:
        sel = event.get("selection") if isinstance(event, dict) else event.selection
        boxes = sel.get("box") if sel else None
    except (AttributeError, KeyError, TypeError):
        return None
    if not boxes:
        return None
    box = boxes[0]
    xs = box.get("x") if isinstance(box, dict) else None
    ys = box.get("y") if isinstance(box, dict) else None
    if not xs or not ys or len(xs) < 2 or len(ys) < 2:
        return None
    return (float(min(xs)), float(max(xs)), float(min(ys)), float(max(ys)))


def _render_netcdf_plotly(fields: dict, filepath: Path):
    """
    Render the MUR GHRSST Plotly view with box-select driven, view-aware
    full-resolution resampling.

    Drawing a box on the SST map stores its lon/lat bounds in session state and
    reruns so the region re-renders at full detail. A reset button returns to
    the global view; it bumps a per-file "epoch" so the SST chart gets a fresh
    widget key and its stale box selection is cleared (otherwise the reset would
    immediately re-apply the old selection and zoom right back in).
    """
    file_key = str(filepath)
    bounds_store = st.session_state.setdefault("nc_view_bounds", {})
    epoch_store = st.session_state.setdefault("nc_view_epoch", {})
    view_bounds = bounds_store.get(file_key)
    epoch = epoch_store.get(file_key, 0)

    ctrl1, ctrl2 = st.columns([1, 4])
    with ctrl1:
        if st.button("⟲ Reset to full view", key=f"nc_reset_{file_key}",
                     disabled=view_bounds is None):
            bounds_store.pop(file_key, None)
            epoch_store[file_key] = epoch + 1
            st.rerun()
    with ctrl2:
        st.caption(
            "Use the **box select** tool (drag a rectangle) on the SST map to "
            "zoom in — the region re-renders at full resolution. Click "
            "**Reset to full view** to return to the global map."
        )

    fig_main, fig_aux = create_interactive_netcdf_plot(
        fields, filepath, view_bounds)

    event = st.plotly_chart(
        fig_main, use_container_width=True,
        key=f"nc_main_{file_key}_{epoch}",
        on_select="rerun", selection_mode="box"
    )

    # A fresh box selection (different from the stored view) -> zoom and rerun.
    new_bounds = _extract_box_bounds(event)
    if new_bounds is not None and new_bounds != view_bounds:
        bounds_store[file_key] = new_bounds
        st.rerun()

    st.plotly_chart(fig_aux, use_container_width=True,
                    key=f"nc_aux_{file_key}_{epoch}")


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

    elif format_type == 'nc':
        variables = data['variables']
        dimensions = data['dimensions']
        attributes = data['attributes']

        # Check if MUR GHRSST format
        is_mur_ghrsst = 'analysed_sst' in variables

        with col2:
            if is_mur_ghrsst:
                st.metric("Product", "MUR GHRSST L4")
            else:
                st.metric("Product", "Generic NetCDF")
        with col3:
            dim_str = " x ".join([f"{v:,}" for v in dimensions.values()])
            st.metric("Dimensions", dim_str)

        # Show title if available
        if 'title' in attributes:
            st.write(f"**Title:** {attributes['title']}")

        st.write("#### Dimensions")
        dim_cols = st.columns(len(dimensions))
        for i, (dim_name, dim_size) in enumerate(dimensions.items()):
            with dim_cols[i]:
                st.metric(dim_name, f"{dim_size:,}")

        st.write("#### Variables")
        var_names = list(variables.keys())
        # Show key variables first for MUR GHRSST
        if is_mur_ghrsst:
            key_vars = ['analysed_sst', 'analysis_error', 'mask',
                        'sea_ice_fraction', 'sst_anomaly']
            sorted_vars = [v for v in key_vars if v in var_names]
            sorted_vars += [v for v in var_names if v not in key_vars]
        else:
            sorted_vars = var_names

        for var_name in sorted_vars[:8]:  # Limit to 8 variables
            var = variables[var_name]
            shape = var['data'].shape if hasattr(var['data'], 'shape') else 'scalar'
            units = var['attributes'].get('units', '')
            long_name = var['attributes'].get('long_name', '')
            st.write(f"- **{var_name}**: {shape} {units}")
            if long_name:
                st.caption(f"  {long_name}")

        if len(sorted_vars) > 8:
            st.write(f"*... and {len(sorted_vars) - 8} more variables*")

        # SST statistics for MUR GHRSST
        if is_mur_ghrsst:
            st.write("#### SST Statistics")
            sst_var = variables['analysed_sst']
            # NOTE: netCDF4 auto-applies scale_factor and add_offset
            # So sst_data is already in Kelvin (NOT raw int16 values)
            sst_data = sst_var['data']

            # Get valid data (sample for speed)
            # netCDF4 auto-masks fill values, so use masked array handling
            sample_size = min(1000000, sst_data.size)
            flat = sst_data.flatten()
            if len(flat) > sample_size:
                indices = np.random.choice(len(flat), sample_size, replace=False)
                sample = flat[indices]
            else:
                sample = flat
            # Handle both masked arrays and regular arrays
            if isinstance(sample, np.ma.MaskedArray):
                valid = sample.compressed()  # Get non-masked values
            else:
                valid = sample[~np.isnan(sample)]
            if len(valid) > 0:
                # Data already in Kelvin, just convert to Celsius
                sst_celsius = valid - 273.15
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Mean SST", f"{sst_celsius.mean():.2f} °C")
                with col2:
                    st.metric("Std Dev", f"{sst_celsius.std():.2f} °C")
                with col3:
                    st.metric("Min SST", f"{sst_celsius.min():.2f} °C")
                with col4:
                    st.metric("Max SST", f"{sst_celsius.max():.2f} °C")
                st.caption(f"(Based on {len(valid):,} sampled points)")


def compare_files_data(
    data1: dict, data2: dict, format_type: str, tolerance: float = 1e-6
) -> dict:
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

    elif format_type == 'nc':
        # NetCDF comparison - delegates to the cached full-resolution diff
        # builder, then maps its results into this function's output schema.
        file1_path = data1.get('_filepath')
        file2_path = data2.get('_filepath')

        if not file1_path or not file2_path:
            results['comparisons'].append({
                'field': 'files',
                'match': False,
                'message': 'File paths not provided for NetCDF comparison'
            })
            results['all_match'] = False
            return results

        try:
            from netCDF4 import Dataset
        except ImportError:
            results['comparisons'].append({
                'field': 'netCDF4',
                'match': False,
                'message': 'netCDF4 package required'
            })
            results['all_match'] = False
            return results

        # Dimension check (cheap) before kicking off the full-res pass.
        with Dataset(file1_path, 'r') as ds1, Dataset(file2_path, 'r') as ds2:
            dims1 = {k: len(v) for k, v in ds1.dimensions.items()}
            dims2 = {k: len(v) for k, v in ds2.dimensions.items()}
            has_sst1 = 'analysed_sst' in ds1.variables
            has_sst2 = 'analysed_sst' in ds2.variables
            sst1_shape = ds1.variables['analysed_sst'].shape if has_sst1 else None
            sst2_shape = ds2.variables['analysed_sst'].shape if has_sst2 else None

        if dims1 == dims2:
            results['comparisons'].append({
                'field': 'dimensions',
                'match': True,
                'message': f"Match: {dims1}"
            })
        else:
            results['comparisons'].append({
                'field': 'dimensions',
                'match': False,
                'message': f"Different: {dims1} vs {dims2}"
            })
            results['all_match'] = False

        if not (has_sst1 and has_sst2):
            return results

        if sst1_shape != sst2_shape:
            results['comparisons'].append({
                'field': 'analysed_sst',
                'match': False,
                'message': f"Different shapes: {sst1_shape} vs {sst2_shape}"
            })
            results['all_match'] = False
            return results

        # Single full-resolution pass; cached for the plot to reuse.
        diff_info = get_or_build_diff(file1_path, file2_path,
                                      tolerance=tolerance)

        valid_count = diff_info['n_valid']
        if valid_count > 0:
            max_diff = diff_info['max_abs']
            mean_diff = diff_info['mean']
            rmse = diff_info['rmse']
            num_diff = diff_info['num_diff']
            pct_diff = diff_info['pct_diff']

            if num_diff == 0:
                results['comparisons'].append({
                    'field': 'analysed_sst',
                    'match': True,
                    'message': f"Match within tolerance ({valid_count:,} valid pixels)"
                })
            else:
                results['comparisons'].append({
                    'field': 'analysed_sst',
                    'match': False,
                    'message': (f"Differs: {num_diff:,} pixels "
                                f"({pct_diff:.4f}%), "
                                f"max={max_diff:.4f}K, "
                                f"mean={mean_diff:.6f}K, "
                                f"RMSE={rmse:.6f}K")
                })
                results['all_match'] = False

            worst_row = diff_info['worst_row']
            results['stats']['analysed_sst'] = {
                'max_diff': max_diff,
                'mean_diff': mean_diff,
                'rmse': rmse,
                'num_diff': num_diff,
                'pct_diff': pct_diff,
                'valid_count': valid_count,
                'tail_thresholds': diff_info['tail_thresholds'],
                'tail_counts': diff_info['tail_counts'],
                'worst_value': (diff_info['worst_value']
                                if worst_row >= 0 else None),
                'worst_lat': (diff_info['worst_lat']
                              if worst_row >= 0 else None),
                'worst_lon': (diff_info['worst_lon']
                              if worst_row >= 0 else None),
            }
        else:
            results['comparisons'].append({
                'field': 'analysed_sst',
                'match': True,
                'message': 'No valid overlapping data'
            })

    return results


def _max_abs_decimate(arr: np.ndarray, factor: int) -> np.ndarray:
    """Block-reduce a 2D array by ``factor`` along each axis, keeping the
    value with the largest absolute magnitude in each block (sign preserved).
    NaNs are ignored; all-NaN blocks yield NaN. Edge blocks are NaN-padded."""
    if factor <= 1:
        return arr
    h, w = arr.shape
    out_h = (h + factor - 1) // factor
    out_w = (w + factor - 1) // factor
    pad_h = out_h * factor - h
    pad_w = out_w * factor - w
    if pad_h or pad_w:
        arr = np.pad(arr, ((0, pad_h), (0, pad_w)), constant_values=np.nan)
    blocks = arr.reshape(out_h, factor, out_w, factor)
    blocks = blocks.transpose(0, 2, 1, 3).reshape(out_h, out_w, factor * factor)
    abs_blocks = np.abs(blocks)
    all_nan = np.all(np.isnan(abs_blocks), axis=-1)
    safe = np.where(np.isnan(abs_blocks), -np.inf, abs_blocks)
    idx = np.argmax(safe, axis=-1)
    out = np.take_along_axis(blocks, idx[..., None], axis=-1).squeeze(-1)
    out[all_nan] = np.nan
    return out


def build_full_res_diff(file1_path, file2_path, tolerance: float = 0.0001,
                        max_display: int = 2000,
                        chunk_rows: int = 1000) -> dict:
    """One full-resolution pass over the two NetCDF files.

    Materializes the full ``analysed_sst`` difference as a single in-memory
    ``float32`` image, then computes every downstream metric from it: summary
    statistics, tail-threshold counts, worst-pixel location, a fixed-edge
    histogram, and a max-abs decimated array for plotting. The full diff
    array is dropped before the function returns, so the cached result is
    small (~few MB).

    Diff is in Kelvin (== degrees Celsius for a difference). The valid
    GHRSST range [200, 350] K is applied per pixel before differencing.

    Memory peak (during the pass, before the diff array drops out of scope):
    ``nlat * nlon * 4`` bytes for the diff, plus ~120 MB of transient chunk
    buffers. For a global MUR pair (36000 x 17999) that's ~2.6 GB.
    """
    from netCDF4 import Dataset

    with Dataset(file1_path, 'r') as ds1, Dataset(file2_path, 'r') as ds2:
        if ('analysed_sst' not in ds1.variables
                or 'analysed_sst' not in ds2.variables):
            raise ValueError(
                'analysed_sst missing from one of the NetCDF files'
            )
        sv1 = ds1.variables['analysed_sst']
        sv2 = ds2.variables['analysed_sst']
        lon = np.asarray(ds1.variables['lon'][:])
        lat = np.asarray(ds1.variables['lat'][:])
        is_3d_1 = sv1.ndim == 3
        is_3d_2 = sv2.ndim == 3
        shape1 = sv1.shape[1:] if is_3d_1 else sv1.shape
        shape2 = sv2.shape[1:] if is_3d_2 else sv2.shape
        if shape1 != shape2:
            raise ValueError(
                f'analysed_sst shape mismatch: {shape1} vs {shape2}'
            )
        nlat, nlon = shape1
        if (nlat, nlon) != (len(lat), len(lon)):
            raise ValueError(
                f'coord shape ({len(lat)}, {len(lon)}) != data shape {shape1}'
            )

        subsample = max(1, max(nlon, nlat) // max_display)
        chunk_rows = max(1, chunk_rows)

        diff = np.full((nlat, nlon), np.nan, dtype=np.float32)

        for start in range(0, nlat, chunk_rows):
            end = min(start + chunk_rows, nlat)
            c1 = sv1[0, start:end, :] if is_3d_1 else sv1[start:end, :]
            c2 = sv2[0, start:end, :] if is_3d_2 else sv2[start:end, :]
            if hasattr(c1, 'filled'):
                c1 = c1.filled(np.nan)
            if hasattr(c2, 'filled'):
                c2 = c2.filled(np.nan)
            c1 = np.asarray(c1, dtype=np.float32)
            c2 = np.asarray(c2, dtype=np.float32)
            c1[(c1 < 200) | (c1 > 350)] = np.nan
            c2[(c2 < 200) | (c2 > 350)] = np.nan
            diff[start:end, :] = c1 - c2

    # Stats from the full diff image. Use float64 accumulators for accuracy.
    n_valid = int(np.count_nonzero(~np.isnan(diff)))
    tail_thresholds = [0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0]

    if n_valid > 0:
        sum_d = float(np.nansum(diff, dtype=np.float64))
        sq_temp = np.multiply(diff, diff, dtype=np.float32)  # ~2.6 GB transient
        sum_sq = float(np.nansum(sq_temp, dtype=np.float64))
        del sq_temp
        mean = sum_d / n_valid
        var = max(0.0, sum_sq / n_valid - mean * mean)
        std = float(np.sqrt(var))
        rmse = float(np.sqrt(sum_sq / n_valid))
        min_d = float(np.nanmin(diff))
        max_d = float(np.nanmax(diff))

        abs_diff = np.abs(diff)  # ~2.6 GB transient
        max_abs = float(np.nanmax(abs_diff))
        tail_counts = [int(np.nansum(abs_diff > t)) for t in tail_thresholds]
        num_diff = int(np.nansum(abs_diff > tolerance))
        pct_diff = 100.0 * num_diff / n_valid
        flat_idx = int(np.nanargmax(abs_diff))
        worst_row, worst_col = (int(x) for x in np.unravel_index(flat_idx,
                                                                 diff.shape))
        worst_value = float(diff[worst_row, worst_col])
        worst_lat = float(lat[worst_row])
        worst_lon = float(lon[worst_col])
        del abs_diff

        HIST_LO, HIST_HI, HIST_N = -10.0, 10.0, 200
        hist_edges = np.linspace(HIST_LO, HIST_HI, HIST_N + 1)
        # np.histogram drops NaN and out-of-range values
        hist_counts, _ = np.histogram(diff, bins=hist_edges)
        overflow_low = int(np.nansum(diff < HIST_LO))
        overflow_high = int(np.nansum(diff > HIST_HI))
    else:
        mean = std = rmse = 0.0
        min_d = max_d = max_abs = 0.0
        tail_counts = [0] * len(tail_thresholds)
        num_diff = 0
        pct_diff = 0.0
        worst_row = worst_col = -1
        worst_value = 0.0
        worst_lat = worst_lon = 0.0
        hist_edges = np.linspace(-10.0, 10.0, 201)
        hist_counts = np.zeros(200, dtype=np.int64)
        overflow_low = overflow_high = 0

    diff_plot = _max_abs_decimate(diff, subsample)
    lon_plot = lon[::subsample][: diff_plot.shape[1]]
    lat_plot = lat[::subsample][: diff_plot.shape[0]]

    # `diff` goes out of scope here; only derived (small) artifacts returned.
    return {
        'shape': (nlat, nlon),
        'lon': lon,
        'lat': lat,
        'subsample': subsample,
        'n_valid': n_valid,
        'mean': mean,
        'std': std,
        'rmse': rmse,
        'min': min_d,
        'max': max_d,
        'max_abs': max_abs,
        'num_diff': num_diff,
        'pct_diff': pct_diff,
        'tolerance': tolerance,
        'tail_thresholds': tail_thresholds,
        'tail_counts': tail_counts,
        'worst_row': worst_row,
        'worst_col': worst_col,
        'worst_value': worst_value,
        'worst_lat': worst_lat,
        'worst_lon': worst_lon,
        'hist_counts': hist_counts,
        'hist_edges': hist_edges,
        'overflow_low': overflow_low,
        'overflow_high': overflow_high,
        'diff_plot': diff_plot,
        'lon_plot': lon_plot,
        'lat_plot': lat_plot,
    }


def get_or_build_diff(file1_path, file2_path,
                      tolerance: float = 0.0001) -> dict:
    """Session-cached wrapper around :func:`build_full_res_diff`.

    Keyed by file paths + mtimes + tolerance. Only the most recent result is
    retained to bound memory.
    """
    try:
        mt1 = os.path.getmtime(file1_path)
        mt2 = os.path.getmtime(file2_path)
    except OSError:
        mt1 = mt2 = 0.0
    key = ('full_res_diff', str(file1_path), str(file2_path),
           mt1, mt2, float(tolerance))
    cache = st.session_state.setdefault('_diff_cache', {})
    if key not in cache:
        cache.clear()
        cache[key] = build_full_res_diff(file1_path, file2_path,
                                         tolerance=tolerance)
    return cache[key]


def _region_diff_stats(diff: np.ndarray) -> dict:
    """Summary stats + fixed-edge histogram for an in-memory diff image.

    Uses the same metric definitions and histogram edges as
    :func:`build_full_res_diff` so a zoomed region's numbers stay consistent
    with the global pass.
    """
    n_valid = int(np.count_nonzero(~np.isnan(diff)))
    HIST_LO, HIST_HI, HIST_N = -10.0, 10.0, 200
    hist_edges = np.linspace(HIST_LO, HIST_HI, HIST_N + 1)
    if n_valid > 0:
        sum_d = float(np.nansum(diff, dtype=np.float64))
        mean = sum_d / n_valid
        sq = np.multiply(diff, diff, dtype=np.float32)
        sum_sq = float(np.nansum(sq, dtype=np.float64))
        del sq
        var = max(0.0, sum_sq / n_valid - mean * mean)
        std = float(np.sqrt(var))
        rmse = float(np.sqrt(sum_sq / n_valid))
        min_d = float(np.nanmin(diff))
        max_d = float(np.nanmax(diff))
        hist_counts, _ = np.histogram(diff, bins=hist_edges)
        overflow_low = int(np.nansum(diff < HIST_LO))
        overflow_high = int(np.nansum(diff > HIST_HI))
    else:
        mean = std = rmse = min_d = max_d = 0.0
        hist_counts = np.zeros(HIST_N, dtype=np.int64)
        overflow_low = overflow_high = 0
    return {
        'n_valid': n_valid, 'mean': mean, 'std': std, 'rmse': rmse,
        'min': min_d, 'max': max_d,
        'hist_counts': hist_counts, 'hist_edges': hist_edges,
        'overflow_low': overflow_low, 'overflow_high': overflow_high,
    }


def build_region_diff(file1_path, file2_path, view_bounds,
                      target: int = 2000, chunk_rows: int = 1000) -> dict:
    """Full-resolution ``analysed_sst`` difference for one lon/lat sub-region.

    Reads only the rows/columns covering ``view_bounds`` from both NetCDF
    files (chunked to bound memory), differences them at native resolution,
    then max-abs decimates the region to ~``target`` px for display. This
    powers the box-select "zoom re-renders at full resolution" behavior of the
    Plotly comparison view, mirroring the single-file viewer.

    Diff is in Kelvin (== °C for a difference); the valid GHRSST range
    [200, 350] K is applied per pixel before differencing, matching
    :func:`build_full_res_diff`.

    Returns a dict with the decimated region image (``diff_plot``), its
    coordinate axes (``lon_plot``/``lat_plot``), the decimation ``factor``,
    and region-only summary stats + a fixed-edge histogram.
    """
    from netCDF4 import Dataset

    with Dataset(file1_path, 'r') as ds1, Dataset(file2_path, 'r') as ds2:
        if ('analysed_sst' not in ds1.variables
                or 'analysed_sst' not in ds2.variables):
            raise ValueError(
                'analysed_sst missing from one of the NetCDF files')
        lon = np.asarray(ds1.variables['lon'][:])
        lat = np.asarray(ds1.variables['lat'][:])
        lon_slice, lat_slice = slice_to_bounds(lon, lat, view_bounds)

        sv1 = ds1.variables['analysed_sst']
        sv2 = ds2.variables['analysed_sst']
        is_3d_1 = sv1.ndim == 3
        is_3d_2 = sv2.ndim == 3
        shape1 = sv1.shape[1:] if is_3d_1 else sv1.shape
        shape2 = sv2.shape[1:] if is_3d_2 else sv2.shape
        if shape1 != shape2:
            raise ValueError(
                f'analysed_sst shape mismatch: {shape1} vs {shape2}')

        lat0, lat1 = lat_slice.start, lat_slice.stop
        nlat_r = lat1 - lat0
        nlon_r = lon_slice.stop - lon_slice.start
        # Region diff held at full res; chunked reads keep the two source
        # arrays from being resident simultaneously (peak ~ region + a chunk).
        diff = np.full((nlat_r, nlon_r), np.nan, dtype=np.float32)
        step = max(1, chunk_rows)
        for start in range(lat0, lat1, step):
            end = min(start + step, lat1)
            c1 = (sv1[0, start:end, lon_slice] if is_3d_1
                  else sv1[start:end, lon_slice])
            c2 = (sv2[0, start:end, lon_slice] if is_3d_2
                  else sv2[start:end, lon_slice])
            if hasattr(c1, 'filled'):
                c1 = c1.filled(np.nan)
            if hasattr(c2, 'filled'):
                c2 = c2.filled(np.nan)
            c1 = np.asarray(c1, dtype=np.float32)
            c2 = np.asarray(c2, dtype=np.float32)
            c1[(c1 < 200) | (c1 > 350)] = np.nan
            c2[(c2 < 200) | (c2 > 350)] = np.nan
            diff[start - lat0:end - lat0, :] = c1 - c2

    lon_r = lon[lon_slice]
    lat_r = lat[lat_slice]
    factor = max(1, int(np.ceil(max(nlat_r, nlon_r) / float(target))))
    diff_plot = _max_abs_decimate(diff, factor)
    lon_plot = lon_r[::factor][: diff_plot.shape[1]]
    lat_plot = lat_r[::factor][: diff_plot.shape[0]]

    stats = _region_diff_stats(diff)
    del diff  # drop the full-res region image before returning
    stats.update({
        'diff_plot': diff_plot,
        'lon_plot': lon_plot,
        'lat_plot': lat_plot,
        'factor': factor,
        'region_shape': (nlat_r, nlon_r),
    })
    return stats


def get_or_build_region_diff(file1_path, file2_path, view_bounds) -> dict:
    """Session-cached wrapper around :func:`build_region_diff`.

    Keyed by file paths + mtimes + (rounded) view bounds. Only the most recent
    region is retained so repeated reruns at one zoom level don't re-read the
    files, while panning/zooming to a new region drops the previous one.
    """
    try:
        mt1 = os.path.getmtime(file1_path)
        mt2 = os.path.getmtime(file2_path)
    except OSError:
        mt1 = mt2 = 0.0
    bkey = (tuple(round(float(b), 6) for b in view_bounds)
            if view_bounds is not None else None)
    key = ('region_diff', str(file1_path), str(file2_path), mt1, mt2, bkey)
    cache = st.session_state.setdefault('_region_diff_cache', {})
    if key not in cache:
        cache.clear()
        cache[key] = build_region_diff(file1_path, file2_path, view_bounds)
    return cache[key]


def _diff_color_limit(diff_info: dict, override: float = 0.0) -> float:
    """Robust ±color limit for the SST difference image.

    If ``override`` is greater than 0, it is used directly (e.g. ``0.5`` →
    color range ±0.5°C). Otherwise the limit is derived from the
    full-resolution streaming histogram in ``diff_info``:
    ±max(|2nd pct|, |98th pct|), capped at 5°C. Shared by the matplotlib and
    Plotly comparison renderers so both use identical limits.
    """
    if override and override > 0:
        return float(override)

    n_valid = diff_info['n_valid']
    if n_valid <= 0:
        return 5.0

    hist_counts = diff_info['hist_counts']
    hist_edges = diff_info['hist_edges']
    overflow_low = diff_info['overflow_low']
    overflow_high = diff_info['overflow_high']

    total = hist_counts.sum() + overflow_low + overflow_high
    cum = np.cumsum(hist_counts) + overflow_low
    target_lo = 0.02 * total
    target_hi = 0.98 * total
    # Place overflow at the edges (-10 / +10 °C) for limit computation
    if overflow_low >= target_lo:
        lo = -10.0
    else:
        lo_idx = int(np.searchsorted(cum, target_lo))
        lo = hist_edges[min(lo_idx, len(hist_edges) - 1)]
    if (total - overflow_high) <= target_hi:
        hi = 10.0
    else:
        hi_idx = int(np.searchsorted(cum, target_hi))
        hi = hist_edges[min(hi_idx, len(hist_edges) - 1)]
    diff_limit = min(5.0, max(abs(lo), abs(hi)))
    return diff_limit if diff_limit != 0 else 1e-6


def _discrete_colorscale(name: str, n: int, reverse: bool = False):
    """Build a piecewise-constant Plotly colorscale of ``n`` bands sampled
    from the named continuous scale (e.g. ``'RdBu'``). Used to quantize the
    difference heatmap into a fixed number of colors."""
    import plotly.colors as pc

    n = max(2, int(n))
    positions = [i / (n - 1) for i in range(n)]
    colors = pc.sample_colorscale(name, positions, colortype='rgb')
    if reverse:
        colors = colors[::-1]
    scale = []
    for i, c in enumerate(colors):
        scale.append([i / n, c])
        scale.append([(i + 1) / n, c])
    return scale


def create_comparison_plot(data1: dict, data2: dict, format_type: str,
                           file1_name: str, file2_name: str,
                           diff_color_limit: float = 0.0,
                           diff_color_levels: int = 0) -> plt.Figure:
    """
    Create a comparison visualization showing both datasets and their difference.

    Args:
        data1: First data dictionary
        data2: Second data dictionary
        format_type: File format type
        file1_name: Name of first file
        file2_name: Name of second file
        diff_color_limit: Manual ±color limit (°C) for the NetCDF difference
            image; 0 (default) auto-scales from the difference histogram.
        diff_color_levels: Number of discrete color bands for the NetCDF
            difference image; 0 (default) uses a continuous colormap.

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

    elif format_type == 'nc':
        # NetCDF comparison: pull the cached full-resolution diff (built once
        # per file pair) and plot the max-abs decimated array with full-res
        # stats from the same single in-memory diff image.
        file1_path = data1.get('_filepath')
        file2_path = data2.get('_filepath')

        if not file1_path or not file2_path:
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.text(0.5, 0.5,
                    'NetCDF comparison requires file paths\n'
                    '(re-open the files via the comparison UI)',
                    ha='center', va='center', fontsize=14)
            ax.axis('off')
            return fig

        try:
            diff_info = get_or_build_diff(file1_path, file2_path)
        except ValueError as exc:
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.text(0.5, 0.5, str(exc),
                    ha='center', va='center', fontsize=14)
            ax.axis('off')
            return fig
        except ImportError:
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.text(0.5, 0.5, 'netCDF4 package required',
                    ha='center', va='center', fontsize=14)
            ax.axis('off')
            return fig

        diff_plot = diff_info['diff_plot']
        lon_plot = diff_info['lon_plot']
        lat_plot = diff_info['lat_plot']

        n_valid = diff_info['n_valid']
        mean_diff = diff_info['mean']
        std_diff = diff_info['std']
        rmse = diff_info['rmse']
        min_diff = diff_info['min']
        max_diff = diff_info['max']
        hist_counts = diff_info['hist_counts']
        hist_edges = diff_info['hist_edges']
        overflow_low = diff_info['overflow_low']
        overflow_high = diff_info['overflow_high']

        # Robust color limits from the full-resolution streaming histogram,
        # unless the caller pinned an explicit ±limit.
        diff_limit = _diff_color_limit(diff_info, override=diff_color_limit)

        fig = plt.figure(figsize=(14, 10), constrained_layout=True)
        gs = fig.add_gridspec(2, 1, height_ratios=[2, 1])

        ax_diff = fig.add_subplot(gs[0])
        diff_cmap = 'RdBu_r'
        if diff_color_levels and diff_color_levels >= 2:
            diff_cmap = plt.colormaps['RdBu_r'].resampled(int(diff_color_levels))
        im_diff = ax_diff.pcolormesh(lon_plot, lat_plot, diff_plot,
                                     cmap=diff_cmap,
                                     vmin=-diff_limit, vmax=diff_limit,
                                     shading='nearest')
        ax_diff.set_xlabel('Longitude (degrees)', fontsize=11)
        ax_diff.set_ylabel('Latitude (degrees)', fontsize=11)

        if n_valid > 0:
            ax_diff.set_title(
                f'SST Difference: {file1_name} - {file2_name}\n'
                f'Mean: {mean_diff:.4f}°C | Std: {std_diff:.4f}°C | '
                f'RMSE: {rmse:.4f}°C | Color range: ±{diff_limit:.2f}°C '
                f'(max-abs decimation, full-res stats)',
                fontsize=12, fontweight='bold'
            )
        else:
            ax_diff.set_title(
                f'SST Difference: {file1_name} - {file2_name}',
                fontsize=12, fontweight='bold'
            )

        ax_diff.set_aspect('equal', adjustable='box')
        ax_diff.grid(True, alpha=0.3)
        plt.colorbar(im_diff, ax=ax_diff, label='Difference (°C)',
                     shrink=0.8, pad=0.02)

        ax_hist = fig.add_subplot(gs[1])
        if n_valid > 0 and hist_counts.sum() > 0:
            bin_centers = 0.5 * (hist_edges[:-1] + hist_edges[1:])
            ax_hist.bar(bin_centers, hist_counts,
                        width=(hist_edges[1] - hist_edges[0]),
                        edgecolor='black', alpha=0.7, color='steelblue')
            ax_hist.axvline(x=0, color='r', linestyle='--', linewidth=2,
                            label='Zero')
            ax_hist.axvline(x=mean_diff, color='orange',
                            linestyle='-', linewidth=2, label='Mean')
            ax_hist.set_xlabel('Difference (°C)', fontsize=11)
            ax_hist.set_ylabel('Count', fontsize=11)
            ax_hist.set_title('Difference Distribution (full resolution)',
                              fontsize=12)
            ax_hist.legend(loc='upper right')
            ax_hist.grid(True, alpha=0.3)

            overflow_note = ''
            if overflow_low or overflow_high:
                overflow_note = (
                    f"\nClipped: {overflow_low:,} < -10°C, "
                    f"{overflow_high:,} > +10°C"
                )
            stats_text = (
                f"N valid: {n_valid:,}\n"
                f"Mean: {mean_diff:.4f}°C\n"
                f"Std: {std_diff:.4f}°C\n"
                f"Min: {min_diff:.4f}°C\n"
                f"Max: {max_diff:.4f}°C\n"
                f"RMSE: {rmse:.4f}°C"
                f"{overflow_note}"
            )
            ax_hist.text(0.98, 0.98, stats_text,
                         transform=ax_hist.transAxes,
                         verticalalignment='top',
                         horizontalalignment='right',
                         bbox=dict(boxstyle='round', facecolor='wheat',
                                   alpha=0.8),
                         fontsize=10, family='monospace')
        else:
            ax_hist.text(0.5, 0.5, 'No valid difference data',
                         ha='center', va='center', fontsize=14)
            ax_hist.set_title('Difference Distribution')

        return fig

    else:
        # Unsupported format
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5,
                f'Comparison visualization not implemented for {format_type} format',
                ha='center', va='center', fontsize=14)
        ax.axis('off')
        return fig


def create_comparison_plot_interactive(data1: dict, data2: dict,
                                       format_type: str,
                                       file1_name: str, file2_name: str,
                                       diff_color_limit: float = 0.0,
                                       diff_color_levels: int = 0,
                                       view_bounds: Optional[tuple] = None):
    """Interactive Plotly version of the comparison visualization.

    Renders the ``analysed_sst`` difference as a box-select-enabled
    zoom/pan/hover heatmap plus a difference histogram. When ``view_bounds`` is
    ``None`` the global view uses the cached, max-abs-decimated full-resolution
    diff from :func:`get_or_build_diff`. When a box is selected the region is
    re-read from both files at native resolution via
    :func:`get_or_build_region_diff`, so zooming in reveals progressively more
    detail (down to native pixels) — matching the single-file viewer.

    The color limit is always derived from the *global* difference histogram
    (or the manual override) so colors stay stable across zoom levels; the
    histogram and summary stats reflect the currently-viewed region.

    Returns ``(fig_main, fig_aux)`` — the selection-enabled difference map and
    its companion histogram figure — or ``None`` for formats/conditions
    without an interactive view so the caller can fall back to matplotlib.

    Args:
        diff_color_limit: Manual ±color limit (°C); 0 auto-scales from the
            difference histogram.
        diff_color_levels: Number of discrete color bands; 0 uses a continuous
            colorscale.
        view_bounds: (lon_min, lon_max, lat_min, lat_max) of the zoomed region,
            or None for the global view.
    """
    if format_type != 'nc':
        return None

    file1_path = data1.get('_filepath')
    file2_path = data2.get('_filepath')
    if not file1_path or not file2_path:
        return None

    import plotly.graph_objects as go

    # Global pass (cached). Provides the stable color limit and the global
    # decimated image used when not zoomed in. May raise ValueError (shape
    # mismatch) / ImportError; the caller catches and falls back to matplotlib.
    diff_info = get_or_build_diff(file1_path, file2_path)
    diff_limit = _diff_color_limit(diff_info, override=diff_color_limit)

    # Region-aware data: cached global decimation for the full view, or a
    # freshly read full-resolution slice when zoomed in.
    if view_bounds is None:
        stats = diff_info
        diff_plot = diff_info['diff_plot']
        lon_plot = diff_info['lon_plot']
        lat_plot = diff_info['lat_plot']
        factor = diff_info['subsample']
        region_note = 'Full globe'
    else:
        stats = get_or_build_region_diff(file1_path, file2_path, view_bounds)
        diff_plot = stats['diff_plot']
        lon_plot = stats['lon_plot']
        lat_plot = stats['lat_plot']
        factor = stats['factor']
        if len(lon_plot) and len(lat_plot):
            region_note = (
                f'Lon [{float(np.nanmin(lon_plot)):.2f}, '
                f'{float(np.nanmax(lon_plot)):.2f}], '
                f'Lat [{float(np.nanmin(lat_plot)):.2f}, '
                f'{float(np.nanmax(lat_plot)):.2f}]')
        else:
            region_note = 'Selected region'

    n_valid = stats['n_valid']
    mean_diff = stats['mean']
    std_diff = stats['std']
    rmse = stats['rmse']
    min_diff = stats['min']
    max_diff = stats['max']
    hist_counts = stats['hist_counts']
    hist_edges = stats['hist_edges']
    overflow_low = stats['overflow_low']
    overflow_high = stats['overflow_high']

    limit_note = (f'manual ±{diff_limit:.3g}°C' if diff_color_limit and
                  diff_color_limit > 0 else f'auto ±{diff_limit:.2f}°C')
    detail = 'native resolution' if factor == 1 else f'÷{factor} of full'
    if n_valid > 0:
        diff_title = (
            f'SST Difference: {file1_name} - {file2_name}<br>'
            f'<sub>{region_note} | Mean {mean_diff:.4f}°C | '
            f'Std {std_diff:.4f}°C | RMSE {rmse:.4f}°C | '
            f'Color range {limit_note} ({detail}, max-abs)</sub>'
        )
    else:
        diff_title = (f'SST Difference: {file1_name} - {file2_name}'
                      f'<br><sub>{region_note}</sub>')

    # ----- Main difference map (box-select enabled, standalone figure) -----
    # Quantize into discrete bands when requested, else continuous RdBu.
    if diff_color_levels and diff_color_levels >= 2:
        heat_colorscale = _discrete_colorscale('RdBu', diff_color_levels,
                                               reverse=True)
        heat_reverse = False
    else:
        heat_colorscale = 'RdBu'
        heat_reverse = True

    fig_main = go.Figure()
    fig_main.add_trace(
        go.Heatmap(
            z=diff_plot, x=lon_plot, y=lat_plot,
            colorscale=heat_colorscale, reversescale=heat_reverse,
            zmin=-diff_limit, zmax=diff_limit, zmid=0.0,
            colorbar=dict(title='Diff (°C)'),
            hovertemplate=('lon %{x:.3f}°<br>lat %{y:.3f}°<br>'
                           'diff %{z:.4f} °C<extra></extra>'),
        )
    )
    fig_main.update_layout(
        title=diff_title, height=650,
        margin=dict(t=90, b=50, l=60, r=20),
        dragmode='select', showlegend=False,
    )
    fig_main.update_xaxes(title_text='Longitude (°)')
    fig_main.update_yaxes(title_text='Latitude (°)',
                          scaleanchor='x', scaleratio=1.0)

    # ----- Companion difference histogram -----
    hist_title = ('Difference Distribution (visible region)'
                  if view_bounds is not None
                  else 'Difference Distribution (full resolution)')
    fig_aux = go.Figure()
    if n_valid > 0 and hist_counts.sum() > 0:
        bin_centers = 0.5 * (hist_edges[:-1] + hist_edges[1:])
        fig_aux.add_trace(
            go.Bar(
                x=bin_centers, y=hist_counts,
                width=(hist_edges[1] - hist_edges[0]),
                marker_color='steelblue', marker_line_color='black',
                marker_line_width=0.3, opacity=0.8,
                hovertemplate='diff %{x:.3f}°C<br>%{y:,} px<extra></extra>',
                showlegend=False,
            )
        )
        fig_aux.add_vline(x=0.0, line_dash='dash', line_color='red',
                          line_width=2)
        fig_aux.add_vline(x=mean_diff, line_color='orange', line_width=2)
        fig_aux.update_xaxes(title_text='Difference (°C)')
        fig_aux.update_yaxes(title_text='Count')

        overflow_note = ''
        if overflow_low or overflow_high:
            overflow_note = (f'<br>Clipped: {overflow_low:,} < -10°C, '
                             f'{overflow_high:,} > +10°C')
        stats_text = (
            f'N valid: {n_valid:,}<br>'
            f'Mean: {mean_diff:.4f}°C<br>'
            f'Std: {std_diff:.4f}°C<br>'
            f'Min: {min_diff:.4f}°C<br>'
            f'Max: {max_diff:.4f}°C<br>'
            f'RMSE: {rmse:.4f}°C{overflow_note}'
        )
        fig_aux.add_annotation(
            xref='x domain', yref='y domain', x=0.99, y=0.98,
            xanchor='right', yanchor='top', align='right',
            text=stats_text, showarrow=False,
            font=dict(size=11, family='monospace'),
            bgcolor='wheat', opacity=0.85, bordercolor='black',
            borderwidth=1,
        )
    else:
        fig_aux.add_annotation(
            xref='x domain', yref='y domain', x=0.5, y=0.5,
            text='No valid difference data', showarrow=False,
            font=dict(size=14),
        )
    fig_aux.update_layout(height=320, title=hist_title,
                          margin=dict(t=50, b=50, l=60, r=20), bargap=0)

    return fig_main, fig_aux


def _render_comparison_plotly(data1: dict, data2: dict, format_type: str,
                              file1_name: str, file2_name: str,
                              diff_color_limit: float = 0.0,
                              diff_color_levels: int = 0) -> bool:
    """Render the Plotly comparison view with box-select driven, view-aware
    full-resolution re-rendering of the SST difference.

    Mirrors :func:`_render_netcdf_plotly`: drawing a box on the difference map
    stores its lon/lat bounds in session state and reruns so the region
    re-reads from both files at native resolution. A reset button returns to
    the global view, bumping a per-pair "epoch" so the chart gets a fresh
    widget key and its stale box selection is cleared.

    Returns True if an interactive view was rendered, False if this
    format/condition has no interactive comparison (caller falls back to
    matplotlib).
    """
    file1_path = data1.get('_filepath')
    file2_path = data2.get('_filepath')
    if format_type != 'nc' or not file1_path or not file2_path:
        return False

    pair_key = f"{file1_path}|{file2_path}"
    bounds_store = st.session_state.setdefault('cmp_view_bounds', {})
    epoch_store = st.session_state.setdefault('cmp_view_epoch', {})
    view_bounds = bounds_store.get(pair_key)
    epoch = epoch_store.get(pair_key, 0)

    ctrl1, ctrl2 = st.columns([1, 4])
    with ctrl1:
        if st.button('⟲ Reset to full view', key=f'cmp_reset_{pair_key}',
                     disabled=view_bounds is None):
            bounds_store.pop(pair_key, None)
            epoch_store[pair_key] = epoch + 1
            st.rerun()
    with ctrl2:
        st.caption(
            'Use the **box select** tool (drag a rectangle) on the difference '
            'map to zoom in — the region re-renders at full resolution. Click '
            '**Reset to full view** to return to the global map.'
        )

    figs = create_comparison_plot_interactive(
        data1, data2, format_type, file1_name, file2_name,
        diff_color_limit=diff_color_limit,
        diff_color_levels=diff_color_levels,
        view_bounds=view_bounds,
    )
    if figs is None:
        return False
    fig_main, fig_aux = figs

    event = st.plotly_chart(
        fig_main, use_container_width=True,
        key=f'cmp_main_{pair_key}_{epoch}',
        on_select='rerun', selection_mode='box',
    )

    # A fresh box selection (different from the stored view) -> zoom and rerun.
    new_bounds = _extract_box_bounds(event)
    if new_bounds is not None and new_bounds != view_bounds:
        bounds_store[pair_key] = new_bounds
        st.rerun()

    st.plotly_chart(fig_aux, use_container_width=True,
                    key=f'cmp_aux_{pair_key}_{epoch}')
    return True


def check_password() -> bool:
    """Prompt for a password and return True if correct.

    The expected password is read from .streamlit/secrets.toml (key: app_password).
    If no password is configured, access is granted without a prompt.
    """
    try:
        correct_password = st.secrets["app_password"]
    except (KeyError, FileNotFoundError):
        # No password configured – allow access
        return True

    if st.session_state.get("authenticated"):
        return True

    st.title("MUR Data Viewer")
    st.markdown("Please enter the password to continue.")
    password = st.text_input("Password", type="password", key="_password_input")
    if password:
        if password == correct_password:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


def main():
    """Main Streamlit application."""

    if not check_password():
        return

    # Title and description
    st.title("MUR Data Viewer")
    st.markdown("Web-based interface for MUR SST processing data files")

    # Get base directory
    base_dir = get_base_directory()

    # Initialize session state
    if 'selected_file_path' not in st.session_state:
        st.session_state.selected_file_path = None
    if 'reference_file' not in st.session_state:
        st.session_state.reference_file = None
    if 'reference_data' not in st.session_state:
        st.session_state.reference_data = None
    if 'reference_format' not in st.session_state:
        st.session_state.reference_format = None

    # Sidebar options
    st.sidebar.header("Options")

    # Mode selector
    mode = st.sidebar.radio(
        "Mode:",
        ["View File", "Compare Files"],
    )

    # Display options
    st.sidebar.write("---")
    st.sidebar.write("**Display Options:**")
    show_info = st.sidebar.checkbox("Show file info", value=True)

    plot_type = st.sidebar.radio(
        "Plot type:",
        ["Matplotlib (Fast)", "Plotly (Interactive)"],
        help="Matplotlib is faster. Plotly allows zoom/pan."
    )
    use_plotly = plot_type.startswith("Plotly")

    # Defaults (overridden in the sidebar when Compare mode is selected)
    tolerance = 1e-6
    diff_color_limit = 0.0
    diff_color_levels = 0

    # Compare mode: reference file status
    if mode == "Compare Files":
        st.sidebar.write("---")
        st.sidebar.write("**Reference File:**")
        if st.session_state.reference_file:
            st.sidebar.success(f"`{Path(st.session_state.reference_file).name}`")
            if st.sidebar.button("Clear Reference", use_container_width=True):
                st.session_state.reference_file = None
                st.session_state.reference_data = None
                st.session_state.reference_format = None
                st.rerun()
        else:
            st.sidebar.info("No reference set")

        tolerance = st.sidebar.number_input(
            "Comparison tolerance:",
            min_value=1e-10,
            max_value=1.0,
            value=1e-6,
            format="%.2e",
        )

        diff_color_limit = st.sidebar.number_input(
            "Diff color scale ±°C (0 = auto):",
            min_value=0.0,
            max_value=20.0,
            value=0.0,
            step=0.1,
            format="%.3g",
            help="NetCDF difference image color range. 0 auto-scales from the "
                 "difference histogram; e.g. 0.5 pins the range to -0.5…+0.5°C.",
        )

        diff_color_levels = st.sidebar.number_input(
            "Diff color levels (0 = continuous):",
            min_value=0,
            max_value=256,
            value=0,
            step=1,
            help="Number of discrete colors for the NetCDF difference image. "
                 "0 uses a continuous colormap (default); e.g. 8 buckets the "
                 "range into 8 colors.",
        )

    # Initialize directory navigation state
    if 'current_dir' not in st.session_state:
        st.session_state.current_dir = str(base_dir)

    current_dir = Path(st.session_state.current_dir)
    if not current_dir.exists():
        current_dir = base_dir
        st.session_state.current_dir = str(base_dir)

    # Sidebar file browser
    st.sidebar.write("---")
    st.sidebar.write("**File Browser:**")

    # Show data root with expander to change it
    with st.sidebar.expander("Data Root", expanded=False):
        st.caption(f"Current: `{base_dir}`")
        st.caption("Set via MUR_BASE_DIR environment variable")
        new_root = st.text_input(
            "Change root:",
            value=str(base_dir),
            key="new_base_dir",
            label_visibility="collapsed",
        )
        if new_root and Path(new_root).exists() and Path(new_root).is_dir():
            if str(Path(new_root).resolve()) != str(base_dir):
                if st.button("Apply", use_container_width=True):
                    st.session_state.current_dir = new_root
                    os.environ['MUR_BASE_DIR'] = new_root
                    st.rerun()

    # Show current path as clickable breadcrumbs
    try:
        rel_path = current_dir.relative_to(base_dir)
        is_relative = True
    except ValueError:
        rel_path = current_dir
        is_relative = False

    # Build breadcrumb path segments
    if is_relative and str(rel_path) != '.':
        path_parts = list(rel_path.parts)
    else:
        path_parts = []

    # Display path with clickable segments
    if not path_parts:
        # At root
        st.sidebar.markdown("**Path:** `/`")
    else:
        # Root link
        if st.sidebar.button("🏠", key="nav_root", help="Go to root"):
            st.session_state.current_dir = str(base_dir)
            st.rerun()

        # Show path as text, with "Jump to" selectbox for ancestors
        path_display = " / ".join(path_parts)
        st.sidebar.caption(f"📂 {path_display}")

        # Build ancestor paths for navigation (exclude current dir)
        if len(path_parts) > 1:
            ancestor_options = ["(jump to parent...)"]
            ancestor_paths = [None]  # Placeholder for index 0

            for i in range(len(path_parts) - 1):
                ancestor_path = base_dir / Path(*path_parts[:i + 1])
                label = "/" + "/".join(path_parts[:i + 1])
                ancestor_options.append(label)
                ancestor_paths.append(ancestor_path)

            selected = st.sidebar.selectbox(
                "Jump to:",
                range(len(ancestor_options)),
                format_func=lambda i: ancestor_options[i],
                key="breadcrumb_jump",
                label_visibility="collapsed",
            )

            # Only navigate if user selected an actual path (not placeholder)
            if selected > 0 and ancestor_paths[selected] is not None:
                st.session_state.current_dir = str(ancestor_paths[selected])
                # Reset selectbox to avoid infinite rerun loop
                st.session_state.breadcrumb_jump = 0
                st.rerun()

    # Folder dropdown - build list of navigation options
    folder_options = []
    folder_paths = []

    # Add parent option if not at root
    if current_dir != base_dir:
        parent = current_dir.parent
        try:
            parent.relative_to(base_dir)
            folder_options.append(".. (parent)")
            folder_paths.append(parent)
        except ValueError:
            pass

    # Add subdirectories
    try:
        subdirs = sorted([d for d in current_dir.iterdir() if d.is_dir()])
        for subdir in subdirs:
            folder_options.append(f"{subdir.name}/")
            folder_paths.append(subdir)
    except PermissionError:
        pass

    # Folder selector dropdown
    if folder_options:
        folder_names = ["(current folder)"] + folder_options
        folder_idx = st.sidebar.selectbox(
            "Folder:",
            range(len(folder_names)),
            format_func=lambda i: folder_names[i],
            key="folder_select",
        )
        if folder_idx > 0:
            new_dir = folder_paths[folder_idx - 1]
            if str(new_dir) != st.session_state.current_dir:
                st.session_state.current_dir = str(new_dir)
                st.rerun()
    else:
        st.sidebar.caption("No subfolders")

    # List files with supported extensions
    supported_patterns = [
        "*.nc", "*.nc4",
        "*.bip", "*.biq", "*.bii", "*.bic", "*.bin",
        "*.gds", "*.map",
        "*.c[0-9]*", "*.u[0-9]*",
        "*.gz",
    ]
    files = []
    for pattern in supported_patterns:
        files.extend(current_dir.glob(pattern))
    # Sort by modification time (newest first)
    files = sorted(set(files), key=lambda f: f.stat().st_mtime, reverse=True)

    # File selector dropdown
    selected_file = None
    if files:
        # Use file paths as string options (more reliable than indices)
        file_path_strs = [""] + [str(f) for f in files]
        file_labels = ["(select a file)"] + [f.name for f in files]

        # Find default selection
        default_value = ""
        prev_path = st.session_state.selected_file_path
        if prev_path and prev_path in file_path_strs:
            default_value = prev_path

        # Clear stale selection key when directory changes
        dir_key = f"_last_dir_for_file_select"
        if st.session_state.get(dir_key) != str(current_dir):
            st.session_state[dir_key] = str(current_dir)
            if '_file_select' in st.session_state:
                del st.session_state['_file_select']

        selected_path = st.sidebar.selectbox(
            "File:",
            file_path_strs,
            index=file_path_strs.index(default_value) if default_value in file_path_strs else 0,
            format_func=lambda p: file_labels[file_path_strs.index(p)],
            key='_file_select',
        )

        if selected_path:
            selected_file = Path(selected_path)
            st.session_state.selected_file_path = selected_path
        else:
            st.session_state.selected_file_path = None
    else:
        st.sidebar.info("No supported files here")

    # Show selected file and action buttons in sidebar
    if selected_file:
        st.sidebar.write("---")
        st.sidebar.success(f"**Selected:**\n{selected_file.name}")

        if mode == "Compare Files":
            if st.sidebar.button("Set as Reference", use_container_width=True):
                # Just store the path - data will be loaded during comparison
                st.session_state.reference_file = str(selected_file)
                st.session_state.reference_data = None  # Clear any stale data
                st.session_state.reference_format = None
                st.rerun()

            compare_disabled = st.session_state.reference_file is None
            if st.sidebar.button("Compare to Reference", use_container_width=True,
                                 disabled=compare_disabled):
                st.session_state.compare_target = str(selected_file)
                st.rerun()

    # Main content area for visualization
    st.subheader("Visualization")

    if mode == "View File":
        # Single file visualization
        if selected_file:
            try:
                format_type = DataFileReader.detect_format(selected_file)

                with st.spinner(f"Reading {format_type.upper()} file..."):
                    if format_type == 'nc':
                        # Cached read so box-select reruns don't re-read the
                        # multi-GB grid from disk on every zoom.
                        data = _read_file_cached(
                            str(selected_file),
                            os.path.getmtime(selected_file)
                        )
                    else:
                        data = read_file(selected_file)

                if show_info:
                    display_file_info(data, format_type, selected_file)

                st.write("---")

                with st.spinner("Creating visualization..."):
                    if format_type in ['bip', 'biq', 'bii', 'bic', 'bin']:
                        if use_plotly:
                            try:
                                fig = create_interactive_point_plot(
                                    data, format_type, selected_file
                                )
                                st.plotly_chart(fig, use_container_width=True)
                            except Exception as e:
                                st.warning(f"Plotly failed: {e}")
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
                    elif format_type == 'nc':
                        if use_plotly:
                            fields = load_netcdf_fields(
                                str(selected_file),
                                os.path.getmtime(selected_file)
                            )
                            if fields is None:
                                st.info(
                                    "NetCDF file is not MUR GHRSST format; "
                                    "using matplotlib view."
                                )
                                fig = create_netcdf_plot(data, selected_file)
                                if fig is not None:
                                    st.pyplot(fig)
                                    plt.close(fig)
                            else:
                                try:
                                    _render_netcdf_plotly(fields, selected_file)
                                except Exception as e:
                                    st.warning(
                                        f"Plotly failed: {e}. Using matplotlib."
                                    )
                                    import traceback
                                    with st.expander("Plotly error details"):
                                        st.code(traceback.format_exc())
                                    fig = create_netcdf_plot(data, selected_file)
                                    if fig is not None:
                                        st.pyplot(fig)
                                        plt.close(fig)
                        else:
                            fig = create_netcdf_plot(data, selected_file)
                            if fig is not None:
                                st.pyplot(fig)
                                plt.close(fig)
                            else:
                                st.error("Failed to create matplotlib figure")
                    else:
                        st.info(f"No visualization for {format_type} format.")

            except Exception as e:
                st.error(f"Error: {e}")
                import traceback
                with st.expander("Details"):
                    st.code(traceback.format_exc())
        else:
            st.info("Select a file from the browser to visualize it.")

    else:  # Compare mode
        ref_file = st.session_state.reference_file
        cmp_file = getattr(st.session_state, 'compare_target', None)

        if not ref_file:
            st.info("Set a reference file first, then select a file to compare.")
        elif not cmp_file:
            st.info(
                f"Reference: **{Path(ref_file).name}**\n\n"
                "Select another file and click Compare."
            )
        elif ref_file == cmp_file:
            st.warning("Cannot compare a file to itself.")
        else:
            # Perform comparison
            try:
                ref_path = Path(ref_file)
                cmp_path = Path(cmp_file)

                # Detect formats first (fast)
                ref_fmt = DataFileReader.detect_format(ref_path)
                cmp_fmt = DataFileReader.detect_format(cmp_path)

                if ref_fmt != cmp_fmt:
                    st.error(
                        f"Cannot compare different formats: "
                        f"{ref_fmt.upper()} vs {cmp_fmt.upper()}"
                    )
                else:
                    st.write(f"**Reference:** {Path(ref_file).name}")
                    st.write(f"**Comparison:** {cmp_path.name}")
                    st.write(f"**Format:** {ref_fmt.upper()}")

                    # For NetCDF, use memory-efficient comparison (chunked stats, subsampled plot)
                    if ref_fmt == 'nc':
                        st.write("---")

                        # Pass file paths for memory-efficient processing
                        ref_data = {'_filepath': str(ref_path)}
                        cmp_data = {'_filepath': str(cmp_path)}

                        with st.spinner("Comparing files (chunked for memory efficiency)..."):
                            results = compare_files_data(
                                ref_data, cmp_data, ref_fmt, tolerance
                            )

                        st.write("**Field Comparison:**")
                        for comp in results['comparisons']:
                            icon = "✅" if comp['match'] else "❌"
                            st.write(
                                f"{icon} **{comp['field']}**: {comp['message']}"
                            )

                        # Difference tail distribution (computed over every valid pixel)
                        sst_stats = results.get('stats', {}).get('analysed_sst')
                        if sst_stats and sst_stats.get('tail_counts'):
                            st.write("**Difference tail (all valid pixels):**")
                            vc = sst_stats['valid_count']
                            table_lines = [
                                "| \\|diff\\| > | pixels | % of valid |",
                                "|---|---:|---:|",
                            ]
                            for _t, _c in zip(sst_stats['tail_thresholds'],
                                              sst_stats['tail_counts']):
                                _pct = (100.0 * _c / vc) if vc else 0.0
                                table_lines.append(
                                    f"| {_t:g} K | {_c:,} | {_pct:.4f}% |"
                                )
                            st.markdown("\n".join(table_lines))
                            if sst_stats.get('worst_lat') is not None:
                                st.markdown(
                                    f"**Worst pixel:** "
                                    f"{sst_stats['worst_value']:+.4f} K at "
                                    f"lat {sst_stats['worst_lat']:.4f}, "
                                    f"lon {sst_stats['worst_lon']:.4f}"
                                )

                        st.write("---")

                        if results['all_match']:
                            st.success("Files match within tolerance!")
                        else:
                            st.warning("Differences found.")

                    else:
                        # For other formats, load the files
                        with st.spinner("Loading files for comparison..."):
                            ref_data = read_file(ref_path)
                            cmp_data = read_file(cmp_path)

                        st.write(f"**Tolerance:** {tolerance:.2e}")
                        st.write("---")

                        results = compare_files_data(
                            ref_data, cmp_data, ref_fmt, tolerance
                        )

                        st.write("**Field Comparison:**")
                        for comp in results['comparisons']:
                            icon = "✅" if comp['match'] else "❌"
                            st.write(
                                f"{icon} **{comp['field']}**: {comp['message']}"
                            )

                        st.write("---")

                        # Summary
                        if results['all_match']:
                            st.success("All fields match within tolerance!")
                        else:
                            st.warning("Some differences found.")

                    # Visualization
                    st.write("---")
                    st.subheader("Comparison Visualization")

                    with st.spinner("Creating comparison plots (subsampled for display)..."):
                        rendered = False
                        # Honor the Plotly radio button for formats that have
                        # an interactive comparison view (currently NetCDF).
                        # Box-select on the difference map zooms in and
                        # re-renders the region at full resolution.
                        if use_plotly:
                            try:
                                rendered = _render_comparison_plotly(
                                    ref_data, cmp_data, ref_fmt,
                                    Path(ref_file).name, cmp_path.name,
                                    diff_color_limit=diff_color_limit,
                                    diff_color_levels=diff_color_levels,
                                )
                            except Exception as e:
                                st.warning(
                                    f"Plotly comparison failed, falling back "
                                    f"to matplotlib: {e}"
                                )

                        if not rendered:
                            fig = create_comparison_plot(
                                ref_data, cmp_data, ref_fmt,
                                Path(ref_file).name, cmp_path.name,
                                diff_color_limit=diff_color_limit,
                                diff_color_levels=diff_color_levels,
                            )
                            if fig is not None:
                                st.pyplot(fig)
                                plt.close(fig)
                            else:
                                st.error("Figure was not created")

            except Exception as e:
                st.error(f"Error comparing files: {e}")
                import traceback
                with st.expander("Show error details"):
                    st.code(traceback.format_exc())


if __name__ == '__main__':
    main()
