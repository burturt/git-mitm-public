from logging import debug


class Refs:
    def __init__(self, refs: dict = {}, HEAD: bytes = None):
        self.refs = refs
        self.HEAD = HEAD

    def __repr__(self):
        return f"<Refs {self.refs}>"

    def export_dumb(self):
        res = b""
        for ref, hash in self.refs.items():
            if ref == b"HEAD":
                continue
            res += hash + b"\t" + ref + b"\n"
        return res

    def export_smart_request(self) -> bytes:

        # payload = "0011command=fetch0014agent=git/2.46.00016object-format=sha10001000dthin-pack000dofs-delta0032want 7b4f66bd8f17d10b399aa55f34ef734a6ce3d992\n0032want 7b4f66bd8f17d10b399aa55f34ef734a6ce3d992\n0009done\n0000"

        res = b"0011command=fetch0014agent=git/2.46.00016object-format=sha10001000dofs-delta"
        # add HEAD as command
        res += b"0032want " + self.refs[b"HEAD"] + b"\n"

        for ref in set(self.refs.values()):
            res += b"0032want " + ref + b"\n"

        res += b"0009done\n0000"
        return res

    @classmethod
    def from_dumb_bytes(cls, init: bytes):
        refs = {}
        for refline in init.split(b"\n"):
            if b"\t" in refline:
                hash, ref = refline.split(b"\t", 1)
                refs[ref] = hash

        return cls(refs)

    @classmethod
    def from_smart_bytes(cls, init_content: list[bytes]):
        refs = {}
        head = None
        for line in init_content:
            debug(line)

            if line == b"packfile\n":
                raise ValueError("Packfile found in refs?")
            s = line.split(b" ")
            refs[s[1].strip()] = s[0]
            if s[1].strip() == b"HEAD":
                assert s[2].startswith(b"symref-target:")
                head = s[2][14:].strip()
        return cls(refs, HEAD=head)
