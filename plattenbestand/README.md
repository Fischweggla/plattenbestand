# IBE Plattenbestand-Management

Webbasiertes Bestandsmanagement-System für die Plattenbestände der IBE Innovative Bauelemente GmbH.
Verwaltet Lagerbestände an drei Produktionsstandorten (Birkach, Brandis, Dinkelsbühl) mit 10 Materialarten.

## Funktionsumfang

### Dateneingabe (Workflow)
- Geführter Workflow: Standort → Datum → Material → Länge → Stärke → Eingabemaske
- Automatische Übernahme des Vorbestands aus dem letzten Eintrag
- Berechnung: **Summe = Vorbestand + Zugang − Abgang − Abfall**
- Nur ganzzahlige Eingaben erlaubt

### Bestandsübersicht
- Grafische Darstellung aller Materialarten im Excel-Stil (Stärke × Länge)
- Tab-Ansicht: Gesamt (alle Werke summiert) oder Einzelstandort
- Farbcodierung nach Bestandshöhe
- Zeilen- und Spaltensummen

### Auswertungen
- KPI-Übersicht: Gesamtbestand, Zugang, Abgang, Abfall, Abfallquote
- Donut-Diagramme: Verteilung nach Materialart und Standort
- Bewegungsdiagramm: Zugang/Abgang/Abfall pro Material
- Heatmap: Standorte × Materialarten
- Zeitverlauf: Bestandsentwicklung als Liniendiagramm
- Top/Bottom-Rankings: Höchste und niedrigste Bestände

### Benutzerverwaltung
| Rolle            | Rechte                                                  |
|------------------|---------------------------------------------------------|
| **Fertigung**    | Eigenen Standort sehen, neue Werte eintragen            |
| **Bereichsleiter** | Wie Fertigung + bestehende Daten ändern              |
| **Admin**        | Alle Standorte, Benutzerverwaltung, Änderungsprotokoll  |

### Audit-Log
- Vollständiges Änderungsprotokoll aller Aktionen
- Login/Logout, Dateneingaben, Änderungen, Benutzerverwaltung
- IP-Adresse und Zeitstempel

### API (vorbereitet für ERP)
- `GET /api/v1/inventory?location=99&date=2025-04-14`
- `GET /api/v1/locations`

## Technik

| Komponente | Technologie                    |
|------------|--------------------------------|
| Backend    | Python 3.12, Flask, SQLAlchemy |
| Datenbank  | PostgreSQL 16                  |
| Frontend   | Jinja2, Chart.js, Roboto       |
| Auth       | Flask-Login, bcrypt             |
| Deployment | Gunicorn, Nginx, Systemd        |
| Design     | IBE Corporate Design (Dunkelblau #00324B, Blaugrau #9AAEB7) |

## Materialarten

| Material                                        | Stärken (mm)         | Längen (mm)                           |
|-------------------------------------------------|----------------------|---------------------------------------|
| Beschichtetes Styropor LPS                      | 15, 25, 35, 40       | 1650–2750, 3020                       |
| Unbeschichtetes Styropor LPS                    | 11, 21, 31, 36, 45   | 1650–2750, 3020                       |
| Beschichtete PU Platten                         | 25                   | 1650–2750                             |
| Unbeschichtete PU Platten                       | 21                   | 1650–2750                             |
| Beschichtete Mineralfaser LPS                   | 25                   | 1650–2750                             |
| Unbeschichtete Mineralfaserplatten LPS          | 20                   | 1650–2750                             |
| Unbeschichtete Holzfaserplatte                  | 20, 21               | 2350, 2750                            |
| Beschichtete Holzfaserplatte                    | 24, 25               | 2350, 2750                            |
| Unbeschichtet gelbes Styropor / Perimeter B-3000| 21                   | 1650–2750                             |
| Beschichtet gelbes Styropor / Perimeter B-3000  | 25                   | 1650–2750                             |

## Standorte

| Standort     | Code |
|--------------|------|
| Birkach      | 99   |
| Brandis      | 98   |
| Dinkelsbühl  | 96   |

## Installation

### Voraussetzungen
- Python 3.10+
- PostgreSQL 16+

### Lokale Entwicklung

```bash
cd plattenbestand
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# .env anlegen
cp .env.example .env
# SECRET_KEY und DATABASE_URL in .env anpassen

# PostgreSQL-Datenbank anlegen
sudo -u postgres createuser plattenbestand -P
sudo -u postgres createdb plattenbestand -O plattenbestand

# Server starten
python3 app.py
```

Erreichbar unter http://localhost:5000

**Standard-Login:** `admin` / `admin2025` — Passwort nach erstem Login ändern!

### Docker

```bash
docker compose up -d
```

Startet die App mit PostgreSQL auf Port 5000.

### Proxmox LXC

```bash
# Auf einem Debian 12 / Ubuntu 24.04 LXC Container:
chmod +x deploy-lxc.sh
./deploy-lxc.sh
```

Installiert PostgreSQL, Python, Nginx und richtet den Systemd-Service ein.

## Projektstruktur

```
plattenbestand/
├── app.py              # Flask-Anwendung, Routen, Init
├── models.py           # Datenbankmodelle (SQLAlchemy)
├── config.py           # Konfiguration (.env)
├── requirements.txt    # Python-Abhängigkeiten
├── Dockerfile          # Container-Build
├── docker-compose.yml  # Docker Compose (App + PostgreSQL)
├── deploy-lxc.sh       # Proxmox LXC Deployment-Skript
├── .env.example        # Umgebungsvariablen-Vorlage
├── static/
│   ├── css/style.css   # IBE Corporate Design
│   └── img/            # Logos (iBE)
└── templates/
    ├── base.html           # Layout mit Sidebar
    ├── login.html          # Anmeldeseite
    ├── dashboard.html      # Startseite
    ├── entry_select.html   # Dateneingabe-Workflow
    ├── entry_form.html     # Eingabemaske
    ├── inventory.html      # Bestandsübersicht
    ├── reports.html        # Auswertungen
    ├── users.html          # Benutzerliste
    ├── user_form.html      # Benutzer anlegen/bearbeiten
    └── audit.html          # Änderungsprotokoll
```

## Lizenz

Proprietär — IBE Innovative Bauelemente Produktions- und Vertriebs GmbH
