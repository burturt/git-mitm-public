from .objects import GitObject, get_hash, parse_object
from logging import debug
import pickle


async def insert_raw(hash: str, content: bytes, db) -> None:
    debug(f"Inserting {hash} into database")
    await db.execute(
        "INSERT INTO objects (hash, blob) VALUES ($1, $2) ON CONFLICT (hash) DO NOTHING;",
        hash,
        content,
    )


async def insert_object(obj: GitObject, db) -> None:
    debug(f"Inserting object {obj.calc_hash_new()} into database")
    await db.execute(
        "INSERT INTO objects (hash, blob) VALUES ($1, $2) ON CONFLICT (hash) DO NOTHING;",
        obj.calc_hash_new(),
        obj.export_object_new(),
    )


async def set_ref(repo: str, ref: str, new: str, db) -> None:
    debug(f"Setting {repo}:{ref} to be set to {new}")
    await db.execute(
        "INSERT INTO refs (remote, old, new) VALUES ($1, $2, $3) ON CONFLICT (remote, old) DO UPDATE SET new = $3;",
        repo,
        ref,
        new,
    )


async def get_object(hash: str, db) -> GitObject:
    return parse_object(
        (await db.fetchrow("SELECT blob FROM objects WHERE hash = $1;", hash))["blob"]
    )


async def get_ref(repo: str, ref: str, db) -> str:
    return (
        await db.fetchrow(
            "SELECT new FROM refs WHERE remote = $1 AND old = $2;", repo, ref
        )
    )["new"]


async def set_completed(repo: str, refs: bytes, db) -> None:
    await db.execute(
        "INSERT INTO cache (remote, ref_blob) VALUES ($1, $2) ON CONFLICT (remote) DO NOTHING;",
        repo,
        refs,
    )


async def get_ref_object(repo: str, db) -> bytes | None:
    res = await db.fetchrow("SELECT ref_blob FROM cache WHERE remote = $1;", repo)
    return None if res is None else res["ref_blob"]
