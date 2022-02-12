"""Basic authentication with password only
"""

__author__ = "Rogier Steehouder"
__date__ = "2022-01-29"
__version__ = "2.0"

import base64
import binascii
import datetime
import getpass

from loguru import logger
from passlib.context import CryptContext
from starlette.authentication import (
    AuthCredentials,
    AuthenticationBackend,
    AuthenticationError,
    SimpleUser,
)
from starlette.responses import JSONResponse

from .config import cfg


def on_auth_error(request: "starlette.requests.Request", exc: Exception):
    """Authentication error"""
    return JSONResponse(
        {"error": str(exc)}, status_code=401, headers={"WWW-Authenticate": "Basic"}
    )


# See: https://www.starlette.io/authentication/
class BasicAuthBackend(AuthenticationBackend):
    """Basic single user authentication for Starlette"""

    context = CryptContext(["pbkdf2_sha256"])

    def __init__(self):
        self.logger = logger.bind(logtype="main.auth")

        pwd = cfg.get("security.password")
        if pwd is not None:
            cfg["security.hash"] = Security.context.hash(pwd)
            del cfg["security.password"]
            cfg.save()
            self.logger.info("New password hashed and saved")
        del pwd

        pwd_hash = cfg.get("security.hash")
        if pwd_hash is None:
            pwd = getpass.getpass()
            pwd_hash = self.context.hash(pwd)
            cfg["security.hash"] = pwd_hash
            cfg.save()
            self.logger.info("New password hashed and saved")

        self.hash = pwd_hash

    async def authenticate(self, conn):
        """Password middleware for Starlette"""
        if "Authorization" not in conn.headers:
            raise AuthenticationError("Basic Authorization required")

        auth = conn.headers["Authorization"]
        try:
            scheme, credentials = auth.split()
            if scheme.lower() != "basic":
                raise AuthenticationError("Basic Authorization required")
            decoded = base64.b64decode(credentials).decode("ascii")
        except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
            raise AuthenticationError("Invalid Authorization")

        username, _, password = decoded.partition(":")

        ok = self.context.verify(password, self.hash)
        if not ok:
            self.logger.warning("Invalid password")
            raise AuthenticationError("Invalid Authorization")
        if self.context.needs_update(self.hash):
            self.logger.warning("Hash needs update")

        return AuthCredentials(["authenticated"]), SimpleUser(username)
