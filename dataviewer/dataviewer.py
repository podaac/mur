#!/usr/bin/env python3
"""
MUR Data Viewer - Browse and visualize MUR SST processing data files.

Supports various binary formats used in MUR processing pipeline:
- .bip: Ice SST point data
- .gds: Gridded land/ice mask
- .bii: In-situ buoy observations
- .bic: Satellite L2P swath data
- .biq: Unified observation format
- .bin: Legacy satellite format
- .map: Quick-look gridded SST output
- .cXX: Multi-scale coefficient files
- .uXX: Uncertainty coefficient files
- .nc/.nc4: NetCDF output files
"""

import sys
import argparse
import warnings
from pathlib import Path
from typing import Optional, Tuple
import numpy as np

# Handle both relative and absolute imports
try:
    from .format_readers import read_file, DataFileReader
except ImportError:
    from format_readers import read_file, DataFileReader


def compute_robust_stats(data: np.ndarray) -> dict:
    """
    Compute robust statistics using median and MAD (Median Absolute Deviation).

    MAD is a robust estimate of standard deviation that is resistant to outliers.
    The relationship: robust_std ≈ 1.4826 * MAD

    Args:
        data: Input array

    Returns:
        Dictionary with keys:
        - median: Median value
        - mad: Median Absolute Deviation
        - robust_std: Robust standard deviation estimate
        - n_outliers_4sigma: Number of points beyond 4 robust sigma
        - pct_outliers_4sigma: Percentage of outliers
    """
    median = np.median(data)
    mad = np.median(np.abs(data - median))
    robust_std = 1.4826 * mad

    # Count outliers beyond 4 robust sigma
    outlier_mask = np.abs(data - median) > 4 * robust_std
    n_outliers = np.sum(outlier_mask)
    pct_outliers = 100.0 * n_outliers / len(data) if len(data) > 0 else 0.0

    return {
        'median': median,
        'mad': mad,
        'robust_std': robust_std,
        'n_outliers_4sigma': n_outliers,
        'pct_outliers_4sigma': pct_outliers
    }


def smart_downsample(x: np.ndarray, y: np.ndarray, c: Optional[np.ndarray] = None,
                     max_points: int = 100000) -> tuple:
    """
    Intelligently downsample data while preserving outliers and distribution.

    Args:
        x: X coordinates array
        y: Y coordinates array
        c: Optional color/value array
        max_points: Maximum number of points to keep

    Returns:
        Tuple of (x_down, y_down, c_down) or (x_down, y_down) if c is None
    """
    if len(x) <= max_points:
        return (x, y, c) if c is not None else (x, y)

    # Identify outliers (beyond 3 sigma in either dimension)
    mean_x, std_x = x.mean(), x.std()
    mean_y, std_y = y.mean(), y.std()

    outlier_mask = (np.abs(x - mean_x) > 3 * std_x) | (np.abs(y - mean_y) > 3 * std_y)

    # Keep all outliers
    outliers_x = x[outlier_mask]
    outliers_y = y[outlier_mask]
    outliers_c = c[outlier_mask] if c is not None else None

    # Randomly sample from normal points
    normal_x = x[~outlier_mask]
    normal_y = y[~outlier_mask]
    normal_c = c[~outlier_mask] if c is not None else None

    n_sample = max_points - len(outliers_x)

    if len(normal_x) > n_sample:
        indices = np.random.choice(len(normal_x), n_sample, replace=False)
        normal_x = normal_x[indices]
        normal_y = normal_y[indices]
        if normal_c is not None:
            normal_c = normal_c[indices]

    # Combine outliers and sampled normal points
    x_down = np.concatenate([outliers_x, normal_x])
    y_down = np.concatenate([outliers_y, normal_y])

    if c is not None:
        c_down = np.concatenate([outliers_c, normal_c])
        return x_down, y_down, c_down
    else:
        return x_down, y_down


def slice_to_bounds(lon: np.ndarray, lat: np.ndarray,
                    bounds: Optional[tuple]) -> Tuple[slice, slice]:
    """
    Map a lon/lat bounding box to index slices into the lon/lat axes.

    Used to crop a full-resolution grid to the region currently being viewed
    before resampling, so zooming shows progressively more detail.

    Args:
        lon: 1D longitude array, assumed monotonic ascending
        lat: 1D latitude array, monotonic ascending OR descending
        bounds: (lon_min, lon_max, lat_min, lat_max), or None for full extent

    Returns:
        (lon_slice, lat_slice). Degenerate/empty selections (<2 cells on an
        axis) fall back to that axis's full extent.
    """
    n_lon, n_lat = len(lon), len(lat)
    if bounds is None:
        return slice(0, n_lon), slice(0, n_lat)

    lon_min, lon_max, lat_min, lat_max = bounds

    # Longitude: ascending
    i0 = int(np.searchsorted(lon, lon_min, side='left'))
    i1 = int(np.searchsorted(lon, lon_max, side='right'))
    i0, i1 = max(0, i0), min(n_lon, i1)

    # Latitude: handle ascending or descending axis
    if n_lat > 1 and lat[0] > lat[-1]:
        rev = lat[::-1]
        j0 = n_lat - int(np.searchsorted(rev, lat_max, side='right'))
        j1 = n_lat - int(np.searchsorted(rev, lat_min, side='left'))
    else:
        j0 = int(np.searchsorted(lat, lat_min, side='left'))
        j1 = int(np.searchsorted(lat, lat_max, side='right'))
    j0, j1 = max(0, j0), min(n_lat, j1)

    # Guard degenerate selections -> full extent on the affected axis
    if i1 - i0 < 2:
        i0, i1 = 0, n_lon
    if j1 - j0 < 2:
        j0, j1 = 0, n_lat

    return slice(i0, i1), slice(j0, j1)


def block_mean_resample(arr2d: np.ndarray, lon: np.ndarray, lat: np.ndarray,
                        target: int = 1500) -> tuple:
    """
    Area-mean (block) resample a 2D field and its coordinate axes to roughly
    a target output size, ignoring NaNs.

    Unlike stride decimation, area averaging preserves the field between
    samples (fronts/eddies aren't dropped). When the region already fits in
    ``target`` the inputs are returned unchanged (native resolution).

    Args:
        arr2d: 2D field indexed [lat, lon]
        lon: 1D longitude axis matching arr2d's second dimension
        lat: 1D latitude axis matching arr2d's first dimension
        target: approximate maximum size of the longer output axis

    Returns:
        (z, x, y, factor) where z is the resampled field, x/y are the
        resampled cell-center coordinates, and factor is the block size used.
    """
    from skimage.measure import block_reduce

    n_lat, n_lon = arr2d.shape
    factor = max(1, int(np.ceil(max(n_lat, n_lon) / float(target))))
    if factor == 1:
        return arr2d, lon, lat, 1

    with warnings.catch_warnings():
        # All-NaN blocks make nanmean warn; the NaN result is what we want.
        warnings.simplefilter('ignore', category=RuntimeWarning)
        z = block_reduce(arr2d, (factor, factor), func=np.nanmean, cval=np.nan)
        x = block_reduce(lon, (factor,), func=np.nanmean, cval=np.nan)
        y = block_reduce(lat, (factor,), func=np.nanmean, cval=np.nan)

    return z, x, y, factor


def nearest_resample(arr2d: np.ndarray, factor: int) -> np.ndarray:
    """
    Stride (nearest) downsample for categorical fields such as the land/sea/ice
    mask, where area averaging would produce meaningless fractional classes.

    Uses the same ``factor`` as :func:`block_mean_resample` so the output
    dimensions line up with that function's coordinate axes.
    """
    if factor <= 1:
        return arr2d
    return arr2d[::factor, ::factor]


def print_file_info(data: dict, format_type: str, filepath: Path, verbose: bool = False):
    """
    Print summary information about the data file.

    Args:
        data: Dictionary returned by format reader
        format_type: File format type
        filepath: Path to file
    """
    print(f"\n{'='*80}")
    print(f"File: {filepath.name}")
    print(f"Format: {format_type.upper()}")
    print(f"Path: {filepath}")
    print(f"{'='*80}\n")

    if format_type in ['bip', 'biq']:
        print(f"Number of points: {data['N']:,}")

        if data['N'] == 0:
            print("\n⚠️  File contains no data points (empty file)")
            return

        print(f"\nLongitude range: [{data['lon'].min():.4f}, {data['lon'].max():.4f}]")
        print(f"Latitude range:  [{data['lat'].min():.4f}, {data['lat'].max():.4f}]")
        print(f"SST range:       [{data['sst'].min():.4f}, {data['sst'].max():.4f}] °C")
        print(f"SST mean:        {data['sst'].mean():.4f} °C")
        print(f"SST std:         {data['sst'].std():.4f} °C")

        # Robust statistics
        robust_stats = compute_robust_stats(data['sst'])
        print("\nRobust SST statistics:")
        print(f"SST median:      {robust_stats['median']:.4f} °C")
        print(f"SST robust std:  {robust_stats['robust_std']:.4f} °C")
        n_out = robust_stats['n_outliers_4sigma']
        pct_out = robust_stats['pct_outliers_4sigma']
        print(f"Outliers (>4σ):  {n_out:,} ({pct_out:.2f}%)")

        print(f"\nHour range:      [{data['hour'].min():.4f}, "
              f"{data['hour'].max():.4f}]")
        print(f"Weight range:    [{data['weight'].min():.4f}, {data['weight'].max():.4f}]")

    elif format_type == 'gds':
        ii, jj = data['dimensions']
        print(f"Grid dimensions: {ii} × {jj} = {ii*jj:,} points")
        print(f"\nLongitude range: [{data['lon'].min():.4f}, {data['lon'].max():.4f}]")
        print(f"Latitude range:  [{data['lat'].min():.4f}, {data['lat'].max():.4f}]")

        # Mask statistics
        mask_unique = np.unique(data['mask'])
        print(f"\nMask values: {mask_unique}")
        for val in mask_unique:
            count = np.sum(data['mask'] == val)
            pct = 100.0 * count / data['mask'].size
            print(f"  {val}: {count:,} points ({pct:.2f}%)")

        # Ice statistics
        ice_valid = data['icemap'][data['icemap'] >= 0]
        if len(ice_valid) > 0:
            print(f"\nIce concentration range: [{ice_valid.min()}, {ice_valid.max()}]%")
            ice_present = np.sum(data['icemap'] > 0)
            ice_pct = 100.0 * ice_present / data['icemap'].size
            print(f"Pixels with ice: {ice_present:,} ({ice_pct:.2f}%)")

    elif format_type == 'bii':
        print(f"Year: {data['year']}")
        print(f"Day of year: {data['day']}")
        print(f"Number of observations: {data['N']:,}")

        if data['N'] == 0:
            print("\n⚠️  File contains no observations (empty file)")
            return

        print(f"\nLongitude range: [{data['lon'].min():.4f}, {data['lon'].max():.4f}]")
        print(f"Latitude range:  [{data['lat'].min():.4f}, {data['lat'].max():.4f}]")
        print(f"SST range:       [{data['sst'].min():.4f}, {data['sst'].max():.4f}] °C")
        print(f"SST mean:        {data['sst'].mean():.4f} °C")
        print(f"SST std:         {data['sst'].std():.4f} °C")

        # Robust statistics
        robust_stats = compute_robust_stats(data['sst'])
        print("\nRobust SST statistics:")
        print(f"SST median:      {robust_stats['median']:.4f} °C")
        print(f"SST robust std:  {robust_stats['robust_std']:.4f} °C")
        n_out = robust_stats['n_outliers_4sigma']
        pct_out = robust_stats['pct_outliers_4sigma']
        print(f"Outliers (>4σ):  {n_out:,} ({pct_out:.2f}%)")

        # Platform type statistics
        platforms = np.unique(data['platform_type'])
        print(f"\nPlatform types: {platforms}")
        for ptype in platforms:
            count = np.sum(data['platform_type'] == ptype)
            pct = 100.0 * count / data['N']
            print(f"  {ptype:.0f}: {count:,} observations ({pct:.2f}%)")

    elif format_type in ['bic', 'bin']:
        print(f"Year: {data['year']}")
        print(f"Day of year: {data['day']}")
        print(f"Number of observations: {data['N']:,}")

        if data['N'] == 0:
            print("\n⚠️  File contains no observations (empty file)")
            return

        print(f"\nLongitude range: [{data['lon'].min():.4f}, {data['lon'].max():.4f}]")
        print(f"Latitude range:  [{data['lat'].min():.4f}, {data['lat'].max():.4f}]")
        print(f"SST range:       [{data['sst'].min():.4f}, {data['sst'].max():.4f}] °C")
        print(f"SST mean:        {data['sst'].mean():.4f} °C")
        print(f"SST std:         {data['sst'].std():.4f} °C")

        # Robust statistics
        robust_stats = compute_robust_stats(data['sst'])
        print("\nRobust SST statistics:")
        print(f"SST median:      {robust_stats['median']:.4f} °C")
        print(f"SST robust std:  {robust_stats['robust_std']:.4f} °C")
        n_out = robust_stats['n_outliers_4sigma']
        pct_out = robust_stats['pct_outliers_4sigma']
        print(f"Outliers (>4σ):  {n_out:,} ({pct_out:.2f}%)")

        print(f"\nBias range:      [{data['bias'].min():.4f}, "
              f"{data['bias'].max():.4f}] °C")
        print(f"RMS range:       [{data['rms'].min():.4f}, "
              f"{data['rms'].max():.4f}] °C")

        if 'quality' in data:
            qualities = np.unique(data['quality'])
            print(f"\nQuality values: {qualities}")
            for q in qualities:
                count = np.sum(data['quality'] == q)
                pct = 100.0 * count / data['N']
                print(f"  {q}: {count:,} observations ({pct:.2f}%)")

    elif format_type == 'map':
        nlon, nlat = data['dimensions']
        print(f"Grid dimensions: {nlon} × {nlat} = {nlon*nlat:,} points")
        print(f"\nLongitude range: [{data['lon'].min():.4f}, {data['lon'].max():.4f}]")
        print(f"Latitude range:  [{data['lat'].min():.4f}, {data['lat'].max():.4f}]")

        # SST statistics (excluding NaN values)
        sst_valid = data['sst'][~np.isnan(data['sst'])]
        if len(sst_valid) > 0:
            print(f"\nSST range:       [{sst_valid.min():.4f}, {sst_valid.max():.4f}] °C")
            print(f"SST mean:        {sst_valid.mean():.4f} °C")
            print(f"SST std:         {sst_valid.std():.4f} °C")

            # Count invalid pixels
            n_invalid = np.sum(np.isnan(data['sst']))
            pct_invalid = 100.0 * n_invalid / data['sst'].size
            print(f"\nInvalid pixels:  {n_invalid:,} ({pct_invalid:.2f}%)")
            print(f"Valid pixels:    {len(sst_valid):,} ({100-pct_invalid:.2f}%)")
        else:
            print("\n⚠️  No valid SST data found")

    elif format_type in ['csp', 'usp']:
        print(f"Scale level: L={data.get('scale', 'unknown')}")
        print(f"Grid dimensions: mx={data['mx']}, my={data['my']}, mz={data['mz']}, nv={data['nv']}")
        print(f"Total coefficients: {data['coefficients'].size:,}")
        print(f"Coefficient shape: {data['coefficients'].shape}")
        print(f"\nSpatial bounds:")
        print(f"  X: [{data['xmin']:.4f}, {data['xmax']:.4f}]")
        print(f"  Y: [{data['ymin']:.4f}, {data['ymax']:.4f}]")
        print(f"\nCoefficient statistics:")
        print(f"  Min:  {data['coefficients'].min():.6f}")
        print(f"  Max:  {data['coefficients'].max():.6f}")
        print(f"  Mean: {data['coefficients'].mean():.6f}")
        print(f"  Std:  {data['coefficients'].std():.6f}")

    elif format_type == 'nc':
        print(f"Dimensions: {data['dimensions']}")
        print(f"\nVariables:")
        for var_name, var_data in data['variables'].items():
            shape = var_data['data'].shape
            dtype = var_data['data'].dtype
            print(f"  {var_name:20s} {str(shape):20s} {dtype}")

        print(f"\nGlobal attributes:")
        if verbose:
            for attr, value in data['attributes'].items():
                print(f"  {attr:30s} = {value}")
        else:
            for attr, value in list(data['attributes'].items())[:10]:
                value_str = str(value)
                if len(value_str) > 60:
                    value_str = value_str[:57] + "..."
                print(f"  {attr:30s} = {value_str}")
            if len(data['attributes']) > 10:
                print(f"  ... and {len(data['attributes']) - 10} more (use -v for all)")

    print()


def add_coastlines(ax):
    """
    Add simple coastlines to a plot using Natural Earth data if available.

    Args:
        ax: Matplotlib axes object
    """
    try:
        # Try using cartopy's Natural Earth coastline data
        import cartopy.io.shapereader as shpreader

        # Get Natural Earth coastlines (low resolution for speed)
        coastlines = shpreader.natural_earth(resolution='110m',
                                              category='physical',
                                              name='coastline')

        # Read and plot coastlines
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
        # Cartopy not available or error accessing data - silently skip
        pass


def plot_data(data: dict, format_type: str, filepath: Path,
              resample: Optional[int] = None):
    """
    Plot data using matplotlib.

    Args:
        data: Dictionary returned by format reader
        format_type: File format type
        filepath: Path to file
        resample: Resampling factor for large grids (None = auto)
    """
    try:
        import matplotlib
        import matplotlib.pyplot as plt
        from matplotlib.colors import ListedColormap

        # Ensure we're using an interactive backend
        backend = matplotlib.get_backend()
        if backend.lower() == 'agg':
            # AGG is non-interactive, try to use a GUI backend
            try:
                matplotlib.use('TkAgg')
            except ImportError:
                try:
                    matplotlib.use('Qt5Agg')
                except ImportError:
                    print("⚠️  Using non-interactive backend. "
                          "Install tkinter or PyQt5 for interactive plots.")
    except ImportError:
        print("❌ matplotlib not available. Install with: pip install matplotlib")
        return

    # Check if cartopy is available for coastlines
    try:
        import cartopy.crs as ccrs  # noqa: F401
        import cartopy.feature as cfeature  # noqa: F401
        has_cartopy = True
    except ImportError:
        has_cartopy = False

    print("📊 Preparing plot...")
    print(f"   Using matplotlib backend: {matplotlib.get_backend()}")

    if format_type in ['bip', 'biq', 'bii', 'bic', 'bin']:
        # Scatter plot for point data
        num_points = data.get('N', len(data['sst']))
        print(f"   Dataset contains {num_points:,} points")

        # Check if file is empty
        if num_points == 0:
            print("   ⚠️  Cannot plot: file contains no data points")
            return

        # Check if SST is constant (e.g., landice data with all points at -1.8°C)
        sst_is_constant = data['sst'].std() < 1e-6
        if sst_is_constant:
            sst_val = data['sst'].mean()
            print(f"   ℹ️  SST is constant ({sst_val:.4f}°C) - "
                  "showing simplified plots")

        # Filter out invalid lat/lon values
        valid_mask = (
            (data['lon'] >= -180) & (data['lon'] <= 180) &
            (data['lat'] >= -90) & (data['lat'] <= 90)
        )
        num_invalid = np.sum(~valid_mask)
        if num_invalid > 0:
            print(f"   ⚠️  Filtering {num_invalid:,} points with invalid coordinates")
            print("      (lon must be [-180, 180], lat must be [-90, 90])")
            # Apply filter to all arrays
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
            # Update point count
            num_points = len(data['lon'])
            data['N'] = num_points
            print(f"   Valid points remaining: {num_points:,}")

        # Determine rendering strategy based on point count
        use_density = False
        use_downsampling = False
        DENSITY_THRESHOLD = 100000  # Use density plots above this

        if num_points > DENSITY_THRESHOLD:
            # Try to use mpl-scatter-density for best performance
            try:
                import mpl_scatter_density
                use_density = True
                print(f"   Using density rendering for optimal performance...")
            except ImportError:
                # Fall back to downsampling
                use_downsampling = True
                print(f"   ⚠️  Large dataset detected ({num_points:,} points)")
                print(f"   Downsampling to 100k points (install mpl-scatter-density for better performance)")
                print(f"      pip install mpl-scatter-density")

        # Prepare data
        if use_downsampling:
            lon_plot, lat_plot, sst_plot = smart_downsample(
                data['lon'], data['lat'], data['sst'], max_points=100000
            )
            if 'weight' in data:
                _, _, weight_plot = smart_downsample(
                    data['lon'], data['lat'], data['weight'], max_points=100000
                )
            if 'rms' in data:
                _, _, rms_plot = smart_downsample(
                    data['lon'], data['lat'], data['rms'], max_points=100000
                )
            if 'platform_type' in data:
                _, _, platform_plot = smart_downsample(
                    data['lon'], data['lat'], data['platform_type'], max_points=100000
                )
            print(f"   Plotting {len(lon_plot):,} sampled points...")
        else:
            lon_plot, lat_plot, sst_plot = data['lon'], data['lat'], data['sst']
            weight_plot = data.get('weight')
            rms_plot = data.get('rms')
            platform_plot = data.get('platform_type')
            if not use_density:
                print(f"   Creating scatter plots for {num_points:,} points...")

        # Compute robust colorbar limits for SST (±3 sigma)
        robust_stats = compute_robust_stats(data['sst'])
        vmin_sst = robust_stats['median'] - 3 * robust_stats['robust_std']
        vmax_sst = robust_stats['median'] + 3 * robust_stats['robust_std']
        print(f"   SST colorbar limits: [{vmin_sst:.2f}, {vmax_sst:.2f}] °C "
              f"(median ± 3σ robust)")
        if robust_stats['n_outliers_4sigma'] > 0:
            n_out = robust_stats['n_outliers_4sigma']
            pct = robust_stats['pct_outliers_4sigma']
            print(f"   Note: {n_out:,} outliers ({pct:.2f}%) beyond ±4σ")

        # Create figure with appropriate projections
        if use_density:
            from matplotlib.colors import LinearSegmentedColormap
            # Custom colormap: white background for low density
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

            # Use different layout for BII (3 plots) vs others (4 plots)
            if format_type == 'bii':
                fig = plt.figure(figsize=(16, 10))
                ax1 = fig.add_subplot(2, 2, 1, projection='scatter_density')
                ax2 = fig.add_subplot(2, 2, 2, projection='scatter_density')
                ax3 = fig.add_subplot(2, 1, 2)  # Histogram (full width bottom)
                axes = {'sst': ax1, 'platform': ax2, 'hist': ax3}
            else:
                fig = plt.figure(figsize=(15, 12))
                ax1 = fig.add_subplot(2, 2, 1, projection='scatter_density')
                ax2 = fig.add_subplot(2, 2, 2)  # Histogram doesn't need density
                ax3 = fig.add_subplot(2, 2, 3, projection='scatter_density', sharex=ax1, sharey=ax1)
                ax4 = fig.add_subplot(2, 2, 4, projection='scatter_density', sharex=ax1, sharey=ax1)
                axes = [[ax1, ax2], [ax3, ax4]]

            if format_type == 'bii':
                # BII-specific layout: SST map, platform map, histogram
                density1 = axes['sst'].scatter_density(lon_plot, lat_plot,
                                                       c=sst_plot,
                                                       cmap='RdYlBu_r', dpi=72,
                                                       vmin=vmin_sst,
                                                       vmax=vmax_sst)
                axes['sst'].set_xlabel('Longitude')
                axes['sst'].set_ylabel('Latitude')
                axes['sst'].set_title('SST Distribution (Mean)')
                axes['sst'].set_aspect('equal', adjustable='box')
                axes['sst'].grid(True, alpha=0.3)
                if has_cartopy:
                    add_coastlines(axes['sst'])
                plt.colorbar(density1, ax=axes['sst'], label='SST (°C)')

                # Platform type distribution with discrete colors
                # Use regular scatter (not scatter_density) for categorical data
                # to avoid averaging platform types which creates invalid intermediate colors
                # Platform type names from iQUAM/ICOADS documentation
                platform_names = {
                    0: 'Unknown', 1: 'Merchant Ship', 2: 'OSV (off station)',
                    3: 'OSV (on station)', 4: 'Lightship', 5: 'Ship',
                    6: 'Moored Buoy', 7: 'Drifting Buoy', 8: 'Ice Buoy',
                    9: 'Ice Station', 10: 'Oceanographic', 11: 'MBT',
                    12: 'XBT', 13: 'C-MAN'
                }
                unique_types = sorted(set(platform_plot.astype(int)))
                n_types = len(unique_types)
                # Create discrete colormap for the specific platform types
                from matplotlib.colors import BoundaryNorm
                tab10 = plt.colormaps.get_cmap('tab10')
                colors = [tab10(i % 10) for i in range(n_types)]
                cmap = ListedColormap(colors)
                # Set boundaries so each type gets its own color band
                bounds = [unique_types[0] - 0.5] + [t + 0.5 for t in unique_types]
                norm = BoundaryNorm(bounds, cmap.N)

                # Convert projection to regular axes for scatter plot
                ax_platform = fig.add_subplot(2, 2, 2)
                axes['platform'].remove()
                axes['platform'] = ax_platform
                sc_platform = axes['platform'].scatter(lon_plot, lat_plot,
                                                       c=platform_plot, s=1,
                                                       cmap=cmap, norm=norm,
                                                       alpha=0.6)
                axes['platform'].set_xlabel('Longitude')
                axes['platform'].set_ylabel('Latitude')
                axes['platform'].set_title('Platform Type Distribution')
                axes['platform'].set_aspect('equal', adjustable='box')
                axes['platform'].grid(True, alpha=0.3)
                if has_cartopy:
                    add_coastlines(axes['platform'])
                # Create colorbar with platform type names
                cbar = plt.colorbar(sc_platform, ax=axes['platform'],
                                    label='Platform Type', ticks=unique_types)
                cbar.set_ticklabels([platform_names.get(t, f'Type {t}')
                                     for t in unique_types])
            else:
                # Standard 4-panel layout for other formats
                # SST aggregated plot (mean values)
                density1 = axes[0][0].scatter_density(lon_plot, lat_plot,
                                                       c=sst_plot,
                                                       cmap='RdYlBu_r', dpi=72,
                                                       vmin=vmin_sst,
                                                       vmax=vmax_sst)
                axes[0][0].set_xlabel('Longitude')
                axes[0][0].set_ylabel('Latitude')
                axes[0][0].set_title('SST Distribution (Mean)')
                axes[0][0].set_aspect('equal', adjustable='box')
                axes[0][0].grid(True, alpha=0.3)
                if has_cartopy:
                    add_coastlines(axes[0][0])
                cbar1 = plt.colorbar(density1, ax=axes[0][0], label='SST (°C)')

                # Geographic coverage density (point count)
                density2 = axes[1][0].scatter_density(lon_plot, lat_plot,
                                                       cmap=white_viridis, dpi=72)
                axes[1][0].set_xlabel('Longitude')
                axes[1][0].set_ylabel('Latitude')
                axes[1][0].set_title('Geographic Coverage (Density)')
                axes[1][0].set_aspect('equal', adjustable='box')
                axes[1][0].grid(True, alpha=0.3)
                if has_cartopy:
                    add_coastlines(axes[1][0])
                cbar2 = plt.colorbar(density2, ax=axes[1][0], label='Point Density')

                # Additional field aggregated (mean values)
                if format_type in ['bip', 'biq']:
                    density3 = axes[1][1].scatter_density(lon_plot, lat_plot,
                                                           c=weight_plot,
                                                           cmap='viridis', dpi=72)
                    axes[1][1].set_xlabel('Longitude')
                    axes[1][1].set_ylabel('Latitude')
                    axes[1][1].set_title('Weight Distribution (Mean)')
                    axes[1][1].set_aspect('equal', adjustable='box')
                    axes[1][1].grid(True, alpha=0.3)
                    if has_cartopy:
                        add_coastlines(axes[1][1])
                    cbar3 = plt.colorbar(density3, ax=axes[1][1], label='Weight')
                elif format_type in ['bic', 'bin']:
                    density3 = axes[1][1].scatter_density(lon_plot, lat_plot,
                                                           c=rms_plot,
                                                           cmap='hot_r', dpi=72)
                    axes[1][1].set_xlabel('Longitude')
                    axes[1][1].set_ylabel('Latitude')
                    axes[1][1].set_title('RMS Error Distribution (Mean)')
                    axes[1][1].set_aspect('equal', adjustable='box')
                    axes[1][1].grid(True, alpha=0.3)
                    if has_cartopy:
                        add_coastlines(axes[1][1])
                    cbar3 = plt.colorbar(density3, ax=axes[1][1], label='RMS (°C)')
                else:
                    axes[1][1].axis('off')
        else:
            # Use different layout for BII (3 plots) vs others (4 plots)
            if format_type == 'bii':
                fig = plt.figure(figsize=(16, 10))
                ax1 = fig.add_subplot(2, 2, 1)
                ax2 = fig.add_subplot(2, 2, 2)
                ax3 = fig.add_subplot(2, 1, 2)  # Histogram (full width bottom)
                axes = {'sst': ax1, 'platform': ax2, 'hist': ax3}
            else:
                # Create figure with linked axes for the 3 scatter plots
                fig = plt.figure(figsize=(15, 12))
                ax1 = fig.add_subplot(2, 2, 1)
                ax2 = fig.add_subplot(2, 2, 2)
                ax3 = fig.add_subplot(2, 2, 3, sharex=ax1, sharey=ax1)
                ax4 = fig.add_subplot(2, 2, 4, sharex=ax1, sharey=ax1)
                axes = np.array([[ax1, ax2], [ax3, ax4]])

            if format_type == 'bii':
                # BII-specific layout: SST map, histogram, platform type map
                sc1 = axes['sst'].scatter(lon_plot, lat_plot, c=sst_plot,
                                          s=1, cmap='RdYlBu_r', alpha=0.6,
                                          vmin=vmin_sst, vmax=vmax_sst)
                axes['sst'].set_xlabel('Longitude')
                axes['sst'].set_ylabel('Latitude')
                axes['sst'].set_title('SST Distribution')
                axes['sst'].set_aspect('equal', adjustable='box')
                axes['sst'].grid(True, alpha=0.3)
                if has_cartopy:
                    add_coastlines(axes['sst'])
                plt.colorbar(sc1, ax=axes['sst'], label='SST (°C)')

                # Platform type distribution with discrete colors
                platform_names = {
                    0: 'Unknown', 1: 'Merchant Ship', 2: 'OSV (off station)',
                    3: 'OSV (on station)', 4: 'Lightship', 5: 'Ship',
                    6: 'Moored Buoy', 7: 'Drifting Buoy', 8: 'Ice Buoy',
                    9: 'Ice Station', 10: 'Oceanographic', 11: 'MBT',
                    12: 'XBT', 13: 'C-MAN'
                }
                unique_types = sorted(set(platform_plot.astype(int)))
                n_types = len(unique_types)
                # Create discrete colormap for the specific platform types
                from matplotlib.colors import BoundaryNorm
                tab10 = plt.colormaps.get_cmap('tab10')
                colors = [tab10(i % 10) for i in range(n_types)]
                cmap = ListedColormap(colors)
                bounds = [unique_types[0] - 0.5] + [t + 0.5 for t in unique_types]
                norm = BoundaryNorm(bounds, cmap.N)

                sc2 = axes['platform'].scatter(lon_plot, lat_plot, c=platform_plot,
                                               s=1, cmap=cmap, norm=norm, alpha=0.6)
                axes['platform'].set_xlabel('Longitude')
                axes['platform'].set_ylabel('Latitude')
                axes['platform'].set_title('Platform Type Distribution')
                axes['platform'].set_aspect('equal', adjustable='box')
                axes['platform'].grid(True, alpha=0.3)
                if has_cartopy:
                    add_coastlines(axes['platform'])
                # Create colorbar with platform type names
                cbar = plt.colorbar(sc2, ax=axes['platform'],
                                    label='Platform Type', ticks=unique_types)
                cbar.set_ticklabels([platform_names.get(t, f'Type {t}')
                                     for t in unique_types])
            else:
                # Standard 4-panel layout for other formats
                # SST scatter
                sc1 = axes[0, 0].scatter(lon_plot, lat_plot, c=sst_plot,
                                         s=1, cmap='RdYlBu_r', alpha=0.6,
                                         vmin=vmin_sst, vmax=vmax_sst)
                axes[0, 0].set_xlabel('Longitude')
                axes[0, 0].set_ylabel('Latitude')
                axes[0, 0].set_title('SST Distribution')
                axes[0, 0].set_aspect('equal', adjustable='box')
                axes[0, 0].grid(True, alpha=0.3)
                if has_cartopy:
                    add_coastlines(axes[0, 0])
                plt.colorbar(sc1, ax=axes[0, 0], label='SST (°C)')

                # Geographic coverage (shares axes with SST plot)
                axes[1, 0].scatter(lon_plot, lat_plot, s=1, alpha=0.3)
                axes[1, 0].set_xlabel('Longitude')
                axes[1, 0].set_ylabel('Latitude')
                axes[1, 0].set_title('Geographic Coverage')
                axes[1, 0].set_aspect('equal', adjustable='box')
                axes[1, 0].grid(True, alpha=0.3)
                if has_cartopy:
                    add_coastlines(axes[1, 0])

                # Additional field (shares axes with SST and coverage plots)
                if format_type in ['bip', 'biq'] and weight_plot is not None:
                    sc3 = axes[1, 1].scatter(lon_plot, lat_plot, c=weight_plot,
                                             s=1, cmap='viridis', alpha=0.6)
                    axes[1, 1].set_xlabel('Longitude')
                    axes[1, 1].set_ylabel('Latitude')
                    axes[1, 1].set_title('Weight Distribution')
                    axes[1, 1].set_aspect('equal', adjustable='box')
                    axes[1, 1].grid(True, alpha=0.3)
                    if has_cartopy:
                        add_coastlines(axes[1, 1])
                    plt.colorbar(sc3, ax=axes[1, 1], label='Weight')
                elif format_type in ['bic', 'bin'] and rms_plot is not None:
                    sc3 = axes[1, 1].scatter(lon_plot, lat_plot, c=rms_plot,
                                             s=1, cmap='hot_r', alpha=0.6)
                    axes[1, 1].set_xlabel('Longitude')
                    axes[1, 1].set_ylabel('Latitude')
                    axes[1, 1].set_title('RMS Error Distribution')
                    axes[1, 1].set_aspect('equal', adjustable='box')
                    axes[1, 1].grid(True, alpha=0.3)
                    if has_cartopy:
                        add_coastlines(axes[1, 1])
                    plt.colorbar(sc3, ax=axes[1, 1], label='RMS (°C)')
                else:
                    axes[1, 1].axis('off')

        # SST histogram (same for all rendering modes)
        if format_type == 'bii':
            # BII uses dict-based axes
            hist_ax = axes['hist']
        elif use_density:
            hist_ax = axes[0][1]
        else:
            hist_ax = axes[0, 1]

        hist_ax.hist(data['sst'], bins=100, edgecolor='black', alpha=0.7)
        hist_ax.set_xlabel('SST (°C)')
        hist_ax.set_ylabel('Count (log scale)')
        hist_ax.set_title('SST Histogram')
        hist_ax.set_yscale('log')
        hist_ax.grid(True, alpha=0.3)

        # Add help text
        coastline_note = (
            "\n• Coastlines: cartopy installed" if has_cartopy
            else "\n• Install cartopy for coastlines"
        )
        if use_density:
            help_text = (
                "VALUE AGGREGATION MODE\n"
                f"Total Points: {num_points:,}\n\n"
                "What you're seeing:\n"
                "• Top-left: MEAN SST value in each pixel\n"
                "  Color = average temperature\n"
                "• Top-right: Histogram of ALL SST values\n"
                "• Bottom-left: Point DENSITY (observation count)\n"
                "• Bottom-right: MEAN weight/RMS value\n\n"
                "How it works:\n"
                f"• Dataset has >{DENSITY_THRESHOLD:,} points\n"
                "• Data aggregated into pixels (mean)\n"
                "• Fast rendering, interactive zoom/pan\n"
                f"{coastline_note}\n\n"
                "Tip: Use --info for detailed statistics"
            )
        elif use_downsampling:
            help_text = (
                "DOWNSAMPLED MODE\n"
                f"Total Points: {num_points:,}\n"
                f"Displayed: {len(lon_plot):,}\n\n"
                "What you're seeing:\n"
                "• Random sample of data points\n"
                "• All outliers (>3σ) preserved\n"
                "• Representative distribution\n\n"
                "For better performance:\n"
                "  pip install mpl-scatter-density\n"
                f"{coastline_note}\n\n"
                "Tip: Histogram shows ALL data points"
            )
        else:
            help_text = (
                f"SCATTER PLOT MODE\n"
                f"Total Points: {num_points:,}\n\n"
                "What you're seeing:\n"
                "• Every individual data point\n"
                "• Color indicates value (see colorbar)\n"
                "• Full resolution visualization\n\n"
                "Panels:\n"
                "• Top-left: SST spatial distribution\n"
                "• Top-right: SST value histogram\n"
                "• Bottom-left: Geographic coverage\n"
                "• Bottom-right: Additional field\n"
                f"{coastline_note}\n"
            )

        # Add text box
        fig.text(0.02, 0.02, help_text,
                fontsize=8, family='monospace',
                verticalalignment='bottom',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

        plt.suptitle(f'{filepath.name}\n{format_type.upper()}: {data.get("N", len(data["sst"])):,} observations')
        print("   Rendering plot...")
        plt.tight_layout(rect=[0, 0.12, 1, 0.98])  # Make room for help text
        print("✅ Opening plot window...")
        plt.show()

    elif format_type == 'gds':
        # Grid plots
        ii, jj = data['dimensions']
        print(f"   Grid size: {ii:,} × {jj:,} = {ii*jj:,} pixels")

        # Determine resampling
        max_display_size = 5000
        if resample is None:
            need_resample = max(ii, jj) > max_display_size
            if need_resample:
                resample_factor = int(np.ceil(max(ii, jj) / max_display_size))
            else:
                resample_factor = 1
        else:
            resample_factor = resample

        if resample_factor > 1:
            print(f"   Resampling by factor of {resample_factor} for display...")

        # Resample for display
        if resample_factor > 1:
            # Simple and fast: just take every Nth pixel (nearest neighbor)
            # Now that we've fixed the Fortran ordering, this should work correctly
            mask_display = data['mask'][::resample_factor, ::resample_factor]
            icemap_display = data['icemap'][::resample_factor, ::resample_factor]

            new_shape = mask_display.shape
            print(f"   Display size: {new_shape[0]:,} × {new_shape[1]:,} pixels")
        else:
            mask_display = data['mask']
            icemap_display = data['icemap']

        print("   Creating grid plots...")
        # Create subplots with shared axes for synchronized zoom/pan
        fig, axes = plt.subplots(1, 2, figsize=(15, 6), sharex=True, sharey=True)

        # Mask - use discrete colormap for categorical data
        # Define mask value meanings per LANDICE_MASK_ENCODING.md
        mask_labels = {
            1: 'Open sea',
            2: 'Land',
            3: 'Coast',
            5: 'Open lake',
            7: 'Lake shore',
            9: 'Sea + ice',
            11: 'Coast + ice',
            13: 'Lake + ice',
            15: 'Complex shore'
        }

        # Get unique values and create discrete colormap
        unique_vals = sorted(np.unique(data['mask']))
        n_colors = len(unique_vals)

        # Use tab10 colormap and extract colors
        from matplotlib.colors import BoundaryNorm
        tab10 = plt.colormaps.get_cmap('tab10')
        colors = [tab10(i / 10) for i in range(n_colors)]
        cmap = ListedColormap(colors)

        # Create boundaries for discrete colormap
        # Boundaries are between values to create bins
        bounds = [unique_vals[0] - 0.5]
        for i in range(len(unique_vals) - 1):
            bounds.append((unique_vals[i] + unique_vals[i+1]) / 2)
        bounds.append(unique_vals[-1] + 0.5)
        norm = BoundaryNorm(bounds, cmap.N)

        im1 = axes[0].imshow(mask_display.T, cmap=cmap, norm=norm,
                             aspect='equal', origin='lower', interpolation='none')
        axes[0].set_xlabel('Longitude Index (nlon)')
        axes[0].set_ylabel('Latitude Index (nlat)')
        axes[0].set_title('Land/Ice Mask')

        # Add colorbar with proper tick labels
        cbar1 = plt.colorbar(im1, ax=axes[0], label='Mask Value',
                            ticks=unique_vals)
        cbar1.set_ticklabels([mask_labels.get(v, str(v)) for v in unique_vals])

        # Ice concentration - use 'none' to see actual pixel values
        im2 = axes[1].imshow(icemap_display.T, cmap='Blues',
                             vmin=-1, vmax=100,
                             aspect='equal', origin='lower', interpolation='none')
        axes[1].set_xlabel('Longitude Index (nlon)')
        axes[1].set_ylabel('Latitude Index (nlat)')
        axes[1].set_title('Ice Concentration (%)')
        plt.colorbar(im2, ax=axes[1], label='Ice %')

        # Add help text for grid data
        if resample_factor > 1:
            help_text = (
                f"GRID DATA (RESAMPLED)\n"
                f"Full Grid: {ii:,} × {jj:,} = {ii*jj:,} pixels\n"
                f"Display: {mask_display.shape[0]:,} × {mask_display.shape[1]:,}\n"
                f"Resample Factor: {resample_factor}×\n\n"
                "What you're seeing:\n"
                "• Left: Land/ice mask (categorical values)\n"
                "• Right: Ice concentration (0-100%)\n"
                "• Data resampled for faster display\n"
                "• Statistics computed on full resolution\n\n"
                "Tip: Use --resample N to control resolution"
            )
        else:
            help_text = (
                f"GRID DATA\n"
                f"Grid: {ii:,} × {jj:,} = {ii*jj:,} pixels\n\n"
                "What you're seeing:\n"
                "• Left: Land/ice mask values\n"
                "  Different colors = different surface types\n"
                "• Right: Ice concentration (%)\n"
                "  Blue intensity = ice percentage\n\n"
                "Panels show full resolution data"
            )

        fig.text(0.02, 0.02, help_text,
                fontsize=8, family='monospace',
                verticalalignment='bottom',
                bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8))

        plt.suptitle(f'{filepath.name}\n{format_type.upper()}: {ii}×{jj} grid')
        print("   Rendering plot...")
        plt.tight_layout(rect=[0, 0.12, 1, 0.98])
        print("✅ Opening plot window...")
        plt.show()

    elif format_type == 'map':
        # Grid plot for .map files
        nlon, nlat = data['dimensions']
        print(f"   Grid size: {nlon:,} × {nlat:,} = {nlon*nlat:,} pixels")

        # Check if all data is invalid
        sst_valid = data['sst'][~np.isnan(data['sst'])]
        if len(sst_valid) == 0:
            print("   ⚠️  Cannot plot: file contains no valid SST data (all NaN)")
            return

        print("   Creating SST map plot...")
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
            add_coastlines(axes[0])

        # Add colorbar
        cbar1 = plt.colorbar(im1, ax=axes[0], label='SST (°C)', shrink=0.8)

        # SST histogram
        sst_valid = data['sst'][~np.isnan(data['sst'])]
        if len(sst_valid) > 0:
            axes[1].hist(sst_valid.flatten(), bins=100, edgecolor='black', alpha=0.7)
            axes[1].set_xlabel('SST (°C)')
            axes[1].set_ylabel('Count')
            axes[1].set_title('SST Distribution')
            axes[1].grid(True, alpha=0.3)

            # Add statistics text
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

        # Add help text
        coastline_note = (
            "\n• Coastlines: cartopy installed" if has_cartopy
            else "\n• Install cartopy for coastlines"
        )
        help_text = (
            f"QUICK-LOOK GRIDDED SST\n"
            f"Grid: {nlon} × {nlat}\n"
            f"Resolution: ~{360.0/nlon:.3f}° × {180.0/nlat:.3f}°\n\n"
            "What you're seeing:\n"
            "• Left: SST field interpolated from\n"
            "  B-spline coefficients\n"
            "• Right: SST value distribution\n\n"
            "Purpose:\n"
            "• Quick visual QC during processing\n"
            "• Intermediate output (not final product)\n"
            f"{coastline_note}"
        )

        fig.text(0.02, 0.02, help_text,
                fontsize=8, family='monospace',
                verticalalignment='bottom',
                bbox=dict(boxstyle='round', facecolor='lightcyan', alpha=0.8))

        plt.suptitle(f'{filepath.name}\nMAP: {nlon}×{nlat} grid')
        print("   Rendering plot...")
        plt.tight_layout(rect=[0, 0.15, 1, 0.98])
        print("✅ Opening plot window...")
        plt.show()

    elif format_type in ['csp', 'usp']:
        # Coefficient visualization
        coef = data['coefficients']
        print(f"   Coefficient array shape: {coef.shape}")

        # Take a slice through the middle
        if coef.ndim == 4:
            slice_z = coef.shape[2] // 2
            slice_v = 0
            coef_slice = coef[:, :, slice_z, slice_v]
            print(f"   Plotting slice at z={slice_z}, v={slice_v}...")
        else:
            coef_slice = coef[:, :]
            print("   Plotting 2D coefficient array...")

        fig, axes = plt.subplots(1, 2, figsize=(15, 6))

        # 2D slice
        im1 = axes[0].imshow(coef_slice.T, cmap='RdBu_r',
                             aspect='equal', origin='lower')
        axes[0].set_xlabel('X index')
        axes[0].set_ylabel('Y index')
        axes[0].set_title(f'Coefficient Slice (z={slice_z}, v={slice_v})')
        plt.colorbar(im1, ax=axes[0], label='Coefficient Value')

        # Histogram
        axes[1].hist(coef.flatten(), bins=100, edgecolor='black', alpha=0.7)
        axes[1].set_xlabel('Coefficient Value')
        axes[1].set_ylabel('Count')
        axes[1].set_title('Coefficient Distribution')
        axes[1].grid(True, alpha=0.3)
        axes[1].set_yscale('log')

        # Add help text for coefficient data
        scale_label = f"L={data['scale']}" if data.get('scale') else ""
        if coef.ndim == 4:
            help_text = (
                f"COEFFICIENT DATA\n"
                f"Shape: {coef.shape}\n"
                f"Scale: {scale_label}\n\n"
                "What you're seeing:\n"
                "• Left: 2D slice through coefficient array\n"
                f"  Showing z={slice_z}, v={slice_v}\n"
                "• Right: Distribution of ALL coefficients\n"
                "  (log scale for clarity)\n\n"
                "4D array dimensions:\n"
                "  (mx+3) × (my+3) × mz × nv\n"
                "  Spatial × Spatial × Depth × Variables"
            )
        else:
            help_text = (
                f"COEFFICIENT DATA\n"
                f"Shape: {coef.shape}\n"
                f"Scale: {scale_label}\n\n"
                "What you're seeing:\n"
                "• Left: 2D coefficient array\n"
                "  Color shows coefficient magnitude\n"
                "• Right: Distribution of coefficients\n"
                "  (log scale for clarity)\n\n"
                "Used in multi-scale analysis"
            )

        fig.text(0.02, 0.02, help_text,
                fontsize=8, family='monospace',
                verticalalignment='bottom',
                bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))

        plt.suptitle(f'{filepath.name}\n{format_type.upper()}: {scale_label} {coef.shape}')
        print("   Rendering plot...")
        plt.tight_layout(rect=[0, 0.15, 1, 0.98])
        print("✅ Opening plot window...")
        plt.show()

    elif format_type == 'nc':
        # NetCDF plotting for MUR GHRSST files
        variables = data['variables']
        dimensions = data['dimensions']

        # Check if this is a MUR GHRSST file
        is_mur_ghrsst = 'analysed_sst' in variables

        if not is_mur_ghrsst:
            print("⚠️  NetCDF plotting currently optimized for MUR GHRSST format.")
            print("    Use dedicated tools like ncview or Panoply for other NetCDF files.")
            return

        print(f"   Detected MUR GHRSST L4 product")
        print(f"   Grid dimensions: {dimensions}")

        # Extract key variables
        sst_var = variables['analysed_sst']
        lon = variables['lon']['data'][:]
        lat = variables['lat']['data'][:]
        # NOTE: netCDF4 auto-applies scale_factor and add_offset when reading data
        # So sst_data is already in Kelvin (NOT raw int16 values)
        sst_data = sst_var['data'][0, :, :] if sst_var['data'].ndim == 3 else sst_var['data'][:, :]

        # Data is already in Kelvin from netCDF4 auto-scaling, just convert to Celsius
        # DO NOT apply scale_factor/add_offset again - that causes double-scaling bug!
        sst_celsius = sst_data - 273.15

        # netCDF4 auto-masking handles fill values, but ensure we have a masked array
        if not isinstance(sst_celsius, np.ma.MaskedArray):
            fill_value = sst_var['attributes'].get('_FillValue', -32768)
            # If not auto-masked, the fill value would be scaled: fill * scale + offset
            scale = sst_var['attributes'].get('scale_factor', 1.0)
            offset = sst_var['attributes'].get('add_offset', 0.0)
            scaled_fill = fill_value * scale + offset - 273.15
            sst_celsius = np.ma.masked_where(np.isclose(sst_celsius, scaled_fill), sst_celsius)

        # Get mask if available
        mask = None
        if 'mask' in variables:
            mask_var = variables['mask']
            mask = mask_var['data'][0, :, :] if mask_var['data'].ndim == 3 else mask_var['data'][:, :]

        # Determine subsampling for large grids
        max_display = 5000
        subsample = max(1, max(len(lon), len(lat)) // max_display)

        if subsample > 1:
            print(f"   Subsampling by {subsample}x for display (full resolution: {len(lon)}×{len(lat)})")
            lon_plot = lon[::subsample]
            lat_plot = lat[::subsample]
            sst_plot = sst_celsius[::subsample, ::subsample]
            if mask is not None:
                mask_plot = mask[::subsample, ::subsample]
        else:
            lon_plot = lon
            lat_plot = lat
            sst_plot = sst_celsius
            mask_plot = mask

        print(f"   Creating MUR SST visualization...")
        print(f"   Display grid: {len(lon_plot)}×{len(lat_plot)}")

        # Compute robust colorbar limits
        sst_valid = (sst_plot[~sst_plot.mask] if hasattr(sst_plot, 'mask')
                     else sst_plot[~np.isnan(sst_plot)])
        if len(sst_valid) > 0:
            vmin = np.percentile(sst_valid, 1)
            vmax = np.percentile(sst_valid, 99)
        else:
            vmin, vmax = -2, 35

        # Create figure with 2 rows:
        # Row 1: Large SST map (full width)
        # Row 2: Histogram and mask side-by-side
        has_mask = mask is not None
        # Use constrained_layout for GridSpec compatibility (avoids tight_layout issues)
        fig = plt.figure(figsize=(18, 12), constrained_layout=True)

        # Use GridSpec for flexible layout
        gs = fig.add_gridspec(2, 2, height_ratios=[1.5, 1])

        # SST map - spans full width of top row
        ax1 = fig.add_subplot(gs[0, :])

        im1 = ax1.pcolormesh(lon_plot, lat_plot, sst_plot.T,
                             cmap='RdYlBu_r', vmin=vmin, vmax=vmax,
                             shading='auto')
        ax1.set_xlabel('Longitude (degrees)', fontsize=11)
        ax1.set_ylabel('Latitude (degrees)', fontsize=11)
        ax1.set_title('MUR SST Analysis (°C)', fontsize=14, fontweight='bold')
        ax1.set_aspect('equal', adjustable='box')
        ax1.grid(True, alpha=0.3)
        if has_cartopy:
            add_coastlines(ax1)
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
            from matplotlib.colors import BoundaryNorm
            mask_labels = {
                1: 'Open sea', 2: 'Land', 3: 'Coast',
                5: 'Open lake', 9: 'Sea+ice', 11: 'Coast+ice',
                13: 'Lake+ice', 15: 'Complex'
            }
            unique_vals = sorted(np.unique(mask_plot))
            n_colors = len(unique_vals)
            tab10 = plt.colormaps.get_cmap('tab10')
            colors = [tab10(i / 10) for i in range(n_colors)]
            cmap_mask = ListedColormap(colors)
            bounds = [unique_vals[0] - 0.5] + [v + 0.5 for v in unique_vals]
            norm = BoundaryNorm(bounds, cmap_mask.N)

            im3 = ax3.pcolormesh(lon_plot, lat_plot, mask_plot.T,
                                cmap=cmap_mask, norm=norm, shading='auto')
            ax3.set_xlabel('Longitude (degrees)')
            ax3.set_ylabel('Latitude (degrees)')
            ax3.set_title('Land/Sea/Ice Mask')
            ax3.set_aspect('equal', adjustable='box')
            ax3.grid(True, alpha=0.3)

            cbar3 = plt.colorbar(im3, ax=ax3, label='Surface Type',
                                ticks=unique_vals, shrink=0.8)
            cbar3.set_ticklabels([mask_labels.get(v, str(v))
                                  for v in unique_vals])

        # Add help text
        coastline_note = (
            "\n• Coastlines: cartopy installed" if has_cartopy
            else "\n• Install cartopy for coastlines"
        )

        title_str = data['attributes'].get('title', 'MUR SST L4 Analysis')
        resolution = f"{len(lon)}×{len(lat)}"
        if subsample > 1:
            resolution += f" (displayed at {len(lon_plot)}×{len(lat_plot)})"

        help_text = (
            f"MUR GHRSST L4 PRODUCT\n"
            f"Resolution: {resolution}\n"
            f"Spatial: ~0.01° (~1km)\n\n"
            "Variables shown:\n"
            "• analysed_sst: Foundation SST\n"
        )
        if mask is not None:
            help_text += "• mask: Surface classification\n"
        help_text += (
            f"\nOther variables available:\n"
            f"  {', '.join([v for v in ['analysis_error', 'sea_ice_fraction', 'dt_1km_data'] if v in variables])}\n"
            f"{coastline_note}"
        )

        fig.text(0.02, 0.02, help_text,
                fontsize=8, family='monospace',
                verticalalignment='bottom',
                bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.8))

        plt.suptitle(f'{filepath.name}\n{title_str}')
        print("   Rendering plot...")
        # Note: No tight_layout needed - using constrained_layout=True
        print("✅ Opening plot window...")
        plt.show()


def compare_files(file1: Path, file2: Path, tolerance: float = 1e-6):
    """
    Compare two data files of the same format.

    Args:
        file1: First file path
        file2: Second file path
        tolerance: Numerical tolerance for float comparisons
    """
    print(f"\nComparing:")
    print(f"  File 1: {file1}")
    print(f"  File 2: {file2}")
    print()

    # Detect formats
    fmt1 = DataFileReader.detect_format(file1)
    fmt2 = DataFileReader.detect_format(file2)

    if fmt1 != fmt2:
        print(f"❌ Different formats: {fmt1} vs {fmt2}")
        return

    # Read files
    print(f"Reading {fmt1} files...")
    data1 = read_file(file1)
    data2 = read_file(file2)

    # Compare based on format
    all_match = True

    if fmt1 in ['bip', 'biq']:
        # Compare point data
        if data1['N'] != data2['N']:
            print(f"❌ Different number of points: {data1['N']} vs {data2['N']}")
            all_match = False
        else:
            print(f"✅ Number of points match: {data1['N']}")

        for field in ['lon', 'lat', 'sst', 'hour', 'weight']:
            if not np.allclose(data1[field], data2[field], atol=tolerance, rtol=tolerance):
                max_diff = np.max(np.abs(data1[field] - data2[field]))
                print(f"❌ {field} differs (max diff: {max_diff})")
                all_match = False
            else:
                print(f"✅ {field} matches")

    elif fmt1 == 'gds':
        # Compare grid data
        if data1['dimensions'] != data2['dimensions']:
            print(f"❌ Different dimensions: {data1['dimensions']} vs {data2['dimensions']}")
            all_match = False
        else:
            print(f"✅ Dimensions match: {data1['dimensions']}")

        for field in ['mask', 'lon', 'lat', 'icemap']:
            arr1 = data1[field]
            arr2 = data2[field]

            if not np.allclose(arr1, arr2, atol=tolerance, rtol=tolerance):
                max_diff = np.max(np.abs(arr1.astype(float) - arr2.astype(float)))
                num_diff = np.sum(arr1 != arr2)
                pct_diff = 100.0 * num_diff / arr1.size
                print(f"❌ {field} differs: {num_diff:,} elements ({pct_diff:.4f}%), max diff: {max_diff}")
                all_match = False
            else:
                print(f"✅ {field} matches")

    else:
        print(f"⚠️  Comparison not implemented for {fmt1} format")

    print()
    if all_match:
        print("🎉 All fields match!")
    else:
        print("❌ Some differences found")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='MUR Data Viewer - Browse and visualize MUR SST processing data files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Supported formats:
  .bip      Ice SST point data
  .gds      Gridded land/ice mask
  .bii      In-situ buoy observations
  .bic      Satellite L2P swath data
  .biq      Unified observation format
  .bin      Legacy satellite format
  .map      Quick-look gridded SST output
  .cXX      Multi-scale coefficient files
  .uXX      Uncertainty coefficient files
  .nc/.nc4  NetCDF output files

Examples:
  # View and plot (default behavior)
  %(prog)s data.gds

  # View info only (no plot)
  %(prog)s data.bip --info

  # Compare two files
  %(prog)s file1.bip file2.bip --compare

  # Export to text
  %(prog)s data.biq --export output.txt
        """
    )

    parser.add_argument('file', type=str, nargs='+',
                        help='Data file(s) to view')
    parser.add_argument('--info', action='store_true',
                        help='Show info only (no plotting)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Show full details (e.g. all NetCDF global attributes)')
    parser.add_argument('--compare', action='store_true',
                        help='Compare two files (requires exactly 2 files)')
    parser.add_argument('--export', type=str, metavar='FILE',
                        help='Export data to text file')
    parser.add_argument('--resample', type=int, metavar='N',
                        help='Resampling factor for large grids '
                             '(default: auto, max 5000 pixels)')
    parser.add_argument('--tolerance', type=float, default=1e-6,
                        help='Numerical tolerance for comparisons (default: 1e-6)')

    args = parser.parse_args()

    # Validate arguments
    if args.compare:
        if len(args.file) != 2:
            print("❌ --compare requires exactly 2 files")
            sys.exit(1)
        compare_files(Path(args.file[0]), Path(args.file[1]), args.tolerance)
        return

    # Process each file
    for filepath_str in args.file:
        filepath = Path(filepath_str)

        if not filepath.exists():
            print(f"❌ File not found: {filepath}")
            continue

        try:
            # Detect format
            format_type = DataFileReader.detect_format(filepath)

            # Read file
            print(f"Reading {format_type.upper()} file: {filepath.name}")
            data = read_file(filepath)

            # Print info
            print_file_info(data, format_type, filepath, verbose=args.verbose)

            # Plot by default unless --info flag is set
            if not args.info:
                plot_data(data, format_type, filepath, args.resample)

            # Export if requested
            if args.export:
                export_path = Path(args.export)
                print(f"Exporting to {export_path}...")

                with open(export_path, 'w') as f:
                    f.write(f"# MUR Data Export\n")
                    f.write(f"# File: {filepath}\n")
                    f.write(f"# Format: {format_type}\n\n")

                    # Export based on format
                    if format_type in ['bip', 'biq', 'bii', 'bic', 'bin']:
                        # Point data: lon, lat, sst, ...
                        f.write("# lon, lat, sst")
                        if 'hour' in data:
                            f.write(", hour")
                        if 'weight' in data:
                            f.write(", weight")
                        if 'bias' in data:
                            f.write(", bias, rms")
                        f.write("\n")

                        for i in range(len(data['lon'])):
                            f.write(f"{data['lon'][i]:.6f}, {data['lat'][i]:.6f}, {data['sst'][i]:.6f}")
                            if 'hour' in data:
                                f.write(f", {data['hour'][i]:.6f}")
                            if 'weight' in data:
                                f.write(f", {data['weight'][i]:.6f}")
                            if 'bias' in data:
                                f.write(f", {data['bias'][i]:.6f}, {data['rms'][i]:.6f}")
                            f.write("\n")
                    else:
                        f.write("# Export not implemented for this format\n")

                print(f"✅ Exported to {export_path}")

        except Exception as e:
            print(f"❌ Error processing {filepath}: {e}")
            import traceback
            traceback.print_exc()


if __name__ == '__main__':
    main()
