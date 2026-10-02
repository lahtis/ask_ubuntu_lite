import pytest

import config

def test_config_migration_adds_version_and_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        'model = "llama3.1:8b"\n'
        'ollama_urls = ["http://localhost:11434"]\n',
        encoding="utf-8",
    )

    data = {
        "model": "llama3.1:8b",
        "ollama_urls": ["http://localhost:11434"],
    }

    migrated = config._migrate_config(data, path)

    assert migrated["config_version"] == config.CONFIG_VERSION
    assert migrated["ollama_health_cache_ttl"] == 30
    assert migrated["ollama_health_timeout"] == 1.5
    assert migrated["ollama_health_backoff"] == [2, 4, 8, 16, 30, 60]
    assert migrated["ollama_chat_timeout"] == 120

    text = path.read_text(encoding="utf-8")
    assert "config_version = 1" in text
    assert "ollama_health_cache_ttl = 30" in text

    backup = path.with_name("config.toml.bak")
    assert backup.exists()


def test_config_migration_does_not_overwrite_existing_values(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        'model = "custom:7b"\n'
        'ollama_health_timeout = 5.0\n'
        'ollama_chat_timeout = 300\n',
        encoding="utf-8",
    )

    data = {
        "model": "custom:7b",
        "ollama_health_timeout": 5.0,
        "ollama_chat_timeout": 300,
    }

    migrated = config._migrate_config(data, path)

    assert migrated["ollama_health_timeout"] == 5.0
    assert migrated["ollama_chat_timeout"] == 300
    assert migrated["ollama_health_cache_ttl"] == 30
    assert migrated["ollama_health_backoff"] == [2, 4, 8, 16, 30, 60]


def test_config_migration_creates_byte_for_byte_backup(tmp_path):
    path = tmp_path / "config.toml"
    original = (
        '# User configuration\n'
        'model = "custom:7b"\n'
        '\n'
        'ollama_urls = ["http://localhost:11434"]\n'
    )
    path.write_text(original, encoding="utf-8")

    data = {
        "model": "custom:7b",
        "ollama_urls": ["http://localhost:11434"],
    }

    config._migrate_config(data, path)

    backup = path.with_name("config.toml.bak")

    assert backup.read_text(encoding="utf-8") == original


def test_config_migration_does_not_modify_current_version(tmp_path):
    path = tmp_path / "config.toml"
    original = (
        "config_version = 1\n"
        'model = "custom:7b"\n'
    )
    path.write_text(original, encoding="utf-8")

    data = {
        "config_version": 1,
        "model": "custom:7b",
    }

    migrated = config._migrate_config(data, path)

    assert migrated == data
    assert path.read_text(encoding="utf-8") == original
    assert not path.with_name("config.toml.bak").exists()

def test_config_migration_failure_keeps_original(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    original = 'model = "custom:7b"\n'
    path.write_text(original, encoding="utf-8")

    data = {
        "model": "custom:7b",
    }

    def fail_write(*args, **kwargs):
        raise OSError("simulated write failure")

    monkeypatch.setattr(config, "_write_config_atomically", fail_write)

    migrated = config._migrate_config(data, path)

    assert migrated == data
    assert path.read_text(encoding="utf-8") == original

    backup = path.with_name("config.toml.bak")
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == original

def test_config_migration_does_not_modify_newer_version(tmp_path):
    path = tmp_path / "config.toml"
    original = (
        "config_version = 999\n"
        'model = "future:1b"\n'
    )
    path.write_text(original, encoding="utf-8")

    data = {
        "config_version": 999,
        "model": "future:1b",
    }

    migrated = config._migrate_config(data, path)

    assert migrated == data
    assert path.read_text(encoding="utf-8") == original
    assert not path.with_name("config.toml.bak").exists()

def test_normalize_lang():
    assert config.normalize_lang("fi") == "fi"
    assert config.normalize_lang("pt_BR") == "pt-BR"
    assert config.normalize_lang("en-US") == "en-US"
    for bad in ("../../etc/x", "fi/../..", "", None, "toolonglang", "f"):
        assert config.normalize_lang(bad) == "en"


def test_local_config_ignored_by_default(tmp_path, monkeypatch):
    (tmp_path / "config.toml").write_text('model = "evil:1b"\nollama_urls = ["http://evil:1"]\n')
    monkeypatch.chdir(tmp_path)
    data, path = config._find_config()
    assert "model" not in data and path != tmp_path / "config.toml"


def test_local_config_opt_in(tmp_path, monkeypatch):
    (tmp_path / "config.toml").write_text('model = "dev:1b"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ASK_ALLOW_LOCAL_CONFIG", "1")
    data, _ = config._find_config()
    assert data["model"] == "dev:1b"


def test_invalid_number_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("ASK_NUM_PREDICT", "abc")
    assert config.get("num_predict") == config.DEFAULTS["num_predict"]
    monkeypatch.setenv("ASK_REPEAT_PENALTY", "1.5")
    assert config.get("repeat_penalty") == 1.5


def test_search_dirs_in_snap(tmp_path, monkeypatch):
    real = tmp_path / "home"
    common = real / "snap" / "ask-ubuntu" / "common"
    common.mkdir(parents=True)
    monkeypatch.setenv("SNAP", "/snap/ask-ubuntu/1")
    monkeypatch.setenv("SNAP_NAME", "ask-ubuntu")
    monkeypatch.setenv("SNAP_REAL_HOME", str(real))
    monkeypatch.setenv("SNAP_USER_COMMON", str(common))
    import appenv
    dirs = appenv.config_search_dirs()
    assert dirs == [common / "config", real / ".config" / "ask-ubuntu"]


def test_limits():
    assert 1 <= config.MAX_ITERATIONS <= 20
    assert config.LANG_CODE == "en"
