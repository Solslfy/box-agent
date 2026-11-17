import httpx
import pytest

from box_agent.updater import (
    RELEASES_URL,
    Release,
    check_latest,
    is_newer,
    parse_version,
    write_swap_script,
)

DL = "https://github.com/Solslfy/box-agent/releases/download/v0.2.0/BoxAgent.exe"
ASSET = {"name": "BoxAgent.exe", "browser_download_url": DL}


def client(status=200, body=None):
    def handler(request):
        assert str(request.url) == RELEASES_URL
        return httpx.Response(status, json=body or {})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_version():
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("0.10.0") == (0, 10, 0)


@pytest.mark.parametrize("bad", ["", "v1.2", "latest", "v1.2.x"])
def test_parse_invalid(bad):
    with pytest.raises(ValueError):
        parse_version(bad)


def test_is_newer():
    assert is_newer("v0.1.10", "0.1.9")
    assert not is_newer("v0.1.0", "0.1.0")
    assert not is_newer("v0.0.9", "0.1.0")
    assert not is_newer("garbage", "0.1.0")


def test_check_latest_newer():
    body = {"tag_name": "v0.2.0", "html_url": "https://page", "assets": [ASSET]}
    assert check_latest("0.1.0", http=client(body=body)) == Release(
        "0.2.0", DL, "https://page"
    )


def test_check_latest_rejects_foreign_download_url():
    asset = {"name": "BoxAgent.exe", "browser_download_url": "https://evil.example/BoxAgent.exe"}
    body = {"tag_name": "v0.2.0", "html_url": "p", "assets": [asset]}
    assert check_latest("0.1.0", http=client(body=body)) is None


def test_check_latest_same_version_none():
    body = {"tag_name": "v0.1.0", "html_url": "p", "assets": [ASSET]}
    assert check_latest("0.1.0", http=client(body=body)) is None


def test_check_latest_no_asset_none():
    body = {"tag_name": "v0.2.0", "html_url": "p", "assets": []}
    assert check_latest("0.1.0", http=client(body=body)) is None


def test_check_latest_http_error_none():
    assert check_latest("0.1.0", http=client(status=404)) is None


def test_swap_script_contents(tmp_path):
    new = tmp_path / "new.exe"
    target = tmp_path / "Box Agent" / "BoxAgent.exe"
    script = write_swap_script(4321, new, target, tmp_path / "swap.cmd")
    text = script.read_text()
    assert "PID eq 4321" in text
    assert str(new) in text and str(target) in text
    assert "move /Y" in text
    assert 'start ""' in text
