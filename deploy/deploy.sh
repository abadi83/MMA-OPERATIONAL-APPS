#!/bin/bash
# ══════════════════════════════════════════════════════
# iScan Pro By MMA — VPS Deployment Script
# ══════════════════════════════════════════════════════
#
# Cara pakai (di VPS):
#   1. Clone/pindahkan project ke /opt/iscan-pro/
#   2. chmod +x deploy/deploy.sh
#   3. sudo bash deploy/deploy.sh
#
# ══════════════════════════════════════════════════════

set -e  # Stop on first error

APP_NAME="iscan"
APP_DIR="/opt/iscan-pro"
DOMAIN="iscan.mitra-mulia-abadi.com"  # ← GANTI dengan domain VPS kamu

echo "═══════════════════════════════════════"
echo "🚀 iScan Pro — VPS Deployment"
echo "═══════════════════════════════════════"
echo ""

# ── 1. System dependencies ──
echo "📦 [1/7] Install system dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv nginx-full certbot python3-certbot-nginx sqlite3

# Verify nginx has sub_filter module
if ! nginx -V 2>&1 | grep -q "http_sub_module"; then
    echo "⚠️  WARNING: nginx http_sub_module not found! PWA injection requires it."
    echo "   Install nginx-full: apt-get install -y nginx-full"
fi

# ── 2. Create app directory ──
echo "📁 [2/7] Setup app directory: ${APP_DIR}"
mkdir -p ${APP_DIR}
# Copy all project files (kecuali deploy folder & DB)
rsync -av --exclude='deploy/' --exclude='*.db' --exclude='__pycache__/' --exclude='.git/' ./ ${APP_DIR}/

# ── 3. Python virtual environment ──
echo "🐍 [3/7] Create Python virtual environment..."
python3 -m venv ${APP_DIR}/venv
source ${APP_DIR}/venv/bin/activate
pip install --upgrade pip -q
pip install -r ${APP_DIR}/requirements.txt -q
deactivate

# ── 4. Directory permissions ──
echo "🔐 [4/7] Set permissions..."
chown -R www-data:www-data ${APP_DIR}
chmod -R 755 ${APP_DIR}
# Make sure data folders are writable
mkdir -p ${APP_DIR}/logs ${APP_DIR}/Gudang_Arsip_Excel ${APP_DIR}/Handover_Reports ${APP_DIR}/Sales_Reports ${APP_DIR}/Packing_Videos
chown -R www-data:www-data ${APP_DIR}/logs ${APP_DIR}/Gudang_Arsip_Excel ${APP_DIR}/Handover_Reports ${APP_DIR}/Sales_Reports ${APP_DIR}/Packing_Videos

# ── 5. systemd service ──
echo "⚙️  [5/7] Setup systemd service..."
cp ${APP_DIR}/deploy/iscan.service /etc/systemd/system/iscan.service
systemctl daemon-reload
systemctl enable iscan
systemctl restart iscan

# ── 6. Nginx ──
echo "🌐 [6/7] Setup Nginx reverse proxy..."
cp ${APP_DIR}/deploy/nginx-iscan.conf /etc/nginx/sites-available/iscan
ln -sf /etc/nginx/sites-available/iscan /etc/nginx/sites-enabled/iscan
# Remove default site
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

# ── 7. SSL (Let's Encrypt) ──
echo "🔒 [7/7] Setup SSL certificate..."
certbot --nginx -d ${DOMAIN} --non-interactive --agree-tos --email admin@${DOMAIN} || echo "⚠️  SSL setup skipped (pastikan domain sudah mengarah ke VPS ini)"

# ── Done ──
echo ""
echo "═══════════════════════════════════════"
echo "✅ Deployment Selesai!"
echo "═══════════════════════════════════════"
echo ""
echo "🌐 URL: https://${DOMAIN}"
echo "📊 Status:  systemctl status iscan"
echo "📜 Logs:    journalctl -u iscan -f"
echo "🔄 Restart: systemctl restart iscan"
echo ""
echo "⚠️  Pastikan:"
echo "   1. Domain ${DOMAIN} sudah pointing ke IP VPS ini"
echo "   2. Port 80 & 443 terbuka di firewall VPS"
echo "   3. Cek status: systemctl status iscan nginx"
echo ""
