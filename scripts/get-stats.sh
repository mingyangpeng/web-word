#!/bin/bash

# GSD Stats Query - Local Implementation
# This script replaces the missing gsd-sdk query stats.json command

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Get stats from the Node.js script
STATS=$(node "$SCRIPT_DIR/get-stats.js")

# Check if script succeeded
if [ $? -eq 0 ]; then
  # Output as JSON
  echo "$STATS"
else
  echo '{"error": "Failed to gather stats"}'
  exit 1
fi
