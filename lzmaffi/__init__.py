# vim: ts=4 sw=4 et
"""Interface to the liblzma compression library.

This module provides a class for reading and writing compressed files,
classes for incremental (de)compression, and convenience functions for
one-shot (de)compression.

These classes and functions support both the XZ and legacy LZMA
container formats, as well as raw compressed data streams.
"""

__all__ = [
    "CHECK_NONE", "CHECK_CRC32", "CHECK_CRC64", "CHECK_SHA256",
    "CHECK_ID_MAX", "CHECK_UNKNOWN",
    "FILTER_LZMA1", "FILTER_LZMA2", "FILTER_DELTA", "FILTER_X86", "FILTER_IA64",
    "FILTER_ARM", "FILTER_ARMTHUMB", "FILTER_POWERPC", "FILTER_SPARC",
    "FORMAT_AUTO", "FORMAT_XZ", "FORMAT_ALONE", "FORMAT_RAW",
    "MF_HC3", "MF_HC4", "MF_BT2", "MF_BT3", "MF_BT4",
    "MODE_FAST", "MODE_NORMAL", "PRESET_DEFAULT", "PRESET_EXTREME",
    "STREAM_HEADER_SIZE",
    "decode_stream_footer", "decode_index",

    "LZMACompressor", "LZMADecompressor", "LZMAFile", "LZMAError",
    "open", "compress", "decompress", "is_check_supported",
]

import io
from io import DEFAULT_BUFFER_SIZE as _BUFFER_SIZE
from ._lzmamodule2 import *
from ._lzmamodule2 import _encode_filter_properties, _decode_filter_properties

SEEK_SET, SEEK_CUR, SEEK_END = 0, 1, 2

_MODE_CLOSED   = 0
_MODE_READ     = 1
_MODE_READ_EOF = 2
_MODE_WRITE    = 3

__version__ = "0.3.0"

def memoryview_tobytes(buffer):
    return buffer.tobytes() if isinstance(buffer, memoryview) else buffer

class _LZMAFile(io.BufferedIOBase):
    """A file object providing transparent LZMA (de)compression.

    An _LZMAFile acts as a wrapper for an existing file object. To
    refer directly to a named file on disk, use lzma.open.

    Note that _LZMAFile provides a *binary* file interface - data read
    is returned as bytes, and data to be written must be given as bytes.
    """

    def __init__(self, fp, mode="r",
                 format=None, check=-1, close_fp=False, preset=None, filters=None):
        self._mode = _MODE_CLOSED
        self._pos = 0
        self._size = -1

        if mode in ("r", "rb"):
            if check != -1:
                raise ValueError("Cannot specify an integrity check "
                                 "when opening a file for reading")
            if preset is not None:
                raise ValueError("Cannot specify a preset compression "
                                 "level when opening a file for reading")
            if format is None:
                format = FORMAT_AUTO
            mode_code = _MODE_READ
            # Save the args to pass to the LZMADecompressor initializer.
            # If the file contains multiple compressed streams, each
            # stream will need a separate decompressor object.
            self._init_args = {"format":format, "filters":filters}
            self._decompressor = LZMADecompressor(**self._init_args)
            self._buffer = None
        elif mode in ("w", "wb", "a", "ab"):
            if format is None:
                format = FORMAT_XZ
            mode_code = _MODE_WRITE
            self._compressor = LZMACompressor(format=format, check=check,
                                              preset=preset, filters=filters)
        else:
            raise ValueError("Invalid mode: {!r}".format(mode))

        self._fp = fp
        self._closefp = close_fp
        self._mode = mode_code

    def close(self):
        """Flush and close the file.

        May be called more than once without error. Once the file is
        closed, any other operation on it will raise a ValueError.
        """
        if self._mode == _MODE_CLOSED:
            return
        try:
            if self._mode in (_MODE_READ, _MODE_READ_EOF):
                self._decompressor = None
                self._buffer = None
            elif self._mode == _MODE_WRITE:
                self._fp.write(self._compressor.flush())
                self._compressor = None
        finally:
            try:
                if self._closefp:
                    self._fp.close()
            finally:
                self._fp = None
                self._closefp = False
                self._mode = _MODE_CLOSED

    @property
    def closed(self):
        """True if this file is closed."""
        return self._mode == _MODE_CLOSED

    def fileno(self):
        """Return the file descriptor for the underlying file."""
        self._check_not_closed()
        return self._fp.fileno()

    def readable(self):
        """Return whether the file was opened for reading."""
        self._check_not_closed()
        return self._mode in (_MODE_READ, _MODE_READ_EOF)

    def writable(self):
        """Return whether the file was opened for writing."""
        self._check_not_closed()
        return self._mode == _MODE_WRITE

    def seekable(self):
        """Return whether the file can be seeked."""
        self._check_not_closed()
        return False

    # Mode-checking helper functions.

    def _check_not_closed(self):
        if self.closed:
            raise ValueError("I/O operation on closed file")

    def _check_can_read(self):
        if not self.readable():
            raise io.UnsupportedOperation("File not open for reading")

    def _check_can_write(self):
        if not self.writable():
            raise io.UnsupportedOperation("File not open for writing")

    # Fill the readahead buffer if it is empty. Returns False on EOF.
    def _fill_buffer(self):
        # Depending on the input data, our call to the decompressor may not
        # return any data. In this case, try again after reading another block.
        while True:
            if self._buffer:
                return True

            if self._decompressor.unused_data:
                rawblock = self._decompressor.unused_data
            else:
                rawblock = self._fp.read(_BUFFER_SIZE)

            if not rawblock:
                if self._decompressor.eof:
                    self._mode = _MODE_READ_EOF
                    self._size = self._pos
                    return False
                else:
                    raise EOFError("Compressed file ended before the "
                                   "end-of-stream marker was reached")

            # Continue to next stream.
            if self._decompressor.eof:
                self._decompressor = LZMADecompressor(**self._init_args)

            # running memoryview here would often copy the bytes because
            # memoryview(b'data').tobytes() copies the bytes.
            # instead, self._buffer is made into a memoryview whenever it's a
            # bytes object that gets sliced.
            self._buffer = self._decompressor.decompress(rawblock)

    def read(self, size=-1):
        """Read up to size uncompressed bytes from the file.

        If size is negative or omitted, read until EOF is reached.
        Returns b"" if the file is already at EOF.
        """
        self._check_can_read()
        if size is None:
            #This is not needed on Python 3 where the comparison to zeo
            #will fail with a TypeError.
            raise TypeError("Read size should be an integer, not None")
        if self._mode == _MODE_READ_EOF or size == 0:
            return b""
        elif size < 0:
            return self._read_all()
        else:
            return self._read_block(size)

    # Read data until EOF.
    # If return_data is false, consume the data without returning it.
    def _read_all(self, return_data=True):
        blocks = []
        while self._fill_buffer():
            if return_data:
                blocks.append(memoryview_tobytes(self._buffer))
            self._pos += len(self._buffer)
            self._buffer = None
        if return_data:
            return b"".join(blocks)

    # Read a block of up to n bytes.
    # If return_data is false, consume the data without returning it.
    def _read_block(self, n, return_data=True):
        blocks = []
        while n > 0 and self._fill_buffer():
            if n < len(self._buffer):
                data = memoryview_tobytes(self._buffer[:n])
                self._buffer = memoryview(self._buffer)[n:]
            else:
                data = memoryview_tobytes(self._buffer)
                self._buffer = None
            if return_data:
                blocks.append(data)
            self._pos += len(data)
            n -= len(data)
        if return_data:
            return b"".join(blocks)

    def peek(self, size=-1):
        """Return buffered data without advancing the file position.

        Always returns at least one byte of data, unless at EOF.
        The exact number of bytes returned is unspecified.
        """
        self._check_can_read()
        if self._mode == _MODE_READ_EOF or not self._fill_buffer():
            return b""
        return memoryview_tobytes(self._buffer)

    def read1(self, size=-1):
        """Read up to size uncompressed bytes, while trying to avoid
        making multiple reads from the underlying stream.

        Returns b"" if the file is at EOF.
        """
        # Usually, read1() calls _fp.read() at most once. However, sometimes
        # this does not give enough data for the decompressor to make progress.
        # In this case we make multiple reads, to avoid returning b"".
        self._check_can_read()
        if size is None:
            #This is not needed on Python 3 where the comparison to zero
            #will fail with a TypeError. 
            raise TypeError("Read size should be an integer, not None")
        if (size == 0 or self._mode == _MODE_READ_EOF or
            not self._fill_buffer()):
            return b""
        if 0 < size < len(self._buffer):
            data = memoryview_tobytes(self._buffer[:size])
            self._buffer = memoryview(self._buffer)[size:]
        else:
            data = memoryview_tobytes(self._buffer)
            self._buffer = None
        self._pos += len(data)
        return data

    def write(self, data):
        """Write a bytes object to the file.

        Returns the number of uncompressed bytes written, which is
        always len(data). Note that due to buffering, the file on disk
        may not reflect the data written until close() is called.
        """
        self._check_can_write()
        compressed = self._compressor.compress(data)
        self._fp.write(compressed)
        self._pos += len(data)
        return len(data)

    def tell(self):
        """Return the current file position."""
        self._check_not_closed()
        return self._pos

def _peek(fp, n):
    ret = fp.read(n)
    fp.seek(-len(ret), SEEK_CUR)
    if len(ret) != n:
        return False
    return ret

class _SeekableXZFile(io.BufferedIOBase):
    def __init__(self, fp, close_fp=False):
        self._mode = _MODE_CLOSED
        self._fp = fp
        self._closefp = close_fp
        index = None
        filesize = fp.seek(0, SEEK_END)

        checks = []
        while fp.tell() > 0:
            # read one stream
            if fp.tell() < 2 * STREAM_HEADER_SIZE:
                raise LZMAError("file too small")

            # read stream paddings (4 bytes each)
            fp.seek(-4, SEEK_CUR)
            padding = 0
            while _peek(fp, 4) == b'\x00\x00\x00\x00':
                fp.seek(-4, SEEK_CUR)
                padding += 4

            fp.seek(-STREAM_HEADER_SIZE + 4, SEEK_CUR)

            stream_flags = decode_stream_footer(_peek(fp, STREAM_HEADER_SIZE))
            fp.seek(-stream_flags.backward_size, SEEK_CUR)

            new_index = decode_index(_peek(fp, stream_flags.backward_size), padding)
            fp.seek(-new_index.blocks_size, SEEK_CUR)
            fp.seek(-STREAM_HEADER_SIZE, SEEK_CUR)

            stream_flags2 = decode_stream_header(_peek(fp, STREAM_HEADER_SIZE))
            if not stream_flags.matches(stream_flags2):
                raise LZMAError("header and footer don't match")
            checks.append(stream_flags.check)
            
            if index is not None:
                new_index.append(index)
            index = new_index
        if index is None:
            raise LZMAError("file is empty")

        checks.reverse()
        self._check = checks
        self._index = index
        self._size = index.uncompressed_size
        self._move_to_block(0)

    block_boundaries = property(lambda self: [block.uncompressed_file_offset for _i, block in self._index])

    def _init_decompressor(self, stream_data, block_data):
        self._mode = _MODE_READ
        self._pos = self._block_offset = block_data.uncompressed_file_offset
        self._block_ends_at = block_data.uncompressed_file_offset + \
                block_data.uncompressed_size
        self._buffer = None
        self._fp.seek(block_data.compressed_file_offset, SEEK_SET)
        header_size = decode_block_header_size(_peek(self._fp, 1))
        header = self._fp.read(header_size)
        self._decompressor = LZMADecompressor(format=FORMAT_BLOCK, header=header,
                check=self._check[stream_data.number-1],
                unpadded_size=block_data.unpadded_size)

    def _move_to_block(self, offset):
        # find and load the block that has the byte at 'offset'.
        next_block_details = self._index.find(offset)
        if next_block_details is None:
            self._pos = self._size
            self._mode = _MODE_READ_EOF
            return False
        else:
            self._init_decompressor(*next_block_details)
            return True

    def read(self, size=-1):
        """Read up to size uncompressed bytes from the file.

        If size is negative or omitted, read until EOF is reached.
        Returns b"" if the file is already at EOF.
        """
        self._check_not_closed()
        if size is None:
            #This is not needed on Python 3 where the comparison to zeo
            #will fail with a TypeError.
            raise TypeError("Read size should be an integer, not None")
        if self._mode == _MODE_READ_EOF or size == 0:
            return b""
        elif size < 0:
            return self._read_all()
        else:
            return self._read_block(size)

    # Read data until EOF.
    # If return_data is false, consume the data without returning it.
    def _read_all(self, return_data=True):
        blocks = []
        while self._fill_buffer():
            if return_data:
                blocks.append(memoryview_tobytes(self._buffer))
            self._pos += len(self._buffer)
            self._buffer = None
        if return_data:
            return b"".join(blocks)

    # Read a block of up to n bytes.
    # If return_data is false, consume the data without returning it.
    def _read_block(self, n, return_data=True):
        blocks = []
        while n > 0 and self._fill_buffer():
            if n < len(self._buffer):
                data = memoryview_tobytes(self._buffer[:n])
                self._buffer = memoryview(self._buffer)[n:]
            else:
                data = memoryview_tobytes(self._buffer)
                self._buffer = None
            if return_data:
                blocks.append(data)
            self._pos += len(data)
            n -= len(data)
        if return_data:
            return b"".join(blocks)

    def peek(self, size=-1):
        """Return buffered data without advancing the file position.

        Always returns at least one byte of data, unless at EOF.
        The exact number of bytes returned is unspecified.
        """
        self._check_not_closed()
        if self._mode == _MODE_READ_EOF or not self._fill_buffer():
            return b""
        return memoryview_tobytes(self._buffer)

    def read1(self, size=-1):
        """Read up to size uncompressed bytes, while trying to avoid
        making multiple reads from the underlying stream.

        Returns b"" if the file is at EOF.
        """
        # Usually, read1() calls _fp.read() at most once. However, sometimes
        # this does not give enough data for the decompressor to make progress.
        # In this case we make multiple reads, to avoid returning b"".
        self._check_not_closed()
        if size is None:
            #This is not needed on Python 3 where the comparison to zero
            #will fail with a TypeError. 
            raise TypeError("Read size should be an integer, not None")
        if (size == 0 or self._mode == _MODE_READ_EOF or
            not self._fill_buffer()):
            return b""
        if 0 < size < len(self._buffer):
            data = memoryview_tobytes(self._buffer[:size])
            self._buffer = memoryview(self._buffer)[size:]
        else:
            data = memoryview_tobytes(self._buffer)
            self._buffer = None
        self._pos += len(data)
        return data

    # Fill the readahead buffer if it is empty. Returns False on EOF.
    def _fill_buffer(self):
        # Depending on the input data, our call to the decompressor may not
        # return any data. In this case, try again after reading another block.
        while True:
            if self._buffer:
                return True

            if self._decompressor.unused_data:
                rawblock = self._decompressor.unused_data
            else:
                rawblock = self._fp.read(_BUFFER_SIZE)

            if not rawblock:
                if self._decompressor.eof:
                    self._mode = _MODE_READ_EOF
                    return False
                else:
                    raise EOFError("Compressed file ended before the "
                                   "end-of-stream marker was reached")

            # Continue to next block or stream.
            if self._decompressor.eof:
                if self._move_to_block(self._pos):
                    continue
                else:
                    return False

            self._buffer = self._decompressor.decompress(rawblock)

    def seek(self, offset, whence=0):
        """Change the file position.

        The new position is specified by offset, relative to the
        position indicated by whence. Possible values for whence are:

            0: start of stream (default): offset must not be negative
            1: current stream position
            2: end of stream; offset must not be positive

        Returns the new file position.

        Note that seeking is emulated, sp depending on the parameters,
        this operation may be extremely slow.
        """
        if offset is None:
            #This is not needed on Python 3 where the comparison to self._pos
            #will fail with a TypeError.
            raise TypeError("Seek offset should be an integer, not None")

        self._check_not_closed()

        # Recalculate offset as an absolute file position.
        if whence == 0:
            pass
        elif whence == 1:
            offset = self._pos + offset
        elif whence == 2:
            offset = self._size + offset
        else:
            raise ValueError("Invalid value for whence: {}".format(whence))

        offset = max(offset, 0)

        if not self._pos <= offset < self._block_ends_at:
            # switch blocks or load the block from its first byte.
            # this changes self._pos.
            self._move_to_block(offset)

        # Make it so that offset is the number of bytes to skip forward.
        offset -= self._pos

        # Read and discard data until we reach the desired position.
        if self._mode != _MODE_READ_EOF:
            self._read_block(offset, return_data=False)

        return self._pos

    def tell(self):
        self._check_not_closed()
        return self._pos

    def fileno(self):
        """Return the file descriptor for the underlying file."""
        self._check_not_closed()
        return self._fp.fileno()

    @property
    def closed(self):
        return self._mode == _MODE_CLOSED

    def _check_not_closed(self):
        if self.closed:
            raise ValueError("I/O operation on closed file")

    def close(self):
        """Flush and close the file.

        May be called more than once without error. Once the file is
        closed, any other operation on it will raise a ValueError.
        """
        if self.closed:
            return
        try:
            if self._closefp:
                self._fp.close()
        finally:
            self._decompressor = None
            self._buffer = None
            self._fp = None
            self._closefp = False
            self._mode = _MODE_CLOSED

    def writable(self):
        self._check_not_closed()
        return False

    def readable(self):
        self._check_not_closed()
        return True

    def seekable(self):
        self._check_not_closed()
        return True

def LZMAFile(filename, mode="r",
                 format=None, check=-1, preset=None, filters=None, seek=True):
    """Open an LZMA-compressed file in binary mode.

    filename is a... TODO original docstring

    mode can be "r" for reading (default), "w" for (over)writing, or
    "a" for appending. These can equivalently be given as "rb", "wb",
    and "ab" respectively.

    format specifies the container format to use for the file.
    If mode is "r", this defaults to FORMAT_AUTO. Otherwise, the
    default is FORMAT_XZ.

    seek specifies whether to provide support for seeking in the file.
    This is only supported for xz files. This skips to the end of the file
    to read the index so if the file is on a slow medium (e.g. tape) you
    may wish to set this to False.

    check specifies the integrity check to use. This argument can
    only be used when opening a file for writing. For FORMAT_XZ,
    the default is CHECK_CRC64. FORMAT_ALONE and FORMAT_RAW do not
    support integrity checks - for these formats, check must be
    omitted, or be CHECK_NONE.

    close_fp specifies whether the LZMAFile "owns" the underlying stream
    and should close it when the LZMAFile is closed.

    When opening a file for reading, the *preset* argument is not
    meaningful, and should be omitted. The *filters* argument should
    also be omitted, except when format is FORMAT_RAW (in which case
    it is required).

    When opening a file for writing, the settings used by the
    compressor can be specified either as a preset compression
    level (with the *preset* argument), or in detail as a custom
    filter chain (with the *filters* argument). For FORMAT_XZ and
    FORMAT_ALONE, the default is to use the PRESET_DEFAULT preset
    level. For FORMAT_RAW, the caller must always specify a filter
    chain; the raw compressor does not support preset compression
    levels. The *seek* argument is not meaningful, and should be
    omitted.

    preset (if provided) should be an integer in the range 0-9,
    optionally OR-ed with the constant PRESET_EXTREME.

    filters (if provided) should be a sequence of dicts. Each dict
    should have an entry for "id" indicating ID of the filter, plus
    additional entries for options to the filter.
    """
    if hasattr(filename, "read") or hasattr(filename, "write"):
        fp = filename
        close_fp = False
    else:
        if "b" not in mode:
            mode += "b"
        fp = io.open(filename, mode)
        close_fp = True

    if 'r' in mode and seek and fp.seekable():
        if format is None:
            format = FORMAT_AUTO
        if format == FORMAT_XZ or (format == FORMAT_AUTO and _detect_xz(fp)) and mode in ('r', 'rb'):
            if check != -1:
                raise ValueError("Cannot specify an integrity check "
                                 "when opening a file for reading")
            if preset is not None:
                raise ValueError("Cannot specify a preset compression "
                                 "level when opening a file for reading")
            return _SeekableXZFile(fp, close_fp=close_fp)

    return _LZMAFile(fp, mode=mode, format=format, check=check, close_fp=close_fp,
        preset=preset, filters=filters)

def _detect_xz(fp):
    fp.seek(0)
    return _peek(fp, 6) == b'\xfd7zXZ\x00'

def open(filename, mode="rb",
         format=None, check=-1, preset=None, filters=None,
         encoding=None, errors=None, newline=None, seek=True):
    """Open an LZMA-compressed file in binary or text mode.

    filename can be either an actual file name (given as a str or bytes object),
    in which case the named file is opened, or it can be an existing file object
    to read from or write to.

    The mode argument can be "r", "rb" (default), "w", "wb", "a", or "ab" for
    binary mode, or "rt", "wt" or "at" for text mode.

    The format, check, preset and filters arguments specify the compression
    settings, as for LZMACompressor, LZMADecompressor and LZMAFile.

    For binary mode, this function is equivalent to the LZMAFile constructor:
    LZMAFile(filename, mode, ...). In this case, the encoding, errors and
    newline arguments must not be provided.

    For text mode, a LZMAFile object is created, and wrapped in an
    io.TextIOWrapper instance with the specified encoding, error handling
    behavior, and line ending(s).

    """
    if "t" in mode:
        if "b" in mode:
            raise ValueError("Invalid mode: %r" % (mode,))
    else:
        if encoding is not None:
            raise ValueError("Argument 'encoding' not supported in binary mode")
        if errors is not None:
            raise ValueError("Argument 'errors' not supported in binary mode")
        if newline is not None:
            raise ValueError("Argument 'newline' not supported in binary mode")

    lz_mode = mode.replace("t", "")
    binary_file = LZMAFile(filename, lz_mode, format=format, check=check,
                           preset=preset, filters=filters, seek=seek)

    if "t" in mode:
        return io.TextIOWrapper(binary_file, encoding, errors, newline)
    else:
        return binary_file


def compress(data, format=FORMAT_XZ, check=-1, preset=None, filters=None):
    """Compress a block of data.

    Refer to LZMACompressor's docstring for a description of the
    optional arguments *format*, *check*, *preset* and *filters*.

    For incremental compression, use an LZMACompressor object instead.
    """
    comp = LZMACompressor(format, check, preset, filters)
    return comp.compress(data) + comp.flush()


def decompress(data, format=FORMAT_AUTO, memlimit=None, filters=None):
    """Decompress a block of data.

    Refer to LZMADecompressor's docstring for a description of the
    optional arguments *format*, *check* and *filters*.

    For incremental decompression, use a LZMADecompressor object instead.
    """
    results = []
    while True:
        decomp = LZMADecompressor(format, memlimit, filters)
        results.append(decomp.decompress(data))
        if not decomp.eof:
            raise LZMAError("Compressed data ended before the "
                            "end-of-stream marker was reached")
        if not decomp.unused_data:
            return b"".join(results)
        # There is unused data left over. Proceed to next stream.
        data = decomp.unused_data
