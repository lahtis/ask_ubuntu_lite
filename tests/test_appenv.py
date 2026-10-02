import pytest

import appenv
import guard


@pytest.fixture
def snap_env(tmp_path, monkeypatch):
    """Simuloi snapin sisäpuolta: HOME osoittaa snapin data-kansioon."""
    real = tmp_path / "home"
    snap_home = real / "snap" / "ask-ubuntu" / "12"
    common = real / "snap" / "ask-ubuntu" / "common"
    snap_home.mkdir(parents=True)
    common.mkdir(parents=True)
    monkeypatch.delenv("ASK_UBUNTU_ALLOW_FILE", raising=False)
    monkeypatch.setenv("SNAP", "/snap/ask-ubuntu/12")
    monkeypatch.setenv("SNAP_NAME", "ask-ubuntu")
    monkeypatch.setenv("SNAP_REAL_HOME", str(real))
    monkeypatch.setenv("SNAP_USER_DATA", str(snap_home))
    monkeypatch.setenv("SNAP_USER_COMMON", str(common))
    monkeypatch.setenv("HOME", str(snap_home))   # juuri näin snap tekee
    monkeypatch.setenv("LD_LIBRARY_PATH", "/snap/ask-ubuntu/12/lib")
    monkeypatch.setenv("PATH", "/snap/ask-ubuntu/12/usr/bin:/usr/bin:/bin")
    return real


def test_detects_snap_and_not_other_snaps():
    assert appenv.in_ask_ubuntu_snap({"SNAP": "/snap/ask-ubuntu/1", "SNAP_NAME": "ask-ubuntu"})
    assert not appenv.in_ask_ubuntu_snap({"SNAP": "/snap/firefox/1", "SNAP_NAME": "firefox"})
    assert not appenv.in_ask_ubuntu_snap({})           # tyhjä dict ei putoa os.environiin


def test_real_home_and_expand(snap_env):
    assert appenv.real_home() == snap_env
    assert appenv.expand_home("~/.ssh") == str(snap_env / ".ssh")


def test_guard_protects_real_home_inside_snap(snap_env):
    """Ilman SNAP_REAL_HOME-tukea ~/.ssh osoittaisi snapin data-kansioon."""
    (snap_env / ".ssh").mkdir()
    assert guard.is_blocked(str(snap_env / ".ssh" / "id_rsa"))
    assert guard.is_blocked("~/.ssh/config")
    assert not guard.is_blocked(str(snap_env / "notes.txt"))


def test_dirs_use_user_common(snap_env):
    assert appenv.app_config_dir() == snap_env / "snap" / "ask-ubuntu" / "common" / "config"
    assert appenv.app_cache_dir().is_dir()


def test_host_env_strips_snap_leaks(snap_env):
    e = appenv.host_env({"MANWIDTH": "80"})
    assert "LD_LIBRARY_PATH" not in e
    assert "/snap/ask-ubuntu" not in e["PATH"]
    assert e["HOME"] == str(snap_env)
    assert e["MANWIDTH"] == "80"


def test_host_env_untouched_outside_snap(monkeypatch):
    monkeypatch.delenv("SNAP", raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/x")
    assert appenv.host_env()["LD_LIBRARY_PATH"] == "/x"


def test_tools_availability(monkeypatch):
    import tools
    monkeypatch.setattr(appenv, "which_host", lambda b: None if b == "docker" else "/usr/bin/" + b)
    names = tools.get_tools()
    assert "docker_ps" not in names and "check_disk" in names
    assert "docker_ps" in tools.get_tools(available_only=False)

def test_socket_path_outside_snap(tmp_path, monkeypatch):
    monkeypatch.delenv("SNAP", raising=False)
    monkeypatch.delenv("SNAP_NAME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert appenv.socket_path() == tmp_path / ".cache" / "ask-ubuntu" / "ask.sock"


def test_socket_path_in_snap(snap_env):
    assert appenv.socket_path() == (
        snap_env / "snap" / "ask-ubuntu" / "common" / "ask.sock"
    )
