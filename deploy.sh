#!/bin/bash
# Deploy Robo-Trader to a remote server
# Usage: ./deploy.sh <server-ip>
#
# Prerequisites:
#   1. Create a DigitalOcean droplet ($4/mo, Ubuntu 24.04, 1GB RAM)
#      https://cloud.digitalocean.com/droplets/new
#   2. SSH into it: ssh root@<ip>
#   3. Install Docker: curl -fsSL https://get.docker.com | sh
#   4. Run this script from your Mac: ./deploy.sh <ip>

set -e

SERVER=$1
if [ -z "$SERVER" ]; then
    echo "Usage: ./deploy.sh <server-ip>"
    exit 1
fi

echo "==> Syncing code to server..."
rsync -avz --exclude '.venv' --exclude '__pycache__' --exclude 'logs' --exclude '.git' \
    /Users/arnavmukherjee/Robo-Trader-Agent/ root@$SERVER:/opt/robo-trader/

echo "==> Copying .env..."
scp /Users/arnavmukherjee/Robo-Trader-Agent/.env root@$SERVER:/opt/robo-trader/.env

echo "==> Building and starting on server..."
ssh root@$SERVER "cd /opt/robo-trader && docker compose up -d --build"

echo "==> Done! Scalper running 24/7 at $SERVER"
echo "    View logs: ssh root@$SERVER 'docker compose -f /opt/robo-trader/docker-compose.yml logs -f'"
