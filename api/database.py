"""
Async SQLite Database Engine — Dual HiTek + ICMR Support
Optimized for high-speed local lookups with multi-hop symmetric BFS traversal.
Supports querying by 10-digit mobile number and 12-digit Aadhaar UID.
"""

import asyncio
import logging
import os
import re
import sqlite3
from functools import wraps
from typing import Any

import aiosqlite

from api.config import (
    DB_PATH,
    DB_RETRY_ATTEMPTS,
    DB_RETRY_DELAY,
    MAX_RESULTS,
    MAX_GLOBAL_RESULTS,
    DEEP_SEARCH_DEPTH,
    SQLITE_CACHE_SIZE_KB,
    SQLITE_MMAP_SIZE_BYTES,
    SQLITE_SYNCHRONOUS,
)

logger = logging.getLogger(__name__)


def retry_on_lock(func):
    """
    Retry decorator for SQLite concurrency locks.
    Exponential backoff on sqlite3.OperationalError ('locked' or 'busy').
    If all attempts are exhausted, the original exception is raised.
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        delay = DB_RETRY_DELAY
        last_exc: Exception | None = None
        for attempt in range(1, DB_RETRY_ATTEMPTS + 1):
            try:
                return await func(*args, **kwargs)
            except (sqlite3.OperationalError, aiosqlite.OperationalError) as e:
                last_exc = e
                err_msg = str(e).lower()
                if "locked" in err_msg or "busy" in err_msg:
                    logger.warning(
                        f"Database locked (attempt {attempt}/{DB_RETRY_ATTEMPTS}). "
                        f"Retrying in {delay:.2f}s..."
                    )
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    raise
        if last_exc:
            raise last_exc
        return None
    return wrapper


class SchemaAdapter:
    """
    Central schema discovery and canonicalization adapter.
    Normalizes arbitrary column names across heterogeneous SQLite tables
    (HiTek telecom tables, ICMR COVID/Aadhaar registries, or consolidated schemas).
    """

    PHONE_ALIASES = {
        "mobile", "phonenumber", "phone", "contact", "contactno", "contact_no",
        "cell", "mobilenumber", "mobile_no", "mobileno", "telephonenumber", "telephone",
        "msisdn", "phone_number"
    }
    ALT_PHONE_ALIASES = {
        "altmobile", "alt_mobile", "othernumber", "other_number", "altphone",
        "alt_phone", "secondarymobile", "secondary_mobile", "alternatenumber",
        "alternate_number", "alternatephone", "alternate_phone"
    }
    AADHAAR_ALIASES = {
        "aadharnumber", "aadhar", "aadhaar", "uid", "uidai", "aadhaarnumber",
        "aadharno", "aadhar_no", "aadhaarno", "aadhaar_no",
        "adhar", "adharno", "adhar_no", "adharnumber"
    }
    NAME_ALIASES = {
        "name", "fullname", "full_name", "customername", "customer_name",
        "username", "user_name", "beneficiaryname", "beneficiary_name",
        "patientname", "patient_name"
    }
    FATHER_ALIASES = {
        "fathersname", "fathers_name", "fathername", "father_name",
        "father", "careof", "care_of", "co", "c_o", "parentname", "parent_name", "guardian"
    }
    ADDRESS_ALIASES = {
        "address", "fulladdress", "full_address", "residentialaddress",
        "residential_address", "resaddress", "res_address", "addr",
        "permanentaddress", "permanent_address"
    }
    DISTRICT_ALIASES = {"district", "dist", "city"}
    STATE_ALIASES = {"state", "st", "province"}
    PINCODE_ALIASES = {"pincode", "pin_code", "pin", "postalcode", "postal_code", "zip"}
    CIRCLE_ALIASES = {"circle", "telecomcircle", "telecom_circle", "region", "operator"}

    @staticmethod
    def _clean_key(col: str) -> str:
        """Strip underscores, spaces, hyphens and lowercase."""
        return re.sub(r"[_\s\-]", "", col.lower())

    @classmethod
    def match_column(cls, col_name: str, alias_set: set[str]) -> bool:
        normalized = cls._clean_key(col_name)
        return normalized in alias_set or col_name.lower() in alias_set

    @classmethod
    def analyze_table(cls, table_name: str, raw_columns: list[str]) -> dict[str, list[str]]:
        """Map a table's actual column names to canonical schema categories."""
        mapping: dict[str, list[str]] = {
            "phone": [],
            "alt_phone": [],
            "aadhaar": [],
            "name": [],
            "father": [],
            "address": [],
            "district": [],
            "state": [],
            "pincode": [],
            "circle": [],
        }
        for col in raw_columns:
            cleaned = cls._clean_key(col)
            if cleaned in cls.PHONE_ALIASES:
                mapping["phone"].append(col)
            elif cleaned in cls.ALT_PHONE_ALIASES:
                mapping["alt_phone"].append(col)
            elif cleaned in cls.AADHAAR_ALIASES:
                mapping["aadhaar"].append(col)
            elif cleaned in cls.NAME_ALIASES:
                mapping["name"].append(col)
            elif cleaned in cls.FATHER_ALIASES:
                mapping["father"].append(col)
            elif cleaned in cls.ADDRESS_ALIASES:
                mapping["address"].append(col)
            elif cleaned in cls.DISTRICT_ALIASES:
                mapping["district"].append(col)
            elif cleaned in cls.STATE_ALIASES:
                mapping["state"].append(col)
            elif cleaned in cls.PINCODE_ALIASES:
                mapping["pincode"].append(col)
            elif cleaned in cls.CIRCLE_ALIASES:
                mapping["circle"].append(col)
        return mapping


def _quote_ident(ident: str) -> str:
    """Safely quote SQLite table or column identifier with double-quote escaping."""
    return '"' + str(ident).replace('"', '""') + '"'


class DatabaseManager:
    """Async SQLite manager with dynamic schema mapping and BFS relational graph search."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._table_maps: dict[str, dict[str, list[str]]] = {}
        self.is_ready = False

    async def connect(self):
        """Open connection with high-performance PRAGMA settings and inspect schemas."""
        logger.info(f"Opening SQLite database at {self.db_path}")
        if not os.path.isfile(self.db_path):
            logger.warning(f"SQLite file does not exist at '{self.db_path}'. Engine initialized in degraded mode.")
            self.is_ready = False
            return

        self._conn = await aiosqlite.connect(self.db_path, timeout=30)
        self._conn.row_factory = aiosqlite.Row

        # Performance tuning: execute each PRAGMA independently so failures don't cascade
        pragmas = [
            "PRAGMA journal_mode=WAL;",
            f"PRAGMA synchronous={SQLITE_SYNCHRONOUS};",
            "PRAGMA busy_timeout=10000;",
            f"PRAGMA cache_size=-{SQLITE_CACHE_SIZE_KB};",     # e.g. -64000 (~64MB memory cache)
            f"PRAGMA mmap_size={SQLITE_MMAP_SIZE_BYTES};",     # e.g. 2GB memory-mapped I/O
            "PRAGMA temp_store=MEMORY;",
            "PRAGMA query_only=ON;",
        ]
        for p in pragmas:
            try:
                await self._conn.execute(p)
            except Exception as e:
                logger.debug(f"Could not apply {p}: {e}")

        await self._inspect_schemas()
        if len(self._table_maps) > 0:
            self.is_ready = True
            logger.info(f"Database operational. Identified searchable tables/views: {list(self._table_maps.keys())}")
        else:
            self.is_ready = False
            logger.warning("Database connected but no searchable HiTek or ICMR tables were identified.")

    async def _inspect_schemas(self):
        """Inspect all user tables and views, and canonicalize column mappings."""
        self._table_maps.clear()
        try:
            async with self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%';"
            ) as cursor:
                tables = [row["name"] for row in await cursor.fetchall()]

            for t in tables:
                # Use safely quoted table name
                safe_table = _quote_ident(t)
                async with self.conn.execute(f"PRAGMA table_info({safe_table});") as cursor:
                    raw_cols = [row["name"] for row in await cursor.fetchall()]
                    mapping = SchemaAdapter.analyze_table(t, raw_cols)
                    # Only register tables that have at least one searchable column
                    if mapping["phone"] or mapping["alt_phone"] or mapping["aadhaar"]:
                        self._table_maps[t] = mapping
        except Exception as e:
            logger.warning(f"Schema inspection warning: {e}")

    async def close(self):
        if self._conn:
            await self._conn.close()
            self._conn = None
            self.is_ready = False

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    # ── Search Primitives with Safe Quoting ────────────────────────────

    @retry_on_lock
    async def search_by_mobile(self, mobile: str, limit: int = MAX_RESULTS) -> list[dict[str, Any]]:
        """Exact indexed lookup across all tables having phone or alt_phone columns."""
        results: list[dict[str, Any]] = []
        for table, schema in self._table_maps.items():
            cols_to_search = schema["phone"] + schema["alt_phone"]
            for col in cols_to_search:
                try:
                    query = f'SELECT * FROM {_quote_ident(table)} WHERE {_quote_ident(col)} = ? LIMIT ?'
                    async with self.conn.execute(query, (mobile, limit)) as cursor:
                        rows = await cursor.fetchall()
                        for r in rows:
                            d = dict(r)
                            d["_source_table"] = table
                            results.append(d)
                except Exception as e:
                    # Re-raise database lock/busy errors to trigger @retry_on_lock
                    if "lock" in str(e).lower() or "busy" in str(e).lower():
                        raise
                    logger.error(f"Error querying {table}.{col}: {e}")
        return results

    @retry_on_lock
    async def search_by_aadhar(self, aadhar: str, limit: int = MAX_RESULTS) -> list[dict[str, Any]]:
        """Exact indexed lookup across all tables having Aadhaar/UID columns."""
        results: list[dict[str, Any]] = []
        for table, schema in self._table_maps.items():
            for col in schema["aadhaar"]:
                try:
                    query = f'SELECT * FROM {_quote_ident(table)} WHERE {_quote_ident(col)} = ? LIMIT ?'
                    async with self.conn.execute(query, (aadhar, limit)) as cursor:
                        rows = await cursor.fetchall()
                        for r in rows:
                            d = dict(r)
                            d["_source_table"] = table
                            results.append(d)
                except Exception as e:
                    # Re-raise database lock/busy errors to trigger @retry_on_lock
                    if "lock" in str(e).lower() or "busy" in str(e).lower():
                        raise
                    logger.error(f"Error querying {table}.{col}: {e}")
        return results

    # ── Symmetric BFS Multi-Hop Relational Traversal ──────────────────

    async def deep_search(self, seed: str, max_depth: int = DEEP_SEARCH_DEPTH) -> dict[str, Any]:
        """
        Symmetric BFS multi-hop graph traversal.
        - Seed can be an Indian mobile number (10 digits) or Aadhaar UID (12 digits).
        - At each hop, discovered phones & Aadhaar numbers are queued for the next hop.
        - Symmetrically traverses phone -> aadhaar -> alt_numbers -> phone chains.
        - Uses deterministic canonical tuples for deduplication (no Python hash() collisions).
        """
        max_depth = max(1, min(max_depth, 5))
        digits = re.sub(r"\D", "", seed.strip())

        is_aadhar = len(digits) == 12
        visited_phones: set[str] = set()
        visited_aadhars: set[str] = set()

        phone_queue: list[str] = []
        aadhar_queue: list[str] = []

        if is_aadhar:
            aadhar_queue.append(digits)
        else:
            phone_queue.append(digits)

        all_rows: list[dict[str, Any]] = []
        seen_canonical_keys: set[tuple] = set()
        depth = 0
        truncated = False

        while (phone_queue or aadhar_queue) and depth < max_depth:
            next_phones: list[str] = []
            next_aadhars: list[str] = []

            # Process Phone Queue
            for phone in phone_queue:
                if phone in visited_phones:
                    continue
                visited_phones.add(phone)

                rows = await self.search_by_mobile(phone)
                for row in rows:
                    key = self._row_canonical_key(row)
                    if key in seen_canonical_keys:
                        continue
                    seen_canonical_keys.add(key)
                    all_rows.append(row)

                    if len(all_rows) >= MAX_GLOBAL_RESULTS:
                        truncated = True
                        break

                    # Symmetric discovery
                    for ad in self._extract_all_aadhars(row):
                        if ad not in visited_aadhars and ad not in next_aadhars:
                            next_aadhars.append(ad)

                    for alt in self._extract_all_phones(row):
                        if alt not in visited_phones and alt not in next_phones:
                            next_phones.append(alt)

                if truncated:
                    break

            if truncated:
                break

            # Process Aadhaar Queue
            for aadhar in aadhar_queue:
                if aadhar in visited_aadhars:
                    continue
                visited_aadhars.add(aadhar)

                rows = await self.search_by_aadhar(aadhar)
                for row in rows:
                    key = self._row_canonical_key(row)
                    if key in seen_canonical_keys:
                        continue
                    seen_canonical_keys.add(key)
                    all_rows.append(row)

                    if len(all_rows) >= MAX_GLOBAL_RESULTS:
                        truncated = True
                        break

                    # Symmetric discovery
                    for ph in self._extract_all_phones(row):
                        if ph not in visited_phones and ph not in next_phones:
                            next_phones.append(ph)

                    for ad in self._extract_all_aadhars(row):
                        if ad not in visited_aadhars and ad not in next_aadhars:
                            next_aadhars.append(ad)

                if truncated:
                    break

            phone_queue = next_phones
            aadhar_queue = next_aadhars
            depth += 1

            if truncated:
                break

        return self._build_profile(seed, all_rows, search_depth=depth, truncated=truncated)

    # ── Canonical Field Extraction Helpers ─────────────────────────────

    def _row_canonical_key(self, row: dict[str, Any]) -> tuple:
        """Deterministic tuple for row deduplication without hash randomization."""
        table = row.get("_source_table", "")
        phones = sorted(self._extract_all_phones(row))
        aadhars = sorted(self._extract_all_aadhars(row))
        name = self._extract_first_field(row, SchemaAdapter.NAME_ALIASES) or ""
        father = self._extract_first_field(row, SchemaAdapter.FATHER_ALIASES) or ""
        addr = self._extract_first_field(row, SchemaAdapter.ADDRESS_ALIASES) or ""
        clean_addr = re.sub(r"[\s!,.-]+", " ", addr).strip().lower()
        return (
            table,
            tuple(phones),
            tuple(aadhars),
            name.strip().lower(),
            father.strip().lower(),
            clean_addr,
        )

    def _extract_all_phones(self, row: dict[str, Any]) -> list[str]:
        """Extract all valid normalized 10-digit phone numbers from row."""
        found = set()
        table = row.get("_source_table")
        cols_to_check = []
        if table and table in self._table_maps:
            cols_to_check = self._table_maps[table]["phone"] + self._table_maps[table]["alt_phone"]
        else:
            cols_to_check = list(row.keys())

        for c in cols_to_check:
            val = row.get(c)
            if val is not None:
                # Handle possible multiple numbers delimited by slash, comma, or pipe
                parts = re.split(r"[/,;|]", str(val))
                for part in parts:
                    d = re.sub(r"\D", "", part)
                    if len(d) == 13 and d.startswith("091"):
                        d = d[3:]
                    elif len(d) == 12 and d.startswith("91") and d[2] in "6789":
                        d = d[2:]
                    elif len(d) == 11 and d.startswith("0") and d[1] in "6789":
                        d = d[1:]
                    if len(d) == 10 and d[0] in "6789":
                        found.add(d)
        return list(found)

    def _extract_all_aadhars(self, row: dict[str, Any]) -> list[str]:
        """Extract all valid 12-digit Aadhaar numbers from row."""
        found = set()
        table = row.get("_source_table")
        cols_to_check = []
        if table and table in self._table_maps:
            cols_to_check = self._table_maps[table]["aadhaar"]
        else:
            cols_to_check = list(row.keys())

        for c in cols_to_check:
            val = row.get(c)
            if val is not None:
                d = re.sub(r"\D", "", str(val))
                if len(d) == 12:
                    found.add(d)
        return list(found)

    def _extract_first_field(self, row: dict[str, Any], alias_set: set[str]) -> str | None:
        """Find the first matching non-empty column value from aliases."""
        for k, v in row.items():
            if k.startswith("_"):
                continue
            cleaned_k = SchemaAdapter._clean_key(k)
            if cleaned_k in alias_set and v is not None:
                s = str(v).strip()
                if s and s.lower() not in ("none", "null", "n/a", "-"):
                    return s
        return None

    def _clean_address(self, raw: str) -> str:
        """Normalize address separators and excessive punctuation."""
        if not raw:
            return ""
        s = re.sub(r"[!]+", ", ", raw)
        s = re.sub(r"[\s,]{2,}", ", ", s)
        return s.strip(", ").strip()

    def _build_profile(
        self,
        seed: str,
        rows: list[dict[str, Any]],
        search_depth: int = 1,
        truncated: bool = False,
    ) -> dict[str, Any]:
        """Consolidate rows across HiTek and ICMR into a clean unified response."""
        phones: list[str] = []
        other_numbers: list[str] = []
        aadhars: list[str] = []
        names: list[str] = []
        father_names: list[str] = []
        addresses: list[str] = []
        districts: list[str] = []
        states: list[str] = []
        pincodes: list[str] = []
        regions: list[str] = []

        seen_phones: set[str] = set()
        seen_others: set[str] = set()
        seen_aadhars: set[str] = set()
        seen_names: set[str] = set()
        seen_fathers: set[str] = set()
        seen_addresses: set[str] = set()
        seen_districts: set[str] = set()
        seen_states: set[str] = set()
        seen_pincodes: set[str] = set()
        seen_regions: set[str] = set()

        for row in rows:
            # Phones & Alternate numbers
            for ph in self._extract_all_phones(row):
                if ph not in seen_phones:
                    seen_phones.add(ph)
                    phones.append(ph)
                if ph != seed and ph not in seen_others:
                    seen_others.add(ph)
                    other_numbers.append(ph)

            # Aadhaar
            for ad in self._extract_all_aadhars(row):
                if ad not in seen_aadhars:
                    seen_aadhars.add(ad)
                    aadhars.append(ad)

            # Name
            name = self._extract_first_field(row, SchemaAdapter.NAME_ALIASES)
            if name and name not in seen_names:
                seen_names.add(name)
                names.append(name)

            # Father Name
            father = self._extract_first_field(row, SchemaAdapter.FATHER_ALIASES)
            if father and father not in seen_fathers:
                seen_fathers.add(father)
                father_names.append(father)

            # Address
            addr_raw = self._extract_first_field(row, SchemaAdapter.ADDRESS_ALIASES)
            if addr_raw:
                cleaned_addr = self._clean_address(addr_raw)
                if cleaned_addr and cleaned_addr not in seen_addresses:
                    seen_addresses.add(cleaned_addr)
                    addresses.append(cleaned_addr)

            # Location / Demographics (ICMR / HiTek)
            dist = self._extract_first_field(row, SchemaAdapter.DISTRICT_ALIASES)
            if dist and dist not in seen_districts:
                seen_districts.add(dist)
                districts.append(dist)

            st = self._extract_first_field(row, SchemaAdapter.STATE_ALIASES)
            if st and st not in seen_states:
                seen_states.add(st)
                states.append(st)

            pin = self._extract_first_field(row, SchemaAdapter.PINCODE_ALIASES)
            if pin:
                pin_digits = re.sub(r"\D", "", pin)
                if len(pin_digits) == 6 and pin_digits not in seen_pincodes:
                    seen_pincodes.add(pin_digits)
                    pincodes.append(pin_digits)

            reg = self._extract_first_field(row, SchemaAdapter.CIRCLE_ALIASES)
            if reg and reg not in seen_regions:
                seen_regions.add(reg)
                regions.append(reg)

        raw_tables = list(dict.fromkeys(r.get("_source_table") for r in rows if r.get("_source_table")))
        sources: list[str] = []
        for t in raw_tables:
            t_clean = t.lower()
            if any(k in t_clean for k in ("user", "hitek", "telecom", "phone")):
                if "hitek_telecom" not in sources:
                    sources.append("hitek_telecom")
            elif any(k in t_clean for k in ("icmr", "aadhar", "aadhaar", "demographic")):
                if "icmr_demographics" not in sources:
                    sources.append("icmr_demographics")
            else:
                if t not in sources:
                    sources.append(t)
        if not sources and len(rows) > 0:
            sources = ["hitek_telecom", "icmr_demographics"]

        return {
            "success": len(rows) > 0,
            "found": len(rows) > 0,
            "query": seed,
            "query_type": "aadhaar" if len(seed) == 12 else "phone",
            "meta": {
                "search_depth": search_depth,
                "total_records": len(rows),
                "truncated": truncated,
                "response_time_ms": 0,
                "engine": "SQLite WAL",
            },
            "identity": {
                "primary_phones": phones,
                "aadhaar_numbers": aadhars,
                "alternate_numbers": other_numbers,
                "names": names,
                "father_names": father_names,
            },
            "location": {
                "addresses": addresses,
                "districts": districts,
                "states": states,
                "pincodes": pincodes,
            },
            "telecom": {
                "circles": regions,
            },
            "phones": phones,
            "aadhar_numbers": aadhars,
            "other_numbers": other_numbers,
            "names": names,
            "father_names": father_names,
            "addresses": addresses,
            "districts": districts,
            "states": states,
            "pincodes": pincodes,
            "regions": regions,
            "sources": sources,
            "total_records": len(rows),
            "search_depth": search_depth,
            "truncated": truncated,
            "credits": {
                "developer": "@Unknownlll2829",
                "github": "https://github.com/Unknown-2829/hitek-icmr-db-osint",
            },
        }


# Singleton database manager instance
db = DatabaseManager()
