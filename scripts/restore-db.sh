#!/usr/bin/env bash
# =============================================================================
# PostgreSQL Production Database Restore Script
# Usage: ./scripts/restore-db.sh <path_to_backup_file.sql.gz>
# =============================================================================
set -euo pipefail

BACKUP_FILE="${1:-}"

if [[ -z "$BACKUP_FILE" || ! -f "$BACKUP_FILE" ]]; then
    echo "Error: Please specify a valid backup file (.sql.gz)." >&2
    echo "Usage: $0 ./backups/lms_db_YYYYMMDD_HHMMSSZ.sql.gz" >&2
    exit 1
fi

echo "============================================================================="
echo " WARNING: THIS WILL OVERWRITE THE CURRENT DATABASE: lms_db"
echo "============================================================================="
read -rp "Are you sure you want to restore from $BACKUP_FILE? (yes/NO): " CONFIRM

if [[ "$CONFIRM" != "yes" ]]; then
    echo "Restore canceled."
    exit 0
fi

echo "Stopping application services before restore..."
docker compose stop backend webhooks-worker frontend

echo "Restoring database from compressed archive..."
gunzip -c "$BACKUP_FILE" | docker compose exec -T postgres psql -U lms_migrator -d lms_db

echo "Restarting application services..."
docker compose start backend webhooks-worker frontend

echo "=== Database restore completed successfully! ==="

