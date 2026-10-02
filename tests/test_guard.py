import os
import pytest

import guard
from guard import AccessDenied


@pytest.fixture(autouse=True)
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ASK_UBUNTU_ALLOW_FILE", str(tmp_path / "allow.txt"))
    return home


# ── polut ────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", [".ssh/id_rsa", ".aws/credentials", ".env",
                                 ".env.local", "srv/server.pem", "my_password.txt",
                                 ".mozilla/x/cookies.sqlite"])
def test_blocked_in_home(fake_home, rel):
    assert guard.is_blocked(str(fake_home / rel))
    with pytest.raises(AccessDenied):
        guard.check_path(str(fake_home / rel))


@pytest.mark.parametrize("p", ["/etc/shadow", "/dev/zero", "/dev/urandom",
                               "/proc/self/environ", "/etc/ssh/ssh_host_rsa_key"])
def test_blocked_system(p):
    assert guard.is_blocked(p)


def test_env_example_allowed(fake_home):
    assert not guard.is_blocked(str(fake_home / ".env.example"))


def test_symlink_to_secret_blocked(fake_home):
    (fake_home / ".ssh").mkdir()
    (fake_home / ".ssh" / "config").write_text("x")
    link = fake_home / "innocent.txt"
    link.symlink_to(fake_home / ".ssh" / "config")
    assert guard.is_blocked(str(link))


def test_user_allow_file(fake_home, tmp_path):
    secret = fake_home / "notes_secret.txt"
    secret.write_text("x")
    assert guard.is_blocked(str(secret))
    (tmp_path / "allow.txt").write_text(f"# kommentti\n{secret}\n")
    assert not guard.is_blocked(str(secret))


def test_normal_file_ok(fake_home):
    f = fake_home / "a.txt"
    f.write_text("x")
    assert guard.check_path(str(f)) == f.resolve()


# ── komennot: pitää toimia ───────────────────────────────────

@pytest.mark.parametrize("cmd", [
    "systemctl status ssh", "systemctl --user status foo",
    "systemctl list-units --type=service --no-pager",
    "systemctl list-units --type service",
    "ps aux", "ps -ef", "ps -eo pid,comm", "ps --sort=-pcpu -e",
    "ip addr show", "ip addr show eth0", "ip route", "ip -br addr show",
    "journalctl -n 20 -u ssh", "journalctl -b --no-pager",
    "df -h", "df -x tmpfs -h /", "free -h", "uptime", "whoami", "date -u",
    "stat -c %n /",
])
def test_allowed_commands(cmd):
    assert guard.parse_and_validate(cmd)[0] == cmd.split()[0]


# ── komennot: pitää estää ────────────────────────────────────

@pytest.mark.parametrize("cmd", [
    "ls -R ~",                    # rekursio kiertäisi polkusuojauksen
    "cat /dev/zero", "cat /etc/shadow", "cat ~/.ssh/id_rsa",
    "tail -f /var/log/syslog", "journalctl -f",
    "ip addr flush eth0", "ip addr add 1.2.3.4/24",
    "ip link set eth0 down",
    "systemctl restart ssh", "systemctl status ssh; id",
    "ls | cat", "ls > x", "ls $(id)", "cat ../etc/passwd",
    "rm -rf /", "sudo ls", "whoami extra", "uptime -p",
    "head -n", "ps -x",
])
def test_blocked_commands(cmd):
    with pytest.raises(AccessDenied):
        guard.parse_and_validate(cmd)


def test_path_token_is_resolved(fake_home):
    f = fake_home / "real.txt"
    f.write_text("x")
    link = fake_home / "link.txt"
    link.symlink_to(f)
    tokens = guard.parse_and_validate(f"cat {link}")
    assert tokens == ["cat", str(f.resolve())]


def test_too_many_tokens():
    with pytest.raises(AccessDenied):
        guard.parse_and_validate("ls " + " ".join(["a"] * 30))
