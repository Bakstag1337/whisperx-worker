#!/bin/bash
set -e

echo "=== RunPod WhisperX Worker Entrypoint ==="

# URL to download handler.py from GitHub (can be overridden via env var)
HANDLER_URL="${HANDLER_URL:-https://raw.githubusercontent.com/Bakstag1337/whisperx-worker/main/handler.py}"

echo "Attempting to download latest handler.py from: $HANDLER_URL"

# Try to download from GitHub with 10 second timeout
if curl -fsSL --max-time 10 "$HANDLER_URL" -o /app/handler.py 2>/dev/null; then
    echo "✓ Handler downloaded successfully from GitHub"
else
    echo "⚠ Failed to download from GitHub, using fallback version"
    if [ -f /app/handler.py.fallback ]; then
        cp /app/handler.py.fallback /app/handler.py
        echo "✓ Using fallback handler.py"
    else
        echo "✗ ERROR: No fallback handler.py found!"
        exit 1
    fi
fi

# Clean up old temporary files (older than 1 hour) to prevent disk space issues
echo "Cleaning up old temporary files..."
find /workspace/tmp -type f -mmin +60 -delete 2>/dev/null || true
echo "✓ Cleanup complete"

echo "Starting worker..."
exec python -u /app/handler.py
