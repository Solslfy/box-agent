from box_agent.settings import DEFAULT_MODEL, Settings, load, save


def test_load_missing_returns_defaults(tmp_path):
    assert load(tmp_path / "x.json") == Settings()


def test_roundtrip(tmp_path):
    p = tmp_path / "sub" / "settings.json"
    save(Settings(max_steps=7), p)
    assert load(p).max_steps == 7


def test_unknown_and_missing_keys(tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"max_steps": 3, "bogus": 1}', encoding="utf-8")
    s = load(p)
    assert s.max_steps == 3
    assert s.model == DEFAULT_MODEL


def test_corrupt_json_returns_defaults(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{not json", encoding="utf-8")
    assert load(p) == Settings()


def test_api_key_not_in_json(tmp_path):
    p = tmp_path / "s.json"
    save(Settings(), p)
    text = p.read_text(encoding="utf-8")
    assert "api_key" not in text
    assert "openrouter" not in text.lower()
