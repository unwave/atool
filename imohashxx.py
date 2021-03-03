# imohash from https://pypi.org/project/imohash/ by kalafut using xxhash
# imohash does not want to install for Blender's python, murmur installation fails

from __future__ import division

import binascii
import glob
import os
import sys

import xxhash
# import varint
# from . import varint


SAMPLE_THRESHOLD = 256 * 1024
SAMPLE_SIZE = 32 * 1024

#Hashes an opened file object. Compatible with paramimo SFTPFile and regular files.
def hashfileobject(f, sample_threshhold=SAMPLE_THRESHOLD, sample_size=SAMPLE_SIZE, hexdigest=False):
    #get file size from file object
    f.seek(0, os.SEEK_END)
    size = f.tell()
    f.seek(0, os.SEEK_SET)

    if size < sample_threshhold or sample_size < 1:
        data = f.read()
    else:
        data = f.read(sample_size)
        f.seek(size//2)
        data += f.read(sample_size)
        f.seek(-sample_size, os.SEEK_END)
        data += f.read(sample_size)

    hash_tmp = xxhash.xxh3_128_digest(data)
    hash_ = hash_tmp[7::-1] + hash_tmp[16:7:-1]
    enc_size = encode(size)
    digest = enc_size + hash_[len(enc_size):]

    return binascii.hexlify(digest).decode() if hexdigest else digest

def hashfile(filename, sample_threshhold=SAMPLE_THRESHOLD, sample_size=SAMPLE_SIZE, hexdigest=False):
    with open(filename, 'rb') as f:
        return hashfileobject(f, sample_threshhold, sample_size, hexdigest)


def imosum():
    if len(sys.argv) == 1:
        print('imosum filenames')
        return

    files = set()

    for x in sys.argv[1:]:
        files.update(glob.glob(x))

    for fn in files:
        if not os.path.isdir(fn):
            print('{}  {}'.format(hashfile(fn, hexdigest=True), fn))


# varint from https://pypi.org/project/varint/ by fmoo
# varint takes very long to install from pip

"""Varint encoder/decoder

varints are a common encoding for variable length integer data, used in
libraries such as sqlite, protobuf, v8, and more.

Here's a quick and dirty module to help avoid reimplementing the same thing
over and over again.
"""

from io import BytesIO
# import sys

if sys.version > '3':
    def _byte(b):
        return bytes((b, ))
else:
    def _byte(b):
        return chr(b)

def encode(number):
    """Pack `number` into varint bytes"""
    buf = b''
    while True:
        towrite = number & 0x7f
        number >>= 7
        if number:
            buf += _byte(towrite | 0x80)
        else:
            buf += _byte(towrite)
            break
    return buf

def decode_stream(stream):
    """Read a varint from `stream`"""
    shift = 0
    result = 0
    while True:
        i = _read_one(stream)
        result |= (i & 0x7f) << shift
        shift += 7
        if not (i & 0x80):
            break

    return result

def decode_bytes(buf):
    """Read a varint from from `buf` bytes"""
    return decode_stream(BytesIO(buf))


def _read_one(stream):
    """Read a byte from the file (as an integer)

    raises EOFError if the stream ends while reading bytes.
    """
    c = stream.read(1)
    if c == '':
        raise EOFError("Unexpected EOF while reading bytes")
    return ord(c)