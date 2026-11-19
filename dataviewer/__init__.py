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

# Data-source layer. Imported lazily-safe: sources.py pulls earthaccess,
# s3fs and requests only inside the methods that need them, so importing the
# package never requires any of the remote-access dependencies.
from .viewer_config import ViewerConfig, load_config
from .sources import (
    Granule,
    Catalog,
    CatalogError,
    CatalogUnavailable,
    LocalCatalog,
    PublicMurCatalog,
    MaapStacCatalog,
    get_catalog,
    parse_l4_date,
)

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
    'ViewerConfig',
    'load_config',
    'Granule',
    'Catalog',
    'CatalogError',
    'CatalogUnavailable',
    'LocalCatalog',
    'PublicMurCatalog',
    'MaapStacCatalog',
    'get_catalog',
    'parse_l4_date',
]
