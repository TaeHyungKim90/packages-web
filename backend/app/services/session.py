from dataclasses import dataclass
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings

STATE_SALT = "oauth-state"
SESSION_SALT = "session-user"


@dataclass(frozen=True)
class SessionUser:
    login: str
    name: str | None = None
    avatar_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "login": self.login,
            "name": self.name,
            "avatar_url": self.avatar_url,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionUser":
        login = data.get("login")
        if not login:
            raise ValueError("session missing login")
        return cls(
            login=str(login),
            name=data.get("name"),
            avatar_url=data.get("avatar_url"),
        )


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt=salt)


def sign_oauth_state(nonce: str) -> str:
    return _serializer(STATE_SALT).dumps({"n": nonce})


def verify_oauth_state(token: str, *, max_age: int = 600) -> str:
    try:
        data = _serializer(STATE_SALT).loads(token, max_age=max_age)
    except SignatureExpired as exc:
        raise ValueError("oauth state expired") from exc
    except BadSignature as exc:
        raise ValueError("invalid oauth state") from exc
    nonce = data.get("n") if isinstance(data, dict) else None
    if not nonce:
        raise ValueError("oauth state missing nonce")
    return str(nonce)


def dump_session(user: SessionUser) -> str:
    return _serializer(SESSION_SALT).dumps(user.to_dict())


def load_session(token: str) -> SessionUser:
    try:
        data = _serializer(SESSION_SALT).loads(
            token,
            max_age=settings.session_max_age_seconds,
        )
    except SignatureExpired as exc:
        raise ValueError("session expired") from exc
    except BadSignature as exc:
        raise ValueError("invalid session") from exc
    if not isinstance(data, dict):
        raise ValueError("invalid session payload")
    return SessionUser.from_dict(data)
