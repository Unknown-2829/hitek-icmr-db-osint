# HiTek & ICMR DB OSINT — Self-Hosted SQLite WAL Engine (Legacy v1)

A high-performance, asynchronous REST API and cybernetic dark terminal web interface engineered for multi-hop relational identity intelligence across self-hosted SQLite databases containing **HiTek (Telecom)** and **ICMR (Aadhaar & Demographics)** registries.

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![SQLite](https://img.shields.io/badge/SQLite-WAL%20Engine-003B57.svg?style=flat&logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat)](https://opensource.org/licenses/MIT)
[![Developer](https://img.shields.io/badge/Developer-%40Unknownlll2829-181717.svg?style=flat&logo=github&logoColor=white)](https://github.com/Unknown-2829)

> [!NOTE]
> **Looking for our Cloud Intelligence Portal?**
> The zero-database cloud client with live search across 2.5B+ records is available on the [`main` branch](https://github.com/Unknown-2829/hitek-icmr-db-osint/tree/main).
> The **`legacy-v1`** branch is the dedicated home for self-hosters running local SQLite databases on their own VPS or bare-metal infrastructure.

---

## ⚡ Architectural Highlights

- **Dual-Registry Relational Intelligence**: Bridges disparate databases — combining telecom-centric subscriber records (`users` / HiTek) with Aadhaar-linked demographic records (`icmr`).
- **Symmetric Multi-Hop BFS Engine**: Recursively traverses linked identity graphs across configurable search depths (1 to 5 hops):
  $$\text{Phone} \longleftrightarrow \text{Aadhaar UID} \longleftrightarrow \text{Alternate Number} \longleftrightarrow \text{Co-listed Identity}$$
- **High-Throughput SQLite WAL Engine**:
  - Full asynchronous I/O powered by `aiosqlite`.
  - `PRAGMA journal_mode = WAL` enabling non-blocking concurrent reads during background batch inserts.
  - `PRAGMA synchronous = NORMAL` for optimal balance of durability and write performance.
  - `PRAGMA cache_size = -64000` (64 MB memory page cache) and `PRAGMA mmap_size = 2147483648` (2 GB zero-copy OS page cache memory mapping) for ultra-low latency sub-50ms indexed lookups.
- **Dynamic `SchemaAdapter`**: Auto-detects and normalizes heterogenous column names (e.g., `mobile`, `phonenumber`, `aadhar`, `uid`, `fname`, `c_o`, `residential_address`, etc.) without manual migrations.
- **Cycle Prevention & Deterministic Deduplication**: Tracks visited nodes across all traversal hops to eliminate infinite loops and deduplicate identities cleanly without fragile hashing.
- **Dual-Format Hybrid JSON Payload**: Emits both consolidated flat arrays (`phones`, `aadhar_numbers`, `names`, `addresses`, `regions`) for backward compatibility with v1 clients and Telegram bots, alongside modern semantic nested objects (`identity`, `location`, `telecom`, `meta`) for v2 consumers.
- **Production-Grade VPS Safeguards**:
  - In-memory sliding-window rate limiting per client IP with reverse-proxy trust headers.
  - Safe SQL identifier quoting against table/column injection.
  - Internal error masking: sensitive stack traces and filesystem paths are never leaked to clients.
  - Optional API key authentication (`API_AUTH_ENABLED=true`).
- **Cybernetic Dark Terminal Web UI**: Decoupled, zero-build vanilla JS/CSS3/HTML5 frontend featuring JetBrains Mono typography, glassmorphism cards, live copy helpers, floating canvas particles, and toast notifications.

---

## 🔍 How Multi-Hop BFS Traversal Works

Traditional OSINT databases perform single-table lookups, missing secondary connections. The **Legacy v1 BFS Engine** connects identities across boundaries:

```
[ Seed Query: Phone (9876543210) OR Aadhaar (111122223333) ]
                              │
                              ▼
        ┌───────────────────────────────────────────┐
        │        HOP 1: Primary Index Lookup        │
        │ • Finds subscriber records                │
        │ • Extracts co-listed Aadhaar / Alt Phone   │
        └─────────────────────┬─────────────────────┘
                              │
                              ▼
        ┌───────────────────────────────────────────┐
        │      HOP 2: Cross-Registry Traversal      │
        │ • HiTek Alt Phone ◄──► ICMR Aadhaar UID   │
        │ • Discovers family members / co-habitants │
        └─────────────────────┬─────────────────────┘
                              │
                              ▼
        ┌───────────────────────────────────────────┐
        │       HOP 3..N: Extended Identity Graph   │
        │ • Uncovers additional SIMs & addresses    │
        │ • Halts at max depth or visited convergence│
        └───────────────────────────────────────────┘
```

---

## 🌐 API Reference

### 1. Root Capability Document & Discovery

Returns a machine-readable capability specification including operational status, memory-mapped I/O bounds, detected tables, and endpoint routing.

- **Method**: `GET /` or `HEAD /`
- **Headers Returned**: `Cache-Control: no-store`, `X-Powered-By: Phantom OSINT by @Unknownlll2829`

```bash
curl -i http://localhost:8000/
```

<details>
<summary><strong>View Example Response (200 OK)</strong></summary>

```json
{
  "app": "HiTek & ICMR DB OSINT API",
  "version": "1.2.0",
  "status": "online",
  "environment": "vps-production",
  "engine": {
    "type": "SQLite WAL (Asynchronous aiosqlite)",
    "database_connected": true,
    "tables_detected": 2,
    "page_cache_mb": 64,
    "mmap_size_gb": 2.0
  },
  "endpoints": {
    "unified_lookup": "/api/lookup?q={number}&depth={1-5}",
    "phone_lookup": "/api/phone?number={10_digit_mobile}&depth={1-5}",
    "aadhaar_lookup": "/api/aadhaar?uid={12_digit_aadhaar}&depth={1-5}",
    "health": "/health",
    "stats": "/api/stats",
    "documentation": "/docs"
  },
  "search_capabilities": {
    "modes": ["auto", "phone", "aadhaar", "bfs"],
    "default_depth": 3,
    "max_depth": 5,
    "max_global_results": 100,
    "data_masking": false
  },
  "credits": {
    "developer": "@Unknownlll2829",
    "github": "https://github.com/Unknown-2829/hitek-icmr-db-osint"
  }
}
```
</details>

---

### 2. Unified Multi-Mode Lookup

Auto-detects whether the query is a 10-digit Indian phone number or 12-digit Aadhaar UID and executes a multi-hop BFS graph traversal.

- **Endpoint**: `GET /api/lookup`
- **Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `q` | `string` | **Yes\*** | 10-digit mobile number or 12-digit Aadhaar UID. Auto-normalizes prefixes (`+91`, `091`, `0`, spaces, hyphens). |
| `number` | `string` | Optional | Legacy alias for `q` (backwards-compatible with v1 clients). |
| `aadhaar` | `string` | Optional | Explicit alias for `q` specifically for Aadhaar queries. |
| `depth` | `integer` | Optional | Maximum BFS relational hops (`1` to `5`, default: `3`). |

*\*At least one query parameter (`q`, `number`, or `aadhaar`) must be provided.*

#### Example Request:
```bash
curl "http://localhost:8000/api/lookup?q=9876543210&depth=3"
```

---

### 3. Dedicated Phone Lookup

Optimized endpoint strictly typed for mobile number queries.

- **Endpoint**: `GET /api/phone`
- **Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `number` | `string` | **Yes** | 10-digit Indian mobile number (e.g. `9876543210`). |
| `depth` | `integer` | Optional | BFS search depth (`1` to `5`, default: `3`). |

#### Example Request:
```bash
curl "http://localhost:8000/api/phone?number=9876543210&depth=3"
```

<details>
<summary><strong>View Example Response (200 OK)</strong></summary>

```json
{
  "success": true,
  "found": true,
  "query": "9876543210",
  "query_type": "phone",
  "meta": {
    "search_depth": 3,
    "total_records": 5,
    "truncated": false,
    "response_time_ms": 14,
    "engine": "SQLite WAL"
  },
  "identity": {
    "primary_phones": ["9811111111", "9876543210", "9123456789"],
    "aadhaar_numbers": ["111122223333", "999988887777"],
    "alternate_numbers": ["9811111111", "9123456789"],
    "names": ["Arun Patel", "Vikram Sharma"],
    "father_names": ["Ramesh Patel", "Suresh Sharma"]
  },
  "location": {
    "addresses": ["House 42, Pocket B, Rohini Sector 15", "Flat 302, Palm Grove, Bandra West"],
    "districts": ["North Delhi", "Mumbai Suburban"],
    "states": ["Delhi", "Maharashtra"],
    "pincodes": ["110085", "400050"]
  },
  "telecom": {
    "circles": ["DELHI", "MUMBAI"]
  },
  "phones": ["9811111111", "9876543210", "9123456789"],
  "aadhar_numbers": ["111122223333", "999988887777"],
  "other_numbers": ["9811111111", "9123456789"],
  "names": ["Arun Patel", "Vikram Sharma"],
  "father_names": ["Ramesh Patel", "Suresh Sharma"],
  "addresses": ["House 42, Pocket B, Rohini Sector 15", "Flat 302, Palm Grove, Bandra West"],
  "districts": ["North Delhi", "Mumbai Suburban"],
  "states": ["Delhi", "Maharashtra"],
  "pincodes": ["110085", "400050"],
  "regions": ["DELHI", "MUMBAI"],
  "sources": ["hitek_telecom", "icmr_demographics"],
  "total_records": 5,
  "search_depth": 3,
  "truncated": false,
  "credits": {
    "developer": "@Unknownlll2829",
    "github": "https://github.com/Unknown-2829/hitek-icmr-db-osint"
  },
  "response_time_ms": 14
}
```
</details>

---

### 4. Dedicated Aadhaar Lookup

Optimized endpoint strictly typed for Aadhaar UID queries.

- **Endpoint**: `GET /api/aadhaar`
- **Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `uid` | `string` | **Yes** | 12-digit Indian Aadhaar UID (e.g. `111122223333`). |
| `depth` | `integer` | Optional | BFS search depth (`1` to `5`, default: `3`). |

#### Example Request:
```bash
curl "http://localhost:8000/api/aadhaar?uid=111122223333&depth=2"
```

---

### 5. Service Health Probe

Stateful readiness check. Returns `200 OK` when operational, or `503 Service Unavailable` if database access is degraded.

- **Endpoint**: `GET /health`

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "healthy",
  "service": "HiTek & ICMR DB OSINT API",
  "version": "1.2.0",
  "database_connected": true,
  "tables_indexed": 2,
  "rate_limiting": true,
  "auth_enabled": false
}
```

---

### 6. Database & Schema Statistics

Returns detected tables, active row counts, and normalized column mappings introspected by `SchemaAdapter`.

- **Endpoint**: `GET /api/stats`

```bash
curl http://localhost:8000/api/stats
```

---

### 7. Interactive OpenAPI / Swagger UI

Interactive Swagger documentation is served at `/docs`. *(ReDoc has been intentionally disabled for speed and security)*.

- **URL**: `http://localhost:8000/docs`

---

## 🚀 Quick Start (Self-Hosting)

### 1. Requirements

- **Operating System**: Linux (Ubuntu 22.04+, Debian 12, Rocky Linux 9) or Windows / macOS for development.
- **Python**: 3.10 or higher (`python3 --version`).
- **Disk I/O**: Fast NVMe SSD strongly recommended for large datasets.
- **SQLite**: 3.35+ with WAL support.

### 2. Installation

```bash
# Clone the legacy-v1 branch
git clone -b legacy-v1 https://github.com/Unknown-2829/hitek-icmr-db-osint.git
cd hitek-icmr-db-osint

# Create and activate Python virtual environment
python3 -m venv venv
source venv/bin/activate       # On Windows: .\venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Environment Configuration

Copy the example configuration:
```bash
cp .env.example .env
nano .env                      # Or edit with your preferred editor
```

Key configuration variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `/data/users.db` | Absolute path to your SQLite database file. |
| `API_HOST` | `0.0.0.0` | IP interface to bind Uvicorn. |
| `API_PORT` | `8000` | Port for the API server. |
| `DEEP_SEARCH_DEPTH` | `3` | Default BFS traversal depth (1–5). |
| `MAX_RESULTS` | `25` | Maximum records per individual table query. |
| `MAX_GLOBAL_RESULTS` | `100` | Global record cap to prevent memory exhaustion. |
| `RATE_LIMIT_ENABLED` | `true` | In-memory sliding-window request throttling. |
| `RATE_LIMIT_REQUESTS`| `60` | Max requests per rate limit window. |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Sliding window duration in seconds. |
| `API_AUTH_ENABLED` | `false` | Enable API Key requirement (`X-API-Key` or `?api_key=`). |
| `API_KEY` | `""` | Secret API key if authentication is enabled. |
| `CORS_ORIGINS` | `*` | Allowed CORS origins (comma-separated or `*`). |

### 4. Running the Engine

Start the server using Uvicorn:
```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 2
```

Verify the server is running:
```bash
curl http://127.0.0.1:8000/health
```

---

## 🗄️ Database Preparation & Indexing

To achieve ultra-fast **sub-50ms** lookups across millions of records, create indexes on your database tables:

```sql
-- 1. Index HiTek / Telecom table on the mobile column
CREATE INDEX IF NOT EXISTS idx_users_mobile ON users(mobile);

-- 2. Index ICMR / Demographics table on BOTH mobile and Aadhaar columns
CREATE INDEX IF NOT EXISTS idx_icmr_mobile ON icmr(mobile);
CREATE INDEX IF NOT EXISTS idx_icmr_aadhar ON icmr(aadhar);
```

### Generate a Synthetic Test Database

Need to test your setup immediately without loading production data? Use the included sample database generator:

```bash
python scripts/generate_sample_db.py
```
This creates a populated `sample_test.db` with indexed cross-linked HiTek and ICMR records ready for testing.

---

## 💻 Cybernetic Dark Terminal UI

The static web application is housed in the `website/` folder. It requires **no build tools, no Node.js, and no bundlers**.

### Connecting Frontend to Your API:

1. Copy `website/config.example.js` to `website/config.js`:
   ```javascript
   window.APP_CONFIG = {
     API_BASE: "http://localhost:8000"  // Set to your VPS API URL or domain
   };
   ```
2. Open `website/index.html` in your web browser, or serve it via Nginx / Cloudflare Pages.

Features included in the frontend:
- **Interactive Mode Switching**: Unified Search, Phone Mode, and Aadhaar Mode.
- **Search Depth Slider**: Adjust BFS recursion on the fly (1 to 5 hops).
- **One-Click Copy Helpers**: Copy entire identity cards or individual identifiers to clipboard.
- **Toast Notifications & Particle Canvas**: Sleek feedback on lookups, network states, and copy actions.
- **Embedded API Documentation**: Full documentation interface available at `website/docs.html`.

For comprehensive instructions on deploying with Nginx, Systemd services, and free SSL certificates, refer to [DEPLOYMENT.md](DEPLOYMENT.md).

---

## 🧪 Automated Testing

A comprehensive test suite verifies schema adaptation, query normalization, multi-hop BFS graph traversal, endpoint responses, capability documents, and rate limiting:

```bash
pytest tests -v
```

All 7 integration tests run against an in-memory SQLite fixture and validate full engine stability.

---

## 📁 Repository Structure

```
hitek-icmr-db-osint/
├── api/
│   ├── __init__.py          # Package initialization
│   ├── config.py            # Environment & runtime configuration
│   ├── database.py          # Asynchronous SQLite WAL engine & BFS traversal
│   └── main.py              # FastAPI server & route handlers
├── website/
│   ├── index.html           # Dark terminal search interface
│   ├── docs.html            # Static API documentation explorer
│   ├── style.css            # Cyberpunk terminal styling & animations
│   ├── app.js               # Reactive frontend logic & API client
│   ├── config.example.js    # Client configuration template
│   └── favicon.svg          # Vector terminal icon
├── scripts/
│   └── generate_sample_db.py# Synthetic test database generator
├── tests/
│   └── test_legacy.py       # Integration & unit test suite
├── .env.example             # Example environment variables
├── .gitignore               # Git exclusion rules (ignores *.db, *.db-wal, etc.)
├── DEPLOYMENT.md            # Comprehensive VPS deployment & hardening guide
├── nginx.conf.example       # Hardened reverse-proxy configuration
├── requirements.txt         # Production Python dependencies
└── README.md                # Project documentation
```

---

## 🛡️ Security & Privacy Notice

- This software is engineered strictly for authorized open-source intelligence (OSINT) research, threat analysis, and educational purposes.
- Never expose unauthenticated endpoints containing sensitive personal data on the public internet without rate limiting, firewall controls, or API key authentication.
- Ensure your local SQLite databases comply with applicable regional privacy and data handling laws.

---

## 📜 Developer & Community

- **Developer**: [@Unknownlll2829](https://github.com/Unknown-2829)
- **GitHub Repository**: [Unknown-2829/hitek-icmr-db-osint](https://github.com/Unknown-2829/hitek-icmr-db-osint)
- **License**: [MIT License](LICENSE) — Feel free to fork, adapt, and build upon this work.
