#!/bin/bash
# =============================================================================
# IBE Plattenbestand — Deployment auf Proxmox LXC Container
# Getestet mit Debian 12 / Ubuntu 24.04
# Verwendet git clone aus dem GitHub-Repository
# =============================================================================

set -e

REPO_URL="https://github.com/Fischweggla/plattenbestand.git"
APP_DIR="/opt/plattenbestand"
DB_USER="plattenbestand"
DB_PASS="plattenbestand"
DB_NAME="plattenbestand"

echo ""
echo "=========================================="
echo "  IBE Plattenbestand — LXC Deployment"
echo "=========================================="
echo ""

# --- 1. System aktualisieren ---
echo "[1/7] System aktualisieren..."
apt-get update && apt-get upgrade -y

# --- 2. Pakete installieren ---
echo "[2/7] Pakete installieren..."
apt-get install -y \
    postgresql postgresql-contrib \
    python3 python3-pip python3-venv \
    nginx \
    git

# --- 3. PostgreSQL einrichten ---
echo "[3/7] PostgreSQL einrichten..."
systemctl enable postgresql
systemctl start postgresql

sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}';"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};"

# --- 4. Repository klonen ---
echo "[4/7] Repository klonen..."
if [ -d "${APP_DIR}/.git" ]; then
    echo "  Repository existiert bereits, aktualisiere..."
    cd "$APP_DIR"
    git pull
else
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# In den plattenbestand-Unterordner wechseln
cd "${APP_DIR}/plattenbestand"

# --- 5. Python-Umgebung einrichten ---
echo "[5/7] Python-Umgebung einrichten..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# .env erstellen falls nicht vorhanden
if [ ! -f .env ]; then
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > .env << ENVEOF
SECRET_KEY=${SECRET}
DATABASE_URL=postgresql://${DB_USER}:${DB_PASS}@localhost:5432/${DB_NAME}
ENVEOF
    echo "  .env erstellt"
fi

# --- 6. Systemd Service ---
echo "[6/7] Systemd Service einrichten..."
cat > /etc/systemd/system/plattenbestand.service << EOF
[Unit]
Description=IBE Plattenbestand App
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=${APP_DIR}/plattenbestand
EnvironmentFile=${APP_DIR}/plattenbestand/.env
Environment=PATH=${APP_DIR}/plattenbestand/venv/bin
ExecStart=${APP_DIR}/plattenbestand/venv/bin/gunicorn --bind 127.0.0.1:5000 --workers 3 --timeout 120 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Berechtigungen
chown -R www-data:www-data "${APP_DIR}"

# --- 7. Nginx Reverse Proxy ---
echo "[7/7] Nginx einrichten..."
cat > /etc/nginx/sites-available/plattenbestand << EOF
server {
    listen 80;
    server_name _;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /static {
        alias ${APP_DIR}/plattenbestand/static;
        expires 7d;
    }
}
EOF

ln -sf /etc/nginx/sites-available/plattenbestand /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Services starten
systemctl daemon-reload
systemctl enable plattenbestand
systemctl start plattenbestand
systemctl restart nginx

# --- Fertig ---
IP=$(hostname -I | awk '{print $1}')
echo ""
echo "=========================================="
echo "  Deployment abgeschlossen!"
echo "=========================================="
echo ""
echo "  URL:    http://${IP}"
echo "  Login:  admin / admin2025"
echo ""
echo "  WICHTIG:"
echo "  - Passwort nach erstem Login ändern!"
echo "  - PostgreSQL-Passwort in .env ändern!"
echo ""
echo "  Update durchführen:"
echo "    cd ${APP_DIR} && git pull"
echo "    cd plattenbestand && source venv/bin/activate"
echo "    pip install -r requirements.txt"
echo "    sudo systemctl restart plattenbestand"
echo ""
