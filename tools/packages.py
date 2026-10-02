"""Pakettityökalut: apt ja snap (vain lukuoperaatiot)."""
from .registry import tool
from ._common import run, is_safe_name, limit_lines

_SEARCH_CHARS = "-_. "


@tool("apt_search", readonly=True, requires=("apt-cache",),
      description=("Etsii apt-paketteja avainsanalla. Näyttää paketin nimen ja "
                   "lyhyen kuvauksen. Käyttää apt-cache search -komentoa."),
      params={"keyword": "Hakusana, esim. 'python' tai 'editor'"})
def apt_search(keyword: str) -> str:
    if not is_safe_name(keyword, _SEARCH_CHARS, 100):
        return f"[virhe] virheellinen hakusana: {keyword}"
    out = run(["apt-cache", "search", "--names-only", keyword], timeout=15)
    if out == "(ei tulostetta)":
        return f"(ei tuloksia hakusanalle '{keyword}')"
    return limit_lines(out, 30)


@tool("snap_list", readonly=True, requires=("snap",),
      description="Listaa asennetut snap-paketit versioineen ja kanavineen")
def snap_list() -> str:
    return limit_lines(run(["snap", "list"], timeout=10), 60)


@tool("snap_search", readonly=True, requires=("snap",),
      description="Etsii snap-paketteja Snap Storesta avainsanalla",
      params={"keyword": "Hakusana, esim. 'vlc' tai 'editor'"})
def snap_search(keyword: str) -> str:
    if not is_safe_name(keyword, _SEARCH_CHARS, 100):
        return f"[virhe] virheellinen hakusana: {keyword}"
    # "--" estää hakusanan tulkitsemisen optioksi
    return limit_lines(run(["snap", "find", "--", keyword], timeout=15), 30)


@tool("snap_info", readonly=True, requires=("snap",),
      description="Näyttää tietyn snap-paketin tiedot (kuvaus, kanavat, versiot)",
      params={"name": "Snap-paketin nimi, esim. 'firefox'"})
def snap_info(name: str) -> str:
    if not is_safe_name(name):
        return f"[virhe] virheellinen snap-nimi: {name}"
    return limit_lines(run(["snap", "info", "--", name], timeout=15), 60)
