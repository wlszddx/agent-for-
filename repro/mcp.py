import json
import sys

from repro import __version__
from repro.session import EvidenceLog
from repro.tools import TOOL_SPECS, dispatch


def serve(job):
    log = EvidenceLog(job)
    while True:
        message = _read()
        if message is None:
            return
        if message.get("id") is None:
            continue
        response = _handle(job, message, log)
        _write(response)


def _handle(job, message, log):
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        return _ok(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "repro", "version": __version__},
            },
        )
    if method == "tools/list":
        tools = []
        for spec in TOOL_SPECS:
            function = spec["function"]
            tools.append(
                {
                    "name": function["name"],
                    "description": function["description"],
                    "inputSchema": function["parameters"],
                }
            )
        return _ok(request_id, {"tools": tools})
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        result = dispatch(job, name, arguments)
        try:
            log.record(name, arguments, result)
        except OSError:
            pass
        return _ok(
            request_id,
            {
                "content": [
                    {"type": "text", "text": json.dumps(result, ensure_ascii=False)}
                ],
                "isError": False,
            },
        )
    return _error(request_id, -32601, f"unknown method {method}")


def _ok(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code, text):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": text},
    }


_framing = "jsonl"


def _read():
    global _framing
    while True:
        line = sys.stdin.buffer.readline()
        if line == b"":
            return None
        if line in (b"\r\n", b"\n"):
            continue
        if line.lstrip().startswith(b"{"):
            _framing = "jsonl"
            return json.loads(line.decode("utf-8"))
        _framing = "headers"
        headers = {_header(line)}
        while True:
            header = sys.stdin.buffer.readline()
            if header == b"":
                return None
            if header in (b"\r\n", b"\n"):
                break
            headers.add(_header(header))
        length = int(dict(headers)["content-length"])
        body = sys.stdin.buffer.read(length)
        return json.loads(body.decode("utf-8"))


def _header(line):
    key, value = line.decode("ascii").split(":", 1)
    return key.strip().lower(), value.strip()


def _write(message):
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if _framing == "headers":
        sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
        sys.stdout.buffer.write(body)
    else:
        sys.stdout.buffer.write(body)
        sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()
