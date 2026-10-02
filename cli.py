"""Komentoriviasiakas. Keskustelee daemonin kanssa.

Tukee kahta tilaa:
  - Striimaava (oletus): vastaus tulostuu token kerrallaan
  - Ei-striimaava: koko vastaus tulostetaan kerralla (ASK_NO_STREAM=1)

Molemmat käyttävät samaa striimausprotokollaa (vahvistus toimii siksi
molemmissa):
  * {"type": "chunk", "content": "..."}     – tekstinpala
  * {"type": "status", "message": "..."}    – tilatieto (esim. työkalukutsu)
  * {"type": "confirm", ...}                – vahvistuspyyntö kirjoitustyökalulle
  * {"type": "done", "response": "..."}     – lopetus, koko vastaus
  * {"type": "error", "message": "..."}     – virhe

Vahvistukseen vastataan samalla yhteydellä:
  {"action": "confirm", "approved": true|false}
"""

import argparse
import json
import os
import re
import socket
import sys

import appenv
from i18n import L
from _version import __version__

SOCKET_PATH = str(appenv.socket_path())

# Onko striimaus käytössä? Oletus: kyllä. ASK_NO_STREAM=1 pakottaa pois.
USE_STREAM = os.environ.get("ASK_NO_STREAM") != "1"

# ─── Päätteen suojaus ────────────────────────────────────────
# Mallin vastaus voi sisältää tiedostoista tai lokeista peräisin olevia
# ohjausmerkkejä (ESC-sekvenssit voivat mm. kirjoittaa päätteen otsikon tai
# piilottaa tekstiä). Poistetaan kaikki paitsi rivinvaihto ja sarkain.

_ANSI_RE = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])"
)
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def _clean(text) -> str:
    """Poistaa ANSI-sekvenssit ja ohjausmerkit (ESC poistuu aina, vaikka
    sekvenssi olisi jakautunut kahteen chunkkiin)."""
    return _CTRL_RE.sub("", _ANSI_RE.sub("", str(text)))


class DaemonUnavailable(Exception):
    """Daemoniin ei saada yhteyttä."""


# ─── Yhteys daemoniin ────────────────────────────────────────

def _connect() -> socket.socket:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(SOCKET_PATH)
    except (FileNotFoundError, ConnectionRefusedError, PermissionError) as e:
        s.close()
        raise DaemonUnavailable(
            L("Cannot reach the Ask Ubuntu mini daemon ({path}): {reason}. "
              "Is it running?").format(path=SOCKET_PATH, reason=e.strerror or e)
        ) from e
    return s


def call(req: dict) -> dict:
    """Lähettää pyynnön ja lukee yhden JSON-vastauksen (muille asiakkaille)."""
    with _connect() as s:
        s.sendall((json.dumps(req) + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode())


# ─── Työkalun vahvistus ──────────────────────────────────────

def confirm_tool(resp: dict) -> bool:
    """Kysyy käyttäjältä vahvistuksen kirjoitustyökalulle."""
    print()
    print("┌─ " + L("Tool confirmation") + " ──────────────────────────")
    print(f"│ {L('Tool')}:        {_clean(resp.get('tool', '?'))}")
    print(f"│ {L('Description')}: {_clean(resp.get('description', ''))}")
    print(f"│ {L('Arguments')}:   {_clean(resp.get('args', {}))}")
    print(f"│ {L('Type')}:        {L('WRITE')}")
    print("└───────────────────────────────────────────────────────")
    try:
        answer = input(L("Allow? [y/n] ")).strip().lower()
    except EOFError:           # ei interaktiivinen terminaali → hylkää
        return False
    return answer in ("y", "yes", "k", "kyllä")


# ─── Keskustelu ──────────────────────────────────────────────

def ask_stream(prompt: str, quiet: bool = False) -> str:
    """Kysyy daemonilta striimausprotokollalla.

    quiet=True: ei tulosta mitään, palauttaa vain vastauksen (tai virheen).
    Palauttaa koko vastauksen merkkijonona.
    """
    def out(text: str, **kw):
        if not quiet:
            print(text, **kw)

    with _connect() as s:
        s.sendall(json.dumps({
            "action": "ask", "prompt": prompt, "stream": True,
        }).encode() + b"\n")

        buffer = b""
        full_response = ""
        started_output = False

        while True:
            try:
                chunk = s.recv(4096)
            except ConnectionResetError:
                break
            if not chunk:
                break
            buffer += chunk

            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type")

                if etype == "chunk":
                    text = event.get("content", "")
                    started_output = True
                    out(_clean(text), end="", flush=True)
                    full_response += text

                elif etype == "status":
                    out(f"\n  [{_clean(event.get('message', ''))}]", flush=True)

                elif etype == "confirm":
                    if started_output:
                        out("")
                        started_output = False
                    if quiet:
                        approved = False     # hiljaisessa tilassa ei kysytä
                    else:
                        approved = confirm_tool(event)
                        if not approved:
                            print(L("(tool rejected)"))
                    # Vastaus samalle yhteydelle; keskustelu jatkuu daemonissa
                    s.sendall(json.dumps({
                        "action": "confirm", "approved": approved,
                    }).encode() + b"\n")

                elif etype == "done":
                    if started_output:
                        out("")
                    return event.get("response", full_response)

                elif etype == "error":
                    msg = f"{L('[error]')} {_clean(event.get('message', ''))}"
                    if started_output:
                        out("")
                    if quiet:
                        return msg
                    print(msg)
                    return ""

        if started_output:
            out("")
        return full_response


def ask_blocking(prompt: str) -> str:
    """Koko vastaus kerralla (vahvistukset eivät ole mahdollisia: ei kysytä)."""
    return ask_stream(prompt, quiet=True)


# ─── Julkinen rajapinta ──────────────────────────────────────

def ask(prompt: str) -> str:
    """Kysyy daemonilta. Käyttää striimausta jos se on päällä."""
    if USE_STREAM:
        return ask_stream(prompt)
    return ask_blocking(prompt)


def _run(prompt: str) -> None:
    result = ask(prompt)
    if not USE_STREAM:
        print(_clean(result))      # striimaava polku tulostaa itse


# ─── Komentoriviparametrit ───────────────────────────────────

def _parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="ask",
        description="Ask Ubuntu Mini command-line client",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="Question to send to the Ask Ubuntu mini daemon",
    )
    return parser.parse_args()


def main():
    args = _parse_args()

    try:
        if args.prompt:
            _run(" ".join(args.prompt))
            return

        APP_NAME = "Ask Ubuntu Mini"
        print(L("{app} – Ctrl+D to exit").format(app=APP_NAME))
        if USE_STREAM:
            print(L("(streaming on – response appears as it arrives)"))

        while True:
            try:
                prompt = input("> ")
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print()
                continue

            if prompt.strip():
                try:
                    _run(prompt)
                except KeyboardInterrupt:
                    print()
                print()

    except DaemonUnavailable as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print()
        sys.exit(130)


if __name__ == "__main__":
    main()
