#!/bin/bash

echo "=== Current Journal Configuration ==="
echo "Current storage setting:"
grep "Storage=" /etc/systemd/journald.conf

echo ""
echo "=== Fixing Journal Persistence ==="

# Create updated journald.conf with persistent storage
sudo sed -i 's/Storage=volatile/Storage=persistent/' /etc/systemd/journald.conf

# Add retention settings
sudo sed -i '/^\[Journal\]/a SystemMaxUse=500M\nMaxRetentionSec=30day' /etc/systemd/journald.conf

echo "Updated configuration:"
grep -A 5 "^\[Journal\]" /etc/systemd/journald.conf

echo ""
echo "=== Creating persistent journal directory ==="
sudo mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal

echo ""
echo "=== Restarting systemd-journald ==="
sudo systemctl restart systemd-journald

echo ""
echo "=== Verification ==="
echo "New storage location:"
sudo journalctl --disk-usage

echo ""
echo "Journal configuration applied successfully!"
echo "Logs will now persist across reboots and be kept for 30 days (max 500MB)"
