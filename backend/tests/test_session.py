from app.services.session import (
    SessionUser,
    dump_session,
    load_session,
    sign_oauth_state,
    verify_oauth_state,
)


def test_oauth_state_roundtrip():
    token = sign_oauth_state("nonce-abc")
    assert verify_oauth_state(token) == "nonce-abc"


def test_oauth_state_rejects_tamper():
    token = sign_oauth_state("nonce-abc")
    bad = token[:-4] + "xxxx"
    try:
        verify_oauth_state(bad)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_session_roundtrip():
    user = SessionUser(login="alice", name="Alice", avatar_url="https://example/a.png")
    token = dump_session(user)
    loaded = load_session(token)
    assert loaded.login == "alice"
    assert loaded.name == "Alice"
    assert loaded.avatar_url == "https://example/a.png"
