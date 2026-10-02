"""Työkalupaketti.

Jokainen tämän kansion moduuli (paitsi alaviivalla alkavat ja registry)
ladataan automaattisesti, ja sen @tool-dekoraattorit rekisteröivät työkalut.
Uusi työkalu = uusi .py-tiedosto tähän kansioon.

Käyttö:
    import tools
    tools.TOOLS["check_disk"]["func"]()
    tools.get_tools(readonly_only=True)
"""
import importlib
import pkgutil

from .registry import TOOLS, tool, is_available

__all__ = ["TOOLS", "tool", "get_tools", "load_all"]

_loaded = False


def load_all() -> None:
    """Importtaa kaikki työkalumoduulit (kutsutaan kerran importissa)."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    for mod in pkgutil.iter_modules(__path__):
        if mod.name.startswith("_") or mod.name == "registry":
            continue
        try:
            importlib.import_module(f"{__name__}.{mod.name}")
        except Exception as e:  # yksi rikkinäinen moduuli ei kaada kaikkea
            print(f"[tools] moduulin '{mod.name}' lataus epäonnistui: {e}")


def get_tools(readonly_only: bool = False, available_only: bool = True) -> dict:
    """Rekisteröidyt työkalut. Oletuksena vain ne, joiden vaatimat komennot
    (docker, git, snap, ...) löytyvät isäntäjärjestelmästä."""
    return {
        n: t for n, t in TOOLS.items()
        if (not readonly_only or t["readonly"])
        and (not available_only or is_available(t))
    }


load_all()
