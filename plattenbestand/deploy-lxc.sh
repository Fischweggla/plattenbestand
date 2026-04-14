#!/bin/bash
# Deployment-Skript für Proxmox LXC Container
# Getestet mit Debian 12 / Ubuntu 24.04

set -e

echo "=== IBE Plattenbestand - LXC Deployment ==="

# System aktualisieren
apt-get update && apt-get upgrade -y

# PostgreSQL + Python + Nginx installieren
apt-get install -y postgresql postgresql-contrib python3 python3-pip python3-venv nginx

# PostgreSQL Datenbank und Benutzer anlegen
echo "--- PostgreSQL einrichten ---"
sudo -u postgres psql -c "CREATE USER plattenbestand WITH PASSWORD 'plattenbestand';" 2>/dev/null || true
sudo -u postgres psql -c "CREATE DATABASE plattenbestand OWNER plattenbestand;" 2>/dev/null || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE plattenbestand TO plattenbestand;"

# App-Verzeichnis erstellen
APP_DIR="/opt/plattenbestand"
mkdir -p "$APP_DIR"
cd "$APP_DIR"

# Dateien kopieren (oder per rsync/scp übertragen)
echo "Bitte App-Dateien nach $APP_DIR kopieren."
echo "z.B.: rsync -av /pfad/zur/app/ $APP_DIR/"

# Virtual Environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# .env erstellen falls nicht vorhanden
if [ ! -f .env ]; then
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > .env << ENVEOF
SECRET_KEY=$SECRET
DATABASE_URL=postgresql://plattenbestand:plattenbestand@localhost:5432/plattenbestand
ENVEOF
fi

# Systemd Service
cat > /etc/systemd/system/plattenbestand.service << 'EOF'
[Unit]
Description=IBE Plattenbestand App
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/plattenbestand
Environment=PATH=/opt/plattenbestand/venv/bin
EnvironmentFile=/opt/plattenbestand/.env
ExecStart=/opt/plattenbestand/venv/bin/gunicorn --bind 127.0.0.1:5000 --workers 3 --timeout 120 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Berechtigungen
chown -R www-data:www-data "$APP_DIR"

# Nginx Reverse Proxy
cat > /etc/nginx/sites-available/plattenbestand << 'EOF'
server {
    listen 80;
    server_name _;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static {
        alias /opt/plattenbestand/static;
        expires 7d;
    }
}
EOF

ln -sf /etc/nginx/sites-available/plattenbestand /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Services starten
systemctl daemon-reload
systemctl enable postgresql plattenbestand
systemctl start plattenbestand
systemctl restart nginx

echo ""
echo "=== Deployment abgeschlossen ==="
echo "App erreichbar unter: http://$(hostname -I | awk '{print $1}')"
echo "Standard-Login: admin / admin2025"
echo "WICHTIG: Passwort nach erstem Login ändern!"
echo "WICHTIG: PostgreSQL-Passwort in .env und DB ändern!"
