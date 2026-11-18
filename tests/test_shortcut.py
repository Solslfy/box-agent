import subprocess

import pytest

from box_agent.shortcut import SHORTCUT_NAME, ensure_shortcut


class FakeRun:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __call__(self, cmd, env, **kw):
        self.calls.append((cmd, env))
        if self.fail:
            raise subprocess.CalledProcessError(1, cmd)
        open(env["BA_LNK"], "w").close()  # simulate PowerShell saving the .lnk


@pytest.fixture
def paths(tmp_path):
    return tmp_path / "Programs", tmp_path / "marker.txt", tmp_path / "app" / "BoxAgent.exe"


def test_creates_shortcut_pointing_at_exe(paths):
    lnk_dir, marker, exe = paths
    run = FakeRun()
    assert ensure_shortcut(exe, lnk_dir=lnk_dir, marker=marker, run=run)
    cmd, env = run.calls[0]
    # absolute System32 path: a powershell.exe planted next to the app must not run
    assert cmd[0].lower().endswith(r"\system32\windowspowershell\v1.0\powershell.exe")
    # paths travel via env vars, never spliced into the script text
    assert str(exe) not in " ".join(cmd)
    assert env["BA_LNK"] == str(lnk_dir / SHORTCUT_NAME)
    assert env["BA_TARGET"] == str(exe)
    assert env["BA_DIR"] == str(exe.parent)
    assert marker.read_text(encoding="utf-8") == str(exe)


def test_skips_when_up_to_date(paths):
    lnk_dir, marker, exe = paths
    ensure_shortcut(exe, lnk_dir=lnk_dir, marker=marker, run=FakeRun())
    run = FakeRun()
    assert not ensure_shortcut(exe, lnk_dir=lnk_dir, marker=marker, run=run)
    assert run.calls == []


def test_rewrites_when_exe_moved(paths):
    lnk_dir, marker, exe = paths
    ensure_shortcut(exe, lnk_dir=lnk_dir, marker=marker, run=FakeRun())
    moved = exe.parent.parent / "elsewhere" / "BoxAgent.exe"
    run = FakeRun()
    assert ensure_shortcut(moved, lnk_dir=lnk_dir, marker=marker, run=run)
    assert run.calls[0][1]["BA_TARGET"] == str(moved)


def test_rewrites_when_user_deleted_shortcut(paths):
    lnk_dir, marker, exe = paths
    ensure_shortcut(exe, lnk_dir=lnk_dir, marker=marker, run=FakeRun())
    (lnk_dir / SHORTCUT_NAME).unlink()
    run = FakeRun()
    assert ensure_shortcut(exe, lnk_dir=lnk_dir, marker=marker, run=run)


def test_failure_leaves_no_marker(paths):
    lnk_dir, marker, exe = paths
    with pytest.raises(subprocess.CalledProcessError):
        ensure_shortcut(exe, lnk_dir=lnk_dir, marker=marker, run=FakeRun(fail=True))
    assert not marker.exists()
