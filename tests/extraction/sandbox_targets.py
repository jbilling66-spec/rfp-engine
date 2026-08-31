"""Child-process targets for the sandbox containment tests (C2, B51).

Imported by the sandbox CHILD via dotted path, never by the test module
— each function plays a parser with a particular failure mode. Not a
test module; pytest never collects it.
"""

from __future__ import annotations

import os
import resource
import socket
import sys
import time
from pathlib import Path


def echo(payload: dict) -> dict:
    return {"echo": payload.get("x")}


def die_hard(_payload: dict) -> dict:
    os.abort()  # SIGABRT mid-parse: no exception, no cleanup, no result
    raise AssertionError("unreachable")


def sleep_forever(_payload: dict) -> dict:
    time.sleep(60)
    return {"woke": True}


def probe_network(_payload: dict) -> dict:
    try:
        socket.create_connection(("127.0.0.1", 9), timeout=1)
    except OSError as exc:
        return {"raised": exc.__class__.__name__, "message": str(exc)}
    return {"raised": None}


def probe_dns(_payload: dict) -> dict:
    try:
        socket.getaddrinfo("example.com", 443)
    except OSError as exc:
        return {"raised": exc.__class__.__name__}
    return {"raised": None}


def report_jail(_payload: dict) -> dict:
    return {
        "platform": sys.platform,
        "cwd": str(Path.cwd()),
        "rlimit_as": resource.getrlimit(resource.RLIMIT_AS)[0],
        "hf_hub_offline": os.environ.get("HF_HUB_OFFLINE"),
    }


def write_relative(_payload: dict) -> dict:
    Path("parse-output.txt").write_text("cwd-relative write lands in the jail")
    return {"wrote": "parse-output.txt"}
