#!/usr/bin/env bash
# =============================================================================
# Automated PostgreSQL Production Backup Script
# Usage: ./scripts/backup-db.sh [backup_destination_dir]
# =============================================================================
set -euo pipefail

BACKUP_DIR="${1:-./backups}"
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date -u +"%Y%m%d_%H%M%SZ")
BACKUP_FILE="${BACKUP_DIR}/lms_db_${TIMESTAMP}.sql.gz"

echo "=== Starting database backup: $BACKUP_FILE ==="

# Execute pg_dump inside running postgres container
docker compose exec -T postgres pg_dump -U lms_migrator lms_db | gzip > "$BACKUP_FILE"

chmod 600 "$BACKUP_FILE"

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "=== Backup completed successfully! ($SIZE) ==="

# Retain backups for 14 days; delete older backups
find "$BACKUP_DIR" -type f -name "lms_db_*.sql.gz" -mtime +14 -delete
echo "Cleaned backups older than 14 days."

