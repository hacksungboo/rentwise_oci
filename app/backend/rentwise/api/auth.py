"""데모 계정 세션 (명세 §3: 관리자1·직원3, 서버 역할 검사).

비밀번호는 환경변수로 주입하고 기동 시 PBKDF2 해시로만 메모리에 보관한다. 실제 업체 가입/권한 관리 UI는 범위 밖.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

from fastapi import Depends, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from rentwise.api.errors import ApiError
from rentwise.config import settings

COOKIE = "rw_session"
MAX_AGE = 12 * 3600
_ser = URLSafeTimedSerializer(settings.session_secret, salt="rentwise-session")


@dataclass(frozen=True)
class User:
    username: str
    role: str  # ADMIN | STAFF
    name: str
    employee_id: str | None

    def public(self) -> dict:
        return {"username": self.username, "role": self.role, "name": self.name, "employee_id": self.employee_id}


def _hash(pw: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 120_000)


def _load_accounts() -> dict[str, tuple[User, bytes, bytes]]:
    out = {}
    for raw in settings.demo_accounts.split(";"):
        parts = raw.strip().split(":")
        if len(parts) < 4:
            continue
        uname, pw, role, name = parts[:4]
        emp = parts[4] if len(parts) > 4 and parts[4] else None
        salt = os.urandom(16)
        out[uname] = (User(uname, role.upper(), name, emp), salt, _hash(pw, salt))
    return out


ACCOUNTS = _load_accounts()


def login(username: str, password: str, response: Response) -> User:
    acc = ACCOUNTS.get(username)
    if not acc or not hmac.compare_digest(_hash(password, acc[1]), acc[2]):
        raise ApiError(401, "INVALID_CREDENTIALS", "아이디 또는 비밀번호가 올바르지 않습니다.")
    user = acc[0]
    response.set_cookie(COOKIE, _ser.dumps(user.username), max_age=MAX_AGE, httponly=True,
                        secure=settings.cookie_secure, samesite="lax", path="/")
    return user


def logout(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def current_user(request: Request) -> User:
    token = request.cookies.get(COOKIE)
    if not token:
        raise ApiError(401, "UNAUTHENTICATED", "로그인이 필요합니다.")
    try:
        uname = _ser.loads(token, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired):
        raise ApiError(401, "UNAUTHENTICATED", "세션이 만료되었습니다. 다시 로그인해 주세요.")
    acc = ACCOUNTS.get(uname)
    if not acc:
        raise ApiError(401, "UNAUTHENTICATED", "로그인이 필요합니다.")
    return acc[0]


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "ADMIN":
        raise ApiError(403, "FORBIDDEN", "운영 책임자만 수행할 수 있습니다.")
    return user
