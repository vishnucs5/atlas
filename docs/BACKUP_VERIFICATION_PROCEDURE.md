# ATLAS Automated Backup Verification Procedure

## 1. Scope & Objective

Defines daily and weekly verification standards ensuring database backups are complete, uncorrupted, and deterministically restorable.

---

## 2. Verification Cadence

- **Daily Automated Test:** Nightly restore to an isolated sandbox database, followed by schema integrity and data assertion checks.
- **Monthly Disaster Rehearsal:** End-to-end dry-run restoring cluster state from cold storage.

---

## 3. Automated Backup Verification Script

```bash
#!/usr/bin/env bash
set -euo pipefail

BACKUP_FILE="/backups/daily/atlas_latest.dump"
TEST_DB="atlas_restore_verify_$(date +%s)"

echo "==> Creating test database ${TEST_DB}..."
createdb -h $PGHOST -U $PGUSER ${TEST_DB}

echo "==> Restoring dump into test database..."
pg_restore -h $PGHOST -U $PGUSER -d ${TEST_DB} --clean --if-exists ${BACKUP_FILE}

echo "==> Verifying table counts..."
TABLE_COUNT=$(psql -h $PGHOST -U $PGUSER -d ${TEST_DB} -t -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';")
if [ "$TABLE_COUNT" -lt 15 ]; then
    echo "ERROR: Expected at least 15 tables, found ${TABLE_COUNT}"
    exit 1
fi

echo "==> Verifying foreign key integrity..."
psql -h $PGHOST -U $PGUSER -d ${TEST_DB} -c "
SELECT conrelid::regclass, confrelid::regclass 
FROM pg_constraint 
WHERE contype = 'f' AND NOT convalidated;
"

echo "==> Cleaning up test database..."
dropdb -h $PGHOST -U $PGUSER ${TEST_DB}

echo "==> Backup verification SUCCESSFUL."
```
