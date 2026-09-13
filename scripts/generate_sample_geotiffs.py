"""
Regenerates real satellite imagery for SatQuery AI sample data.

Usage:
    python3 scripts/generate_sample_geotiffs.py

Downloads MODIS Terra TrueColor imagery (250m resolution) from NASA GIBS
for Bengaluru East (Whitefield/Sarjapur/KR Puram area) across two years
to demonstrate clear bi-temporal urban change detection.

Area:  12.90-13.10 N, 77.55-77.75 E (Bengaluru East, Karnataka, India)
Year1: February 2019 (pre-expansion baseline)
Year2: February 2024 (post-expansion with visible urban growth)
"""
from pathlib import Path
import subprocess, sys

script = Path(__file__).parent / "fetch_real_satellite_images.py"
if not script.exists():
    print(f"ERROR: {script} not found!")
    sys.exit(1)

subprocess.run([sys.executable, str(script)], check=True)
