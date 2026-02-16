#!/bin/bash
# Deployment script for Oracle server
# This script will be executed by GitHub Actions

set -e  # Exit on error

echo "=== Starting deployment at $(date) ==="

# Navigate to project directory
cd ~/trading-bot

# Store current commit
OLD_COMMIT=$(git rev-parse HEAD)

# Stash any local changes
echo "Stashing local changes..."
git stash

# Pull latest changes
echo "Pulling latest changes from GitHub..."
git pull origin main

# Get new commit
NEW_COMMIT=$(git rev-parse HEAD)

if [ "$OLD_COMMIT" = "$NEW_COMMIT" ]; then
    echo "No changes detected. Deployment skipped."
    exit 0
fi

echo "Updated from $OLD_COMMIT to $NEW_COMMIT"

# Check if requirements.txt changed
if git diff $OLD_COMMIT $NEW_COMMIT --name-only | grep -q "requirements.txt"; then
    echo "requirements.txt changed. Installing dependencies..."
    pip install -r requirements.txt --user
fi

# Restart services if they exist
if systemctl --user is-active --quiet bot.service; then
    echo "Restarting bot service..."
    systemctl --user restart bot.service
    echo "Bot service restarted"
else
    echo "Bot service not running"
fi

if systemctl --user is-active --quiet server.service; then
    echo "Restarting server service..."
    systemctl --user restart server.service
    echo "Server service restarted"
else
    echo "Server service not running"
fi

echo "=== Deployment completed successfully at $(date) ==="
