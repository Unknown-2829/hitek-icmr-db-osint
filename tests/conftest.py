"""
Pytest configuration for HiTek & ICMR OSINT (Legacy v1).
Ensures repository root is always in sys.path for test discovery.
"""

import sys
from pathlib import Path

# Add project root directory to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
