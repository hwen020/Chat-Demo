import hashlib
import logging
import os
import secrets
import time
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import text

from chatflow_shared.schemas import Credentials

log = logging.getLogger("uvicorn.error.chatflow")
passwords = PasswordHasher()
dummy_hash = passwords.hash(secrets.token_urlsafe(32))
MAX_BODY = 32768

def query(conn, sql, **params):
    return conn.execute(text(sql), params)

def row(conn, sql, **params):
    return query(conn, sql, **params).mappings().first()

def rows(conn, sql, **params):
    return query(conn, sql, **params).mappings().all()

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def consume(conn, bucket, maximum):
    window = int(time.time() // 60)
    hit = query(conn, """INSERT INTO rate_limits VALUES (:bucket,:window,1)
                         ON CONFLICT (bucket,minute_bucket) DO UPDATE SET used=rate_limits.used+1
                         WHERE rate_limits.used < :maximum RETURNING used""",
                bucket=bucket, window=window, maximum=maximum).first()
    if not hit:
        raise HTTPException(429, "rate_limited", headers={"Retry-After": str(60 - int(time.time()) % 60)})

def install_auth(app, engine, cookie):
    COOKIE = cookie
    SECURE_COOKIE = os.getenv("COOKIE_SECURE", "1") == "1"
    ORIGINS = frozenset(filter(None, (origin.strip() for origin in os.getenv(
        "APP_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","))))

    def error(status, code, headers=None):
        return JSONResponse({"error": {"code": code}}, status_code=status, headers=headers)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return error(exc.status_code, exc.detail, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return error(422, "invalid_input")

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        log.error("database request failed")
        return error(503, "database_unavailable")

    @app.exception_handler(Exception)
    async def server_error(request, exc):
        log.error("request failed error_type=%s", type(exc).__name__)
        return error(500, "internal_error")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        identifier = uuid4().hex
        start = time.monotonic()
        if request.method in {"POST", "PATCH", "DELETE"}:
            if request.headers.get("origin") not in ORIGINS:
                response = error(403, "origin_denied")
            else:
                length = request.headers.get("content-length")
                if request.method in {"POST", "PATCH"} and length is None:
                    response = error(411, "length_required")
                elif length and (not length.isdecimal() or int(length) > MAX_BODY):
                    response = error(413, "body_too_large")
                else:
                    response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = identifier
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/v1/") and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        log.info("request=%s method=%s status=%s ms=%d", identifier, request.method,
                 response.status_code, (time.monotonic() - start) * 1000)
        return response

    def auth_limit(request, email):
        address = request.client.host if request.client else "unknown"
        with engine.begin() as conn:
            consume(conn, "auth:ip:" + digest(address), 20)
            consume(conn, "auth:account:" + digest(email), 8)

    def new_session(conn, response, user_id):
        token = secrets.token_urlsafe(32)
        query(conn, """INSERT INTO auth_sessions VALUES (:token,:user,now()+interval '7 days')""",
              token=digest(token), user=user_id)
        response.set_cookie(COOKIE, token, httponly=True, secure=SECURE_COOKIE,
                            samesite="lax", max_age=7 * 86400, path="/")

    def user(request: Request):
        token = request.cookies.get(COOKIE)
        if token and len(token) <= 128:
            with engine.connect() as conn:
                account = row(conn, """
                    SELECT u.id,u.email FROM auth_sessions s JOIN users u ON u.id=s.user_id
                    WHERE s.token_hash=:token AND s.expires_at>now()""", token=digest(token))
                if account:
                    return dict(account)
        raise HTTPException(401, "authentication_required")

    @app.post("/v1/auth/register", status_code=201)
    def register(body: Credentials, request: Request, response: Response):
        auth_limit(request, body.email)
        identity = uuid4()
        password_hash = passwords.hash(body.password)
        with engine.begin() as conn:
            inserted = query(conn, """INSERT INTO users(id,email,password_hash) VALUES (:id,:email,:hash)
                                      ON CONFLICT (email) DO NOTHING RETURNING id""",
                             id=identity, email=body.email, hash=password_hash).first()
            if not inserted:
                raise HTTPException(409, "account_exists")
            new_session(conn, response, identity)
        return {"id": identity, "email": body.email}

    @app.post("/v1/auth/login")
    def login(body: Credentials, request: Request, response: Response):
        auth_limit(request, body.email)
        with engine.connect() as conn:
            account = row(conn, "SELECT * FROM users WHERE email=:email", email=body.email)
        try:
            passwords.verify(account["password_hash"] if account else dummy_hash, body.password)
        except VerificationError:
            raise HTTPException(401, "invalid_credentials") from None
        if not account:
            raise HTTPException(401, "invalid_credentials")
        with engine.begin() as conn:
            new_session(conn, response, account["id"])
        return {"id": account["id"], "email": account["email"]}

    @app.post("/v1/auth/logout", status_code=204)
    def logout(request: Request):
        token = request.cookies.get(COOKIE)
        if token and len(token) <= 128:
            with engine.begin() as conn:
                query(conn, "DELETE FROM auth_sessions WHERE token_hash=:token", token=digest(token))
        response = Response(status_code=204)
        response.delete_cookie(COOKIE, path="/", secure=SECURE_COOKIE, httponly=True, samesite="lax")
        return response

    @app.get("/v1/me")
    def identity(account=Depends(user)):
        return account

    return user, ORIGINS
