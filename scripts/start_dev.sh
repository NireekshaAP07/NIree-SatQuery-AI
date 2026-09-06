#!/usr/bin/env bash
# Starts SatQuery AI: root backend (port 8000), query worker, and Next.js frontend (port 3000).
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Trap SIGINT/SIGTERM to kill child processes
cleanup() {
    echo "Stopping SatQuery servers..."
    kill $(jobs -p) 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

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
