import json

import pytest

import i18n


@pytest.fixture
def loc(tmp_path, monkeypatch):
    monkeypatch.setattr(i18n, "LOCALES_DIR", tmp_path / "locales")
    (tmp_path / "locales").mkdir()
    return i18n.UILocalization("fi")


def test_good_translation_saved_atomically(loc, monkeypatch, tmp_path):
    monkeypatch.setattr(i18n, "translate_text", lambda **kw: "Kutsutaan työkalua: {}")
    assert loc.L("Calling tool: {}") == "Kutsutaan työkalua: {}"
    saved = json.loads((tmp_path / "locales" / "fi.json").read_text())
    assert saved == {"Calling tool: {}": "Kutsutaan työkalua: {}"}
    assert not list((tmp_path / "locales").glob("*.tmp"))
    # uusi instanssi lukee tallennetun
    monkeypatch.setattr(i18n, "translate_text", lambda **kw: (_ for _ in ()).throw(AssertionError))
    assert i18n.UILocalization("fi").L("Calling tool: {}") == "Kutsutaan työkalua: {}"


def test_changed_placeholders_rejected(loc, monkeypatch, tmp_path):
    monkeypatch.setattr(i18n, "translate_text", lambda **kw: "Kutsutaan työkalua: {nimi}")
    assert loc.L("Calling tool: {}") == "Calling tool: {}"
    assert not (tmp_path / "locales" / "fi.json").exists()
    # .format ei kaadu
    assert loc.L("Calling tool: {}").format("x") == "Calling tool: x"


def test_bad_entries_ignored_on_load(tmp_path, monkeypatch):
    d = tmp_path / "locales"; d.mkdir()
    (d / "fi.json").write_text(json.dumps({
        "Hello {name}": "Hei {nimi}",        # väärä paikkamerkki
        "Bye": "Näkemiin",
        "Num": 5,                            # ei merkkijono
    }))
    monkeypatch.setattr(i18n, "LOCALES_DIR", d)
    l = i18n.UILocalization("fi")
    assert l._translations == {"Bye": "Näkemiin"}


def test_translation_disabled_does_not_call_shl(loc, monkeypatch):
    monkeypatch.setenv("ASK_MT_ENABLED", "false")
    monkeypatch.setattr(i18n, "translate_text", lambda **kw: (_ for _ in ()).throw(AssertionError))
    assert loc.L("Hello") == "Hello"


def test_path_traversal_language_code(tmp_path, monkeypatch):
    monkeypatch.setattr(i18n, "LOCALES_DIR", tmp_path / "locales")
    l = i18n.UILocalization("../../evil")
    assert l.target_language == "en"
    assert ".." not in str(l._locale_file())


def test_same_language_passthrough():
    assert i18n.UILocalization("en").L("Hi") == "Hi"
