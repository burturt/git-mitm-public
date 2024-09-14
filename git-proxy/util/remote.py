from . import objects
from .db import insert_raw
import requests
from logging import debug, error
from functools import lru_cache


async def dumb_fetch_object(
    hash: bytes, base_url: str, db=None, headers=None
) -> objects.GitObject:
    debug(f"Fetching {base_url}/objects/{hash[0:2].decode()}/{hash[2:].decode()}")
    res = requests.get(
        f"{base_url}/objects/{hash[0:2].decode()}/{hash[2:].decode()}", headers=headers
    ).content
    if db is not None:
        debug("Attempting to insert into database")
        await insert_raw(hash.decode(), res, db)
    return objects.parse_object(res)


class SmartPacket:
    def __init__(self, lines=[]) -> None:
        self.lines = lines

    def add_line(self, line: bytes):
        assert type(line) is bytes
        assert len(line) < 0x10000 - 4
        self.lines.append(line)

    def generate_payload(self):
        out = b""
        for line in self.lines:
            out += f"{len(line):0>4x}".encode()
            out += line
            out += b"0000"

    def __repr__(self):
        return f"<SmartPacket line_conut={len(self.lines)}>"

    def extract_lines(self, line_type=0x01) -> bytes:
        # packfiles are all lines that start with the byte 0x01
        pf = bytearray()
        for line in self.lines:
            if line[0] == line_type:
                pf.extend(line[1:])
        return bytes(pf)

    @classmethod
    @lru_cache(maxsize=None)
    def parse_packet(cls, packet: bytes):
        debug("Parsing packet")
        curr_idx = 0
        new_packet = []
        while curr_idx < len(packet):
            line_len = int(packet[curr_idx : curr_idx + 4], 16)
            # debug(line_len)
            if line_len <= 3:
                curr_idx += 4
                continue
            new_packet.append(packet[4 + curr_idx : line_len + curr_idx])
            curr_idx += line_len
        return cls(lines=new_packet)
