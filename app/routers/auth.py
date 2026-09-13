import time
import uuid
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    create_refresh_token,
    get_current_user,
    get_password_hash,
    verify_password,
    verify_refresh_token,
)
from app.core.database import get_db
from app.core.logger import get_logger
from app.core.redis_client import get_redis_client
from app.middleware.security import log_audit_event
from app.models.user import User
from app.schemas.auth import RefreshTokenRequest, RegisterRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = get_logger("router.auth")

_IN_MEMORY_RATE_LIMITS: dict[str, list[float]] = defaultdict(list)


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def check_rate_limit(key: str, max_requests: int = 15, window_seconds: int = 60) -> bool:
    """
    Sliding window rate limiter.
    Uses Redis if available, falls back to in-memory dictionary.
    Returns True if allowed, False if rate limited.
    """
    now = time.time()
    try:
        redis = get_redis_client()
        r_key = f"ratelimit:{key}"
        pipe = redis.pipeline()
        pipe.zremrangebyscore(r_key, 0, now - window_seconds)
        pipe.zadd(r_key, {str(now): now})
        pipe.zcard(r_key)
        pipe.expire(r_key, window_seconds)
        results = await pipe.execute()
        count = results[2]
        return count <= max_requests
    except Exception:
        timestamps = _IN_MEMORY_RATE_LIMITS[key]
        cutoff = now - window_seconds
        _IN_MEMORY_RATE_LIMITS[key] = [t for t in timestamps if t > cutoff]
        _IN_MEMORY_RATE_LIMITS[key].append(now)
        return len(_IN_MEMORY_RATE_LIMITS[key]) <= max_requests


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    request: Request,
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    client_ip = get_client_ip(request)
    if not await check_rate_limit(f"register:{client_ip}", max_requests=10, window_seconds=60):
        log_audit_event("rate_limit_exceeded", actor=client_ip, details={"endpoint": "/auth/register"})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registration attempts. Please try again later.",
        )

    result = await db.execute(select(User).where(User.username == payload.username))
    existing_user = result.scalars().first()

    if existing_user:
        log_audit_event("registration_failed_duplicate", actor=payload.username, details={"client_ip": client_ip})
        raise HTTPException(status_code=400, detail="Username already registered")

    hashed_password = get_password_hash(payload.password)
    user_id = uuid.uuid4().hex

    new_user = User(
        user_id=user_id,
        username=payload.username,
        hashed_password=hashed_password,
    )
    db.add(new_user)
    await db.commit()

    log_audit_event("user_registered", actor=user_id, details={"username": payload.username, "client_ip": client_ip})
    return {"message": "User registered successfully", "user_id": user_id}


@router.post("/token", response_model=TokenResponse)
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    client_ip = get_client_ip(request)
    if not await check_rate_limit(f"login:{client_ip}", max_requests=15, window_seconds=60):
        log_audit_event("rate_limit_exceeded", actor=client_ip, details={"endpoint": "/auth/token"})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
        )

    result = await db.execute(select(User).where(User.username == form_data.username))
    user = result.scalars().first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        log_audit_event("login_failed_bad_credentials", actor=form_data.username, details={"client_ip": client_ip})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user.user_id})
    refresh_token = create_refresh_token(data={"sub": user.user_id})

    log_audit_event("login_success", actor=user.user_id, details={"username": user.username, "client_ip": client_ip})
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/refresh", response_model=TokenResponse)
async def refresh_access_token(
    request: Request,
    body: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    client_ip = get_client_ip(request)
    if not await check_rate_limit(f"refresh:{client_ip}", max_requests=30, window_seconds=60):
        log_audit_event("rate_limit_exceeded", actor=client_ip, details={"endpoint": "/auth/refresh"})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many token refresh attempts. Please try again later.",
        )

    user_id = verify_refresh_token(body.refresh_token)
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user.user_id})
    new_refresh_token = create_refresh_token(data={"sub": user.user_id})

    log_audit_event("token_refreshed", actor=user.user_id, details={"username": user.username})
    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

