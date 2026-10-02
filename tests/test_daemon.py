"""Päästä päähän -testit: oikea daemon (Unix-socket) + väärä Ollama-palvelin."""
import json
import os
import socket
import stat
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import cli
import config
import core
import daemon


# ── Feikki-Ollama ────────────────────────────────────────────

class FakeOllama:
    def __init__(self):
        self.script, self.requests = [], []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def do_GET(self):
                if self.path == "/api/version":
                    data = json.dumps({"version": "test"}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return

                self.send_response(404)
                self.end_headers()

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                msg = outer.script.pop(0) if outer.script else {
                    "role": "assistant",
                    "content": "(script ended)"
                }
                self.send_response(200)
                if body.get("stream"):
                    self.send_header("Content-Type", "application/x-ndjson")
                    self.end_headers()
                    if msg.get("tool_calls"):
                        lines = [{"message": msg, "done": True}]
                    else:
                        text = msg.get("content", "")
                        h = max(1, len(text) // 2)
                        lines = [
                            {"message": {"content": text[:h]}, "done": False},
                            {"message": {"content": text[h:]}, "done": False},
                            {"message": {"content": ""}, "done": True},
                        ]
                    for l in lines:
                        self.wfile.write((json.dumps(l) + "\n").encode())
                else:
                    data = json.dumps({"message": msg, "done": True}).encode()
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(
            target=self.httpd.serve_forever,
            daemon=True
        ).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"

    def text(self, t):
        self.script.append({"role": "assistant", "content": t})

    def call(self, name, **args):
        self.script.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "function": {
                    "name": name,
                    "arguments": args
                }
            }]
        })


@pytest.fixture
def ollama(monkeypatch):
    f = FakeOllama()
    monkeypatch.setattr(config, "OLLAMA_URLS", [f.url])
    core._invalidate_url_cache()
    yield f
    f.httpd.shutdown()


@pytest.fixture
def sock_path():
    d = tempfile.mkdtemp(prefix="ask")          # lyhyt polku (AF_UNIX-raja ~108)
    path = os.path.join(d, "s.sock")
    server = daemon.make_server(path)
    threading.Thread(
        target=server.serve_forever,
        daemon=True
    ).start()
    yield path
    server.shutdown()
    server.server_close()


def converse(path, prompt, approve=None, timeout=10):
    """Käy striimauskeskustelun läpi. Palauttaa tapahtumalistan."""
    events = []
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(timeout)
        s.connect(path)
        s.sendall(
            json.dumps({
                "action": "ask",
                "prompt": prompt,
                "stream": True
            }).encode() + b"\n"
        )
        buf = b""
        while True:
            data = s.recv(4096)
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                ev = json.loads(line)
                events.append(ev)
                if ev.get("type") == "confirm":
                    s.sendall(
                        json.dumps({
                            "action": "confirm",
                            "approved": approve
                        }).encode() + b"\n"
                    )
                if ev.get("type") in ("done", "error"):
                    return events
    return events


def raw_request(path, obj):
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(10)
        s.connect(path)
        s.sendall(
            (json.dumps(obj) if isinstance(obj, dict) else obj).encode() + b"\n"
        )
        return s.recv(65536)


def tool_msgs(request):
    return [
        m["content"]
        for m in request["messages"]
        if m.get("role") == "tool"
    ]


# ── Keskustelu ───────────────────────────────────────────────

def test_plain_answer_streams(ollama, sock_path):
    ollama.text("Hello there")
    ev = converse(sock_path, "say hi")
    assert ev[-1] == {"type": "done", "response": "Hello there"}
    assert "".join(
        e["content"] for e in ev if e["type"] == "chunk"
    ) == "Hello there"


def test_readonly_tool_roundtrip_wrapped(ollama, sock_path):
    ollama.call("check_uptime")
    ollama.text("Up.")
    ev = converse(sock_path, "how long has this machine been up")
    assert ev[-1]["type"] == "done"
    assert any(e["type"] == "status" for e in ev)
    msgs = tool_msgs(ollama.requests[1])
    assert "TYÖKALUN 'check_uptime'" in msgs[0] and "pelkkää dataa" in msgs[0]


def test_write_tool_approved_continues_conversation(
    ollama, sock_path, tmp_path
):
    target = tmp_path / "made.txt"
    ollama.call("create_file", path=str(target))
    ollama.text("Created.")
    ev = converse(
        sock_path,
        "make a file please",
        approve=True
    )
    confirm = next(e for e in ev if e["type"] == "confirm")
    assert confirm["tool"] == "create_file"
    assert confirm["args"] == {"path": str(target)}
    assert target.exists()
    assert ev[-1] == {
        "type": "done",
        "response": "Created."
    }   # keskustelu jatkui


def test_write_tool_rejected(ollama, sock_path, tmp_path):
    target = tmp_path / "nope.txt"
    ollama.call("create_file", path=str(target))
    ollama.text("Okay, not created.")
    ev = converse(
        sock_path,
        "make a file please",
        approve=False
    )
    assert not target.exists()
    assert ev[-1]["type"] == "done"
    assert "vaatii käyttäjän vahvistuksen" in tool_msgs(
        ollama.requests[1]
    )[0]


def test_explain_blocks_tools_even_if_model_calls_one(ollama, sock_path):
    ollama.script.append({
        "role": "assistant",
        "content": '{"name": "check_disk", "arguments": {}}'
    })
    ollama.text("df shows disk space.")
    ev = converse(sock_path, "explain what df does")
    assert ollama.requests[0]["tools"] == []                        # ei schemoissa
    assert "[estetty]" in tool_msgs(ollama.requests[1])[0]          # eikä suoritettu
    assert ev[-1] == {
        "type": "done",
        "response": "df shows disk space."
    }


def test_unknown_tool_is_reported_not_crashing(ollama, sock_path):
    ollama.call("rm_everything")
    ollama.text("Sorry.")
    ev = converse(sock_path, "do something")
    assert "tuntematon työkalu" in tool_msgs(ollama.requests[1])[0]
    assert ev[-1]["type"] == "done"


def test_too_many_iterations(ollama, sock_path):
    for _ in range(config.MAX_ITERATIONS + 2):
        ollama.call("check_uptime")
    ev = converse(sock_path, "loop forever")
    assert ev[-1]["type"] == "error"


# ── Muut toiminnot ───────────────────────────────────────────

def test_run_tool_never_runs_write_tools(sock_path, tmp_path):
    target = tmp_path / "x.txt"
    r = json.loads(raw_request(
        sock_path,
        {
            "action": "run_tool",
            "name": "create_file",
            "args": {"path": str(target)},
            "confirmed": True
        }
    ))
    assert (
        "vaatii käyttäjän vahvistuksen" in r["result"]
        and not target.exists()
    )

    r = json.loads(raw_request(
        sock_path,
        {
            "action": "run_tool",
            "name": "check_uptime"
        }
    ))
    assert r["ok"] and r["readonly"] and r["result"]


def test_blocking_ask_denies_write_tools(ollama, sock_path, tmp_path):
    target = tmp_path / "b.txt"
    ollama.script.append({
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "function": {
                "name": "create_file",
                "arguments": {"path": str(target)}
            }
        }]
    })
    ollama.text("done")
    r = json.loads(raw_request(
        sock_path,
        {
            "action": "ask",
            "prompt": "make a file"
        }
    ))
    assert r == {"ok": True, "response": "done"}
    assert not target.exists()


def test_bad_requests(sock_path):
    assert json.loads(
        raw_request(sock_path, "not json")
    )["ok"] is False

    assert json.loads(
        raw_request(sock_path, "[1,2]")
    )["ok"] is False

    assert json.loads(
        raw_request(
            sock_path,
            {"action": "ask", "prompt": 5}
        )
    )["ok"] is False

    r = json.loads(
        raw_request(
            sock_path,
            {
                "action": "ask",
                "prompt": "",
                "stream": True
            }
        )
    )
    assert r["type"] == "error"

    assert json.loads(
        raw_request(sock_path, {"action": "nope"})
    )["ok"] is False


def test_oversized_request(sock_path, monkeypatch):
    monkeypatch.setattr(daemon, "MAX_REQUEST_BYTES", 100)
    r = json.loads(
        raw_request(sock_path, "x" * 150)
    )
    assert r["error"] == "request too large"


def test_list_tools_only_available(sock_path):
    r = json.loads(
        raw_request(
            sock_path,
            {"action": "list_tools"}
        )
    )
    assert {"check_disk", "read_file"} <= {
        t["name"] for t in r["tools"]
    }


@pytest.mark.skipif(os.getuid() == 0, reason="root sallitaan")
def test_foreign_uid_rejected(sock_path, monkeypatch):
    monkeypatch.setattr(daemon.os, "getuid", lambda: 54321)
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(5)
        s.connect(sock_path)
        s.sendall(b'{"action": "list_tools"}\n')
        try:
            data = s.recv(4096)
        except ConnectionResetError:
            data = b""
        assert data == b""


# ── Palvelimen käynnistys ────────────────────────────────────

def test_socket_permissions_and_conflicts():
    d = tempfile.mkdtemp(prefix="ask")
    path = os.path.join(d, "s.sock")
    server = daemon.make_server(path)
    try:
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        threading.Thread(
            target=server.serve_forever,
            daemon=True
        ).start()

        with pytest.raises(RuntimeError, match="already running"):
            daemon.make_server(path)
    finally:
        server.shutdown()
        server.server_close()

    stale = os.path.join(d, "regular")
    open(stale, "w").close()
    with pytest.raises(RuntimeError, match="not a socket"):
        daemon.make_server(stale)


# ── CLI ──────────────────────────────────────────────────────

def test_cli_stream_with_confirmation(
    ollama, sock_path, tmp_path, monkeypatch, capsys
):
    target = tmp_path / "cli.txt"
    ollama.call("create_file", path=str(target))
    ollama.text("All done.")
    monkeypatch.setattr(cli, "SOCKET_PATH", sock_path)
    monkeypatch.setattr(
        "builtins.input",
        lambda _="": "y"
    )
    result = cli.ask_stream("make a file please")
    out = capsys.readouterr().out
    assert target.exists()
    assert result == "All done."
    assert "All done." in out


def test_cli_rejection_continues(
    ollama, sock_path, tmp_path, monkeypatch, capsys
):
    target = tmp_path / "cli2.txt"
    ollama.call("create_file", path=str(target))
    ollama.text("Skipped.")
    monkeypatch.setattr(cli, "SOCKET_PATH", sock_path)
    monkeypatch.setattr(
        "builtins.input",
        lambda _="": "n"
    )
    assert cli.ask_stream("make a file please") == "Skipped."
    assert not target.exists()


def test_cli_blocking_mode_buffers(ollama, sock_path, monkeypatch):
    ollama.text("Whole answer")
    monkeypatch.setattr(cli, "SOCKET_PATH", sock_path)
    assert cli.ask_blocking("hi") == "Whole answer"


def test_cli_daemon_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cli,
        "SOCKET_PATH",
        str(tmp_path / "none.sock")
    )
    with pytest.raises(cli.DaemonUnavailable):
        cli.ask_stream("hi")


def test_cli_strips_terminal_escapes():
    assert cli._clean("\x1b[31mred\x1b[0m ok") == "red ok"
    assert cli._clean("\x1b]0;evil title\x07b") == "b"
    assert cli._clean("x\rY\x00z\tT\nN") == "xYz\tT\nN"
    assert "\x1b" not in cli._clean("half\x1b")
