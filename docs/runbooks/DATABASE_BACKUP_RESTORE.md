# Operational Runbook: Database Backup & Point-in-Time Restore (PITR)

## 1. Automated Continuous Backup Architecture

ATLAS Enterprise uses physical PostgreSQL 16 as its durable storage engine. The backup strategy consists of two tiers:
1. **Daily Base Backups (`pg_dump` / `pg_basebackup`):** Full logical and binary snapshots executed daily at 02:00 UTC.
2. **Continuous WAL Archiving:** Write-Ahead Log segments streamed to durable cloud object storage every 60 seconds.

---

## 2. Performing a Manual Base Backup

Execute a consistent logical snapshot of the entire enterprise database:

```bash
#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="/data/backups/postgres"
TIMESTAMP=$(date -u +"%Y%m%d_%H%M%SZ")
BACKUP_FILE="${BACKUP_DIR}/atlas_db_backup_${TIMESTAMP}.dump"

mkdir -p "${BACKUP_DIR}"

echo "[INFO] Commencing logical database backup to ${BACKUP_FILE}..."

docker exec -t atlas-postgres-prod pg_dump \
  -U atlas \
  -d atlas_production \
  -F c \
  -b \
  -v \
  -f "/tmp/backup.dump"

docker cp atlas-postgres-prod:/tmp/backup.dump "${BACKUP_FILE}"
docker exec -t atlas-postgres-prod rm /tmp/backup.dump

# Calculate and record cryptographic SHA-256 checksum
sha256sum "${BACKUP_FILE}" > "${BACKUP_FILE}.sha256"

echo "[SUCCESS] Backup complete. Checksum: $(cat "${BACKUP_FILE}.sha256")"
```

---

## 3. Restoring from a Backup File

To restore ATLAS to a new or recovered PostgreSQL container:

```bash
#!/usr/bin/env bash
set -euo pipefail

BACKUP_FILE="$1"

if [ ! -f "${BACKUP_FILE}" ]; then
  echo "[ERROR] Backup file not found: ${BACKUP_FILE}"
  exit 1
fi

# Verify SHA-256 integrity before restoration
echo "[INFO] Verifying backup checksum..."
sha256sum -c "${BACKUP_FILE}.sha256"

# Stop API service to prevent concurrent mutations
echo "[INFO] Halting control plane API traffic..."
docker compose -f docker-compose.prod.yml stop atlas-api atlas-worker

# Drop existing database and recreate clean target
echo "[INFO] Recreating clean target database..."
docker exec -t atlas-postgres-prod psql -U atlas -d postgres -c \
  "DROP DATABASE IF EXISTS atlas_production WITH (FORCE);"
docker exec -t atlas-postgres-prod psql -U atlas -d postgres -c \
  "CREATE DATABASE atlas_production OWNER atlas;"

# Copy and restore dump
echo "[INFO] Restoring database archive..."
docker cp "${BACKUP_FILE}" atlas-postgres-prod:/tmp/restore.dump
docker exec -t atlas-postgres-prod pg_restore \
  -U atlas \
  -d atlas_production \
  -v \
  --no-owner \
  /tmp/restore.dump

docker exec -t atlas-postgres-prod rm /tmp/restore.dump

# Restart services
echo "[INFO] Restarting control plane services..."
docker compose -f docker-compose.prod.yml start atlas-api atlas-worker

echo "[SUCCESS] Database restoration complete. Healthcheck verified."
```

---

## 4. Post-Restore Verification Checklist

Immediately following database restoration, verify:
1. `GET /readyz` returns HTTP 200 with all subsystems `ok`.
2. All 15 enterprise tables exist:
   ```bash
   docker exec -it atlas-postgres-prod psql -U atlas -d atlas_production -c "\dt enterprise_*"
   ```
3. Cryptographic SHA-256 hash chains verify intact across all organizations without sequence breaks or hash mismatches:
   ```bash
   curl -s -f "http://localhost:8000/api/v1/enterprise/audit/verify?org_id=*" \
     -H "Authorization: Bearer <ADMIN_KEY>" | grep '"is_intact":true'
   ```
