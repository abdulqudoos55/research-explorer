import asyncio
import hashlib
import hmac
import secrets
import time
from collections import OrderedDict, deque

from fastapi import APIRouter, HTTPException, Request, Response
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/auth", tags=["Accounts"])

SITE = "https://research.37-27-39-68.sslip.io"
COOKIE = "research_session"
attempts = OrderedDict()


class Credentials(BaseModel):
    email: str = Field(
        min_length=3,
        max_length=254,
        pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$",
    )
    password: str = Field(min_length=12, max_length=128)


def check_origin(request: Request):
    if request.headers.get("origin") not in (
        SITE, "https://37.27.39.68:8002"
    ):
        raise HTTPException(403, "Please use the secure Research Explorer website.")


def throttle(request: Request):
    # Caddy supplies the real client address. Do not expose auth directly.
    address = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if not address:
        address = request.client.host if request.client else "unknown"
    now = time.monotonic()
    queue = attempts.setdefault(address, deque())
    attempts.move_to_end(address)
    while queue and queue[0] < now - 900:
        queue.popleft()
    if len(queue) >= 20:
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
    queue.append(now)
    while len(attempts) > 10000:
        attempts.popitem(last=False)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode(),
        salt=bytes.fromhex(salt),
        n=16384, r=8, p=1,
    ).hex()
    return salt + ":" + digest


def verify_password(password: str, stored: str) -> bool:
    salt, expected = stored.split(":", 1)
    actual = hashlib.scrypt(
        password.encode(),
        salt=bytes.fromhex(salt),
        n=16384, r=8, p=1,
    ).hex()
    return hmac.compare_digest(actual, expected)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def current_user(request: Request):
    token = request.cookies.get(COOKIE, "")
    if not token or len(token) > 200:
        raise HTTPException(401, "Please log in to use your reading list.")

    async with request.app.state.pool.connection() as connection:
        cursor = await connection.execute(
            """
            SELECT u.id, u.email
            FROM user_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = %s AND s.expires_at > NOW()
            """,
            (token_hash(token),),
        )
        user = await cursor.fetchone()

    if not user:
        raise HTTPException(401, "Your session has expired. Please log in.")
    return {"id": user[0], "email": user[1]}


async def create_session(request: Request, response: Response, user_id: int):
    token = secrets.token_urlsafe(32)
    old_token = request.cookies.get(COOKIE, "")

    async with request.app.state.pool.connection() as connection:
        await connection.execute(
            "DELETE FROM user_sessions WHERE expires_at <= NOW()"
        )
        if old_token:
            await connection.execute(
                "DELETE FROM user_sessions WHERE token_hash = %s",
                (token_hash(old_token),),
            )
        await connection.execute(
            """
            INSERT INTO user_sessions (token_hash, user_id, expires_at)
            VALUES (%s, %s, NOW() + INTERVAL '7 days')
            """,
            (token_hash(token), user_id),
        )

    response.set_cookie(
        COOKIE,
        token,
        secure=True,
        httponly=True,
        samesite="strict",
        max_age=7 * 24 * 60 * 60,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


@router.post("/signup")
async def signup(data: Credentials, request: Request, response: Response):
    check_origin(request)
    throttle(request)
    email = data.email.strip().lower()
    password_hash = await asyncio.to_thread(hash_password, data.password)

    try:
        async with request.app.state.pool.connection() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO users (email, password_hash)
                VALUES (%s, %s) RETURNING id
                """,
                (email, password_hash),
            )
            user_id = (await cursor.fetchone())[0]
    except UniqueViolation:
        raise HTTPException(409, "Unable to register this email. Try logging in.")

    await create_session(request, response, user_id)
    return {"email": email}


@router.post("/login")
async def login(data: Credentials, request: Request, response: Response):
    check_origin(request)
    throttle(request)

    async with request.app.state.pool.connection() as connection:
        cursor = await connection.execute(
            "SELECT id, email, password_hash FROM users WHERE email = %s",
            (data.email.strip().lower(),),
        )
        user = await cursor.fetchone()

    if user:
        valid = await asyncio.to_thread(
            verify_password, data.password, user[2]
        )
    else:
        await asyncio.to_thread(hash_password, data.password)
        valid = False

    if not valid:
        raise HTTPException(401, "Email or password is incorrect.")

    await create_session(request, response, user[0])
    return {"email": user[1]}


@router.get("/me")
async def me(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await current_user(request)


@router.post("/logout")
async def logout(request: Request, response: Response):
    check_origin(request)
    token = request.cookies.get(COOKIE, "")

    async with request.app.state.pool.connection() as connection:
        await connection.execute(
            "DELETE FROM user_sessions WHERE token_hash = %s",
            (token_hash(token),),
        )

    response.delete_cookie(
        COOKIE, path="/", secure=True, httponly=True, samesite="strict"
    )
    return {"status": "logged_out"}

