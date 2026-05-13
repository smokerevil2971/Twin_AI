#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Twin AI — VPS Swap File Setup
# Run this ONCE on your Hetzner VPS after first login (as root or with sudo).
#
# Usage:
#   chmod +x setup_swap.sh
#   sudo bash setup_swap.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e  # Stop immediately if any command fails

echo "======================================"
echo "  Twin AI — Swap File Setup"
echo "======================================"

# Check if swap already exists
if swapon --show | grep -q '/swapfile'; then
    echo "✅ Swap file already exists and is active. Nothing to do."
    swapon --show
    exit 0
fi

echo ""
echo "▶ Step 1: Creating 2 GB swap file..."
fallocate -l 2G /swapfile
echo "   Done."

echo "▶ Step 2: Securing swap file permissions..."
chmod 600 /swapfile
echo "   Done."

echo "▶ Step 3: Formatting as swap space..."
mkswap /swapfile
echo "   Done."

echo "▶ Step 4: Activating swap..."
swapon /swapfile
echo "   Done."

echo "▶ Step 5: Making swap permanent (survives reboots)..."
# Only add if not already in fstab
if ! grep -q '/swapfile' /etc/fstab; then
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo "   Added to /etc/fstab."
else
    echo "   Already in /etc/fstab. Skipped."
fi

echo ""
echo "▶ Step 6: Optimising swap behaviour..."
# swappiness=10 means Linux will only use swap as a last resort
# (default is 60 which is too aggressive for a server)
sysctl vm.swappiness=10
echo 'vm.swappiness=10' >> /etc/sysctl.conf
echo "   Set swappiness to 10 (use swap only as emergency)."

echo ""
echo "======================================"
echo "  ✅ Swap setup complete!"
echo "======================================"
echo ""
echo "Current memory status:"
free -h
echo ""
echo "Swap details:"
swapon --show
