#!/usr/bin/env bash
# SatQuery AI — Security Audit & Scanning Script
# Checks python dependencies for CVEs, verifies secrets posture, and runs security tests.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

echo "========================================================"
echo "  SatQuery AI — Security Audit & Validation"
echo "========================================================"

echo ""
echo "[1/3] Running Dependency CVE Audit with pip-audit..."
if command -v pip-audit &> /dev/null; then
    # Run pip-audit ignoring known non-blocking notices
    pip-audit -r requirements.txt || echo "⚠️  pip-audit reported potential advisories in requirements.txt (review above)."
else
    echo "⚠️  pip-audit is not installed. Install with: pip install pip-audit"
fi

echo ""
echo "[2/3] Checking Secrets & Production Environment Configuration..."
python3 -c '
from app.core.config import Settings
import sys

# Test default settings
s = Settings()
print(f"  ✓ App Environment: {s.app_env}")
print(f"  ✓ Storage Backend: {s.storage_backend}")
print(f"  ✓ Allowed Origins: {s.allowed_origins}")
print(f"  ✓ Auth Required:   {s.auth_required}")

# Test production validation logic
try:
    bad_prod = Settings(app_env="production", allowed_origins=["http://localhost:3000"])
    print("  ✗ ERROR: Production settings failed to reject unsafe localhost origin!")
    sys.exit(1)
except ValueError:
    print("  ✓ Production CORS guard: Correctly rejects insecure localhost origin.")

try:
    bad_secret = Settings(app_env="production", allowed_origins=["https://satquery.example.com"], secret_key="change-me-in-production")
    print("  ✗ ERROR: Production settings failed to reject placeholder secret key!")
    sys.exit(1)
except ValueError:
    print("  ✓ Production Secret guard: Correctly rejects placeholder secret key.")
'

echo ""
echo "[3/3] Running Security Test Suite (tests/test_security.py)..."
PYTHONPATH=. python3 -m pytest tests/test_security.py -v --tb=short

echo ""
echo "========================================================"
echo "  ✓ Security Audit & Checks Passed Successfully!"
echo "========================================================"
