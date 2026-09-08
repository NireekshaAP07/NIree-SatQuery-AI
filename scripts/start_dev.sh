#!/usr/bin/env bash
# Starts SatQuery AI: root backend (port 8000), query worker, and Next.js frontend (port 3000).
#
# Usage:
#   ./scripts/start_dev.sh           # normal start
#   ./scripts/start_dev.sh --seed    # seed demo data then start

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ── Argument parsing ────────────────────────────────────────────────────────────
SEED=false
for arg in "$@"; do
    case $arg in
        --seed) SEED=true ;;
        --help|-h)
            echo "Usage: $0 [--seed]"
            echo "  --seed    Populate the database with demo data before starting."
            exit 0 ;;
    esac
done

# Trap SIGINT/SIGTERM to kill child processes
cleanup() {
    echo "Stopping SatQuery servers..."
    kill $(jobs -p) 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

# ── Optional: seed demo data ─────────────────────────────────────────────────────
if [ "$SEED" = true ]; then
    echo "Seeding demo data..."
    cd "$ROOT_DIR" && python3 scripts/seed_demo.py
    echo "Seed complete."
fi

echo "Starting Backend (Uvicorn on :8000)..."
cd "$ROOT_DIR" && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

echo "Starting Query Worker..."
cd "$ROOT_DIR" && python3 -m app.workers.query_worker &
WORKER_PID=$!

echo "Starting Frontend (Next.js on :3000)..."
cd "$ROOT_DIR/frontend" && npm run dev -- -p 3000 &
FRONTEND_PID=$!

wait $BACKEND_PID $WORKER_PID $FRONTEND_PID
