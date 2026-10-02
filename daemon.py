"""Background service. Receives JSON requests through a Unix socket.

Supports two modes:
  - Blocking: one JSON response per request. Write tools are NOT executed
    in this mode (confirmation requires a streaming connection).
  - Streaming: multiple JSON lines per request
    * {"type": "chunk", "content": "..."}     - text chunk
    * {"type": "status", "message": "..."}    - status information (tool call)
    * {"type": "confirm", ...}                - confirmation request for a write tool
    * {"type": "done", "response": "..."}     - final response
    * {"type": "error", "message": "..."}     - error

Confirmation (streaming mode):
  The daemon sends a "confirm" event and WAITS on the same connection for:
  {"action": "confirm", "approved": true|false}.
  Only the exact call shown to the user is executed. The client cannot change
  arguments or bypass confirmation. The conversation continues after confirmation.

Explanation requests ("Explain ls /tmp", "What does X do?"):
  - All tools are blocked both from the model and during execution
  - Code blocks are removed during post-processing
  - Streaming is skipped; the complete response is buffered

Security:
  socket permissions are 0600 at creation time (umask), peer UID is checked
  (SO_PEERCRED), request size is limited, and connections are handled by
  threads so one blocked client does not prevent others.

Shutdown:
  - Ctrl+C shuts down the daemon
  - Ctrl+D sends EOF to stdin and shuts down the daemon cleanly
"""

import json
import os
import re
import socket
import socketserver
import stat
import struct
import sys
import threading

import appenv
import config
import core
import tools
from i18n import L


SOCKET_PATH = str(appenv.socket_path())
MAX_ITERATIONS = config.MAX_ITERATIONS

# Debug mode: set ASK_DEBUG=1
DEBUG = os.environ.get("ASK_DEBUG") == "1"

# Limits
MAX_REQUEST_BYTES = 1_000_000
CONFIRM_TIMEOUT = 120
_MAX_CONTEXT_CHARS = 4000
_MAX_MODEL_NAME = 100

# Streaming buffer: number of characters buffered before deciding whether
# the content is a tool call or normal text.
_TOOL_CALL_BUFFER_LIMIT = 30

# Prevent man tools when the prompt is a complete command line.
_FULL_CMD_EXCLUDE = {"man_page", "man_flag"}


def _log(msg: str):
    if DEBUG:
        print(f"[DEBUG] {msg}", file=sys.stderr, flush=True)


def _err(req, message: str) -> dict:
    """Return an error response in the format required by the request mode."""
    if isinstance(req, dict) and req.get("stream"):
        return {"type": "error", "message": message}
    return {"ok": False, "error": message}


def _strip_code_blocks(text: str) -> str:
    """Remove code blocks from explanation responses."""
    if not text:
        return text

    text = re.sub(r"`{3}[^\n]*\n.*?`{3}", "", text, flags=re.DOTALL)
    text = re.sub(r"`{3}[^\n]*`{3}", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _looks_like_tool_call_prefix(text: str) -> bool:
    """Return True when the text prefix may be a tool call."""
    stripped = text.lstrip()

    if not stripped:
        return True

    if stripped.startswith(("FunctionFlags", "<tool_call>", "{")):
        return True

    return len(stripped) < _TOOL_CALL_BUFFER_LIMIT


def _select_exclude_tools(prompt: str) -> set[str] | None:
    """Select the tools to exclude based on the prompt.

    - Explanation and how-to requests: block all tools.
    - Complete command line: block man_page and man_flag.
    - Other requests: do not exclude tools.
    """
    if core.is_explain_request(prompt) or core.is_howto_request(prompt):
        return set(tools.TOOLS.keys())

    if core.is_full_command_line(prompt):
        return set(_FULL_CMD_EXCLUDE)

    return None


def _allowed_uids() -> set[int]:
    extra = {
        int(uid)
        for uid in os.environ.get("ASK_ALLOWED_UIDS", "").split(",")
        if uid.strip().isdigit()
    }

    return {os.getuid(), 0} | extra


class Handler(socketserver.StreamRequestHandler):
    def setup(self):
        super().setup()
        self._alive = True

    # ─── Connection ──────────────────────────────────────────

    def _peer_ok(self) -> bool:
        """Allow only the same user and root connections."""
        try:
            creds = self.connection.getsockopt(
                socket.SOL_SOCKET,
                socket.SO_PEERCRED,
                struct.calcsize("3i"),
            )
            _pid, uid, _gid = struct.unpack("3i", creds)
        except (OSError, AttributeError):
            return False

        return uid in _allowed_uids()

    def _send_json(self, obj: dict):
        self.wfile.write((json.dumps(obj) + "\n").encode())
        self.wfile.flush()

    def handle(self):
        if not self._peer_ok():
            _log("peer UID not allowed -> connection closed")
            return

        while self._alive:
            line = self.rfile.readline(MAX_REQUEST_BYTES + 1)

            if not line:
                break

            if len(line) > MAX_REQUEST_BYTES:
                try:
                    self._send_json({
                        "ok": False,
                        "error": "request too large",
                    })
                except OSError:
                    pass

                break

            req = None

            try:
                req = json.loads(line.decode("utf-8"))

                if not isinstance(req, dict):
                    raise ValueError("request must be a JSON object")

                resp = self.dispatch(req)

            except (BrokenPipeError, ConnectionResetError):
                break

            except Exception as e:
                _log(f"error: {e}")
                resp = _err(req, str(e))

            if resp is not None:
                try:
                    self._send_json(resp)
                except (BrokenPipeError, ConnectionResetError):
                    break

    # ─── Request dispatch ────────────────────────────────────

    @staticmethod
    def _ask_params(req: dict):
        """Validate ask request fields."""
        prompt = req.get("prompt", "")

        if not isinstance(prompt, str) or not prompt.strip():
            return None

        context = req.get("context")

        if (
            not isinstance(context, str)
            or not context.strip()
            or len(context) > _MAX_CONTEXT_CHARS
        ):
            context = core.system_context()

        model = req.get("model")

        if (
            not isinstance(model, str)
            or not model.strip()
            or len(model) > _MAX_MODEL_NAME
        ):
            model = core.DEFAULT_MODEL

        return prompt, context, model

    def dispatch(self, req: dict) -> dict | None:
        action = req.get("action", "ask")
        _log(f"action={action}")

        if action == "ask":
            params = self._ask_params(req)

            if params is None:
                return _err(req, "prompt must be a non-empty string")

            if req.get("stream"):
                self.handle_ask_stream(*params)
                return None

            return self.handle_ask_blocking(*params)

        if action == "list_tools":
            return {
                "ok": True,
                "tools": [
                    {
                        "name": name,
                        "readonly": meta["readonly"],
                        "description": meta["description"],
                    }
                    for name, meta in tools.get_tools().items()
                ],
            }

        if action == "run_tool":
            name = req.get("name")

            call = {
                "function": {
                    "name": name,
                    "arguments": req.get("args", {}),
                }
            }

            # confirm=None: write tools are not executed through this route.
            # The previous "confirmed": true flag was client-controlled.
            result = core.execute_tool_call(call, confirm=None)

            meta = tools.TOOLS.get(name) if isinstance(name, str) else None

            return {
                "ok": True,
                "result": result,
                "readonly": bool(meta and meta["readonly"]),
            }

        return {
            "ok": False,
            "error": f"unknown action: {action}",
        }

    # ─── Tool calls ───────────────────────────────────────────

    def _confirm(self, name: str, args: dict) -> bool:
        """Request confirmation from the client on the same connection."""
        meta = tools.TOOLS.get(name, {})

        self._send_json({
            "type": "confirm",
            "tool": name,
            "readonly": False,
            "description": meta.get("description", ""),
            "args": args,
        })

        self.connection.settimeout(CONFIRM_TIMEOUT)

        try:
            line = self.rfile.readline(MAX_REQUEST_BYTES + 1)

        except (OSError, ValueError):
            self._alive = False
            return False

        finally:
            try:
                self.connection.settimeout(None)
            except OSError:
                pass

        if not line:
            self._alive = False
            return False

        try:
            reply = json.loads(line.decode("utf-8"))
        except ValueError:
            return False

        return (
            isinstance(reply, dict)
            and reply.get("action") == "confirm"
            and reply.get("approved") is True
        )

    def _run_tool_calls(
        self,
        calls: list,
        messages: list,
        exclude_tools,
        interactive: bool,
    ) -> None:
        """Execute model tool calls through execute_tool_call."""
        for call in calls:
            if not self._alive:
                return

            fn = call.get("function", {}) if isinstance(call, dict) else {}
            name = str(fn.get("name", "?"))

            _log(f"  -> {name}({fn.get('arguments')})")

            if interactive:
                self._send_json({
                    "type": "status",
                    "message": L("Calling tool: {}").format(name),
                })

            output = core.execute_tool_call(
                call,
                exclude_tools,
                confirm=self._confirm if interactive else None,
            )

            _log(f"  <- {output[:300]!r}")

            messages.append(core.tool_message(name, output))

    # ─── Blocking path ────────────────────────────────────────

    def handle_ask_blocking(
        self,
        prompt: str,
        context: str,
        model: str,
    ) -> dict:
        _log(f"prompt={prompt!r} model={model}")

        is_explain = core.is_explain_request(prompt)
        exclude_tools = _select_exclude_tools(prompt)
        messages = core.initial_messages(prompt, context)

        for iteration in range(MAX_ITERATIONS):
            _log(f"── iteration {iteration + 1}/{MAX_ITERATIONS} ──")

            message = core.chat(
                messages,
                model,
                exclude_tools=exclude_tools,
            )

            tool_calls = (
                message.get("tool_calls") or []
            )[:core.MAX_TOOL_CALLS_PER_TURN]

            content = (message.get("content") or "").strip()

            if not tool_calls:
                if is_explain:
                    content = _strip_code_blocks(content)

                return {
                    "ok": True,
                    "response": content,
                }

            messages.append({
                "role": "assistant",
                "content": message.get("content", "") or "",
                "tool_calls": tool_calls,
            })

            self._run_tool_calls(
                tool_calls,
                messages,
                exclude_tools,
                interactive=False,
            )

        return {
            "ok": False,
            "error": L("Too many consecutive tool calls"),
        }

    # ─── Streaming path ───────────────────────────────────────

    def handle_ask_stream(
        self,
        prompt: str,
        context: str,
        model: str,
    ) -> None:
        """Stream the response directly to the client."""
        _log(f"[stream] prompt={prompt!r} model={model}")

        is_explain = core.is_explain_request(prompt)
        exclude_tools = _select_exclude_tools(prompt)
        force_buffer = is_explain

        messages = core.initial_messages(prompt, context)

        for iteration in range(MAX_ITERATIONS):
            _log(
                f"[stream] ── iteration "
                f"{iteration + 1}/{MAX_ITERATIONS} ──"
            )

            accumulated = ""
            streamed_so_far = False
            detected_tool_calls = None

            try:
                for event in core.chat_stream(
                    messages,
                    model,
                    exclude_tools=exclude_tools,
                ):
                    msg = event["message"]
                    done = event["done"]

                    if msg.get("tool_calls"):
                        detected_tool_calls = msg["tool_calls"]
                        break

                    chunk = msg.get("content", "")

                    if not chunk:
                        if done:
                            break
                        continue

                    accumulated += chunk

                    if force_buffer:
                        continue

                    if not streamed_so_far:
                        if not _looks_like_tool_call_prefix(accumulated):
                            self._send_json({
                                "type": "chunk",
                                "content": accumulated,
                            })
                            streamed_so_far = True
                    else:
                        self._send_json({
                            "type": "chunk",
                            "content": chunk,
                        })

                    if done:
                        break

            except (BrokenPipeError, ConnectionResetError):
                raise

            except Exception as e:
                _log(f"[stream] error: {e}")
                self._send_json({
                    "type": "error",
                    "message": str(e),
                })
                return

            # ─── Structured tool_calls (native Ollama) ─────────
            if detected_tool_calls:
                calls = detected_tool_calls[:core.MAX_TOOL_CALLS_PER_TURN]

                messages.append({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": calls,
                })

                self._run_tool_calls(
                    calls,
                    messages,
                    exclude_tools,
                    interactive=True,
                )

                if not self._alive:
                    return

                continue

            # ─── Tool call embedded in content ────────────────
            parsed = (
                None
                if streamed_so_far
                else core.extract_tool_call(accumulated)
            )

            if parsed:
                _log(f"[stream] content-parsed: {parsed['function']}")

                messages.append({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [parsed],
                })

                self._run_tool_calls(
                    [parsed],
                    messages,
                    exclude_tools,
                    interactive=True,
                )

                if not self._alive:
                    return

                continue

            # ─── No tool call -> final response ───────────────
            if not streamed_so_far and accumulated:
                if force_buffer:
                    accumulated = _strip_code_blocks(accumulated)

                self._send_json({
                    "type": "chunk",
                    "content": accumulated,
                })

            self._send_json({
                "type": "done",
                "response": accumulated,
            })

            return

        self._send_json({
            "type": "error",
            "message": L("Too many consecutive tool calls"),
        })


# ─── Server ──────────────────────────────────────────────────

class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def _socket_in_use(path: str) -> bool:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(1)

    try:
        s.connect(path)
        return True

    except OSError:
        return False

    finally:
        s.close()


def make_server(path: str = SOCKET_PATH) -> Server:
    """Create the server. Raise RuntimeError if the path is invalid or in use."""
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, mode=0o700, exist_ok=True)

    if os.path.lexists(path):
        st = os.lstat(path)

        if not stat.S_ISSOCK(st.st_mode):
            raise RuntimeError(f"{path} exists and is not a socket")

        if st.st_uid != os.getuid():
            raise RuntimeError(f"{path} belongs to another user")

        if _socket_in_use(path):
            raise RuntimeError(f"daemon already running ({path})")

        os.unlink(path)

    # Set the restrictive umask before bind().
    old_umask = os.umask(0o177)

    try:
        server = Server(path, Handler)

    finally:
        os.umask(old_umask)

    os.chmod(path, 0o600)

    return server


def _watch_stdin(server):
    """Shut down the daemon cleanly when stdin reaches EOF (Ctrl+D)."""
    try:
        while True:
            line = sys.stdin.readline()

            if not line:
                server.shutdown()
                return

    except (OSError, ValueError):
        return


def main():
    try:
        server = make_server(SOCKET_PATH)

    except RuntimeError as e:
        print(f"Daemon failed to start: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Daemon listening: {SOCKET_PATH}", file=sys.stderr)

    if DEBUG:
        print("DEBUG mode enabled", file=sys.stderr)

    stdin_watcher = threading.Thread(
        target=_watch_stdin,
        args=(server,),
        daemon=True,
    )
    stdin_watcher.start()

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        pass

    finally:
        server.server_close()

        try:
            os.unlink(SOCKET_PATH)
        except OSError:
            pass


if __name__ == "__main__":
    main()


