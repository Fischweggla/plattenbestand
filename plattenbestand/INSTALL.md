# Installation auf Proxmox LXC Container

## Voraussetzungen

- Proxmox VE 7 oder 8
- Debian 12 oder Ubuntu 24.04 LXC Template
- Internetzugang im Container (für apt + git clone)
- GitHub-Zugang (Repo ist privat)

## Schritt 1: LXC Container erstellen

In der Proxmox-Weboberfläche:

1. **Container erstellen** (oben rechts)
2. Einstellungen:
   - **Template:** Debian 12 oder Ubuntu 24.04
   - **Hostname:** `plattenbestand`
   - **Speicher:** mindestens 8 GB
   - **RAM:** mindestens 512 MB (empfohlen 1024 MB)
   - **CPU:** 1-2 Kerne
   - **Netzwerk:** DHCP oder feste IP im Firmennetz
   - **DNS:** Firmennetz-DNS oder `8.8.8.8`
3. Container starten

## Schritt 2: Im Container anmelden

```bash
# Über Proxmox Shell oder SSH
pct enter <CONTAINER-ID>
```

## Schritt 3: Git installieren und Repo klonen

```bash
apt-get update && apt-get install -y git
```

Da das Repository privat ist, braucht ihr einen GitHub Personal Access Token:

1. GitHub → Settings → Developer Settings → Personal Access Tokens → Tokens (classic)
2. Token erstellen mit Berechtigung `repo`
3. Token kopieren

```bash
# Mit Token klonen (Token statt Passwort eingeben)
git clone https://github.com/Fischweggla/plattenbestand.git /opt/plattenbestand
```

Alternativ, wenn der Token direkt in der URL stehen soll:
```bash
git clone https://DEIN_TOKEN@github.com/Fischweggla/plattenbestand.git /opt/plattenbestand
```

## Schritt 4: Automatisches Deployment-Skript ausführen

```bash
cd /opt/plattenbestand
chmod +x plattenbestand/deploy-lxc.sh
./plattenbestand/deploy-lxc.sh
```

Das Skript macht automatisch folgendes:
- System-Update
- PostgreSQL 16, Python 3, Nginx, Git installieren
- PostgreSQL Datenbank + Benutzer anlegen
- Python Virtual Environment + Abhängigkeiten installieren
- `.env` mit zufälligem Secret Key erstellen
- Systemd-Service einrichten (Autostart)
- Nginx als Reverse Proxy konfigurieren

## Schritt 5: Anmelden

Im Browser die IP des Containers aufrufen:

```
http://<CONTAINER-IP>
```

**Standard-Login:**
- Benutzer: `admin`
- Passwort: `admin2025`

**Sofort nach dem ersten Login das Passwort ändern!**

## Schritt 6: PostgreSQL-Passwort ändern (empfohlen)

```bash
# Neues Passwort in der Datenbank setzen
sudo -u postgres psql -c "ALTER USER plattenbestand WITH PASSWORD 'NEUES_SICHERES_PASSWORT';"

# .env anpassen
nano /opt/plattenbestand/plattenbestand/.env
# DATABASE_URL=postgresql://plattenbestand:NEUES_SICHERES_PASSWORT@localhost:5432/plattenbestand

# Service neu starten
systemctl restart plattenbestand
```

---

## Updates einspielen

Wenn neue Versionen im Git-Repo verfügbar sind:

```bash
cd /opt/plattenbestand
git pull

cd plattenbestand
source venv/bin/activate
pip install -r requirements.txt

sudo systemctl restart plattenbestand
```

## Nützliche Befehle

```bash
# Status prüfen
systemctl status plattenbestand

# Logs ansehen
journalctl -u plattenbestand -f

# Nginx-Logs
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log

# Service neu starten
systemctl restart plattenbestand

# PostgreSQL Backup
pg_dump -U plattenbestand plattenbestand > backup_$(date +%Y%m%d).sql

# PostgreSQL Restore
psql -U plattenbestand plattenbestand < backup_20260414.sql
```

## Firewall (optional)

Falls UFW aktiv ist:

```bash
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS (falls später SSL)
```

## SSL/HTTPS (optional, für später)

Mit Let's Encrypt und Certbot:

```bash
apt-get install -y certbot python3-certbot-nginx
certbot --nginx -d plattenbestand.ibe-innovativ.de
```

## Fehlersuche

| Problem | Lösung |
|---------|--------|
| Seite nicht erreichbar | `systemctl status plattenbestand` und `systemctl status nginx` prüfen |
| 502 Bad Gateway | App läuft nicht: `systemctl restart plattenbestand`, Logs prüfen |
| Datenbank-Fehler | `systemctl status postgresql`, `.env` prüfen |
| Berechtigungsfehler | `chown -R www-data:www-data /opt/plattenbestand` |
| Git pull geht nicht | Token abgelaufen, neuen erstellen |
