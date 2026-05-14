# zlib_io.py
import zlib

ZLIB_HEADER = b'\x78'  # first byte of any zlib stream

def decompress(data):
    for i in range(min(0x100, len(data))):
        if data[i] == 0x78:  # possible zlib header
            candidate = data[i:]
            try:
                d = zlib.decompressobj(wbits=15)
                result = d.decompress(candidate)
                result += d.flush()
                trailing = d.unused_data

                prefix = data[:i]
                stream_start = i
                stream_end   = len(data) - len(trailing)

                print(f"  compressed stream start : 0x{stream_start:04X}")
                print(f"  compressed stream end   : 0x{stream_end:04X}  ({stream_end - stream_start} bytes)")
                print(f"  trailing bytes          : {len(trailing)}")

                return result, prefix, trailing, stream_start

            except zlib.error:
                pass

    raise ValueError("No valid zlib stream found in data")


def compress(data, mode='zlib', level=9, strategy=zlib.Z_FIXED, memlevel=8):

    wbits = 15 if mode == 'zlib' else -15

    c = zlib.compressobj(
        level=level,
        method=zlib.DEFLATED,
        wbits=wbits,
        memLevel=memlevel,
        strategy=strategy,
    )
    return c.compress(data) + c.flush(zlib.Z_FINISH)


