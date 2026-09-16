#!/usr/bin/env python3
"""
Compare truth-data and out directories for landice processing validation.

Ice files: Text files with accumulated lists - check that all truth-data entries
          are contained in out entries.
Land files: Binary Fortran format files (.gds and .bip) - check file presence
           and data values match to 1e-6 precision.
"""

import os
import sys
import gzip
import struct
import argparse
import numpy as np
from pathlib import Path


class FortranReader:
    """Read Fortran unformatted binary files with record headers/trailers."""

    def __init__(self, file_path):
        self.file_path = file_path
        self.f = None

    def __enter__(self):
        self.f = open(self.file_path, 'rb')
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.f:
            self.f.close()

    def read_record_header(self):
        """Read 4-byte record header."""
        data = self.f.read(4)
        if len(data) != 4:
            raise EOFError("Could not read record header")
        return struct.unpack('<I', data)[0]

    def read_record_trailer(self):
        """Read 4-byte record trailer."""
        data = self.f.read(4)
        if len(data) != 4:
            raise EOFError("Could not read record trailer")
        return struct.unpack('<I', data)[0]

    def read_int32(self, count=1):
        """Read int32 values."""
        data = self.f.read(4 * count)
        if len(data) != 4 * count:
            raise EOFError(f"Could not read {count} int32 values")
        if count == 1:
            return struct.unpack('<i', data)[0]
        return struct.unpack(f'<{count}i', data)

    def read_int8(self, count):
        """Read int8 values."""
        data = self.f.read(count)
        if len(data) != count:
            raise EOFError(f"Could not read {count} int8 values")
        return np.frombuffer(data, dtype=np.int8)

    def read_float32(self, count):
        """Read float32 values."""
        data = self.f.read(4 * count)
        if len(data) != 4 * count:
            raise EOFError(f"Could not read {count} float32 values")
        return np.frombuffer(data, dtype=np.float32)


def read_gds_file(file_path):
    """Read .gds file in Fortran format."""
    with FortranReader(file_path) as reader:
        # Read dimensions record
        header1 = reader.read_record_header()
        ii = reader.read_int32()
        jj = reader.read_int32()
        trailer1 = reader.read_record_trailer()

        if header1 != trailer1 or header1 != 8:
            raise ValueError(f"Invalid dimensions record in {file_path}")

        # Read mask and coordinates record
        header2 = reader.read_record_header()
        mask = reader.read_int8(ii * jj).reshape((ii, jj))
        mlon = reader.read_float32(ii)
        mlat = reader.read_float32(jj)
        trailer2 = reader.read_record_trailer()

        expected_size = ii * jj * 1 + ii * 4 + jj * 4
        if header2 != trailer2 or header2 != expected_size:
            raise ValueError(f"Invalid mask/coordinates record in {file_path}")

        # Read icemap record
        header3 = reader.read_record_header()
        icemap = reader.read_int8(ii * jj).reshape((ii, jj))
        trailer3 = reader.read_record_trailer()

        expected_size = ii * jj * 1
        if header3 != trailer3 or header3 != expected_size:
            raise ValueError(f"Invalid icemap record in {file_path}")

    return {
        'dimensions': (ii, jj),
        'mask': mask,
        'mlon': mlon,
        'mlat': mlat,
        'icemap': icemap
    }


def read_bip_file(file_path):
    """Read .bip file in Fortran format."""
    with FortranReader(file_path) as reader:
        # Read N record
        header1 = reader.read_record_header()
        N = reader.read_int32()
        trailer1 = reader.read_record_trailer()

        if header1 != trailer1 or header1 != 4:
            raise ValueError(f"Invalid N record in {file_path}")

        # Read data arrays record
        header2 = reader.read_record_header()
        icelon = reader.read_float32(N)
        icelat = reader.read_float32(N)
        dhr = reader.read_float32(N)
        sst = reader.read_float32(N)
        wgt = reader.read_float32(N)
        trailer2 = reader.read_record_trailer()

        expected_size = N * 4 * 5  # 5 arrays of N float32s each
        if header2 != trailer2 or header2 != expected_size:
            raise ValueError(f"Invalid data arrays record in {file_path}")

    return {
        'N': N,
        'icelon': icelon,
        'icelat': icelat,
        'dhr': dhr,
        'sst': sst,
        'wgt': wgt
    }


def compare_ice_files(truth_dir, out_dir, year=None, day=None):
    """Compare ice files (text lists) - check truth entries are in out entries."""
    print("Comparing ice files...")

    truth_ice_dir = Path(truth_dir) / "ice"
    out_ice_dir = Path(out_dir) / "ice"

    if not truth_ice_dir.exists():
        print(f"❌ Truth ice directory not found: {truth_ice_dir}")
        return False

    if not out_ice_dir.exists():
        print(f"❌ Output ice directory not found: {out_ice_dir}")
        return False

    all_passed = True

    # Find all ice files in truth directory
    truth_ice_files = list(truth_ice_dir.rglob("*.txt"))

    for truth_file in truth_ice_files:
        # Filter by year/day if specified
        if year is not None:
            if f"/{year}/" not in str(truth_file):
                continue
        if day is not None:
            day_str = f"{int(day):03d}"
            if f"_{year}_{day_str}.txt" not in truth_file.name:
                continue
        # Get relative path from truth_ice_dir
        rel_path = truth_file.relative_to(truth_ice_dir)
        out_file = out_ice_dir / rel_path

        if not out_file.exists():
            print(f"❌ Missing output ice file: {rel_path}")
            all_passed = False
            continue

        # Read both files
        try:
            with open(truth_file, 'r') as f:
                truth_lines = set(line.strip() for line in f if line.strip())

            with open(out_file, 'r') as f:
                out_lines = set(line.strip() for line in f if line.strip())

            # Check if all truth entries are in out entries
            missing_entries = truth_lines - out_lines
            if missing_entries:
                print(f"❌ {rel_path}: Missing {len(missing_entries)} entries in output")
                for entry in sorted(missing_entries)[:5]:  # Show first 5
                    print(f"    Missing: {entry}")
                if len(missing_entries) > 5:
                    print(f"    ... and {len(missing_entries) - 5} more")
                all_passed = False
            else:
                print(f"✅ {rel_path}: All truth entries present in output")

        except Exception as e:
            print(f"❌ Error comparing {rel_path}: {e}")
            all_passed = False

    return all_passed


def compare_land_files(truth_dir, out_dir, tolerance=1e-6, year=None, day=None, plot=False):
    """Compare land files (.gds and .bip) - check presence and data values."""
    print("Comparing land files...")

    truth_land_dir = Path(truth_dir) / "land"
    out_land_dir = Path(out_dir) / "land"

    if not truth_land_dir.exists():
        print(f"❌ Truth land directory not found: {truth_land_dir}")
        return False

    if not out_land_dir.exists():
        print(f"❌ Output land directory not found: {out_land_dir}")
        return False

    all_passed = True

    # Find all land files in truth directory
    truth_land_files = list(truth_land_dir.rglob("*.gz"))

    for truth_file in truth_land_files:
        # Filter by year/day if specified
        if year is not None:
            if f"/{year}/" not in str(truth_file):
                continue
        if day is not None:
            day_str = f"{int(day):03d}"
            if f"_{year}_{day_str}." not in truth_file.name:
                continue
        # Get relative path from truth_land_dir
        rel_path = truth_file.relative_to(truth_land_dir)
        out_file = out_land_dir / rel_path

        if not out_file.exists():
            print(f"❌ Missing output land file: {rel_path}")
            all_passed = False
            continue

        try:
            # Decompress and read files
            with gzip.open(truth_file, 'rb') as f:
                truth_data = f.read()
            with gzip.open(out_file, 'rb') as f:
                out_data = f.read()

            # Create temporary files for reading
            import tempfile
            with tempfile.NamedTemporaryFile() as truth_temp, \
                 tempfile.NamedTemporaryFile() as out_temp:

                truth_temp.write(truth_data)
                truth_temp.flush()
                out_temp.write(out_data)
                out_temp.flush()

                # Determine file type and read accordingly
                if rel_path.suffix == '.gz' and '.gds' in rel_path.name:
                    # .gds file
                    truth_parsed = read_gds_file(truth_temp.name)
                    out_parsed = read_gds_file(out_temp.name)

                    # Compare dimensions
                    if truth_parsed['dimensions'] != out_parsed['dimensions']:
                        print(f"❌ {rel_path}: Dimension mismatch")
                        all_passed = False
                        continue

                    # Compare arrays with tolerance
                    arrays_to_compare = ['mask', 'mlon', 'mlat', 'icemap']
                    arrays_match = True
                    diff_info = {}

                    for array_name in arrays_to_compare:
                        truth_array = truth_parsed[array_name]
                        out_array = out_parsed[array_name]

                        if not np.allclose(truth_array, out_array, atol=tolerance, rtol=tolerance):
                            max_diff = np.max(np.abs(truth_array - out_array))
                            num_diff = np.sum(truth_array != out_array)
                            total_elements = truth_array.size
                            pct_diff = 100.0 * num_diff / total_elements

                            msg = (
                                f"❌ {rel_path}: {array_name} differs - "
                                f"{num_diff}/{total_elements} elements "
                                f"({pct_diff:.4f}%), max diff: {max_diff}"
                            )
                            print(msg)
                            diff_info[array_name] = {
                                'truth': truth_array,
                                'output': out_array,
                                'max_diff': max_diff,
                                'num_diff': num_diff,
                                'pct_diff': pct_diff
                            }
                            all_passed = False
                            arrays_match = False

                    if arrays_match:
                        print(f"✅ {rel_path}: All arrays match within tolerance")

                    # Plot if requested
                    if plot and '.gds' in rel_path.name:
                        plot_gds_comparison(
                            truth_parsed, out_parsed, rel_path, diff_info
                        )

                elif rel_path.suffix == '.gz' and '.bip' in rel_path.name:
                    # .bip file
                    truth_parsed = read_bip_file(truth_temp.name)
                    out_parsed = read_bip_file(out_temp.name)

                    # Compare N
                    if truth_parsed['N'] != out_parsed['N']:
                        print(f"❌ {rel_path}: N mismatch ({truth_parsed['N']} vs {out_parsed['N']})")
                        all_passed = False
                        continue

                    # Compare arrays with tolerance
                    arrays_to_compare = ['icelon', 'icelat', 'dhr', 'sst', 'wgt']
                    for array_name in arrays_to_compare:
                        truth_array = truth_parsed[array_name]
                        out_array = out_parsed[array_name]

                        if not np.allclose(truth_array, out_array, atol=tolerance, rtol=tolerance):
                            max_diff = np.max(np.abs(truth_array - out_array))
                            print(f"❌ {rel_path}: {array_name} values differ (max diff: {max_diff})")
                            all_passed = False
                            break
                    else:
                        print(f"✅ {rel_path}: All arrays match within tolerance")
                else:
                    print(f"⚠️  {rel_path}: Unknown file type, skipping")

        except Exception as e:
            print(f"❌ Error comparing {rel_path}: {e}")
            all_passed = False

    return all_passed


def plot_gds_comparison(truth_parsed, out_parsed, rel_path, diff_info):
    """Plot comparison of GDS files with automatic resampling for large grids."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("⚠️  matplotlib not available, skipping plot")
        return

    # Determine which arrays to plot - prioritize those with differences
    arrays_to_plot = []
    if diff_info:
        # Plot arrays that differ, sorted by max difference
        sorted_diffs = sorted(
            diff_info.items(),
            key=lambda x: x[1]['max_diff'],
            reverse=True
        )
        arrays_to_plot = [name for name, _ in sorted_diffs]
    else:
        # No differences, just plot mask and icemap
        arrays_to_plot = ['mask', 'icemap']

    for array_name in arrays_to_plot:
        if array_name in ['mask', 'icemap']:
            # Get arrays (2D)
            truth_array = truth_parsed[array_name].T  # Transpose
            out_array = out_parsed[array_name].T

            # Determine if resampling needed
            max_display_size = 2000
            ii, jj = truth_array.shape
            need_resample = max(ii, jj) > max_display_size

            if need_resample:
                # Calculate resampling factor
                resample_factor = int(
                    np.ceil(max(ii, jj) / max_display_size)
                )
                print(f"  Plotting {array_name}: "
                      f"Large grid ({ii}x{jj}), "
                      f"resampling by {resample_factor}x for display")

                # Resample using simple indexing
                truth_display = truth_array[::resample_factor,
                                           ::resample_factor]
                out_display = out_array[::resample_factor,
                                       ::resample_factor]
            else:
                truth_display = truth_array
                out_display = out_array

            # Create figure with linked axes
            fig, axes = plt.subplots(1, 3, figsize=(15, 5))

            # Link all axes for synchronized zooming/panning
            axes[1].sharex(axes[0])
            axes[1].sharey(axes[0])
            axes[2].sharex(axes[0])
            axes[2].sharey(axes[0])

            # Determine color scale based on data
            if array_name == 'mask':
                vmin, vmax = truth_array.min(), truth_array.max()
                cmap = 'tab10'
            else:  # icemap
                vmin, vmax = -1, 100
                cmap = 'viridis'

            # Plot truth
            im1 = axes[0].imshow(truth_display, cmap=cmap,
                                vmin=vmin, vmax=vmax)
            axes[0].set_title(f'Truth - {array_name}\n{rel_path.name}')
            axes[0].set_xlabel('X index')
            axes[0].set_ylabel('Y index')
            plt.colorbar(im1, ax=axes[0], fraction=0.046, pad=0.04)

            # Plot output
            im2 = axes[1].imshow(out_display, cmap=cmap,
                                vmin=vmin, vmax=vmax)
            axes[1].set_title(f'Output - {array_name}\n{rel_path.name}')
            axes[1].set_xlabel('X index')
            axes[1].set_ylabel('Y index')
            plt.colorbar(im2, ax=axes[1], fraction=0.046, pad=0.04)

            # Plot difference - compute from FULL resolution data
            full_diff = (
                out_array.astype(float) - truth_array.astype(float)
            )
            full_max_diff = np.max(np.abs(full_diff))

            # Find locations of differences for markers
            diff_mask = full_diff != 0
            diff_indices = np.argwhere(diff_mask)

            # Compute display difference with max/min downsampling
            if need_resample:
                # Use max/min downsampling to preserve differences
                diff_display = np.zeros(
                    (truth_display.shape[0], truth_display.shape[1])
                )
                for i in range(diff_display.shape[0]):
                    for j in range(diff_display.shape[1]):
                        # Get the block from full resolution
                        i_start = i * resample_factor
                        i_end = min((i + 1) * resample_factor, full_diff.shape[0])
                        j_start = j * resample_factor
                        j_end = min((j + 1) * resample_factor, full_diff.shape[1])
                        block = full_diff[i_start:i_end, j_start:j_end]

                        # Use max absolute value
                        abs_block = np.abs(block)
                        max_idx = np.unravel_index(
                            np.argmax(abs_block), abs_block.shape
                        )
                        diff_display[i, j] = block[max_idx]
            else:
                diff_display = full_diff

            # Use full resolution max diff for colorbar scaling
            im3 = axes[2].imshow(
                diff_display, cmap='RdBu_r',
                vmin=-full_max_diff if full_max_diff > 0 else -1,
                vmax=full_max_diff if full_max_diff > 0 else 1
            )

            # Overlay markers for first 10 differences on all plots
            if len(diff_indices) > 0:
                num_markers = min(10, len(diff_indices))
                # Get first N differences
                marker_locs = diff_indices[:num_markers]

                # Convert to display coordinates if resampled
                if need_resample:
                    marker_locs_display = marker_locs / resample_factor
                else:
                    marker_locs_display = marker_locs

                # Plot markers on all three subplots
                for ax_idx, ax in enumerate(axes):
                    ax.scatter(
                        marker_locs_display[:, 1],
                        marker_locs_display[:, 0],
                        c='red' if ax_idx == 2 else 'yellow',
                        marker='x',
                        s=100,
                        linewidths=2,
                        label=f'First {num_markers} diffs'
                    )
                    ax.legend(loc='upper right', fontsize=8)

            # Add difference info to title
            if array_name in diff_info:
                info = diff_info[array_name]
                diff_title = (
                    f'Difference\nMax: {full_max_diff:.1f}, '
                    f'{info["num_diff"]:,} elements '
                    f'({info["pct_diff"]:.4f}%)'
                )
                axes[2].set_title(diff_title)
            else:
                axes[2].set_title(f'Difference\nMax: {full_max_diff:.1f}')

            axes[2].set_xlabel('X index')
            axes[2].set_ylabel('Y index')
            plt.colorbar(im3, ax=axes[2], fraction=0.046, pad=0.04)

            # Title
            title_parts = []
            if need_resample:
                title_parts.append(
                    f'Resampled by {resample_factor}x for display'
                )
            if array_name in diff_info:
                title_parts.append(
                    f'⚠️ {array_name.upper()} HAS DIFFERENCES'
                )
            title_parts.append('Press any key to continue...')
            plt.suptitle('\n'.join(title_parts))

            plt.tight_layout()
            plt.show()

            # Print statistics for full-resolution data
            print(f"  {array_name} - Grid shape: {truth_array.shape}")
            print(f"  {array_name} - Diff range: "
                  f"[{full_diff.min():.6f}, {full_diff.max():.6f}]")
            print(f"  {array_name} - Diff mean: "
                  f"{full_diff.mean():.6f}")
            print(f"  {array_name} - Diff std: "
                  f"{full_diff.std():.6f}")
            print(f"  {array_name} - Max absolute diff: "
                  f"{np.abs(full_diff).max():.6f}")
            if array_name in diff_info:
                num_diff = diff_info[array_name]['num_diff']
                pct_diff = diff_info[array_name]['pct_diff']
                print(f"  {array_name} - Different elements: "
                      f"{num_diff:,} ({pct_diff:.4f}%)")

            # Print first 10 difference locations
            if len(diff_indices) > 0:
                num_to_show = min(10, len(diff_indices))
                print(f"  {array_name} - First {num_to_show} "
                      f"diff locations (i, j, truth, output, diff):")
                for idx in range(num_to_show):
                    i, j = diff_indices[idx]
                    truth_val = truth_array[i, j]
                    out_val = out_array[i, j]
                    diff_val = full_diff[i, j]
                    print(f"    [{idx+1}] ({i:5d}, {j:5d}): "
                          f"{truth_val:6.1f} -> {out_val:6.1f} "
                          f"(diff: {diff_val:+6.1f})")
            print()



def main():
    """Main comparison function."""
    parser = argparse.ArgumentParser(
        description='Compare truth-data and output directories for landice processing validation'
    )
    parser.add_argument('truth_dir', nargs='?', default=None,
                        help='Truth data directory (default: tests/truth-data)')
    parser.add_argument('out_dir', nargs='?', default=None,
                        help='Output directory (default: tests/out)')
    parser.add_argument('--year', type=str, default=None,
                        help='Filter by year (e.g., 2025)')
    parser.add_argument('--day', type=str, default=None,
                        help='Filter by day of year (e.g., 199)')
    parser.add_argument('--plot', action='store_true',
                        help='Enable plotting comparison (pauses for each file)')

    args = parser.parse_args()

    # Default paths relative to script location
    script_dir = Path(__file__).parent
    truth_dir = Path(args.truth_dir) if args.truth_dir else script_dir / "truth-data"
    out_dir = Path(args.out_dir) if args.out_dir else script_dir / "out"

    print(f"Comparing truth-data: {truth_dir}")
    print(f"         with output: {out_dir}")
    if args.year:
        print(f"Filtering by year: {args.year}")
    if args.day:
        print(f"Filtering by day: {args.day}")
    if args.plot:
        print("Plot mode: enabled")
    print()

    if not truth_dir.exists():
        print(f"❌ Truth directory not found: {truth_dir}")
        sys.exit(1)

    if not out_dir.exists():
        print(f"❌ Output directory not found: {out_dir}")
        sys.exit(1)

    # Run comparisons
    ice_passed = compare_ice_files(truth_dir, out_dir, year=args.year, day=args.day)
    print()
    land_passed = compare_land_files(truth_dir, out_dir, year=args.year, day=args.day, plot=args.plot)

    print()
    if ice_passed and land_passed:
        print("🎉 All comparisons passed!")
        sys.exit(0)
    else:
        print("❌ Some comparisons failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()