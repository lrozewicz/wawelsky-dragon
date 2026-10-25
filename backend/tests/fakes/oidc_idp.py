"""Fałszywy IdP OIDC — prawdziwy serwer HTTP, bo PyJWKClient używa urllib (brief T6)."""

import base64
import hashlib
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

_IDP_KID = "k1"
_OTHER_KID = "k2"


class _Handler(BaseHTTPRequestHandler):
    """Obsługa discovery, /jwks i /token; FakeIdP dostępny przez atrybut serwera."""

    def log_message(self, format: str, *args: object) -> None:
        """Wyciszenie logów serwera."""

    def _send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        idp: FakeIdP = self.server.idp
        path = urlsplit(self.path).path
        idp.requests.append(path)
        if path == "/.well-known/openid-configuration":
            issuer = idp.issuer
            self._send_json(
                200,
                {
                    "issuer": issuer,
                    "authorization_endpoint": issuer + "/auth",
                    "token_endpoint": issuer + "/token",
                    "jwks_uri": issuer + "/jwks",
                    "end_session_endpoint": issuer + "/logout",
                },
            )
        elif path == "/jwks":
            jwk = jwt.algorithms.RSAAlgorithm.to_jwk(idp.public_key(), as_dict=True)
            self._send_json(200, {"keys": [{**jwk, "kid": _IDP_KID, "alg": "RS256", "use": "sig"}]})
        else:
            self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        idp: FakeIdP = self.server.idp
        path = urlsplit(self.path).path
        idp.requests.append(path)
        length = int(self.headers.get("Content-Length", "0"))
        form = parse_qs(self.rfile.read(length).decode())
        if path != "/token":
            self._send_json(404, {"error": "not_found"})
            return
        grant = idp.grant_for(
            form.get("code", [""])[0],
            form.get("client_secret", [""])[0],
            form.get("code_verifier", [""])[0],
        )
        if grant is None:
            self._send_json(400, {"error": "invalid_grant"})
            return
        self._send_json(200, grant)


class FakeIdP:
    """Lokalny IdP OIDC na losowym porcie: discovery, JWKS, /token z PKCE (brief T6)."""

    client_id: str = "wawelsky-dragon"
    client_secret: str = "idp-secret"  # noqa: S105 — celowa atrapa sekretu IdP

    def __init__(self) -> None:
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.requests: list[str] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._port = 0
        self._grants: dict[str, dict[str, Any]] = {}

    @property
    def issuer(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    def public_key(self) -> rsa.RSAPublicKey:
        return self._key.public_key()

    def __enter__(self) -> "FakeIdP":
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.idp = self  # atrybut na trzonie serwera dla handlera
        self._server = server
        self._port = server.server_address[1]
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None

    def authorize(  # noqa: PLR0913 — parametry claimów z briefu
        self,
        auth_url: str,
        *,
        sub: str,
        email: str | None,
        email_verified: bool = True,
        roles: tuple[str, ...] = (),
        groups: tuple[str, ...] = (),
        id_overrides: dict[str, object] | None = None,
        sign_with_other_key: bool = False,
        alg_none: bool = False,
    ) -> tuple[str, str]:
        """Symuluje przekierowanie do IdP: zwraca (code, state) i zapamiętuje grant."""
        query = parse_qs(urlsplit(auth_url).query)
        state = query["state"][0]
        code = "code-" + secrets.token_urlsafe(12)
        self._grants[code] = {
            "nonce": query["nonce"][0],
            "code_challenge": query["code_challenge"][0],
            "redirect_uri": query["redirect_uri"][0],
            "sub": sub,
            "email": email,
            "email_verified": email_verified,
            "roles": list(roles),
            "groups": list(groups),
            "id_overrides": dict(id_overrides or {}),
            "sign_with_other_key": sign_with_other_key,
            "alg_none": alg_none,
        }
        return code, state

    def grant_for(
        self, code: str, client_secret: str, code_verifier: str
    ) -> dict[str, object] | None:
        """Walidacja wymiany kodu (PKCE + client_secret); None → invalid_grant (brief T6)."""
        grant = self._grants.pop(code, None)
        if grant is None or client_secret != self.client_secret:
            return None
        digest = hashlib.sha256(code_verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        if challenge != grant["code_challenge"]:
            return None
        now = int(time.time())  # IdP to zewnętrzny system — czas systemowy, nie FrozenClock
        claims: dict[str, Any] = {
            "iss": self.issuer,
            "aud": self.client_id,
            "sub": grant["sub"],
            "nonce": grant["nonce"],
            "iat": now,
            "exp": now + 300,
        }
        email = grant["email"]
        if email is not None:
            claims["email"] = email
            claims["email_verified"] = grant["email_verified"]
            claims["preferred_username"] = email.split("@", 1)[0]
        if grant["groups"]:
            claims["groups"] = list(grant["groups"])
        claims.update(grant["id_overrides"])
        if grant["alg_none"]:
            id_token = jwt.encode(claims, None, algorithm="none")
        else:
            id_token = self.sign(claims, other_key=bool(grant["sign_with_other_key"]))
        access_token = self.sign(
            {
                "iss": self.issuer,
                "sub": grant["sub"],
                "azp": self.client_id,
                "exp": now + 300,
                "iat": now,
                "realm_access": {"roles": list(grant["roles"])},
            }
        )
        return {
            "access_token": access_token,
            "id_token": id_token,
            "token_type": "Bearer",
        }

    def sign(self, claims: dict[str, object], *, other_key: bool = False) -> str:
        """RS256 z nagłówkiem kid; other_key — klucz spoza JWKS (podróbka)."""
        key = self.other_key if other_key else self._key
        return jwt.encode(
            claims,
            key,  # generate_private_key() zwraca RSAPrivateKey — pyjwt podpisuje bezpośrednio
            algorithm="RS256",
            headers={"kid": _OTHER_KID if other_key else _IDP_KID},
        )
