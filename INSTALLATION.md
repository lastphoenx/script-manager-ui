# Script Manager UI - Sichere Installation für Produktion

## Kritische Unterschiede zur Quick-Start Anleitung

⚠️ **Die Schritte im README.md sind für Test/Entwicklung. Für Produktion bitte diese Anleitung verwenden!**

---

## Teil 1: Datenbank (MariaDB)

### Schritt 1: Datenbank-User anlegen (als root)

```bash
sudo mysql -u root -p
```

```sql
-- Dedizierten User mit minimalem Zugriff anlegen
CREATE USER IF NOT EXISTS 'script_manager'@'localhost' 
    IDENTIFIED BY 'DEIN_SICHERES_PASSWORT_HIER';

-- Optional: Datenbank erstellen (nur wenn sie noch nicht existiert)
CREATE DATABASE IF NOT EXISTS script_manager 
    CHARACTER SET utf8mb4 
    COLLATE utf8mb4_unicode_ci;

-- Minimale Rechte vergeben (nur für script_manager Datenbank)
GRANT SELECT, INSERT, UPDATE, DELETE ON script_manager.* 
    TO 'script_manager'@'localhost';

FLUSH PRIVILEGES;
exit;
```

### Schritt 2: Schema importieren (als script_manager User)

```bash
# NUR die Tabellen-Definitionen (ohne CREATE DATABASE)
mysql -u script_manager -p script_manager << 'EOF'
-- Jobs table
CREATE TABLE IF NOT EXISTS jobs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    script_name VARCHAR(255) NOT NULL,
    username VARCHAR(255) NULL COMMENT 'User from Authentik header',
    parameters JSON NULL COMMENT 'Script parameters as JSON',
    status ENUM('pending', 'running', 'success', 'failed', 'killed') NOT NULL DEFAULT 'pending',
    pid INT NULL COMMENT 'Process ID when running',
    start_time DATETIME NULL,
    end_time DATETIME NULL,
    exit_code INT NULL,
    log_file VARCHAR(512) NULL COMMENT 'Relative path to log file',
    error_message TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_script_name (script_name),
    INDEX idx_username (username),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at),
    INDEX idx_start_time (start_time)
) ENGINE=InnoDB;

-- Script stats (optional)
CREATE TABLE IF NOT EXISTS script_stats (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    script_name VARCHAR(255) NOT NULL,
    total_runs INT NOT NULL DEFAULT 0,
    success_count INT NOT NULL DEFAULT 0,
    failed_count INT NOT NULL DEFAULT 0,
    avg_duration_seconds DECIMAL(10, 2) NULL,
    last_run DATETIME NULL,
    
    UNIQUE KEY uniq_script (script_name)
) ENGINE=InnoDB;
EOF
```

### Schritt 3: Verbindung testen

```bash
mysql -u script_manager -p script_manager -e "SHOW TABLES;"
```

Erwartete Ausgabe:
```
+---------------------------+
| Tables_in_script_manager  |
+---------------------------+
| jobs                      |
| script_stats              |
+---------------------------+
```

---

## Teil 2: Anwendung installieren

### Schritt 1: Verzeichnis anlegen

```bash
sudo mkdir -p /opt/apps/script-manager-ui
sudo chown $USER:$USER /opt/apps/script-manager-ui
cd /opt/apps/script-manager-ui
```

### Schritt 2: Code clonen/kopieren

```bash
# Falls Git-Repo:
git clone https://github.com/USERNAME/script-manager-ui.git .

# ODER: Manuell hochladen (scp, rsync, etc.)
```

### Schritt 3: Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Schritt 4: .env konfigurieren (WICHTIG!)

**Nicht einfach kopieren, sondern manuell erstellen:**

```bash
nano .env
```

Inhalt:
```env
# Database (MariaDB)
DB_HOST=localhost
DB_PORT=3306
DB_NAME=script_manager
DB_USER=script_manager
DB_PASS=DEIN_SICHERES_PASSWORT_HIER

# Server
HOST=127.0.0.1
PORT=8000
DEBUG=false

# Authentik Forward Auth
AUTHENTIK_HEADER=X-Authentik-Username
AUTH_REQUIRED=true

# Job Management
JOB_TIMEOUT_DEFAULT=3600
JOB_OUTPUT_MAX_SIZE=10485760
```

**Dateiberechtigungen sichern:**
```bash
chmod 600 .env
```

### Schritt 5: scripts.yaml anpassen

```bash
nano scripts.yaml
```

**Prüfe alle `cwd`-Pfade:**
- `/opt/pcloud-tools` → existiert?
- `/opt/entropywatcher` → existiert?
- `/opt/rtb` → existiert?

**Falls Pfade abweichen, anpassen!**

### Schritt 6: Logs-Verzeichnis

```bash
mkdir -p logs
chmod 750 logs
```

### Schritt 7: Test-Start

```bash
source venv/bin/activate
python3 main.py
```

Prüfe in anderem Terminal:
```bash
curl http://localhost:8000/health
```

Erwartete Antwort:
```json
{"status":"healthy","timestamp":"2026-04-30T...","version":"0.1.0"}
```

**Wenn Fehler:** Prüfe Logs und .env-Credentials

---

## Teil 3: Systemd Service (Dauerbetrieb)

### Schritt 1: Service-Datei erstellen

```bash
sudo nano /etc/systemd/system/script-manager-ui.service
```

```ini
[Unit]
Description=Script Manager UI
After=network.target mariadb.service
Requires=mariadb.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/apps/script-manager-ui
Environment="PATH=/opt/apps/script-manager-ui/venv/bin"
ExecStart=/opt/apps/script-manager-ui/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

# Security
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/log/script-manager-ui /srv /srv/nas /srv/nas/restore

[Install]
WantedBy=multi-user.target
```

### Schritt 2: Berechtigungen anpassen

```bash
sudo chown -R www-data:www-data /opt/apps/script-manager-ui
sudo chmod 750 /opt/apps/script-manager-ui
```

### Schritt 3: Service aktivieren

```bash
sudo systemctl daemon-reload
sudo systemctl enable script-manager-ui.service
sudo systemctl start script-manager-ui.service
sudo systemctl status script-manager-ui.service
```

### Schritt 4: Logs prüfen

```bash
sudo journalctl -u script-manager-ui.service -f
```

---

## Teil 4: Nginx Reverse Proxy (mit Authentik)

### Schritt 1: Nginx Site anlegen

```bash
sudo nano /etc/nginx/sites-available/script-manager
```

```nginx
upstream script_manager {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name scripts.deinedomain.de;
    
    # Redirect to HTTPS (nach SSL-Setup)
    # return 301 https://$host$request_uri;
    
    # Authentik Forward Auth
    location / {
        # Forward auth request
        auth_request /outpost.goauthentik.io/auth/nginx;
        auth_request_set $authentik_username $upstream_http_x_authentik_username;
        auth_request_set $authentik_email $upstream_http_x_authentik_email;
        
        # Proxy to FastAPI
        proxy_pass http://script_manager;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Pass Authentik headers
        proxy_set_header X-Authentik-Username $authentik_username;
        proxy_set_header X-Authentik-Email $authentik_email;
        
        # Timeouts für lange Requests
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }
    
    # Authentik outpost endpoint
    location /outpost.goauthentik.io {
        proxy_pass http://DEIN_AUTHENTIK_HOST:9000/outpost.goauthentik.io;
        proxy_set_header Host $host;
        proxy_set_header X-Original-URL $scheme://$http_host$request_uri;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-Uri $request_uri;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### Schritt 2: Site aktivieren

```bash
sudo ln -s /etc/nginx/sites-available/script-manager /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

## Teil 5: Sicherheits-Checks

### ✅ Firewall

```bash
# Nur Nginx darf auf Port 8000 (intern)
sudo ufw status
# Falls Port 8000 extern offen: sudo ufw deny 8000
```

### ✅ .env Berechtigungen

```bash
ls -la /opt/apps/script-manager-ui/.env
# Sollte: -rw------- www-data www-data
```

### ✅ MariaDB User-Rechte

```bash
sudo mysql -u root -p
```

```sql
SHOW GRANTS FOR 'script_manager'@'localhost';
-- Sollte NUR SELECT, INSERT, UPDATE, DELETE auf script_manager.* haben
-- KEIN CREATE, DROP, GRANT
```

### ✅ Subprocess-Sicherheit

In `scripts.yaml` prüfen:
- Keine `cmd: "/bin/bash -c ..."` Konstrukte (Shell-Injection!)
- Alle `cwd`-Pfade existieren und gehören www-data
- Kritische Scripts mit `locked: true` absichern

---

## Troubleshooting

### 1. "Access denied for user 'script_manager'"

```bash
# DB-Passwort in .env korrekt?
grep DB_PASS /opt/apps/script-manager-ui/.env

# User existiert?
sudo mysql -u root -p -e "SELECT User, Host FROM mysql.user WHERE User='script_manager';"
```

### 2. "Failed to create job" oder JSON-Fehler

```bash
# Prüfe MariaDB-Logs
sudo tail -f /var/log/mysql/error.log

# Teste manuell
python3 << 'EOF'
import json
params = {"key": "value"}
print(json.dumps(params))
EOF
```

### 3. Jobs bleiben "pending"

```bash
# Service läuft?
sudo systemctl status script-manager-ui

# Background-Monitor aktiv?
sudo journalctl -u script-manager-ui -n 50 | grep "background_job_monitor"
```

### 4. Logs nicht sichtbar

```bash
# Verzeichnis existiert und beschreibbar?
ls -la /opt/apps/script-manager-ui/logs/
sudo chown -R www-data:www-data /opt/apps/script-manager-ui/logs/
```

---

## Update-Prozedur

```bash
cd /opt/apps/script-manager-ui

# Backup
sudo systemctl stop script-manager-ui
cp -r . ../script-manager-ui.backup

# Update
git pull  # oder neue Dateien hochladen

# Dependencies aktualisieren
source venv/bin/activate
pip install -r requirements.txt --upgrade

# Service neu starten
sudo systemctl start script-manager-ui
sudo systemctl status script-manager-ui
```

---

## Monitoring

### Logs überwachen

```bash
# Systemd Journal
sudo journalctl -u script-manager-ui -f

# Job-Logs
ls -lh /opt/apps/script-manager-ui/logs/

# Nginx Access
sudo tail -f /var/log/nginx/access.log | grep scripts
```

### Health-Check

```bash
# Lokal
curl http://localhost:8000/health

# Extern (via Nginx)
curl https://scripts.deinedomain.de/health
```

### Performance

```bash
# Laufende Jobs
mysql -u script_manager -p script_manager << 'EOF'
SELECT id, script_name, start_time, TIMESTAMPDIFF(MINUTE, start_time, NOW()) AS runtime_min
FROM jobs
WHERE status = 'running'
ORDER BY start_time;
EOF
```

---

**Viel Erfolg bei der Installation!** 🚀
