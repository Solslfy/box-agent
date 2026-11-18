import hashlib

import httpx
import pytest

from box_agent.updater import (
    RELEASES_URL,
    Release,
    check_latest,
    download,
    is_newer,
    parse_sha_file,
    parse_version,
    verify_sha256,
    write_swap_script,
)

DL = "https://github.com/Solslfy/box-agent/releases/download/v0.2.0/BoxAgent.exe"
SHA = DL + ".sha256"
PAGE = "https://github.com/Solslfy/box-agent/releases/tag/v0.2.0"
ASSET = {"name": "BoxAgent.exe", "browser_download_url": DL}
SHA_ASSET = {"name": "BoxAgent.exe.sha256", "browser_download_url": SHA}


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
    body = {"tag_name": "v0.2.0", "html_url": "https://evil.example/", "assets": [ASSET, SHA_ASSET]}
    # page_url is built locally, never taken from the API response
    assert check_latest("0.1.0", http=client(body=body)) == Release("0.2.0", DL, PAGE, SHA)


def test_check_latest_rejects_foreign_download_url():
    asset = {"name": "BoxAgent.exe", "browser_download_url": "https://evil.example/BoxAgent.exe"}
    body = {"tag_name": "v0.2.0", "html_url": "p", "assets": [asset, SHA_ASSET]}
    assert check_latest("0.1.0", http=client(body=body)) is None


def test_check_latest_requires_checksum_asset():
    body = {"tag_name": "v0.2.0", "html_url": "p", "assets": [ASSET]}
    assert check_latest("0.1.0", http=client(body=body)) is None


def test_parse_sha_file():
    h = "a" * 64
    assert parse_sha_file(f"{h}  BoxAgent.exe\n") == h
    assert parse_sha_file(h.upper()) == h
    with pytest.raises(ValueError):
        parse_sha_file("not-a-hash")


def test_verify_sha256(tmp_path):
    f = tmp_path / "x.exe"
    f.write_bytes(b"hello")
    good = hashlib.sha256(b"hello").hexdigest()
    assert verify_sha256(f, good)
    assert not verify_sha256(f, "0" * 64)


def test_download_rejects_redirect_to_foreign_host(tmp_path):
    def handler(request):
        if request.url.host == "github.com":
            return httpx.Response(302, headers={"Location": "https://evil.example/x.exe"})
        return httpx.Response(200, content=b"bad")

    http = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    with pytest.raises(ValueError):
        download(DL, tmp_path / "new.exe", http=http)
    assert not (tmp_path / "new.exe").exists()


def test_download_follows_github_asset_redirect(tmp_path):
    def handler(request):
        if request.url.host == "github.com":
            return httpx.Response(302, headers={"Location": "https://release-assets.githubusercontent.com/a"})
        return httpx.Response(200, content=b"good")

    http = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    assert download(DL, tmp_path / "new.exe", http=http).read_bytes() == b"good"


def test_check_latest_same_version_none():
    body = {"tag_name": "v0.1.0", "html_url": "p", "assets": [ASSET, SHA_ASSET]}
    assert check_latest("0.1.0", http=client(body=body)) is None


def test_check_latest_no_asset_none():
    body = {"tag_name": "v0.2.0", "html_url": "p", "assets": []}
    assert check_latest("0.1.0", http=client(body=body)) is None


def test_check_latest_http_error_none():
    assert check_latest("0.1.0", http=client(status=404)) is None


def test_swap_script_contents(tmp_path):
    new = tmp_path / "new.exe"
    target = tmp_path / "Box Agent" / "BoxAgent.exe"
    script = write_swap_script([4321, 99], new, target, tmp_path / "swap.cmd")
    text = script.read_text()
    assert "PID eq 4321" in text and "PID eq 99" in text
    assert str(new) in text and str(target) in text
    assert "move /Y" in text
    # start the new exe only after a successful move; retry the move on failure
    assert text.index("if not errorlevel 1 goto moved") < text.index(":moved") < text.rindex('start ""')
    assert b"\r\r" not in script.read_bytes()  # cmd needs plain CRLF line endings
    assert "goto retry" in text
    assert "update failed" in text.lower()
