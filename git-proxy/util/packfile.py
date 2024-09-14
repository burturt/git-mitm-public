import zlib
from enum import Enum
from functools import lru_cache, wraps
import struct
from logging import debug, info

if __name__ == "__main__":  # allows running the file directly for testing
    import objects
else:
    from . import objects, db


class OBJ_TYPE(Enum):
    OBJ_UNDEF = 0
    OBJ_COMMIT = 1
    OBJ_TREE = 2
    OBJ_BLOB = 3
    OBJ_TAG = 4
    OBJ_OFS_DELTA = 6
    OBJ_REF_DELTA = 7


OBJ_TYPE.TYPE_DELTA = frozenset((OBJ_TYPE.OBJ_OFS_DELTA, OBJ_TYPE.OBJ_REF_DELTA))


def decode_size_type_encoding(packfile: bytes, idx=0) -> tuple[int, OBJ_TYPE, int]:
    """
    Given input of bytes, uses the packfile variable length size spec and reads the file,
    returning the extracted number

    :param idx: Value to add to bytes used to make number to convert to absolute file byte index

    :returns: tuple(extracted number, object type, bytes used to make number)

    """

    # Note to self: var length numbers are LITTLE ENDIAN

    # Since the first byte bits 5-7 contains the type, we need to "pop" these bits out of the number

    raw_num, new_idx = decode_size_encoding(packfile, idx=idx)

    type_num = OBJ_TYPE((raw_num & 0b0111_0000) >> 4)

    actual_num = ((raw_num >> 7) << 4) + (raw_num & 0b0000_1111)

    return actual_num, type_num, new_idx


def decode_size_encoding(packfile: bytes, idx=0) -> tuple[int, int]:
    """
    Given input of bytes, returns the variable length result as an int

    :param idx: Value to add to bytes used to make number to convert to absolute file byte index

    :returns: tuple(extracted number, bytes used to make number)
    """

    # Format:
    # For each byte:
    # Check if MSb is 0: if so, this is last byte to read
    # Is this first byte? if so, upper 3 bits ignoring MSb is type and should be ignored/saved separately
    # append remaining bits to beginning of number (little endian)
    num = 0
    num_bytes = 0

    while True:
        b = packfile[num_bytes + idx]
        num += (b & 0b0111_1111) << (7 * num_bytes)
        num_bytes += 1
        if not b & 0b1000_0000:
            break
    return num, num_bytes + idx


def get_offset_val(packfile: bytes, idx=0) -> tuple[int, int]:
    """
    Given input of bytes, returns the offset value as an int

    :param idx: Value to add to bytes used to make number to convert to absolute file byte index

    :returns: tuple(extracted number, bytes used to make number)
    """

    # Note to self: offsets are BIG ENDIAN

    # Basically the same as a normal variable length val without type encoding
    # Except add 2^7 + 2^14 + ... + 2^(7*(n-1)) for all n >= 2
    num = 0
    num_bytes = 0

    while True:
        b = packfile[num_bytes + idx]
        num = num << 7
        num += b & 0b0111_1111
        num_bytes += 1
        if not b & 0b1000_0000:
            break
        num += 1  # adds the 2^7 of the *next* loop iteration

    return num, num_bytes + idx


def smart_decompress(pf: bytes, idx=0, max_length=250) -> tuple[bytes, int]:
    """
    Provided some bytes, extracts the bytes using zlib,
    returns the extracted object

    :returns: tuple(object, length of consumed bytes)

    """
    debug("Idx %d Length %d", idx, len(pf))
    d = zlib.decompressobj()
    res = b""
    while not d.eof:
        res += d.decompress(pf[idx : idx + max_length])
        idx += max_length

    idx = min(idx, len(pf))
    debug("Finished decompressing")
    debug(idx)
    debug(len(d.unused_data))
    # if max_length is None:
    #     res = d.decompress(cut)
    # else:
    #     res = b""
    #     debug("decompressing partial bytes")
    #     res += d.decompress(pf[idx:])

    #     debug("EOF")
    if not d.eof:
        raise ValueError("Incomplete decompression object given")

    # print(res)

    # idx is roughly where the next idx should be, but overshot by d.unused_data bytes
    return res, idx - len(d.unused_data)


def read_delta(delta: bytes, base_content: bytes) -> bytes:
    """
    Reads in delta data and returns reconstructed object.

    :param param1: Delta object, decompressed
    :param param2: Object to copy from, decompressed

    :returns: new object
    """

    base_object_size, bytes_used = decode_size_encoding(delta)
    reconstructed_object_size, bytes_used = decode_size_encoding(delta, idx=bytes_used)
    new_object = b""
    debug(f"Base size: {reconstructed_object_size}, delta: {delta}")

    while len(new_object) < reconstructed_object_size:
        bitmap = delta[bytes_used]
        if bitmap & 0b1000_0000:
            # copy from base instruction

            offset = 0
            size = 0

            for i in range(0, 4):
                if bitmap & (0b1 << i):
                    bytes_used += 1
                    offset += delta[bytes_used] << (i * 8)
            for i in range(4, 7):
                if bitmap & (0b1 << i):
                    bytes_used += 1
                    size += delta[bytes_used] << ((i - 4) * 8)

            if size == 0:
                size = 0x10000

            new_object += base_content[offset : offset + size]
            bytes_used += 1
        else:
            assert bitmap != 0
            size = bitmap & 0b0111_1111
            new_object += delta[bytes_used + 1 : bytes_used + 1 + size]
            bytes_used += size + 1

    return new_object


# Caching to allow for efficient delta entry extraction
@lru_cache(maxsize=500_000)
def extract_entry(pf: bytes, idx=0) -> tuple[bytes, OBJ_TYPE, int]:
    """
    Extracts an entry in a packfile given the byte index

    :returns: tuple(decompressed object, type, index of next entry)
    """
    l, type_num, new_idx = decode_size_type_encoding(pf, idx=idx)
    if type_num not in OBJ_TYPE.TYPE_DELTA:
        ex_obj, idx = smart_decompress(pf, idx=new_idx)
        # print(ex_obj)
        # print(contents[:200])
        # print(l)
        # print(type_num)
        assert len(ex_obj) == l
    else:
        if type_num == OBJ_TYPE.OBJ_REF_DELTA.value:
            raise NotImplementedError("Ref deltas are not yet implemented")
        debug(f"Extracting delta size {l}")
        # print(pf[idx:idx+100])
        ex_obj, type_num, idx = extract_delta_ofs(pf, idx=new_idx, base_idx=idx)
        # print(contents[:200])
        # print(l)
        # print(type_num)
    return ex_obj, OBJ_TYPE(type_num), idx


def extract_object(pf: bytes, idx=0) -> tuple[bytes, OBJ_TYPE, int]:
    """
    Extracts an entry in a packfile and reforms object to disk format, including header

    :returns: tuple(decompressed object with header, type, index of next entry)
    """

    ex_obj, obj_type, idx = extract_entry(pf, idx=idx)

    len_data = len(ex_obj)

    match obj_type:
        case OBJ_TYPE.OBJ_BLOB:
            complete_obj = f"blob {len_data}".encode() + b"\0" + ex_obj
        case OBJ_TYPE.OBJ_COMMIT:
            complete_obj = f"commit {len_data}".encode() + b"\0" + ex_obj
        case OBJ_TYPE.OBJ_TREE:
            complete_obj = f"tree {len_data}".encode() + b"\0" + ex_obj
        case OBJ_TYPE.OBJ_TAG:
            complete_obj = f"tag {len_data}".encode() + b"\0" + ex_obj
        case _:
            raise ValueError(f"Found object type {obj_type} unexpected")

    return complete_obj, obj_type, idx


def extract_delta_ofs(pf: bytes, idx=0, base_idx=0) -> tuple[bytes, OBJ_TYPE, bytes]:
    """
    Provided some bytes that represent an offset delta, extracts the bytes using zlib,
    returns the extracted object and new idx after consuming data
    """
    offset, new_idx = get_offset_val(pf, idx=idx)
    # print("Offset:", offset)
    # print("Base:", base_idx)
    base_object, obj_type, _ = extract_entry(pf, idx=base_idx - offset)
    delta_obj, used_bytes = smart_decompress(pf, idx=new_idx)
    reconstructed_object = read_delta(delta_obj, base_object)
    # print("Object:", reconstructed_object)

    return reconstructed_object, obj_type, used_bytes


class Packfile:

    objs: list[objects.GitObject]

    def __init__(self, objs: list[objects.GitObject] = []):
        self.objs = objs

    def gen_packfile(self):
        pf = b"PACK\0\0\0\2" + struct.pack(
            ">I", len(self.objs)
        )  # file signature, version 2, 4 byte file count
        for obj in self.objs:
            match type(obj):
                case objects.CommitObject:
                    obj_type = OBJ_TYPE.OBJ_COMMIT
                case objects.BlobObject:
                    obj_type = OBJ_TYPE.OBJ_BLOB
                case objects.TagObject:
                    obj_type = OBJ_TYPE.OBJ_TAG
                case objects.TreeObject:
                    obj_type = OBJ_TYPE.OBJ_TREE
                case _:
                    raise ValueError("Invalid object")

            stripped_object = obj.raw_contents_new().split(b"\0", 1)[1]
            pf += self.create_var_length(len(stripped_object), obj_type.value)
            pf += zlib.compress(stripped_object)

        pf += bytes.fromhex(objects.get_hash(pf))

        return pf

    @staticmethod
    def create_var_length(val: int, obj_type: int) -> bytes:
        """Creates a variable length size encoding bytes from the input val"""

        assert obj_type > 0
        assert obj_type.bit_length() <= 3

        res = bytearray()
        res += ((obj_type << 4) | (val & 0b0000_1111)).to_bytes(
            1
        )  # form first byte: 1tttnnnn t = type n = part of num
        val >>= 4
        while val != 0:  # continue adding groups of 7 bits
            res[-1] = res[-1] | 0b1000_0000
            res = res + (val & 0b0111_1111).to_bytes(1)
            val >>= 7

        return bytes(res)


async def read_packfile(contents: bytes, database=None, parse=True):
    idx = 0

    assert contents[0:4] == b"PACK"
    assert contents[4:8] == b"\0\0\0\x02"
    num_obj = int.from_bytes(contents[8:12], byteorder="big")
    idx += 12

    new_packfile = Packfile()

    info("Number of objects to extract: %d", num_obj)

    for i in range(num_obj):

        raw_obj, obj_type, idx = extract_object(contents, idx=idx)

        debug("%d: %s", i, obj_type)
        if parse:
            git_obj = objects.parse_object(raw_obj, compressed=False)

            debug(git_obj)
            new_packfile.objs.append(git_obj)

        if database is not None:
            debug(f"Inserting {objects.get_hash(raw_obj)} into db")
            await db.insert_raw(
                objects.get_hash(raw_obj), zlib.compress(raw_obj), database
            )

        # print("Current idx:", idx)
        # print(contents[idx:idx+4])
        # print()
        if i % 100 == 0:
            info(f"Object {i}/{num_obj} extracted")

    print("Remains:", contents[idx:])

    print("Hash:", objects.get_hash(contents[:idx]))

    return new_packfile if parse else None


async def test_main():
    import logging

    logging.basicConfig(level=logging.DEBUG)

    with open("packfile-only.ex", "rb") as f:

        contents = f.read()
        new_packfile = await read_packfile(contents)

        # print(new_packfile.gen_packfile())

        await read_packfile(new_packfile.gen_packfile())


if __name__ == "__main__":
    import asyncio

    asyncio.run(test_main())
