"""run_command-työkalun komentojen validointi.

HUOM: ALLOWED_COMMANDS on tarkoitettu VAIN lukuoperaatioille. Jos komento
MUUTTAA järjestelmää, tee siitä erillinen työkalu (readonly=False), jotta
CLI:n vahvistuslogiikka toimii.

Sääntöavaimet:
  flags              – sallitut pelkät flagit (ja sanat, esim. 'aux', 'show')
  flags_with_value   – flagit, jotka vaativat arvon (-n 20 tai --type=service)
  subcommands        – sallitut alikomennot (ensimmäinen ei-flag-argumentti)
  positional         – path | service_name | word | none
  max_positional     – positionaalisten argumenttien enimmäismäärä
  positional_requires – positionaalinen sallitaan vasta kun jokin näistä
                        sanoista on nähty (esim. ip addr show <iface>)
"""
import shlex

from .errors import AccessDenied
from .paths import check_path

ALLOWED_COMMANDS = {
    "ls": {
        "flags": {"-l", "-a", "-la", "-al", "-h", "-lh", "-lah", "-1", "-t",
                  "-r", "-S", "-i", "--all", "--long", "--human-readable"},
        # -R puuttuu tarkoituksella: se kiertäisi polkusuojauksen
        "positional": "path", "max_positional": 5,
    },
    "cat": {"flags": {"-n", "-b", "-A"}, "positional": "path", "max_positional": 5},
    "head": {"flags_with_value": {"-n", "-c"}, "positional": "path", "max_positional": 5},
    "tail": {"flags_with_value": {"-n", "-c"}, "positional": "path", "max_positional": 5},
    "file": {"flags": {"-b", "-i"}, "positional": "path", "max_positional": 5},
    "stat": {"flags": {"-f"}, "flags_with_value": {"-c"},
             "positional": "path", "max_positional": 5},
    "df": {"flags": {"-h", "-H", "-T", "-i", "-a"}, "flags_with_value": {"-x"},
           "positional": "path", "max_positional": 2},
    "free": {"flags": {"-h", "-m", "-g", "-t", "-b", "-k"}},
    "uptime": {},
    "nproc": {"flags": {"--all"}},
    "hostname": {"flags": {"-f", "-s", "-I"}},
    "whoami": {},
    "date": {"flags": {"-u", "-R", "-I"}},
    "ps": {
        "flags": {"-e", "-f", "-ef", "-aux", "aux", "-efH"},
        "flags_with_value": {"-o", "-eo", "--sort"},
    },
    "ss": {"flags": {"-t", "-u", "-l", "-n", "-p", "-a", "-tln", "-tlnp",
                     "-tulp", "-tan", "-tlnup"}},
    "ip": {
        "subcommands": {"addr", "a", "link", "l", "route", "r"},
        "flags": {"-4", "-6", "-br", "show", "ls"},
        "positional": "iface", "max_positional": 1,
        "positional_requires": {"show", "ls"},
    },
    "systemctl": {
        "subcommands": {"status", "is-active", "is-enabled", "is-failed",
                        "list-units", "show"},
        "flags": {"--no-pager", "--all", "--user"},
        "flags_with_value": {"--type", "--state"},
        "positional": "service_name", "max_positional": 2,
    },
    "journalctl": {
        # -f puuttuu: se jäisi odottamaan aikakatkaisuun asti
        "flags": {"--no-pager", "-b"},
        "flags_with_value": {"-n", "-u", "-p", "--since", "--until"},
    },
}

_FORBIDDEN_SUBSTRINGS = ("$(", "`", ";", "&&", "||", "|", ">", "<", "&", "../", "..\\")
_MAX_TOKENS = 20
_MAX_TOKEN_LEN = 500
_MAX_COMMAND_LEN = 2000


def _validate_token(tok: str) -> None:
    if len(tok) > _MAX_TOKEN_LEN:
        raise AccessDenied(f"liian pitkä argumentti (max {_MAX_TOKEN_LEN} merkkiä)")
    for bad in _FORBIDDEN_SUBSTRINGS:
        if bad in tok:
            raise AccessDenied(f"kielletty merkki tai kuvio: {bad!r}")


def _validate_flag(tok: str, allowed: set, with_value: set, cmd: str) -> int:
    """Palauttaa kuinka monta tokenia kului (1 tai 2)."""
    if "=" in tok:
        flag = tok.partition("=")[0]
        if flag not in with_value:
            raise AccessDenied(f"flag '{flag}' ei ole sallittu komennolle '{cmd}'")
        return 1
    if tok in with_value:
        return 2
    if tok not in allowed:
        raise AccessDenied(f"flag '{tok}' ei ole sallittu komennolle '{cmd}'")
    return 1


def _validate_positional(tok: str, rule: str, cmd: str) -> str:
    """Validoi positionaalisen argumentin ja palauttaa normalisoidun tokenin."""
    if rule == "path":
        return str(check_path(tok))   # ajetaan juuri se polku, joka tarkistettiin
    if rule == "service_name":
        ok = all(c.isalnum() or c in ".-_@" for c in tok)
    elif rule == "iface":
        ok = all(c.isalnum() or c in ".-_:@" for c in tok) and len(tok) <= 32
    elif rule == "none":
        raise AccessDenied(f"komento '{cmd}' ei hyväksy argumentteja")
    else:
        raise AccessDenied(f"tuntematon argumenttisääntö: {rule!r}")
    if not ok:
        raise AccessDenied(f"virheellinen argumentti: {tok}")
    return tok


def _validate(tokens: list[str]) -> list[str]:
    if not tokens:
        raise AccessDenied("tyhjä komento")
    if len(tokens) > _MAX_TOKENS:
        raise AccessDenied(f"liian monta tokenia (max {_MAX_TOKENS})")
    for tok in tokens:
        _validate_token(tok)

    cmd = tokens[0]
    rules = ALLOWED_COMMANDS.get(cmd)
    if rules is None:
        raise AccessDenied(f"komento '{cmd}' ei ole sallittu")

    allowed = rules.get("flags", set())
    with_value = rules.get("flags_with_value", set())
    subcommands = rules.get("subcommands", set())
    pos_rule = rules.get("positional", "none")
    max_pos = rules.get("max_positional", 0)
    requires = rules.get("positional_requires", set())

    out = [cmd]
    i, pos_count, seen_sub = 1, 0, False
    seen_words: set[str] = set()

    while i < len(tokens):
        tok = tokens[i]

        if tok.startswith("-"):
            consumed = _validate_flag(tok, allowed, with_value, cmd)
            if consumed == 2 and i + 1 >= len(tokens):
                raise AccessDenied(f"flag '{tok}' vaatii arvon")
            out.extend(tokens[i:i + consumed])
            i += consumed
            continue

        if subcommands and not seen_sub:
            if tok not in subcommands:
                raise AccessDenied(
                    f"alikomento '{tok}' ei ole sallittu komennolle '{cmd}'")
            seen_sub = True
            out.append(tok)
            i += 1
            continue

        # Sanamuotoiset flagit (esim. 'aux', 'show')
        if tok in allowed:
            seen_words.add(tok)
            out.append(tok)
            i += 1
            continue

        pos_count += 1
        if pos_count > max_pos:
            raise AccessDenied(
                f"liian monta argumenttia komennolle '{cmd}' (max {max_pos})")
        if requires and not (seen_words & requires):
            raise AccessDenied(
                f"argumentti '{tok}' sallitaan vain sanojen "
                f"{sorted(requires)} jälkeen")
        out.append(_validate_positional(tok, pos_rule, cmd))
        i += 1

    return out


def validate_command(tokens: list[str]) -> None:
    """Heittää AccessDenied jos komento ei ole sallittu."""
    _validate(tokens)


def parse_and_validate(command_str: str) -> list[str]:
    """Jäsentää ja validoi komennon. Polkuargumentit palautetaan ratkaistuina."""
    if len(command_str) > _MAX_COMMAND_LEN:
        raise AccessDenied(f"komento on liian pitkä (max {_MAX_COMMAND_LEN} merkkiä)")
    try:
        tokens = shlex.split(command_str)
    except ValueError as e:
        raise AccessDenied(f"komennon jäsennys epäonnistui: {e}")
    return _validate(tokens)
