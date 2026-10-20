"""
Comprehensive Automated Test Suite — HiTek & ICMR SQLite OSINT Engine (Legacy v1)
Tests SchemaAdapter, DatabaseManager, BFS multi-hop graph traversal, and FastAPI endpoints.
"""

import asyncio
import os
import sqlite3
import pytest
from httpx import AsyncClient, ASGITransport

from api.config import DEEP_SEARCH_DEPTH, MAX_RESULTS
from api.database import DatabaseManager, SchemaAdapter
from api.main import app, normalize_query


@pytest.fixture(scope="module")
def sample_db_path(tmp_path_factory):
    """Create a temporary synthetic SQLite database with both HiTek and ICMR tables."""
    tmp_dir = tmp_path_factory.mktemp("db")
    db_file = str(tmp_dir / "test_osint.db")

    conn = sqlite3.connect(db_file)
    cur = conn.cursor()

    # Table 1: users (HiTek telecom schema with alt_mobile and circle)
    cur.execute("""
    CREATE TABLE users (
        name TEXT,
        father_name TEXT,
        mobile TEXT,
        alt_mobile TEXT,
        address TEXT,
        circle TEXT
    )
    """)

    # Table 2: icmr (ICMR COVID/Healthcare schema with aadhar, district, state, pincode)
    cur.execute("""
    CREATE TABLE icmr (
        patient_name TEXT,
        fathers_name TEXT,
        contact_no TEXT,
        uid TEXT,
        residential_address TEXT,
        district TEXT,
        state TEXT,
        pin_code TEXT
    )
    """)

    # Insert synthetic fixture records:
    # Cluster 1: Arun Patel
    # Phone: 9876543210 -> alt_mobile: 9811111111 (in users)
    # Phone: 9876543210 -> Aadhaar: 111122223333 (in icmr)
    cur.execute("""
    INSERT INTO users VALUES (
        'Arun Patel', 'Ramesh Patel', '9876543210', '9811111111',
        'House 12! Sector 4! Rohini', 'DELHI'
    )
    """)
    cur.execute("""
    INSERT INTO icmr VALUES (
        'Arun Patel', 'Ramesh Patel', '9876543210', '111122223333',
        'House 12, Sector 4, Rohini', 'North Delhi', 'Delhi', '110085'
    )
    """)

    # Linked via alt_mobile 9811111111 -> Sita Patel
    # Sita's Aadhaar: 999988887777 (in icmr)
    cur.execute("""
    INSERT INTO icmr VALUES (
        'Sita Patel', 'Arun Patel', '9811111111', '999988887777',
        'House 12, Sector 4, Rohini', 'North Delhi', 'Delhi', '110085'
    )
    """)

    # Standalone record: Vikram Singh
    cur.execute("""
    INSERT INTO users VALUES (
        'Vikram Singh', 'K Singh', '7000000001', NULL,
        'Bhopal MP', 'MADHYA PRADESH'
    )
    """)

    conn.commit()
    conn.close()
    return db_file


# ── Test 1: SchemaAdapter ──────────────────────────────────────────

def test_schema_adapter_matching():
    """Verify SchemaAdapter maps disparate column name variants into canonical categories."""
    cols_users = ["name", "father_name", "mobile", "alt_mobile", "address", "circle", "msisdn"]
    mapped_users = SchemaAdapter.analyze_table("users", cols_users)

    assert "mobile" in mapped_users["phone"]
    assert "msisdn" in mapped_users["phone"]
    assert "alt_mobile" in mapped_users["alt_phone"]
    assert "name" in mapped_users["name"]
    assert "father_name" in mapped_users["father"]
    assert "address" in mapped_users["address"]
    assert "circle" in mapped_users["circle"]

    cols_icmr = ["patient_name", "fathers_name", "contact_no", "uid", "residential_address", "district", "state", "pin_code", "adhar_no"]
    mapped_icmr = SchemaAdapter.analyze_table("icmr", cols_icmr)

    assert "contact_no" in mapped_icmr["phone"]
    assert "uid" in mapped_icmr["aadhaar"]
    assert "adhar_no" in mapped_icmr["aadhaar"]
    assert "patient_name" in mapped_icmr["name"]
    assert "fathers_name" in mapped_icmr["father"]
    assert "residential_address" in mapped_icmr["address"]
    assert "district" in mapped_icmr["district"]
    assert "state" in mapped_icmr["state"]
    assert "pin_code" in mapped_icmr["pincode"]


# ── Test 2: Input Normalization ────────────────────────────────────

def test_query_normalization():
    """Verify input normalization cleans prefixes and detects query types accurately."""
    assert normalize_query("+91 98765 43210") == ("9876543210", "phone")
    assert normalize_query("09876543210") == ("9876543210", "phone")
    assert normalize_query("0919876543210") == ("9876543210", "phone")
    assert normalize_query("1111-2222-3333") == ("111122223333", "aadhaar")
    assert normalize_query("918234567890") == ("918234567890", "aadhaar")
    assert normalize_query("+919182345678") == ("9182345678", "phone")
    assert normalize_query("91-9182345678") == ("9182345678", "phone")
    assert normalize_query("918234567890", hint="aadhaar") == ("918234567890", "aadhaar")
    assert normalize_query("919876543210", hint="phone") == ("9876543210", "phone")
    assert normalize_query("invalid_input") == (None, "invalid")
    assert normalize_query("12345") == (None, "invalid")


# ── Test 3: Database Engine & BFS Traversal ─────────────────────────

@pytest.mark.asyncio
async def test_database_bfs_traversal(sample_db_path):
    """
    Test symmetric BFS multi-hop graph traversal:
    Querying seed phone '9876543210' should traverse:
    Hop 0: seed 9876543210
    Hop 1: finds Arun Patel in users & icmr -> discovers alt_phone 9811111111 and Aadhaar 111122223333
    Hop 2: traverses alt_phone 9811111111 -> discovers Sita Patel and Aadhaar 999988887777
    """
    mgr = DatabaseManager(db_path=sample_db_path)
    await mgr.connect()
    assert mgr.is_ready is True
    assert "users" in mgr._table_maps
    assert "icmr" in mgr._table_maps

    # Test Phone Seed Traversal
    profile = await mgr.deep_search("9876543210", max_depth=3)

    assert profile["found"] is True
    assert profile["total_records"] >= 3
    assert "9876543210" in profile["phones"]
    assert "9811111111" in profile["phones"]
    assert "111122223333" in profile["aadhar_numbers"]
    assert "999988887777" in profile["aadhar_numbers"]
    assert "Arun Patel" in profile["names"]
    assert "Sita Patel" in profile["names"]
    assert "North Delhi" in profile["districts"]
    assert "DELHI" in profile["regions"]

    # Test Reverse Aadhaar Seed Traversal:
    # Starting with Sita's Aadhaar (999988887777) should discover phone 9811111111
    # which leads to Arun Patel (9876543210) and Aadhaar 111122223333
    profile_rev = await mgr.deep_search("999988887777", max_depth=3)
    assert profile_rev["found"] is True
    assert "999988887777" in profile_rev["aadhar_numbers"]
    assert "9811111111" in profile_rev["phones"]
    assert "9876543210" in profile_rev["phones"]
    assert "111122223333" in profile_rev["aadhar_numbers"]
    assert "Sita Patel" in profile_rev["names"]
    assert "Arun Patel" in profile_rev["names"]

    # Test not found
    profile_none = await mgr.deep_search("6999999999", max_depth=2)
    assert profile_none["found"] is False
    assert profile_none["total_records"] == 0

    await mgr.close()


# ── Test 4: FastAPI Endpoints ───────────────────────────────────────

@pytest.mark.asyncio
async def test_fastapi_endpoints(sample_db_path):
    """Test FastAPI /health, /api/lookup, and /api/stats endpoints."""
    # Wire the test DB to app database
    from api.database import db
    db.db_path = sample_db_path

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Health endpoint before/after connect
        await db.connect()
        app.state.db_ready = True

        health_resp = await client.get("/health")
        assert health_resp.status_code == 200
        health_data = health_resp.json()
        assert health_data["status"] == "healthy"
        assert health_data["database_connected"] is True
        assert health_data["tables_indexed"] >= 2
        # Verify sensitive internal filesystem path is not exposed on public health check
        assert "database_path" not in health_data

        # 2. Lookup by phone via ?q=
        resp_q = await client.get("/api/lookup?q=9876543210")
        assert resp_q.status_code == 200
        data_q = resp_q.json()
        assert data_q["success"] is True
        assert data_q["found"] is True
        assert "9876543210" in data_q["phones"]
        assert "111122223333" in data_q["aadhar_numbers"]

        # 3. Lookup by Aadhaar via ?aadhaar= alias
        resp_ad = await client.get("/api/lookup?aadhaar=111122223333")
        assert resp_ad.status_code == 200
        data_ad = resp_ad.json()
        assert data_ad["found"] is True
        assert "9876543210" in data_ad["phones"]

        # 4. Lookup by Aadhaar via ?number= alias (regression test for API-01)
        resp_num_ad = await client.get("/api/lookup?number=111122223333")
        assert resp_num_ad.status_code == 200
        data_num_ad = resp_num_ad.json()
        assert data_num_ad["found"] is True
        assert "9876543210" in data_num_ad["phones"]

        # 5. Lookup with depth parameter
        resp_depth = await client.get("/api/lookup?q=9876543210&depth=1")
        assert resp_depth.status_code == 200
        data_depth = resp_depth.json()
        assert data_depth["search_depth"] == 1

        # 6. Reject conflicting query parameters (regression test for API-02)
        resp_conflict = await client.get("/api/lookup?mobile=9876543210&aadhaar=111122223333")
        assert resp_conflict.status_code == 400
        assert resp_conflict.json()["detail"]["error"]["code"] == "CONFLICTING_PARAMETERS"

        # 7. Missing parameter
        resp_missing = await client.get("/api/lookup")
        assert resp_missing.status_code == 400
        assert resp_missing.json()["detail"]["error"]["code"] == "MISSING_QUERY"

        # 8. Invalid number format
        resp_inv = await client.get("/api/lookup?q=12345")
        assert resp_inv.status_code == 400
        assert resp_inv.json()["detail"]["error"]["code"] == "INVALID_FORMAT"

        # 9. Stats endpoint
        resp_stats = await client.get("/api/stats")
        assert resp_stats.status_code == 200
        stats_data = resp_stats.json()
        assert stats_data["database_ready"] is True
        assert "database_path" in stats_data
        assert "users" in stats_data["detected_tables"]
        assert stats_data["limits"]["max_results_per_table"] == MAX_RESULTS
        assert stats_data["limits"]["default_search_depth"] == DEEP_SEARCH_DEPTH

        await db.close()


@pytest.mark.asyncio
async def test_auth_and_degraded_service(sample_db_path):
    """Test optional API key authentication and 503 degraded service handling."""
    import api.main as main_mod
    from api.database import db
    db.db_path = sample_db_path

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test degraded service response (503 when db is not ready)
        app.state.db_ready = False
        db.is_ready = False
        degraded_resp = await client.get("/api/lookup?q=9876543210")
        assert degraded_resp.status_code == 503
        assert degraded_resp.json()["detail"]["error"]["code"] == "DATABASE_UNAVAILABLE"

        # Restore ready state
        await db.connect()
        app.state.db_ready = True

        # 2. Test API key authentication
        original_auth = main_mod.API_AUTH_ENABLED
        original_key = main_mod.API_KEY
        try:
            main_mod.API_AUTH_ENABLED = True
            main_mod.API_KEY = "super_secret_test_key"

            # Missing auth header -> 401
            resp_no_auth = await client.get("/api/lookup?q=9876543210")
            assert resp_no_auth.status_code == 401
            assert resp_no_auth.json()["detail"]["error"]["code"] == "UNAUTHORIZED"

            # Wrong key -> 401
            resp_bad_auth = await client.get("/api/lookup?q=9876543210", headers={"Authorization": "Bearer wrong_key"})
            assert resp_bad_auth.status_code == 401

            # Valid key via Bearer -> 200
            resp_valid_bearer = await client.get("/api/lookup?q=9876543210", headers={"Authorization": "Bearer super_secret_test_key"})
            assert resp_valid_bearer.status_code == 200

            # Valid key via X-API-Key -> 200
            resp_valid_x = await client.get("/api/lookup?q=9876543210", headers={"X-API-Key": "super_secret_test_key"})
            assert resp_valid_x.status_code == 200

        finally:
            main_mod.API_AUTH_ENABLED = original_auth
            main_mod.API_KEY = original_key
            await db.close()


# ── Test 5: Root Capability Document & Head Probe ───────────────────

@pytest.mark.asyncio
async def test_root_capability_document_and_head(sample_db_path):
    """Test GET / capability document, ReDoc disabled, and HEAD / keepalive probe."""
    from api.database import db
    db.db_path = sample_db_path
    await db.connect()
    app.state.db_ready = True

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Verify ReDoc is disabled
        assert app.redoc_url is None

        # 2. GET / capability document
        resp = await client.get("/")
        assert resp.status_code == 200
        assert resp.headers.get("Cache-Control") == "no-store"
        assert resp.headers.get("X-Powered-By") == "Phantom OSINT by @Unknownlll2829"

        doc = resp.json()
        assert doc["app"] == "HiTek & ICMR DB OSINT API"
        assert doc["status"] == "online"
        assert "engine" in doc
        assert doc["engine"]["database_connected"] is True
        assert doc["engine"]["tables_detected"] >= 2
        assert "page_cache_mb" in doc["engine"]
        assert "mmap_size_gb" in doc["engine"]
        assert "endpoints" in doc
        assert doc["endpoints"]["phone_lookup"] == "/api/phone?number={10_digit_mobile}&depth={1-5}"
        assert doc["endpoints"]["aadhaar_lookup"] == "/api/aadhaar?uid={12_digit_aadhaar}&depth={1-5}"
        assert doc["search_capabilities"]["data_masking"] is False
        assert doc["credits"]["developer"] == "@Unknownlll2829"

        # 3. HEAD / probe
        head_resp = await client.head("/")
        assert head_resp.status_code == 200
        assert head_resp.headers.get("Cache-Control") == "no-store"
        assert head_resp.headers.get("X-Powered-By") == "Phantom OSINT by @Unknownlll2829"
        assert not head_resp.content

    await db.close()


# ── Test 6: Dedicated Mobile & Aadhaar Endpoints ────────────────────

@pytest.mark.asyncio
async def test_dedicated_endpoints_and_hybrid_payload(sample_db_path):
    """Test dedicated /api/phone and /api/aadhaar endpoints with hybrid payload schema."""
    from api.database import db
    db.db_path = sample_db_path
    await db.connect()
    app.state.db_ready = True

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Dedicated Phone via query param ?number=
        resp_ph = await client.get("/api/phone?number=9876543210&depth=2")
        assert resp_ph.status_code == 200
        pdata = resp_ph.json()

        # Hybrid payload verification
        assert pdata["success"] is True
        assert pdata["found"] is True
        assert pdata["query"] == "9876543210"
        assert pdata["query_type"] == "phone"

        # Meta namespace
        assert "meta" in pdata
        assert pdata["meta"]["search_depth"] == 2
        assert pdata["meta"]["total_records"] >= 3
        assert pdata["meta"]["engine"] == "SQLite WAL"

        # Identity namespace (Zero data masking)
        assert "identity" in pdata
        assert "9876543210" in pdata["identity"]["primary_phones"]
        assert "111122223333" in pdata["identity"]["aadhaar_numbers"]
        assert "Arun Patel" in pdata["identity"]["names"]
        assert "Ramesh Patel" in pdata["identity"]["father_names"]

        # Location namespace
        assert "location" in pdata
        assert "North Delhi" in pdata["location"]["districts"]
        assert "Delhi" in pdata["location"]["states"]
        assert "110085" in pdata["location"]["pincodes"]

        # Telecom namespace
        assert "telecom" in pdata
        assert "DELHI" in pdata["telecom"]["circles"]

        # Top-level legacy keys retained for backwards compatibility
        assert "9876543210" in pdata["phones"]
        assert "111122223333" in pdata["aadhar_numbers"]
        assert "Arun Patel" in pdata["names"]
        assert "sources" in pdata
        assert pdata["credits"]["developer"] == "@Unknownlll2829"

        # 2. Dedicated Phone via path param /api/phone/{number}
        resp_ph_path = await client.get("/api/phone/9876543210")
        assert resp_ph_path.status_code == 200
        assert resp_ph_path.json()["found"] is True

        # 3. Dedicated Phone rejects invalid format and rejects Aadhaar UID
        resp_ph_bad = await client.get("/api/phone?number=111122223333")
        assert resp_ph_bad.status_code == 400
        assert resp_ph_bad.json()["detail"]["error"]["code"] == "INVALID_FORMAT"

        resp_ph_missing = await client.get("/api/phone")
        assert resp_ph_missing.status_code == 400
        assert resp_ph_missing.json()["detail"]["error"]["code"] == "MISSING_QUERY"

        # 4. Dedicated Aadhaar via query param ?uid=
        resp_ad = await client.get("/api/aadhaar?uid=111122223333&depth=2")
        assert resp_ad.status_code == 200
        adata = resp_ad.json()
        assert adata["success"] is True
        assert adata["found"] is True
        assert adata["query_type"] == "aadhaar"
        assert "111122223333" in adata["identity"]["aadhaar_numbers"]
        assert "9876543210" in adata["identity"]["primary_phones"]

        # 5. Dedicated Aadhaar via path param /api/aadhaar/{uid}
        resp_ad_path = await client.get("/api/aadhaar/111122223333")
        assert resp_ad_path.status_code == 200
        assert resp_ad_path.json()["found"] is True

        # 6. Dedicated Aadhaar rejects 10-digit mobile number and missing query
        resp_ad_bad = await client.get("/api/aadhaar?uid=9876543210")
        assert resp_ad_bad.status_code == 400
        assert resp_ad_bad.json()["detail"]["error"]["code"] == "INVALID_FORMAT"

        resp_ad_missing = await client.get("/api/aadhaar")
        assert resp_ad_missing.status_code == 400
        assert resp_ad_missing.json()["detail"]["error"]["code"] == "MISSING_QUERY"

    await db.close()
