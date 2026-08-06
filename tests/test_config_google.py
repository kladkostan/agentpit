from agentpit.config import Settings


def _settings(monkeypatch, **env):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings(_env_file=None)


def test_google_sign_in_is_off_by_default(monkeypatch):
    """Unset is the off switch — the app builds no verifier and the endpoint
    answers 503, rather than half-working."""
    assert _settings(monkeypatch).google_client_id == ""


def test_google_client_id_is_read_from_the_environment(monkeypatch):
    s = _settings(monkeypatch, GOOGLE_CLIENT_ID="123-abc.apps.googleusercontent.com")
    assert s.google_client_id == "123-abc.apps.googleusercontent.com"
