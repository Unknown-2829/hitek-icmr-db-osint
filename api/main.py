"""
HiTek + ICMR DB OSINT (Legacy v1) — FastAPI Server
Self-hosted REST API for querying local SQLite HiTek & ICMR databases.
"""

import hmac
import logging
import re
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.config import (
    API_AUTH_ENABLED,
    API_HOST,
    API_KEY,
    API_PORT,
    APP_ENV,
    APP_NAME,
    APP_VERSION,
    CORS_ORIGINS,
    DEEP_SEARCH_DEPTH,
    MAX_GLOBAL_RESULTS,
    MAX_RESULTS,
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
    SQLITE_CACHE_SIZE_KB,
    SQLITE_MMAP_SIZE_BYTES,
    TRUSTED_PROXY_COUNT,
)
from api.database import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("api.main")


# ── Sliding-Window Rate Limiter ────────────────────────────────────
class SlidingWindowRateLimiter:
    """Thread-safe sliding-window rate limiter per client IP."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self._lock = threading.Lock()
        self._windows: dict[str, deque[float]] = defaultdict(deque)
        self._last_cleanup = time.monotonic()

    def is_allowed(self, ip: str) -> tuple[bool, int]:
        """Returns (is_allowed, retry_after_seconds)."""
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            # Throttled cleanup once every 60s if map grows large to prevent lock contention
            if now - self._last_cleanup > 60:
                self._last_cleanup = now
                if len(self._windows) > 200:
                    stale_keys = [k for k, timestamps in self._windows.items() if not timestamps or timestamps[-1] < cutoff]
                    for k in stale_keys:
                        del self._windows[k]

            q = self._windows[ip]
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self.limit:
                retry_after = int(q[0] + self.window - now) + 1
                return False, max(1, retry_after)
            q.append(now)
            return True, 0


rate_limiter = SlidingWindowRateLimiter(RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)


def get_client_ip(request: Request) -> str:
    """Extract real client IP, respecting configured trusted reverse proxies."""
    client_host = request.client.host if request.client else "127.0.0.1"

    # Only honor forwarding headers if TRUSTED_PROXY_COUNT > 0 AND
    # the immediate connecting peer is a trusted local reverse proxy (e.g. Nginx on localhost)
    is_local_proxy = client_host in ("127.0.0.1", "::1", "localhost")

    if TRUSTED_PROXY_COUNT > 0 and is_local_proxy:
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            parts = [p.strip() for p in forwarded.split(",") if p.strip()]
            if parts:
                idx = max(0, len(parts) - TRUSTED_PROXY_COUNT)
                return parts[idx]

    return client_host


def redact_identifier(val: str | None) -> str:
    """Mask sensitive phone/Aadhaar identifier for safe diagnostic logging."""
    if not val:
        return ""
    s = str(val).strip()
    if len(s) <= 4:
        return "*" * len(s)
    return s[:2] + "*" * (len(s) - 4) + s[-2:]


async def check_rate_limit(request: Request) -> None:
    """FastAPI dependency for rate limiting."""
    if not RATE_LIMIT_ENABLED:
        return
    ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(ip)
    if not allowed:
        logger.warning(f"Rate limit exceeded for IP: {ip}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": {
                    "code": "RATE_LIMITED",
                    "message": f"Too many requests. Please retry in {retry_after} seconds.",
                    "retry_after": retry_after,
                }
            },
            headers={"Retry-After": str(retry_after)},
        )


# ── Optional Authentication Dependency ─────────────────────────────
async def verify_auth(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> None:
    """Enforce API key if API_AUTH_ENABLED is turned on."""
    if not API_AUTH_ENABLED:
        return

    provided = None
    if authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    elif x_api_key:
        provided = x_api_key.strip()

    if not provided or not hmac.compare_digest(provided.encode(), API_KEY.strip().encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Valid API key required. Use Authorization: Bearer <key> or X-API-Key: <key>",
                }
            },
        )


# ── Lifespan Startup & Shutdown ────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager: connects SQLite and establishes stateful readiness."""
    app.state.db_ready = False
    try:
        await db.connect()
        app.state.db_ready = True
        logger.info(f"⚡ {APP_NAME} v{APP_VERSION} is operational.")
    except Exception as e:
        logger.error(f"Database connection error during boot: {e}. API marked as degraded.")
    yield
    await db.close()
    app.state.db_ready = False
    logger.info("Database connection closed. API gracefully shut down.")


# ── App Construction ───────────────────────────────────────────────
app = FastAPI(
    title=APP_NAME,
    description=(
        "## HiTek & ICMR DB OSINT API (Legacy v1)\n"
        "Self-hosted REST API for mobile number and Aadhaar intelligence lookup against local SQLite databases.\n\n"
        "- Supports 10-digit Indian mobile numbers and 12-digit Aadhaar UIDs\n"
        "- Symmetric multi-hop relational BFS link traversal\n"
        "- Central SchemaAdapter for arbitrary HiTek and ICMR table schemas\n"
        "- Deterministic deduplication, global result limits, and optional rate limiting\n"
    ),
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,  # Single unified documentation at /docs (ReDoc disabled)
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS if CORS_ORIGINS else ["*"],
    allow_credentials=True if CORS_ORIGINS != ["*"] else False,
    allow_methods=["GET", "OPTIONS", "HEAD"],
    allow_headers=["*"],
)


# ── Query Normalizer ───────────────────────────────────────────────
def normalize_query(raw: str, hint: str | None = None) -> tuple[str | None, str]:
    """
    Normalizes query input into either a 10-digit phone number or a 12-digit Aadhaar UID.
    Disambiguates between 12-digit Aadhaar starting with 91 and 10-digit mobile with +91 country prefix.
    Returns: (normalized_digits, query_type: 'phone' | 'aadhaar' | 'invalid')
    """
    if not raw or len(raw) > 30:
        return None, "invalid"

    stripped = raw.strip()
    digits = re.sub(r"[^\d]", "", stripped)
    if not digits:
        return None, "invalid"

    # Explicit Aadhaar hint
    if hint == "aadhaar":
        if len(digits) == 12:
            return digits, "aadhaar"
        return None, "invalid"

    # Explicit Phone hint
    if hint in ("phone", "mobile", "number"):
        if len(digits) == 13 and digits.startswith("091"):
            digits = digits[3:]
        elif len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        elif len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if len(digits) == 10 and digits[0] in "6789":
            return digits, "phone"
        return None, "invalid"

    # Auto-detection when no explicit hint:
    # Check for explicit phone indicators (+ prefix, leading 0, 091, or separator after 91)
    has_plus = stripped.startswith("+")
    has_sep_91 = bool(re.match(r"^91[\s\-\.]", stripped))

    if len(digits) == 13 and digits.startswith("091"):
        digits = digits[3:]
    elif len(digits) == 11 and digits.startswith("0") and digits[1] in "6789":
        digits = digits[1:]
    elif len(digits) == 12 and digits.startswith("91") and digits[2] in "6789" and (has_plus or has_sep_91):
        digits = digits[2:]

    # Valid 10-digit Indian mobile (starts with 6-9)
    if len(digits) == 10 and digits[0] in "6789":
        return digits, "phone"

    # Valid 12-digit Aadhaar UID
    if len(digits) == 12:
        return digits, "aadhaar"

    return None, "invalid"


# ── Shared Lookup Executor ─────────────────────────────────────────
async def _execute_lookup(clean_q: str, q_type: str, depth: int | None) -> JSONResponse:
    """Internal search runner ensuring unified timing, metadata, and error handling."""
    if not (getattr(app.state, "db_ready", False) and db.is_ready):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "DATABASE_UNAVAILABLE",
                    "message": "Database search engine is currently unavailable or unready.",
                }
            },
        )

    t0 = time.perf_counter()
    hops = depth if depth is not None else DEEP_SEARCH_DEPTH

    try:
        profile = await db.deep_search(clean_q, max_depth=hops)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        profile["query_type"] = q_type
        profile["response_time_ms"] = elapsed_ms
        if "meta" in profile and isinstance(profile["meta"], dict):
            profile["meta"]["response_time_ms"] = elapsed_ms
        return JSONResponse(content=profile)
    except Exception as e:
        logger.exception(f"Unhandled error during deep_search for query: {redact_identifier(clean_q)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "code": "DATABASE_ERROR",
                    "message": "An unexpected error occurred while executing the database search.",
                }
            },
        )


# ── Endpoints ──────────────────────────────────────────────────────

@app.get("/", tags=["System"])
async def root():
    """API Capability Document matching Phantom OSINT specification."""
    is_ready = getattr(app.state, "db_ready", False) and db.is_ready
    cache_mb = abs(SQLITE_CACHE_SIZE_KB) // 1000 if SQLITE_CACHE_SIZE_KB else 64
    mmap_gb = round(SQLITE_MMAP_SIZE_BYTES / (1024 ** 3), 1) if SQLITE_MMAP_SIZE_BYTES else 2.0
    env_str = f"vps-{APP_ENV}" if not APP_ENV.startswith("vps-") else APP_ENV

    content = {
        "app": APP_NAME,
        "version": APP_VERSION,
        "status": "online",
        "environment": env_str,
        "engine": {
            "type": "SQLite WAL (Asynchronous aiosqlite)",
            "database_connected": is_ready,
            "tables_detected": len(db._table_maps),
            "page_cache_mb": cache_mb,
            "mmap_size_gb": mmap_gb,
        },
        "endpoints": {
            "unified_lookup": "/api/lookup?q={number}&depth={1-5}",
            "phone_lookup": "/api/phone?number={10_digit_mobile}&depth={1-5}",
            "aadhaar_lookup": "/api/aadhaar?uid={12_digit_aadhaar}&depth={1-5}",
            "health": "/health",
            "stats": "/api/stats",
            "documentation": "/docs",
        },
        "search_capabilities": {
            "modes": ["auto", "phone", "aadhaar", "bfs"],
            "default_depth": DEEP_SEARCH_DEPTH,
            "max_depth": 5,
            "max_global_results": MAX_GLOBAL_RESULTS,
            "data_masking": False,
        },
        "credits": {
            "developer": "@Unknownlll2829",
            "github": "https://github.com/Unknown-2829/hitek-icmr-db-osint",
        },
    }
    return JSONResponse(
        content=content,
        headers={
            "Cache-Control": "no-store",
            "X-Powered-By": "Phantom OSINT by @Unknownlll2829",
        },
    )


@app.head("/", tags=["System"], include_in_schema=False)
async def root_head():
    """Fast header-only probe for uptime monitors."""
    return Response(
        status_code=200,
        headers={
            "Cache-Control": "no-store",
            "X-Powered-By": "Phantom OSINT by @Unknownlll2829",
        },
    )


@app.get("/health", tags=["System"])
async def health():
    """Stateful health check endpoint for uptime and container orchestration."""
    is_ready = getattr(app.state, "db_ready", False) and db.is_ready
    status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    content = {
        "status": "healthy" if is_ready else "degraded",
        "service": APP_NAME,
        "version": APP_VERSION,
        "database_connected": is_ready,
        "tables_indexed": len(db._table_maps),
        "rate_limiting": RATE_LIMIT_ENABLED,
        "auth_enabled": API_AUTH_ENABLED,
    }
    return JSONResponse(status_code=status_code, content=content)


@app.get(
    "/api/lookup",
    tags=["Lookup"],
    dependencies=[Depends(check_rate_limit), Depends(verify_auth)],
)
async def lookup(
    q: str | None = Query(None, description="10-digit Indian mobile number or 12-digit Aadhaar UID"),
    number: str | None = Query(None, description="Alias for q (legacy compatibility)"),
    aadhaar: str | None = Query(None, description="Explicit Aadhaar UID"),
    query: str | None = Query(None, description="Alias for q"),
    mobile: str | None = Query(None, description="Explicit 10-digit mobile number"),
    depth: int | None = Query(None, ge=1, le=5, description="Max BFS traversal hops (1-5)"),
):
    """
    Search by mobile number or Aadhaar UID with symmetric multi-hop relational BFS analysis.
    
    - Accepts: `q`, `number`, `aadhaar`, `query`, or `mobile`
    - Traverses linked identity chains across all detected HiTek & ICMR tables
    - Returns deduplicated JSON profile with all linked numbers, names, addresses, and regions
    """
    # Reject conflicting explicit parameters
    if mobile and aadhaar and mobile.strip() != aadhaar.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "CONFLICTING_PARAMETERS",
                    "message": "Conflicting parameters: specify either ?mobile= or ?aadhaar=, or use ?q= for unified search.",
                }
            },
        )

    raw_query = q or number or aadhaar or query or mobile
    if not raw_query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "MISSING_QUERY",
                    "message": "Missing required query parameter. Provide ?q=<number> or ?number=<number>",
                }
            },
        )

    # Only explicit mobile/aadhaar parameters impose hints; q, number, query remain generic
    hint = "aadhaar" if aadhaar else ("phone" if mobile else None)
    clean_q, q_type = normalize_query(raw_query, hint=hint)
    if not clean_q:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "INVALID_FORMAT",
                    "message": "Invalid query format. Enter a valid 10-digit Indian mobile number or 12-digit Aadhaar number.",
                }
            },
        )

    return await _execute_lookup(clean_q, q_type, depth)


@app.get(
    "/api/phone",
    tags=["Lookup"],
    dependencies=[Depends(check_rate_limit), Depends(verify_auth)],
)
@app.get(
    "/api/phone/{number}",
    tags=["Lookup"],
    dependencies=[Depends(check_rate_limit), Depends(verify_auth)],
)
async def phone_lookup(
    number: str | None = None,
    q: str | None = Query(None, description="10-digit Indian mobile number"),
    depth: int | None = Query(None, ge=1, le=5, description="Max BFS traversal hops (1-5)"),
):
    """
    Dedicated endpoint for 10-digit Indian mobile number intelligence search.
    Supports query param ?number=, ?q=, or path param /api/phone/{number}.
    """
    raw_query = number or q
    if not raw_query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "MISSING_QUERY",
                    "message": "Missing phone number parameter. Provide ?number=<10_digit_mobile> or path /api/phone/<number>",
                }
            },
        )

    clean_q, q_type = normalize_query(raw_query, hint="phone")
    if not clean_q or q_type != "phone":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "INVALID_FORMAT",
                    "message": "Invalid phone number format. Enter a valid 10-digit Indian mobile number starting with 6–9.",
                }
            },
        )

    return await _execute_lookup(clean_q, "phone", depth)


@app.get(
    "/api/aadhaar",
    tags=["Lookup"],
    dependencies=[Depends(check_rate_limit), Depends(verify_auth)],
)
@app.get(
    "/api/aadhaar/{uid}",
    tags=["Lookup"],
    dependencies=[Depends(check_rate_limit), Depends(verify_auth)],
)
async def aadhaar_lookup(
    uid: str | None = None,
    q: str | None = Query(None, description="12-digit Aadhaar UID"),
    depth: int | None = Query(None, ge=1, le=5, description="Max BFS traversal hops (1-5)"),
):
    """
    Dedicated endpoint for 12-digit Aadhaar UID demographic intelligence search.
    Supports query param ?uid=, ?q=, or path param /api/aadhaar/{uid}.
    """
    raw_query = uid or q
    if not raw_query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "MISSING_QUERY",
                    "message": "Missing Aadhaar UID parameter. Provide ?uid=<12_digit_aadhaar> or path /api/aadhaar/<uid>",
                }
            },
        )

    clean_q, q_type = normalize_query(raw_query, hint="aadhaar")
    if not clean_q or q_type != "aadhaar":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "INVALID_FORMAT",
                    "message": "Invalid Aadhaar UID format. Enter a valid 12-digit Aadhaar UID number.",
                }
            },
        )

    return await _execute_lookup(clean_q, "aadhaar", depth)


@app.get("/api/stats", tags=["System"], dependencies=[Depends(verify_auth)])
async def stats():
    """Database statistics and detected schema information."""
    return {
        "service": APP_NAME,
        "version": APP_VERSION,
        "database_path": db.db_path,
        "database_ready": getattr(app.state, "db_ready", False),
        "detected_tables": {
            t: {
                category: cols
                for category, cols in schema.items()
                if cols
            }
            for t, schema in db._table_maps.items()
        },
        "limits": {
            "max_results_per_table": MAX_RESULTS,
            "default_search_depth": DEEP_SEARCH_DEPTH,
        },
    }


# ── Entry Point ────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=False,
    )
