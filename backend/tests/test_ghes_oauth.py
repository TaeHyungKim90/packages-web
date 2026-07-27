from app.services.ghes_oauth import build_authorize_url


def test_build_authorize_url(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "github_base_url", "https://github.sk-inc.com")
    monkeypatch.setattr(settings, "github_oauth_client_id", "abc")
    monkeypatch.setattr(
        settings,
        "oauth_redirect_uri",
        "http://localhost:5173/api/auth/callback",
    )

    url = build_authorize_url(state="xyz")
    assert url.startswith("https://github.sk-inc.com/login/oauth/authorize?")
    assert "client_id=abc" in url
    assert "state=xyz" in url
    assert "scope=read%3Auser" in url or "scope=read:user" in url
