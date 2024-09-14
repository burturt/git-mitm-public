import zlib
import argparse

parser = argparse.ArgumentParser("View raw object contents")
parser.add_argument("objectid", help="Object ID")
args = parser.parse_args()


def read_object(hash: str) -> bytes:
    with open(f".git/objects/{hash[0:2]}/{hash[2:]}", "rb") as f:
        return zlib.decompress(f.read())


for line in read_object(args.objectid).split(b"\n"):
    print(line)
