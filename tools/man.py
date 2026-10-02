"""Man-sivutyökalut: man_page (tiivistelmä + flag-nimet) ja man_flag (yksi flag).

Suunnittelu:
- Runko: NAME + SYNOPSIS + DESCRIPTION (ei OPTIONS-tekstiä)
- Flag-lista erillisenä osiona, enintään _MAX_FLAGS_DISPLAYED nimeä
- OPTIONS-teksti piilotetaan, jotta malli ei poimi sieltä flag-nimiä
"""
import os
import re
import subprocess

from .registry import tool
from ._common import host_env
from ._common import is_safe_name

_MAX_FLAGS_DISPLAYED = 10

_SECTION_STOPS = {
    "EXAMPLES", "SEE ALSO", "AUTHOR", "AUTHORS", "FILES", "BUGS", "HISTORY",
    "NOTES", "REPORTING BUGS", "COPYRIGHT", "DETAILED DESCRIPTION",
    "STREAM SPECIFIERS", "EXIT CODE", "EXPRESSION EVALUATION",
}


def _fetch_man(command: str) -> tuple[str | None, str | None]:
    """Palauttaa (teksti, virheviesti)."""
    try:
        result = subprocess.run(
            ["man", "--nj", "--no-hyphenation", command],
            capture_output=True, text=True, timeout=10,
            env=host_env({"MANWIDTH": "80", "MANPAGER": "cat"}),
        )
    except subprocess.TimeoutExpired:
        return None, "[virhe] man-sivun haku aikakatkaistiin"
    except FileNotFoundError:
        return None, "[virhe] man-komentoa ei löydy järjestelmästä"
    except Exception as e:
        return None, f"[virhe] {e}"

    if result.returncode != 0:
        return None, f"[virhe] man-sivua ei löydy komennolle '{command}'"
    text = result.stdout.strip()
    if not text:
        return None, f"[virhe] man-sivu '{command}' on tyhjä"
    return text, None


@tool("man_page", readonly=True, requires=("man",),
      description=(
          "Hakee komennon man-sivun tiivistelmän (NAME, SYNOPSIS, "
          "DESCRIPTION) sekä listan tärkeimmistä flageista (VAIN NIMET). "
          "Käytä tätä kun kysytään mitä komento tekee tai mitkä ovat "
          "komennon yleisimmät optiot. Jos kysytään tietystä flagista, "
          "käytä man_flag-työkalua."
      ),
      params={"command": "Komennon nimi, esim. 'df' tai 'systemctl'"})
def man_page(command: str) -> str:
    if not is_safe_name(command):
        return f"[virhe] virheellinen komennon nimi: {command}"

    full_output, err = _fetch_man(command)
    if err:
        return err

    total_lines = full_output.count("\n") + 1
    body = _extract_man_sections(full_output)

    flag_names = _extract_flag_names(full_output)
    if flag_names:
        shown = flag_names[:_MAX_FLAGS_DISPLAYED]
        body += (
            f"\n\nTÄRKEIMMÄT FLAGIT ({len(flag_names)} kpl yhteensä, "
            f"näytetään {len(shown)} – VAIN NIMET, EI KUVAUKSIA):\n"
            + "\n".join(f"  {name}" for name in shown)
        )
        if len(flag_names) > _MAX_FLAGS_DISPLAYED:
            body += f"\n  ...(+{len(flag_names) - _MAX_FLAGS_DISPLAYED} muuta)"

    if total_lines > 2000:
        return (
            f"[MAN-SIVU ON PITKÄ: {total_lines} riviä]\n"
            f"Alla on tiivistelmä man-sivusta sekä flag-lista. "
            f"Jos tarvitset tietyn flagin kuvauksen, käytä man_flag-työkalua.\n"
            f"{'─' * 60}\n" + body
        )
    return body


@tool("man_flag", readonly=True, requires=("man",),
      description=(
          "Hakee tietyn flagin kuvauksen man-sivulta. "
          "Käytä tätä kun kysytään mitä tietty flag tekee, "
          "esim. '-T' tai '--output'."
      ),
      params={
          "command": "Komennon nimi, esim. 'ffmpeg' tai 'df'",
          "flag": "Flag, esim. '-T' tai '--output'",
      })
def man_flag(command: str, flag: str) -> str:
    if not is_safe_name(command):
        return "[virhe] virheellinen komennon nimi"
    if not flag or len(flag) > 30:
        return "[virhe] virheellinen flag"
    if not flag.startswith("-"):
        flag = "-" + flag

    text, err = _fetch_man(command)
    if err:
        return err

    lines = text.split("\n")
    flag_re = re.compile(rf'^\s{{1,10}}{re.escape(flag)}(?:[,\s=]|$)')

    start = next((i for i, l in enumerate(lines) if flag_re.match(l)), None)
    if start is None:
        return (f"[virhe] flagia '{flag}' ei löytynyt komennon '{command}' "
                f"man-sivulta. Tarkista flag-nimi.")

    out = [lines[start].rstrip()]
    for line in lines[start + 1:]:
        if re.match(r'^\s{1,10}-{1,2}\w', line) or not line.strip():
            break
        out.append(line.rstrip())
    return "\n".join(out).strip()


def _extract_flag_names(output: str) -> list[str]:
    """Poimii flag-nimet man-sivun OPTIONS-osiosta."""
    lines = output.split("\n")
    options_start = next(
        (i for i, l in enumerate(lines) if l.strip() == "OPTIONS"), None)
    if options_start is None:
        return []

    flag_start_re = re.compile(r'^\s{1,10}(-{1,2}[a-zA-Z][\w-]*)')
    names, seen = [], set()

    for line in lines[options_start + 1:]:
        if line.strip() in _SECTION_STOPS:
            break
        m = flag_start_re.match(line)
        if m:
            flag = m.group(1).rstrip(",;:")
            if flag and flag not in seen:
                seen.add(flag)
                names.append(flag)
    return names


def _extract_man_sections(output: str) -> str:
    """Poimii NAME, SYNOPSIS ja DESCRIPTION (max 40 riviä); OPTIONS vain otsikkona."""
    lines = output.split("\n")

    starts = {}
    for i, line in enumerate(lines):
        s = line.strip()
        if s in ("NAME", "SYNOPSIS", "DESCRIPTION", "OPTIONS", "DETAILED DESCRIPTION"):
            starts.setdefault(s, i)

    result = []
    name_start = starts.get("NAME", 0)
    synopsis_end = starts.get("DESCRIPTION", starts.get("OPTIONS", name_start + 20))
    result.extend(lines[name_start:synopsis_end])

    if "DESCRIPTION" in starts:
        desc_start = starts["DESCRIPTION"]
        desc_end = starts.get("DETAILED DESCRIPTION",
                              starts.get("OPTIONS", desc_start + 40))
        desc_end = min(desc_end, desc_start + 40)
        result.extend(lines[desc_start:desc_end])
        if "OPTIONS" in starts and desc_end < starts["OPTIONS"]:
            result.append("       ...")

    if "OPTIONS" in starts:
        result += ["", "OPTIONS:",
                   "       (Katso flag-lista alla – käytä man_flag-työkalua "
                   "tietyn flagin kuvaukseen)"]

    return "\n".join(result) if result else "(ei tunnistettuja osioita)"
