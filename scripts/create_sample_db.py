"""
Helper script to generate a synthetic SQLite database for local testing and review.
"""

import os
import sqlite3

def generate_sample_database(output_path: str = "sample_test.db"):
    if os.path.exists(output_path):
        os.remove(output_path)

    conn = sqlite3.connect(output_path)
    cur = conn.cursor()

    # 1. HiTek Schema (users table)
    cur.execute("""
    CREATE TABLE users (
        name TEXT,
        father_name TEXT,
        mobile TEXT,
        alt_mobile TEXT,
        address TEXT,
        circle TEXT
    );
    """)

    # 2. ICMR Schema (icmr table)
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
    );
    """)

    # Indexes for sub-millisecond lookup
    cur.execute("CREATE INDEX idx_users_mobile ON users(mobile);")
    cur.execute("CREATE INDEX idx_users_alt ON users(alt_mobile);")
    cur.execute("CREATE INDEX idx_icmr_contact ON icmr(contact_no);")
    cur.execute("CREATE INDEX idx_icmr_uid ON icmr(uid);")

    # Linked Identity Cluster 1:
    # Arun Patel (9876543210) -> alt 9811111111 -> Aadhaar 111122223333
    cur.execute("""
    INSERT INTO users VALUES (
        'Arun Patel', 'Ramesh Patel', '9876543210', '9811111111',
        'House 42! Pocket B! Rohini Sector 15', 'DELHI'
    );
    """)
    cur.execute("""
    INSERT INTO icmr VALUES (
        'Arun Patel', 'Ramesh Patel', '9876543210', '111122223333',
        'House 42, Pocket B, Rohini Sector 15', 'North Delhi', 'Delhi', '110085'
    );
    """)

    # Linked Identity Cluster 2:
    # Sita Patel (9811111111) -> Aadhaar 999988887777 (linked to Arun via alt_mobile)
    cur.execute("""
    INSERT INTO icmr VALUES (
        'Sita Patel', 'Arun Patel', '9811111111', '999988887777',
        'House 42, Pocket B, Rohini Sector 15', 'North Delhi', 'Delhi', '110085'
    );
    """)

    # Linked Identity Cluster 3:
    # Vikram Sharma (9123456789) -> alt 9876543210 -> Aadhaar 444455556666 (linked to Arun via alt)
    cur.execute("""
    INSERT INTO users VALUES (
        'Vikram Sharma', 'Suresh Sharma', '9123456789', '9876543210',
        'Flat 302, Palm Grove! Bandra West', 'MUMBAI'
    );
    """)
    cur.execute("""
    INSERT INTO icmr VALUES (
        'Vikram Sharma', 'Suresh Sharma', '9123456789', '444455556666',
        'Flat 302, Palm Grove, Bandra West', 'Mumbai Suburban', 'Maharashtra', '400050'
    );
    """)

    conn.commit()
    conn.close()
    print(f"Sample test database generated at: {os.path.abspath(output_path)}")

if __name__ == "__main__":
    generate_sample_database()
