"""
Format readers for MUR SST data files.

Supports reading various binary formats used in MUR processing:
- .bip: Ice SST point data
- .gds: Gridded land/ice mask
- .bii: In-situ observations (buoys)
- .bic: Satellite swath with bias/error
- .biq: Unified observation format
- .bin: Legacy satellite format
- .map: Quick-look gridded SST output
- .cXX: Multi-scale coefficient files
- .uXX: Uncertainty coefficient files
- .nc/.nc4: NetCDF output files
"""

import gzip
import struct
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, Union
import numpy as np

# Handle both relative and absolute imports
try:
    from .fortran_io import FortranReader, fortread
except ImportError:
    from fortran_io import FortranReader, fortread


class DataFileReader:
    """Base class for MUR data file readers."""

    @staticmethod
    def detect_format(filepath: Union[str, Path]) -> str:
        """
        Detect file format from filename.

        Args:
            filepath: Path to file

        Returns:
            Format string: 'bip', 'gds', 'bii', 'bic', 'biq', 'bin', 'map', 'csp', 'usp', 'nc'

        Raises:
            ValueError: If format cannot be determined
        """
        filepath = Path(filepath)
        name = filepath.name.lower()

        # Handle compressed files
        if name.endswith('.gz'):
            name = name[:-3]

        if '.bip' in name:
            return 'bip'
        elif '.gds' in name:
            return 'gds'
        elif '.bii' in name:
            return 'bii'
        elif '.bic' in name:
            return 'bic'
        elif '.biq' in name:
            return 'biq'
        elif '.bin' in name:
            return 'bin'
        elif '.map' in name:
            return 'map'
        elif name.endswith('.nc') or name.endswith('.nc4'):
            return 'nc'
        elif '.c' in name and any(name.endswith(f'.c{i:02d}') for i in range(20)):
            return 'csp'
        elif '.u' in name and any(name.endswith(f'.u{i:02d}') for i in range(20)):
            return 'usp'
        else:
            raise ValueError(f"Unknown file format: {filepath}")

    @staticmethod
    def open_file(filepath: Union[str, Path], mode: str = 'rb'):
        """
        Open file, handling gzip compression automatically.

        Args:
            filepath: Path to file
            mode: File mode ('rb' for binary read)

        Returns:
            File handle (regular or gzip)
        """
        filepath = Path(filepath)
        if filepath.suffix == '.gz':
            return gzip.open(filepath, mode)
        else:
            return open(filepath, mode)


class BIPReader(DataFileReader):
    """
    Reader for .bip files (Ice SST point data).

    Format:
        Record 1: N (int32) - number of points
        Record 2: lon, lat, hour, sst, weight (N float32 each)
    """

    @staticmethod
    def read(filepath: Union[str, Path]) -> Dict[str, Any]:
        """
        Read .bip file.

        Args:
            filepath: Path to .bip or .bip.gz file

        Returns:
            Dictionary with keys:
                - N: number of points
                - lon: longitude array (degrees, -180 to 180)
                - lat: latitude array (degrees, -90 to 90)
                - hour: time offset array (hours from day start)
                - sst: SST array (degrees C)
                - weight: weight array
        """
        with BIPReader.open_file(filepath) as f:
            # Handle gzip: read to temp file
            if filepath.suffix == '.gz':
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(f.read())
                    tmp_path = tmp.name

                with FortranReader(tmp_path) as reader:
                    result = BIPReader._read_fortran(reader)

                Path(tmp_path).unlink()
                return result
            else:
                with FortranReader(filepath) as reader:
                    return BIPReader._read_fortran(reader)

    @staticmethod
    def _read_fortran(reader: FortranReader) -> Dict[str, Any]:
        """Read BIP data from FortranReader."""
        # Record 1: N
        header1 = reader.read_record_header()
        N = reader.read_int32()
        trailer1 = reader.read_record_trailer()

        if header1 != trailer1 or header1 != 4:
            raise ValueError(f"Invalid N record")

        # Record 2: data arrays
        header2 = reader.read_record_header()
        lon = reader.read_float32(N)
        lat = reader.read_float32(N)
        hour = reader.read_float32(N)
        sst = reader.read_float32(N)
        weight = reader.read_float32(N)
        trailer2 = reader.read_record_trailer()

        expected_size = N * 4 * 5
        if header2 != trailer2 or header2 != expected_size:
            raise ValueError(f"Invalid data arrays record")

        return {
            'N': N,
            'lon': lon,
            'lat': lat,
            'hour': hour,
            'sst': sst,
            'weight': weight
        }


class GDSReader(DataFileReader):
    """
    Reader for .gds files (Gridded land/ice mask).

    Format:
        Record 1: ii, jj (int32) - grid dimensions
        Record 2: mask (ii×jj int8), lon (ii float32), lat (jj float32)
        Record 3: icemap (ii×jj int8)
    """

    @staticmethod
    def read(filepath: Union[str, Path]) -> Dict[str, Any]:
        """
        Read .gds file.

        Args:
            filepath: Path to .gds or .gds.gz file

        Returns:
            Dictionary with keys:
                - dimensions: (ii, jj) tuple
                - mask: land/ice mask array (ii×jj)
                - lon: longitude array (ii)
                - lat: latitude array (jj)
                - icemap: ice concentration array (ii×jj, -1 to 100)
        """
        with GDSReader.open_file(filepath) as f:
            # Handle gzip: read to temp file
            if str(filepath).endswith('.gz'):
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(f.read())
                    tmp_path = tmp.name

                with FortranReader(tmp_path) as reader:
                    result = GDSReader._read_fortran(reader)

                Path(tmp_path).unlink()
                return result
            else:
                with FortranReader(filepath) as reader:
                    return GDSReader._read_fortran(reader)

    @staticmethod
    def _read_fortran(reader: FortranReader) -> Dict[str, Any]:
        """Read GDS data from FortranReader."""
        # Record 1: dimensions
        header1 = reader.read_record_header()
        ii = reader.read_int32()
        jj = reader.read_int32()
        trailer1 = reader.read_record_trailer()

        if header1 != trailer1 or header1 != 8:
            raise ValueError(f"Invalid dimensions record")

        # Record 2: mask and coordinates
        header2 = reader.read_record_header()
        # IMPORTANT: Data is written in Fortran/column-major order
        # Use order='F' to reshape correctly
        mask = reader.read_int8(ii * jj).reshape((ii, jj), order='F')
        lon = reader.read_float32(ii)
        lat = reader.read_float32(jj)
        trailer2 = reader.read_record_trailer()

        expected_size = ii * jj * 1 + ii * 4 + jj * 4
        if header2 != trailer2 or header2 != expected_size:
            raise ValueError(f"Invalid mask/coordinates record")

        # Record 3: icemap
        header3 = reader.read_record_header()
        # IMPORTANT: Data is written in Fortran/column-major order
        icemap = reader.read_int8(ii * jj).reshape((ii, jj), order='F')
        trailer3 = reader.read_record_trailer()

        expected_size = ii * jj * 1
        if header3 != trailer3 or header3 != expected_size:
            raise ValueError(f"Invalid icemap record")

        return {
            'dimensions': (ii, jj),
            'mask': mask,
            'lon': lon,
            'lat': lat,
            'icemap': icemap
        }


class BIIReader(DataFileReader):
    """
    Reader for .bii files (In-situ buoy observations).

    Format:
        Record 1: N, year, day (int16)
        Record 2: sst, lon, lat, hour, platform_type (N int16 each, scaled)

    Scaling:
        - sst: divide by 100, subtract 273.15 for Celsius
        - lon, lat, hour, platform_type: divide by 100
    """

    @staticmethod
    def read(filepath: Union[str, Path]) -> Dict[str, Any]:
        """
        Read .bii file.

        Args:
            filepath: Path to .bii file

        Returns:
            Dictionary with keys:
                - N: number of observations
                - year: year
                - day: day of year
                - sst: SST array (degrees C)
                - lon: longitude array (degrees)
                - lat: latitude array (degrees)
                - hour: time array (hours from day start)
                - platform_type: platform type codes
        """
        with open(filepath, 'rb') as f:
            # Record 1: header
            N, year, day = fortread(f, 'integer*4', 1, 'integer*2', 1, 'integer*2', 1)

            # Record 2: data arrays (scaled int16 + platform as int8)
            sst_scaled, lon_scaled, lat_scaled, hour_scaled, platform = fortread(
                f, 'integer*2', N, 'integer*2', N, 'integer*2', N,
                'integer*2', N, 'int8', N
            )

            # Unscale
            scale = 100.0
            sst = sst_scaled / scale  # Already in Celsius
            lon = lon_scaled / scale
            lat = lat_scaled / scale
            hour = hour_scaled / scale
            platform_type = platform.astype(float)  # Platform codes are integers

            return {
                'N': N,
                'year': year,
                'day': day,
                'sst': sst,
                'lon': lon,
                'lat': lat,
                'hour': hour,
                'platform_type': platform_type
            }


class BICReader(DataFileReader):
    """
    Reader for .bic files (Satellite L2P swath with bias/error).

    Format:
        Record 1: year, day, N (int32)
        Record 2: offset, sst_scale, hour_scale (float32)
        Record 3: lon, lat, hour, sst, bias, rms, quality (arrays)

    Data is compressed: sst/bias are int16, rms/quality are uint8.
    """

    @staticmethod
    def read(filepath: Union[str, Path]) -> Dict[str, Any]:
        """
        Read .bic or .bic.gz file.

        Args:
            filepath: Path to .bic or .bic.gz file

        Returns:
            Dictionary with keys:
                - year: year
                - day: day of year
                - N: number of observations
                - lon: longitude array (degrees)
                - lat: latitude array (degrees)
                - hour: time array (hours)
                - sst: SST array (degrees C)
                - bias: bias array (degrees)
                - rms: RMS error array (degrees)
                - quality: quality flag array
        """
        # Handle gzip
        if str(filepath).endswith('.gz'):
            with gzip.open(filepath, 'rb') as gz:
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(gz.read())
                    tmp_path = tmp.name

            with open(tmp_path, 'rb') as f:
                result = BICReader._read_file(f)

            Path(tmp_path).unlink()
            return result
        else:
            with open(filepath, 'rb') as f:
                return BICReader._read_file(f)

    @staticmethod
    def _read_file(f) -> Dict[str, Any]:
        """Read BIC data from file handle."""
        # Record 1: header
        year, day, N = fortread(f, 'integer*4', 1, 'integer*4', 1, 'integer*4', 1)

        # Record 2: scaling parameters
        offset, sst_scale, hour_scale = fortread(
            f, 'real*4', 1, 'real*4', 1, 'real*4', 1
        )

        # Record 3: data arrays
        lon, lat, hour_raw, sst_raw, bias_raw, rms_raw, quality = fortread(
            f, 'real*4', N, 'real*4', N, 'integer*2', N,
            'integer*2', N, 'integer*2', N, 'uint8', N, 'uint8', N
        )

        # Unscale
        hour = hour_raw * hour_scale
        sst = sst_raw * sst_scale + offset
        bias = bias_raw * sst_scale
        rms = rms_raw * sst_scale

        return {
            'year': year,
            'day': day,
            'N': N,
            'lon': lon,
            'lat': lat,
            'hour': hour,
            'sst': sst,
            'bias': bias,
            'rms': rms,
            'quality': quality
        }


class BIQReader(DataFileReader):
    """
    Reader for .biq files (Unified observation format).

    Format:
        Record 1: N (int32)
        Record 2: lon, lat, hour, sst, weight (N float32 each)
    """

    @staticmethod
    def read(filepath: Union[str, Path]) -> Dict[str, Any]:
        """
        Read .biq file.

        Args:
            filepath: Path to .biq file

        Returns:
            Dictionary with keys:
                - N: number of observations
                - lon: longitude array (degrees)
                - lat: latitude array (degrees)
                - hour: time array (hours)
                - sst: SST array (degrees C)
                - weight: weight array
        """
        with open(filepath, 'rb') as f:
            # Record 1: N
            N = fortread(f, 'integer*4', 1)

            # Record 2: data arrays
            lon, lat, hour, sst, weight = fortread(
                f, 'real*4', N, 'real*4', N, 'real*4', N,
                'real*4', N, 'real*4', N
            )

            return {
                'N': N,
                'lon': lon,
                'lat': lat,
                'hour': hour,
                'sst': sst,
                'weight': weight
            }


class BINReader(DataFileReader):
    """
    Reader for .bin files (Legacy satellite format).

    Format:
        Record 1: year, day, N (int32)
        Record 2: lon, lat, sst, bias, rms, hour, conf, sun (arrays)
    """

    @staticmethod
    def read(filepath: Union[str, Path]) -> Dict[str, Any]:
        """
        Read .bin file.

        Args:
            filepath: Path to .bin file

        Returns:
            Dictionary with keys:
                - year: year
                - day: day of year
                - N: number of observations
                - lon: longitude array (degrees)
                - lat: latitude array (degrees)
                - sst: SST array (degrees C)
                - bias: bias array (degrees)
                - rms: RMS error array (degrees)
                - hour: time array (hours)
                - confidence: confidence level array
                - sun: solar zenith indicator (< 0 = night, > 0 = day)
        """
        with open(filepath, 'rb') as f:
            # Record 1: header
            year, day, N = fortread(f, 'integer*4', 1, 'integer*4', 1, 'integer*4', 1)

            # Record 2: data arrays
            lon, lat, sst, bias, rms, hour, conf, sun = fortread(
                f, 'real*4', N, 'real*4', N, 'real*4', N, 'real*4', N,
                'real*4', N, 'real*4', N, 'integer*4', N, 'real*4', N
            )

            return {
                'year': year,
                'day': day,
                'N': N,
                'lon': lon,
                'lat': lat,
                'sst': sst,
                'bias': bias,
                'rms': rms,
                'hour': hour,
                'confidence': conf,
                'sun': sun
            }


class MAPReader(DataFileReader):
    """
    Reader for .map files (Quick-look gridded SST output).

    Format:
        Record 1: nlon, nlat (int32) - grid dimensions
        Record 2: sst (nlon×nlat float32), lon (nlon float32), lat (nlat float32)

    SST values are in Kelvin. Values > 400K are considered invalid.
    """

    @staticmethod
    def read(filepath: Union[str, Path]) -> Dict[str, Any]:
        """
        Read .map file.

        Args:
            filepath: Path to .map file

        Returns:
            Dictionary with keys:
                - dimensions: (nlon, nlat) tuple
                - sst: SST array (nlon×nlat) in Celsius
                - lon: longitude array (nlon)
                - lat: latitude array (nlat)
        """
        with FortranReader(filepath) as reader:
            # Record 1: dimensions
            header1 = reader.read_record_header()
            nlon = reader.read_int32()
            nlat = reader.read_int32()
            trailer1 = reader.read_record_trailer()

            if header1 != trailer1 or header1 != 8:
                raise ValueError("Invalid dimensions record")

            # Record 2: SST grid and coordinates
            header2 = reader.read_record_header()
            # IMPORTANT: Data is written in Fortran/column-major order
            sst = reader.read_float32(nlon * nlat).reshape((nlon, nlat), order='F')
            lon = reader.read_float32(nlon)
            lat = reader.read_float32(nlat)
            trailer2 = reader.read_record_trailer()

            expected_size = nlon * nlat * 4 + nlon * 4 + nlat * 4
            if header2 != trailer2 or header2 != expected_size:
                raise ValueError("Invalid SST/coordinates record")

            # Convert from Kelvin to Celsius
            # Mark invalid values (> 400K or == 999.0) as NaN
            sst_celsius = sst.copy()
            invalid_mask = (sst > 400.0) | (sst == 999.0)
            sst_celsius[invalid_mask] = np.nan
            sst_celsius[~invalid_mask] = sst_celsius[~invalid_mask] - 273.15

            return {
                'dimensions': (nlon, nlat),
                'sst': sst_celsius,
                'lon': lon,
                'lat': lat
            }


class CSPReader(DataFileReader):
    """
    Reader for .cXX coefficient files (Multi-scale analysis coefficients).

    Format:
        Record 1: mx, my, mz, nv (int32)
        Record 2: xmin, xmax, ymin, ymax (float32)
        Record 3: csp array ((mx+3-cix) × (my+3) × mz × nv float32)

    The coefficient array represents B-spline basis function coefficients
    on a hierarchical grid at scale L.
    """

    @staticmethod
    def read(filepath: Union[str, Path]) -> Dict[str, Any]:
        """
        Read .cXX coefficient file.

        Args:
            filepath: Path to coefficient file (e.g., .c10, .c11)

        Returns:
            Dictionary with keys:
                - mx, my, mz, nv: grid dimensions
                - xmin, xmax, ymin, ymax: coordinate bounds
                - coefficients: coefficient array
                - scale: scale level (from filename)
        """
        # Extract scale from filename
        name = Path(filepath).name
        if '.c' in name:
            scale_str = name.split('.c')[-1]
            scale = int(scale_str)
        else:
            scale = None

        with FortranReader(filepath) as reader:
            # Record 1: dimensions
            header1 = reader.read_record_header()
            mx, my, mz, nv = reader.read_int32(4)
            trailer1 = reader.read_record_trailer()

            if header1 != trailer1 or header1 != 16:
                raise ValueError("Invalid dimensions record")

            # Record 2: bounds
            header2 = reader.read_record_header()
            xmin, xmax, ymin, ymax = reader.read_float32(4)
            trailer2 = reader.read_record_trailer()

            if header2 != trailer2 or header2 != 16:
                raise ValueError("Invalid bounds record")

            # Record 3: coefficient array
            # Note: actual dimension is (mx+3-cix) where cix=3 for cyclic boundary
            # From spmm.f: parameter(cix=3) and mx3 = mx+3-cix
            # So the array size is: mx × (my+3) × mz × nv
            cix = 3  # Cyclic boundary condition parameter
            total_size = (mx + 3 - cix) * (my + 3) * mz * nv

            header3 = reader.read_record_header()
            coefficients = reader.read_float32(total_size)
            trailer3 = reader.read_record_trailer()

            expected_size = total_size * 4
            if header3 != trailer3 or header3 != expected_size:
                raise ValueError("Invalid coefficient array record")

            # Reshape coefficient array
            # IMPORTANT: Data is written in Fortran/column-major order
            coefficients = coefficients.reshape(
                (mx + 3 - cix, my + 3, mz, nv), order='F'
            )

            return {
                'mx': mx,
                'my': my,
                'mz': mz,
                'nv': nv,
                'xmin': xmin,
                'xmax': xmax,
                'ymin': ymin,
                'ymax': ymax,
                'coefficients': coefficients,
                'scale': scale
            }


class USPReader(DataFileReader):
    """
    Reader for .uXX uncertainty files (same format as .cXX).

    Contains diagonal approximation of inverse Hessian (1/A_ii)
    representing posterior variance at each grid point.
    """

    @staticmethod
    def read(filepath: Union[str, Path]) -> Dict[str, Any]:
        """
        Read .uXX uncertainty file (same format as CSP).

        Args:
            filepath: Path to uncertainty file (e.g., .u06, .u08)

        Returns:
            Same structure as CSPReader.read()
        """
        return CSPReader.read(filepath)


class NetCDFReader(DataFileReader):
    """
    Reader for MUR NetCDF4 output files.

    Requires netCDF4 package.
    """

    @staticmethod
    def read(filepath: Union[str, Path]) -> Dict[str, Any]:
        """
        Read MUR NetCDF4 file.

        Args:
            filepath: Path to .nc or .nc4 file

        Returns:
            Dictionary with keys:
                - variables: dict of variable name -> data array
                - attributes: global attributes
                - dimensions: dimension sizes
        """
        try:
            from netCDF4 import Dataset
        except ImportError:
            raise ImportError(
                "netCDF4 package required to read NetCDF files. "
                "Install with: pip install netCDF4"
            )

        with Dataset(filepath, 'r') as ds:
            # Read all variables
            variables = {}
            for var_name in ds.variables:
                var = ds.variables[var_name]
                variables[var_name] = {
                    'data': var[:],
                    'dimensions': var.dimensions,
                    'attributes': {attr: var.getncattr(attr)
                                   for attr in var.ncattrs()}
                }

            # Read global attributes
            attributes = {attr: ds.getncattr(attr) for attr in ds.ncattrs()}

            # Read dimensions
            dimensions = {dim: len(ds.dimensions[dim])
                          for dim in ds.dimensions}

            return {
                'variables': variables,
                'attributes': attributes,
                'dimensions': dimensions
            }


def read_file(filepath: Union[str, Path]) -> Dict[str, Any]:
    """
    Auto-detect format and read MUR data file.

    Args:
        filepath: Path to data file

    Returns:
        Dictionary with file contents (structure depends on format)

    Raises:
        ValueError: If file format is not recognized
    """
    format_type = DataFileReader.detect_format(filepath)

    readers = {
        'bip': BIPReader,
        'gds': GDSReader,
        'bii': BIIReader,
        'bic': BICReader,
        'biq': BIQReader,
        'bin': BINReader,
        'map': MAPReader,
        'csp': CSPReader,
        'usp': USPReader,
        'nc': NetCDFReader,
    }

    if format_type not in readers:
        raise ValueError(f"No reader available for format: {format_type}")

    return readers[format_type].read(filepath)
