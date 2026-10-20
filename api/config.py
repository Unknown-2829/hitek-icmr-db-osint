"""
HiTek + ICMR DB OSINT (Legacy v1) — Central Configuration
Loads all runtime settings from environment variables or .env file.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# App Metadata
APP_NAME = "HiTek & ICMR DB OSINT API"
APP_VERSION = "1.2.0"
APP_ENV = os.getenv("APP_ENV", "production")

# Database Path
DB_PATH = os.getenv("DB_PATH", "/data/users.db")

# Server Binding
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))

# Search & Traversal Limits (Validated with sane bounds)
MAX_RESULTS = max(1, min(int(os.getenv("MAX_RESULTS", "25")), 500))                  # Max rows per individual table query
MAX_GLOBAL_RESULTS = max(1, min(int(os.getenv("MAX_GLOBAL_RESULTS", "100")), 2000))  # Global profile row ceiling
DEEP_SEARCH_DEPTH = max(1, min(int(os.getenv("DEEP_SEARCH_DEPTH", "3")), 5))         # Max BFS hops (1-5)
DB_RETRY_ATTEMPTS = max(1, min(int(os.getenv("DB_RETRY_ATTEMPTS", "3")), 10))
DB_RETRY_DELAY = max(0.1, min(float(os.getenv("DB_RETRY_DELAY", "0.5")), 10.0))

# VPS / Cloud SQLite Tuning (High-Performance Dedicated Server Settings)
SQLITE_CACHE_SIZE_KB = max(1000, int(os.getenv("SQLITE_CACHE_SIZE_KB", "64000")))         # ~64 MB
SQLITE_MMAP_SIZE_BYTES = max(0, int(os.getenv("SQLITE_MMAP_SIZE_BYTES", "2147483648")))   # 2 GB
SQLITE_SYNCHRONOUS = os.getenv("SQLITE_SYNCHRONOUS", "NORMAL").upper()

# Authentication (Optional — disabled by default for open self-hosting)
API_AUTH_ENABLED = os.getenv("API_AUTH_ENABLED", "false").lower() in ("true", "1", "yes")
API_KEY = os.getenv("API_KEY", "")

# Rate Limiting (In-memory sliding window per IP)
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() in ("true", "1", "yes")
RATE_LIMIT_REQUESTS = max(1, int(os.getenv("RATE_LIMIT_REQUESTS", "60")))
RATE_LIMIT_WINDOW_SECONDS = max(1, int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")))
TRUSTED_PROXY_COUNT = max(0, int(os.getenv("TRUSTED_PROXY_COUNT", "0")))

# CORS
raw_cors = os.getenv("CORS_ORIGINS", "*")
CORS_ORIGINS = [o.strip() for o in raw_cors.split(",") if o.strip()]
