"""
MUR Data Viewer - Browse and visualize MUR SST processing data files.

This package provides tools for reading, analyzing, and visualizing
various binary and NetCDF formats used in the MUR SST processing pipeline.
"""

from .format_readers import (
    read_file,
    DataFileReader,
    BIPReader,
    GDSReader,
    BIIReader,
    BICReader,
    BIQReader,
    BINReader,
    CSPReader,
    USPReader,
    NetCDFReader,
)

from .fortran_io import FortranReader, fortread

__version__ = '1.0.0'
__all__ = [
    'read_file',
    'DataFileReader',
    'BIPReader',
    'GDSReader',
    'BIIReader',
    'BICReader',
    'BIQReader',
    'BINReader',
    'CSPReader',
    'USPReader',
    'NetCDFReader',
    'FortranReader',
    'fortread',
]
