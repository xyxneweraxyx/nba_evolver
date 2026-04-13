#!/bin/bash
# dev.sh — Lance le backend + frontend en une commande
# Usage: bash dev.sh [--data-dir /chemin/vers/nba_data] [--port 8080]

DATA_DIR="../nba_data"
PORT=8080

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --data-dir) DATA_DIR="$2"; shift 2 ;;
    --port)     PORT="$2";     shift 2 ;;
    *) shift ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_DIR="$SCRIPT_DIR/nba_engine"
FRONTEND_DIR="$SCRIPT_DIR/nba_frontend"

echo "╔══════════════════════════════════════════════════╗"
echo "║  NBA Formula Evolver — Dev launcher              ║"
echo "║  Backend  → http://localhost:$PORT               ║"
echo "║  Frontend → http://localhost:5173                ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# Cleanup on Ctrl+C
cleanup() {
  echo ""
  echo "Shutting down..."
  kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
  exit 0
}
trap cleanup SIGINT SIGTERM

# Build frontend first
echo "Building frontend..."
cd "$FRONTEND_DIR"
npm run build
if [ $? -ne 0 ]; then
  echo "Build failed — aborting."
  exit 1
fi
echo "Build OK."
echo ""

# Start backend
cd "$ENGINE_DIR"
python3 server.py --data-dir "$DATA_DIR" --port "$PORT" &
BACKEND_PID=$!

# Wait a moment for backend to start
sleep 1

# Start frontend
cd "$FRONTEND_DIR"
npm run dev &
FRONTEND_PID=$!

echo "Backend PID:  $BACKEND_PID"
echo "Frontend PID: $FRONTEND_PID"
echo ""
echo "Press Ctrl+C to stop both."
echo ""

# Wait for both
wait $BACKEND_PID $FRONTEND_PID