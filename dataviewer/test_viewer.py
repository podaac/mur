#!/usr/bin/env python3
"""
Simple test script for MUR Data Viewer.

Tests basic functionality with sample data files from landice tests.
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from format_readers import read_file, DataFileReader


def test_format_detection():
    """Test format detection from filenames."""
    print("Testing format detection...")

    test_cases = [
        ('landice_2025_199.gds.gz', 'gds'),
        ('icesst_2025_199.bip', 'bip'),
        ('Global_IQUAM0_2025_199.bii', 'bii'),
        ('Global_MODISA_2025_199.bic.gz', 'bic'),
        ('data.biq', 'biq'),
        ('sensor.bin', 'bin'),
        ('20250718_MRVA4_Global.c10', 'csp'),
        ('20250718_MRVA4_Global.u08', 'usp'),
        ('20250718090000-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv04.1.nc', 'nc'),
    ]

    passed = 0
    failed = 0

    for filename, expected_format in test_cases:
        try:
            detected = DataFileReader.detect_format(filename)
            if detected == expected_format:
                print(f"  ✅ {filename:60s} → {detected}")
                passed += 1
            else:
                print(f"  ❌ {filename:60s} → {detected} (expected {expected_format})")
                failed += 1
        except Exception as e:
            print(f"  ❌ {filename:60s} → Error: {e}")
            failed += 1

    print(f"\nFormat detection: {passed} passed, {failed} failed\n")
    return failed == 0


def test_read_sample_files():
    """Test reading actual sample files if available."""
    print("Testing file reading with sample files...")

    # Look for sample files in landice test directory
    test_dir = Path(__file__).parent.parent / 'landice' / 'tests' / 'truth-data'

    if not test_dir.exists():
        print(f"  ⚠️  Test directory not found: {test_dir}")
        print(f"  Skipping file reading tests\n")
        return True

    # Find sample files
    sample_files = []

    # Look for GDS files
    gds_files = list(test_dir.glob('land/**/2025/*.gds.gz'))
    if gds_files:
        sample_files.append(('GDS', gds_files[0]))

    # Look for BIP files
    bip_files = list(test_dir.glob('land/**/2025/*.bip.gz'))
    if bip_files:
        sample_files.append(('BIP', bip_files[0]))

    if not sample_files:
        print(f"  ⚠️  No sample files found in {test_dir}")
        print(f"  Skipping file reading tests\n")
        return True

    passed = 0
    failed = 0

    for format_type, filepath in sample_files:
        try:
            print(f"  Reading {format_type}: {filepath.name}... ", end='')
            data = read_file(filepath)

            # Basic validation
            if format_type == 'GDS':
                assert 'dimensions' in data
                assert 'mask' in data
                assert 'lon' in data
                assert 'lat' in data
                assert 'icemap' in data
                ii, jj = data['dimensions']
                assert data['mask'].shape == (ii, jj)
                print(f"✅ ({ii}×{jj} grid)")
            elif format_type == 'BIP':
                assert 'N' in data
                assert 'lon' in data
                assert 'lat' in data
                assert 'sst' in data
                assert 'weight' in data
                assert len(data['lon']) == data['N']
                print(f"✅ ({data['N']} points)")

            passed += 1

        except Exception as e:
            print(f"❌")
            print(f"    Error: {e}")
            failed += 1

    print(f"\nFile reading: {passed} passed, {failed} failed\n")
    return failed == 0


def test_fortran_io():
    """Test Fortran I/O utilities."""
    print("Testing Fortran I/O...")

    from fortran_io import FortranReader
    import tempfile
    import struct
    import numpy as np

    # Create a temporary Fortran binary file
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = tmp.name

        # Write a simple record: 3 int32 values
        data = struct.pack('<I', 12)  # Header: 3 * 4 bytes
        data += struct.pack('<iii', 10, 20, 30)  # Data
        data += struct.pack('<I', 12)  # Trailer
        tmp.write(data)

    try:
        # Read it back
        with FortranReader(tmp_path) as reader:
            header = reader.read_record_header()
            values = reader.read_int32(3)
            trailer = reader.read_record_trailer()

            assert header == 12, f"Header mismatch: {header} != 12"
            assert trailer == 12, f"Trailer mismatch: {trailer} != 12"
            assert values == (10, 20, 30), f"Values mismatch: {values} != (10, 20, 30)"

        print("  ✅ FortranReader working correctly")

        # Clean up
        Path(tmp_path).unlink()
        return True

    except Exception as e:
        print(f"  ❌ FortranReader test failed: {e}")
        Path(tmp_path).unlink()
        return False


def main():
    """Run all tests."""
    print("="*80)
    print("MUR Data Viewer - Test Suite")
    print("="*80)
    print()

    results = []

    results.append(("Format Detection", test_format_detection()))
    results.append(("Fortran I/O", test_fortran_io()))
    results.append(("File Reading", test_read_sample_files()))

    print("="*80)
    print("Test Summary")
    print("="*80)

    all_passed = True
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {test_name:30s} {status}")
        if not passed:
            all_passed = False

    print()

    if all_passed:
        print("🎉 All tests passed!")
        return 0
    else:
        print("❌ Some tests failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())
