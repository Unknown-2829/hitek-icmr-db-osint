# 🚀 Production Self-Hosting & Deployment Guide — HiTek & ICMR DB OSINT (Legacy v1)

This comprehensive guide details how to deploy, configure, secure, and maintain the self-hosted **HiTek + ICMR SQLite OSINT Engine** and cybernetic dark terminal web interface on a Linux Virtual Private Server (VPS) or dedicated bare-metal infrastructure.

---

## 🏛️ Architecture Overview

The Legacy v1 architecture is designed for high-concurrency, low-latency relational graph queries on a single machine:

```
[ Web Browser / Client ] ──────────────► [ HTTPS / Port 443 (Nginx) ]
                                                        │
                              ┌─────────────────────────┴─────────────────────────┐
                              │                                                   │
                              ▼                                                   ▼
                [ Static Frontend Assets ]                            [ Reverse Proxy pass ]
                  (/website/ index.html)                               (http://127.0.0.1:8000)
                                                                                  │
                                                                                  ▼
                                                                     [ Uvicorn ASGI Server ]
                                                                      (api.main:app, 2-4 workers)
                                                                                  │
                                                                                  ▼
                                                                     [ Asynchronous aiosqlite ]
                                                                      • WAL Mode (Write-Ahead)
                                                                      • 64 MB Page Cache
                                                                      • 2 GB MMAP I/O
                                                                                  │
                                                                                  ▼
                                                                     [ SQLite DB (/data/users.db) ]
                                                                      • idx_users_mobile
                                                                      • idx_icmr_mobile
                                                                      • idx_icmr_aadhar
```

---

## 🛠️ System Prerequisites

### 1. Hardware Recommendations
| Workload | CPU | RAM | Storage | Expected Lookup Latency |
| :--- | :--- | :--- | :--- | :--- |
| **Development / Testing** (< 100k rows) | 1 vCPU | 1 GB | Standard SSD | ~50–100 ms |
| **Standard Production** (1M–50M rows) | 2 vCPUs | 4 GB | NVMe SSD | ~20–60 ms |
| **High-Throughput Enterprise** (100M+ rows) | 4+ vCPUs | 8–16 GB | Direct-attached NVMe | ~10–40 ms |

> [!IMPORTANT]
> **Storage I/O Speed Matters**: SQLite performance during multi-hop BFS graph traversal is dominated by random read I/O. Using NVMe SSD storage instead of network-attached HDD increases query throughput by orders of magnitude.

### 2. Operating System & Software
- **OS**: Ubuntu 22.04 LTS / 24.04 LTS, Debian 12, or Rocky Linux 9 (64-bit architecture mandatory for 2 GB memory mapping).
- **Python**: 3.10, 3.11, 3.12, 3.13, or 3.14 (`python3 --version`).
- **Web Server**: Nginx 1.18+ with HTTP/2 support.
- **SSL**: Certbot with Nginx plugin for automated Let's Encrypt certificates.

---

## 📦 Step-by-Step Production VPS Setup

### Step 1: Provision Packages & Security Updates

Connect to your VPS via SSH and install the system dependencies:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git nginx certbot python3-certbot-nginx sqlite3 curl ufw
```

### Step 2: Create a Dedicated Unprivileged User

Never execute the OSINT API server or file access routines as the `root` superuser:

```bash
# Create system user 'hitek' with disabled login shell
sudo useradd -r -m -d /opt/hitek-osint -s /bin/false hitek

# Verify user creation
id hitek
```

### Step 3: Clone the Repository (`legacy-v1` Branch)

```bash
# Navigate to deployment directory
cd /opt/hitek-osint

# Clone the legacy-v1 branch as user hitek
sudo -u hitek git clone -b legacy-v1 https://github.com/Unknown-2829/hitek-icmr-db-osint.git .
```

### Step 4: Python Virtual Environment & Dependencies

```bash
# Initialize isolated Python environment
sudo -u hitek python3 -m venv venv

# Upgrade pip and install production dependencies
sudo -u hitek ./venv/bin/pip install --upgrade pip setuptools wheel
sudo -u hitek ./venv/bin/pip install -r requirements.txt
```

---

## 🗄️ Step 5: Database Setup & WAL Permissions

SQLite WAL (Write-Ahead Logging) mode requires write access to the database file **and** its containing directory to dynamically create temporary `-wal` (write journal) and `-shm` (shared-memory index) files during query execution.

```bash
# 1. Create dedicated data directory
sudo mkdir -p /data

# 2. Transfer or copy your database file to /data/users.db
# (Or use the synthetic test generator: sudo -u hitek ./venv/bin/python scripts/generate_sample_db.py)

# 3. Grant strict ownership to the unprivileged 'hitek' user
sudo chown -R hitek:hitek /data

# 4. Set directory and file permissions:
# 750 ensures hitek can read/write and create -wal/-shm files, while public users have no access
sudo chmod 750 /data
sudo chmod 660 /data/users.db
```

### Crucial Database Indexing

Run the following SQL commands to build the B-Tree indexes on your tables:

```bash
sudo -u hitek sqlite3 /data/users.db << 'EOF'
-- Set WAL mode permanently
PRAGMA journal_mode = WAL;

-- HiTek Telecom table index
CREATE INDEX IF NOT EXISTS idx_users_mobile ON users(mobile);

-- ICMR Healthcare & Aadhaar table indexes
CREATE INDEX IF NOT EXISTS idx_icmr_mobile ON icmr(mobile);
CREATE INDEX IF NOT EXISTS idx_icmr_aadhar ON icmr(aadhar);

-- Optimize internal database metadata
PRAGMA optimize;
EOF
```

Verify index coverage:
```bash
sudo -u hitek sqlite3 /data/users.db ".indices"
```

---

## ⚙️ Step 6: Configure Environment (`.env`)

Create the production `.env` file from `.env.example`:

```bash
sudo -u hitek cp .env.example .env
sudo -u hitek nano .env
```

Set your production settings:

```ini
# Database path
DB_PATH=/data/users.db

# Bind address (127.0.0.1 since Nginx acts as reverse proxy)
API_HOST=127.0.0.1
API_PORT=8000

# BFS Traversal Controls
MAX_RESULTS=25
MAX_GLOBAL_RESULTS=100
DEEP_SEARCH_DEPTH=3
DB_RETRY_ATTEMPTS=3
DB_RETRY_DELAY=0.5

# Rate Limiting (Protects from scraping & brute-force)
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=60
RATE_LIMIT_WINDOW_SECONDS=60
TRUSTED_PROXY_COUNT=1

# API Authentication (Optional: set true if private API key required)
API_AUTH_ENABLED=false
API_KEY=

# CORS Configuration
CORS_ORIGINS=*
```

Protect the `.env` file permissions:
```bash
sudo chmod 600 /opt/hitek-osint/.env
```

---

## 🛡️ Step 7: Systemd Service with Linux Security Sandboxing

Create a hardened systemd daemon service definition at `/etc/systemd/system/hitek-osint.service`:

```bash
sudo nano /etc/systemd/system/hitek-osint.service
```

Paste the following production configuration:

```ini
[Unit]
Description=HiTek & ICMR SQLite OSINT Engine Service
Documentation=https://github.com/Unknown-2829/hitek-icmr-db-osint/tree/legacy-v1
After=network.target

[Service]
Type=simple
User=hitek
Group=hitek
WorkingDirectory=/opt/hitek-osint
EnvironmentFile=/opt/hitek-osint/.env

# Execute Uvicorn with 2 workers (adjust based on CPU cores: 2-4 recommended)
ExecStart=/opt/hitek-osint/venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000 --workers 2

# Process Management
Restart=always
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=15
LimitNOFILE=65535

# ── Security Sandboxing Directives ──
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX

# Restrict Filesystem Access
ReadOnlyPaths=/opt/hitek-osint
ReadWritePaths=/tmp /data

[Install]
WantedBy=multi-user.target
```

Reload systemd, enable, and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hitek-osint
sudo systemctl status hitek-osint
```

Check the real-time service logs:
```bash
journalctl -u hitek-osint -n 50 --no-pager
```

---

## 🌐 Step 8: Nginx Reverse Proxy & Let's Encrypt SSL

### 1. Configure Nginx Virtual Host

Copy the provided production template:

```bash
sudo cp /opt/hitek-osint/nginx.conf.example /etc/nginx/sites-available/hitek-osint
sudo nano /etc/nginx/sites-available/hitek-osint
```

Update `server_name` to match your domain (e.g. `api.yourdomain.com`) or VPS public IP.

Enable the site and verify syntax:

```bash
sudo ln -sf /etc/nginx/sites-available/hitek-osint /etc/nginx/sites-enabled/
# Remove default site if present
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

### 2. Configure Firewall (UFW)

```bash
sudo ufw allow 22/tcp comment 'SSH'
sudo ufw allow 80/tcp comment 'HTTP'
sudo ufw allow 443/tcp comment 'HTTPS'
sudo ufw enable
```

### 3. Provision Free TLS/SSL Certificate with Certbot

```bash
sudo certbot --nginx -d api.yourdomain.com
```

Certbot will automatically configure HTTPS redirect and renew certificates via systemd timer.

---

## 💻 Step 9: Frontend Web Interface Deployment

You have two flexible options for hosting the cybernetic dark terminal web interface (`website/`):

### Option A: Served Directly by Nginx on the Same VPS

Uncomment the static website configuration block in your Nginx config (`/etc/nginx/sites-available/hitek-osint`):

```nginx
root /opt/hitek-osint/website;
index index.html;

location / {
    try_files $uri $uri/ /index.html;
}

location ~* \.(css|js|svg|png|jpg|ico)$ {
    expires 7d;
    add_header Cache-Control "public, no-transform";
}

location ~ ^/(api|health|docs|openapi.json) {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 30s;
}
```

Copy and edit `config.js`:
```bash
sudo -u hitek cp /opt/hitek-osint/website/config.example.js /opt/hitek-osint/website/config.js
```
Leave `API_BASE: ""` (relative path) or set to `"https://api.yourdomain.com"`.

Reload Nginx:
```bash
sudo nginx -t && sudo systemctl reload nginx
```

### Option B: Decoupled Serverless (Cloudflare Pages / GitHub Pages / Vercel)

1. Set `website/config.js`:
   ```javascript
   window.APP_CONFIG = {
     API_BASE: "https://api.yourdomain.com"
   };
   ```
2. Upload the `website/` directory to **Cloudflare Pages** or any static host.
3. In your VPS `.env`, ensure `CORS_ORIGINS` includes your frontend domain:
   ```ini
   CORS_ORIGINS=https://your-osint-portal.pages.dev
   ```
4. Restart the service: `sudo systemctl restart hitek-osint`.

---

## ✅ Step 10: Operational Verification & Health Checks

Run these diagnostic commands to verify all services:

### 1. Test Health Probe
```bash
curl -i https://api.yourdomain.com/health
```
*Expected*: `HTTP/2 200` with `"status": "healthy"`, `"database_connected": true`.

### 2. Test Root Capability Discovery
```bash
curl -i https://api.yourdomain.com/
```
*Expected*: Complete JSON capability document reporting engine status, page cache, and endpoint routing.

### 3. Test Multi-Hop Phone Query
```bash
curl -s "https://api.yourdomain.com/api/phone?number=9876543210&depth=3" | jq .
```

### 4. Test Multi-Hop Aadhaar Query
```bash
curl -s "https://api.yourdomain.com/api/aadhaar?uid=111122223333&depth=2" | jq .
```

---

## 🔧 Maintenance, Monitoring & Troubleshooting

### Viewing Real-Time Logs
```bash
# Follow application logs
journalctl -u hitek-osint -f

# Follow Nginx access logs
sudo tail -f /var/log/nginx/access.log

# Follow Nginx error logs
sudo tail -f /var/log/nginx/error.log
```

### Common Issues & Solutions

#### 1. `sqlite3.OperationalError: unable to open database file`
- **Cause**: User `hitek` does not have write permission to `/data/` directory or `/data/users.db`.
- **Fix**: Run `sudo chown -R hitek:hitek /data && sudo chmod 750 /data && sudo chmod 660 /data/users.db`.

#### 2. `503 Service Unavailable: Database connectivity degraded`
- **Cause**: Database file path in `.env` is incorrect or the database file is corrupted/unreadable.
- **Fix**: Check `DB_PATH` in `.env`, verify file exists (`ls -la /data/users.db`), and check `journalctl -u hitek-osint -n 50`.

#### 3. High CPU Usage or Slow Traversal Times (> 500ms)
- **Cause**: Missing database indexes on `mobile` or `aadhar` columns.
- **Fix**: Ensure `CREATE INDEX idx_users_mobile ON users(mobile)` and `CREATE INDEX idx_icmr_aadhar ON icmr(aadhar)` have executed.

#### 4. `429 Too Many Requests`
- **Cause**: Rate limit threshold reached for the calling IP address.
- **Fix**: If using an external reverse proxy (Cloudflare, etc.), ensure `TRUSTED_PROXY_COUNT` in `.env` is set correctly so client real IPs are accurately parsed from `X-Forwarded-For`.

---

## 📜 Credits & Maintenance

- **Developer**: [@Unknownlll2829](https://t.me/Unknownlll2829)
- **Telegram Support**: [Unknown Intelligence](https://t.me/Unknownlll2829)
- **GitHub Repository**: [Unknown-2829/hitek-icmr-db-osint](https://github.com/Unknown-2829/hitek-icmr-db-osint)
- **License**: MIT License
