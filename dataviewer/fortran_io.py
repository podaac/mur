"""
Fortran binary I/O utilities for reading MUR data files.

Fortran unformatted binary files have a record structure where each record
is wrapped with 4-byte headers and trailers indicating the record size.
"""

import struct
import numpy as np
from typing import BinaryIO, Tuple, Union, List


class FortranReader:
    """Read Fortran unformatted binary files with record headers/trailers."""

    def __init__(self, file_path: str):
        """
        Initialize Fortran file reader.

        Args:
            file_path: Path to the Fortran binary file
        """
        self.file_path = file_path
        self.f: Union[BinaryIO, None] = None

    def __enter__(self):
        """Open file for reading."""
        self.f = open(self.file_path, 'rb')
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close file."""
        if self.f:
            self.f.close()

    def read_record_header(self) -> int:
        """
        Read 4-byte record header.

        Returns:
            Size of the following data record in bytes

        Raises:
            EOFError: If header cannot be read
        """
        data = self.f.read(4)
        if len(data) != 4:
            raise EOFError("Could not read record header")
        return struct.unpack('<I', data)[0]

    def read_record_trailer(self) -> int:
        """
        Read 4-byte record trailer.

        Returns:
            Size of the preceding data record (should match header)

        Raises:
            EOFError: If trailer cannot be read
        """
        data = self.f.read(4)
        if len(data) != 4:
            raise EOFError("Could not read record trailer")
        return struct.unpack('<I', data)[0]

    def read_int32(self, count: int = 1) -> Union[int, Tuple[int, ...]]:
        """
        Read int32 values.

        Args:
            count: Number of int32 values to read

        Returns:
            Single int if count=1, tuple of ints otherwise

        Raises:
            EOFError: If data cannot be read
        """
        data = self.f.read(4 * count)
        if len(data) != 4 * count:
            raise EOFError(f"Could not read {count} int32 values")
        if count == 1:
            return struct.unpack('<i', data)[0]
        return struct.unpack(f'<{count}i', data)

    def read_int16(self, count: int) -> np.ndarray:
        """
        Read int16 values into numpy array.

        Args:
            count: Number of int16 values to read

        Returns:
            NumPy array of int16 values

        Raises:
            EOFError: If data cannot be read
        """
        data = self.f.read(2 * count)
        if len(data) != 2 * count:
            raise EOFError(f"Could not read {count} int16 values")
        return np.frombuffer(data, dtype=np.int16)

    def read_int8(self, count: int) -> np.ndarray:
        """
        Read int8 values into numpy array.

        Args:
            count: Number of int8 values to read

        Returns:
            NumPy array of int8 values

        Raises:
            EOFError: If data cannot be read
        """
        data = self.f.read(count)
        if len(data) != count:
            raise EOFError(f"Could not read {count} int8 values")
        return np.frombuffer(data, dtype=np.int8)

    def read_uint8(self, count: int) -> np.ndarray:
        """
        Read uint8 values into numpy array.

        Args:
            count: Number of uint8 values to read

        Returns:
            NumPy array of uint8 values

        Raises:
            EOFError: If data cannot be read
        """
        data = self.f.read(count)
        if len(data) != count:
            raise EOFError(f"Could not read {count} uint8 values")
        return np.frombuffer(data, dtype=np.uint8)

    def read_float32(self, count: int) -> np.ndarray:
        """
        Read float32 values into numpy array.

        Args:
            count: Number of float32 values to read

        Returns:
            NumPy array of float32 values

        Raises:
            EOFError: If data cannot be read
        """
        data = self.f.read(4 * count)
        if len(data) != 4 * count:
            raise EOFError(f"Could not read {count} float32 values")
        return np.frombuffer(data, dtype=np.float32)

    def read_record(self, *dtypes_and_counts) -> Union[np.ndarray, Tuple]:
        """
        Read a complete Fortran record with automatic header/trailer validation.

        Args:
            *dtypes_and_counts: Pairs of (dtype, count) where dtype is a numpy
                               dtype string and count is the number of elements

        Returns:
            Single array if one dtype specified, tuple of arrays otherwise

        Example:
            # Read record with 100 float32s followed by 100 int32s
            floats, ints = reader.read_record('float32', 100, 'int32', 100)
        """
        header = self.read_record_header()

        results = []
        expected_size = 0

        i = 0
        while i < len(dtypes_and_counts):
            dtype_str = dtypes_and_counts[i]
            count = dtypes_and_counts[i + 1]
            i += 2

            dtype = np.dtype(dtype_str)
            expected_size += dtype.itemsize * count

            data = self.f.read(dtype.itemsize * count)
            if len(data) != dtype.itemsize * count:
                raise EOFError(f"Could not read {count} {dtype_str} values")

            arr = np.frombuffer(data, dtype=dtype)
            if count == 1 and not isinstance(count, tuple):
                results.append(arr[0])
            else:
                results.append(arr)

        trailer = self.read_record_trailer()

        if header != trailer or header != expected_size:
            raise ValueError(
                f"Record size mismatch: header={header}, trailer={trailer}, "
                f"expected={expected_size}"
            )

        if len(results) == 1:
            return results[0]
        return tuple(results)


def fortread(f: BinaryIO, *args) -> Union[np.ndarray, Tuple]:
    """
    MATLAB-style fortread function for compatibility with existing code.

    Reads Fortran unformatted records. Each record is wrapped with 4-byte
    header and trailer indicating record size.

    Args:
        f: Open file handle
        *args: Variable arguments specifying data types and counts
               Format: (dtype, count, dtype, count, ...)
               dtype can be: 'integer*4', 'integer*2', 'real*4', 'uint8'
               count is number of elements to read

    Returns:
        Single array if one type specified, tuple of arrays otherwise

    Example:
        # Read 1 int32, 1 int32, 1 int32
        year, day, N = fortread(f, 'integer*4', 1, 'integer*4', 1, 'integer*4', 1)

        # Read N float32s
        lon = fortread(f, 'real*4', N)
    """
    # Parse arguments
    if len(args) % 2 != 0:
        # Old-style: fortread(f, count1, count2, ...)
        # Assumes all float32
        results = []
        for count in args:
            arr = np.frombuffer(f.read(4 * count), dtype=np.float32)
            results.append(arr)
        return tuple(results) if len(results) > 1 else results[0]

    # New-style: fortread(f, 'dtype', count, 'dtype', count, ...)
    header_data = f.read(4)
    if len(header_data) != 4:
        raise EOFError("Could not read record header")
    header = struct.unpack('<I', header_data)[0]

    results = []
    expected_size = 0

    i = 0
    while i < len(args):
        dtype_str = args[i]
        count = args[i + 1]
        i += 2

        # Map MATLAB dtype names to numpy
        dtype_map = {
            'integer*4': ('int32', 4),
            'integer*2': ('int16', 2),
            'real*4': ('float32', 4),
            'uint8': ('uint8', 1),
            'int8': ('int8', 1),
        }

        if dtype_str not in dtype_map:
            raise ValueError(f"Unknown dtype: {dtype_str}")

        np_dtype, itemsize = dtype_map[dtype_str]
        expected_size += itemsize * count

        data = f.read(itemsize * count)
        if len(data) != itemsize * count:
            raise EOFError(f"Could not read {count} {dtype_str} values")

        arr = np.frombuffer(data, dtype=np_dtype)

        # Return scalar for single values
        if count == 1:
            if np_dtype == 'float32':
                results.append(float(arr[0]))
            else:
                results.append(int(arr[0]))
        else:
            results.append(arr)

    trailer_data = f.read(4)
    if len(trailer_data) != 4:
        raise EOFError("Could not read record trailer")
    trailer = struct.unpack('<I', trailer_data)[0]

    if header != trailer or header != expected_size:
        raise ValueError(
            f"Record size mismatch: header={header}, trailer={trailer}, "
            f"expected={expected_size}"
        )

    if len(results) == 1:
        return results[0]
    return tuple(results)
