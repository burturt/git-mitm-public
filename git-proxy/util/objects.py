import zlib
import hashlib
import abc


class GitObject(abc.ABC):
    # Subclasses of GitObject should contain exactly 2 positional arguments: contents and hash
    # And may consist of as many kargs as needed
    def __init__(self, contents: bytes, hash: str | None):
        self.contents = contents
        if hash is not None:
            assert self.calc_hash_orig() == hash

        self.hash = self.calc_hash_orig()

    def __repr__(self) -> str:
        return f"<Git Obj {self.calc_hash_new()[0:6]}>"

    # Get raw orig contents, including header. Should NOT need to be redefined in subclasses
    def raw_contents_orig(self) -> bytes:
        """Get raw orig contents, including header."""
        return (
            self.raw_type
            + b" "
            + str(len(self.contents)).encode()
            + b"\0"
            + self.contents
        )

    # Get raw new contents, including header. MUST be redefined in subclasses
    @abc.abstractmethod
    def raw_contents_new(self) -> bytes:
        """Get raw new contents, including header."""
        raise NotImplementedError()

    # Get original hash. Should NOT need to be redefined in subclasses
    def calc_hash_orig(self) -> str:
        """Get original hash"""
        if self.raw_type is None:
            raise NotImplementedError()
        return get_hash(self.raw_contents_orig())

    # Get new hash. Should NOT need to be redefined in subclasses
    def calc_hash_new(self) -> str:
        """Get new hash"""
        if self.raw_type is None:
            raise NotImplementedError()
        return get_hash(self.raw_contents_new())

    def export_object_new(self) -> bytes:
        """Export new object compressed"""
        return zlib.compress(self.raw_contents_new())

    def export_object_orig(self) -> bytes:
        """Export original object compressed"""
        return zlib.compress(self.raw_contents_orig())

    @classmethod
    def from_bytes(
        cls,
        contents: bytes,
        hash: str | None = None,
        compressed: bool = False,
        type_assert: bytes | None = None,
        **kwargs,
    ):
        if compressed:
            contents = decompress_object(contents)
        assert b"\0" in contents
        # Moved to __init__
        # if hash is not None:
        #     assert get_hash(contents) == hash.lower()
        # else:
        #     hash = get_hash(contents)
        if type_assert is not None:
            assert contents.split(b"\0", 1)[0].split(b" ", 1)[0] == type_assert

        return cls(contents.split(b"\0", 1)[1], hash, **kwargs)


class BlobObject(GitObject):

    def __init__(self, contents: bytes, hash: str):
        self.raw_type = b"blob"
        super().__init__(contents, hash)

    @classmethod
    def from_bytes(self, contents: bytes, hash: str | None = None, compressed=False):
        return super().from_bytes(contents, hash, compressed, type_assert=b"blob")

    def __repr__(self) -> str:
        return f"<Blob Obj {self.calc_hash_new()[0:6]} len={len(self.contents)}>"

    # For blobs, there is no distinction between original and new, so the new and orig methods do the same thing

    def raw_contents_new(self) -> bytes:
        return self.raw_contents_orig()

    # def export_object_new(self) -> tuple[bytes, str]:
    #     return self.raw_contents_orig()

    # def export_object_orig(self) -> tuple[bytes, str]:
    #     ret_contents = f"blob {len(self.contents)}".encode() + b"\0" + self.contents
    #     assert get_hash(ret_contents) == self.hash
    #     return zlib.compress(ret_contents), get_hash(ret_contents)


class TreeObject(GitObject):

    @classmethod
    def from_bytes(self, contents: bytes, hash: str | None = None, compressed=False):

        entries = []

        orig_content = contents
        contents = contents.split(b"\0", 1)[1]

        # since the line split could in theory be in the hash, we must parse it manually
        while len(contents) > 0:
            try:

                mode, contents = contents.split(b" ", 1)
                file, contents = contents.split(b"\0", 1)
                file_hash = contents[:20].hex()
                contents = contents[20:]
                entries.append({"mode": mode, "file": file, "file_hash": file_hash})

            except:
                raise ValueError("Invalid Tree file")

        return super().from_bytes(
            orig_content,
            hash,
            compressed=compressed,
            type_assert=b"tree",
            entries=entries,
        )

    def __repr__(self) -> str:
        return f"<Tree Obj {self.calc_hash_new()[0:6]} {", ".join(f"(mode={i["mode"]} name={i["file"]} hash={i["file_hash"]})" for i in self.entries)}>"

    def raw_contents_new(self) -> bytes:

        export = b""
        for row in self.entries:
            export += (
                row["mode"]
                + b" "
                + row["file"]
                + b"\0"
                + bytes.fromhex(row["file_hash"])
            )

        return b"tree " + str(len(export)).encode() + b"\0" + export

    # def export_object_orig(self) -> bytes:
    #     ret_contents = f"tree {len(self.contents)}".encode() + b"\0" + self.contents
    #     assert get_hash(ret_contents) == self.hash
    #     return zlib.compress(ret_contents), get_hash(ret_contents)

    # def export_object_new(self) -> tuple[bytes, str]:

    #     export = b""
    #     for row in self.entries:
    #         export += row["mode"] + b" " + row["file"] + b"\0" + bytes.fromhex(row["file_hash"])

    #     export = b"tree " + str(len(export)).encode() + b"\0" + export

    #    return zlib.compress(export), get_hash(export)

    def add_file(self, filename: bytes, hash: str, mode: bytes = b"100644"):
        self.entries.append({"mode": mode, "file": filename, "file_hash": hash})

    def get_file(self, filename: bytes):
        for file in self.entries:
            if file["file"] == filename:
                return file

    def del_file(self, filename: bytes):
        for file in self.entries:
            if file["file"] == filename:
                self.entries.remove(file)

    # entries is a list of dicts with 3 keys:
    # mode file file_hash
    # mode: tehnically anything, but stored as bytes
    # 100644 = normal, 100755 = executable, 120000 = symlink, 040000 = directory
    # file: name in file system
    # file_hash: self explanitory. Note that it is stored as a string, not bytes!
    # {"mode": b"100644", "file":  b"README", "file_hash": "a906cb2a4a904a152e80877d4088654daad0c859"}
    def __init__(self, contents: bytes, hash: str, entries: list[list]):
        self.raw_type = b"tree"
        self.entries = entries
        super().__init__(contents, hash)


class TagObject(GitObject):

    @classmethod
    def from_bytes(self, contents: bytes, hash: str | None = None, compressed=False):
        return super().__init__(contents, hash, compressed, type_assert=b"tag")

    def __repr__(self) -> str:
        return f"<Tag Obj {self.calc_hash_new()[0:6]}>"

    # For now, will not parse tag objects
    def __init__(self, contents: bytes, hash: str):
        self.raw_type = b"tag"
        super().__init__(contents, hash)

    def raw_contents_new(self) -> bytes:
        return f"tag {len(self.contents)}".encode() + b"\0" + self.contents

    # def export_object_orig(self) -> tuple[bytes, str]:
    #     ret_contents = f"tag {len(self.contents)}".encode() + b"\0" + self.contents
    #     assert get_hash(ret_contents) == self.hash
    #     return zlib.compress(ret_contents), get_hash(ret_contents)

    # def export_object_new(self) -> tuple[bytes, str]:
    #     ret_contents = f"tag {len(self.contents)}".encode() + b"\0" + self.contents
    #     assert get_hash(ret_contents) == self.hash
    #     return zlib.compress(ret_contents), get_hash(ret_contents)


class CommitObject(GitObject):

    def __init__(
        self,
        contents: bytes,
        hash: str,
        parents: list[bytes] = [],
        author: bytes = None,
        tree: bytes = None,
        committer: bytes = None,
        encoding: bytes = None,
        gpg_sig: bytes = None,
        message: bytes = b"",
    ):
        self.raw_type = b"commit"
        super().__init__(contents, hash)

        self.parents = parents
        self.author = author
        self.tree = tree
        self.committer = committer
        self.encoding = encoding
        self.gpg_sig = gpg_sig
        self.message = message

    @classmethod
    def from_bytes(cls, contents: bytes, hash: str | None = None, compressed=False):

        # Read header information
        # Only 5 standard headers: https://github.com/git/git/blob/master/commit.c#L1444
        # plus signing header

        orig_content = contents
        contents = contents.split(b"\0", 1)[1]

        parents = []
        author = None
        tree = None
        committer = None
        encoding = None
        gpg_sig = None

        for header in contents.split(b"\n"):
            if gpg_sig is not None and not gpg_sig.endswith(
                b"-----END PGP SIGNATURE-----"
            ):
                gpg_sig += header + b"\n"
                continue
            if header == b"":
                break
            elif header.startswith(b"tree"):
                if tree is not None:
                    raise ValueError("Error: multiple trees defined in commit")
                tree = header[5:]
            elif header.startswith(b"parent"):
                parents.append(header[7:])
            elif header.startswith(b"committer"):
                if committer is not None:
                    raise ValueError("Error: multiple committers defined in commit")
                committer = header[10:]
            elif header.startswith(b"author"):
                if author is not None:
                    raise ValueError("Error: multiple authors defined in commit")
                author = header[7:]
            elif header.startswith(b"encoding"):
                encoding = header[9:]
            elif header.startswith(b"gpgsig"):
                gpg_sig = header[7:] + b"\n"
            elif header.startswith(b"mergetag"):
                pass
            else:
                raise ValueError(f"Unknown header: {header}")

        message = contents.split(b"\n\n", 1)[1]

        return super().from_bytes(
            orig_content,
            hash,
            parents=parents,
            author=author,
            tree=tree,
            committer=committer,
            encoding=encoding,
            gpg_sig=gpg_sig,
            message=message,
        )

    def __repr__(self) -> str:
        return f"<Commit Obj {self.calc_hash_new()[0:6]} parents={self.parents} author={self.author} tree={self.tree} committer={self.committer} encoding={self.encoding} gpg_sig={self.gpg_sig} message={self.message}>"

    def raw_contents_new(self) -> bytes:
        export = b""
        if self.tree is not None:
            export += b"tree " + self.tree + b"\n"
        for parent in self.parents:
            export += b"parent " + parent + b"\n"
        if self.author is not None:
            export += b"author " + self.author + b"\n"
        if self.committer is not None:
            export += b"committer " + self.committer + b"\n"
        if self.encoding is not None:
            export += b"encoding " + self.encoding + b"\n"
        # No gpg header included because who needs that?
        export += b"\n"
        export += self.message

        export = b"commit " + str(len(export)).encode() + b"\0" + export

        return export

    # def export_object_orig(self) -> tuple[bytes, str]:
    #     ret_contents = f"commit {len(self.contents)}".encode() + b"\0" + self.contents
    #     assert get_hash(ret_contents) == self.hash
    #     return zlib.compress(ret_contents), get_hash(ret_contents)


# given an object's (compressed or extracted) contents, returns the appropriate instance of a GitObject
def parse_object(obj_contents, hash: str = None, compressed=True) -> GitObject:

    obj_type = None

    if compressed:
        obj_contents = decompress_object(obj_contents)

    match obj_contents.split(b" ", 1)[0]:
        case b"commit":
            obj_type = CommitObject
        case b"blob":
            obj_type = BlobObject
        case b"tree":
            obj_type = TreeObject
        case b"tag":
            obj_type = TagObject
        case _:
            raise ValueError("Invalid object")

    return obj_type.from_bytes(obj_contents, hash, compressed=False)


def decompress_object(object: bytes):
    return zlib.decompress(object)


def get_hash(object: bytes):
    sha1 = hashlib.sha1()
    sha1.update(object)
    return sha1.hexdigest().lower()
