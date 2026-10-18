#!/usr/bin/env bash
# =============================================================================
# LMS Production Cryptographic Secret & Configuration Generator
# Usage: ./scripts/generate-keys.sh [domain.com]
# =============================================================================
set -euo pipefail

DOMAIN="${1:-}"

if [[ -z "$DOMAIN" ]]; then
    read -rp "Enter your production domain (e.g., lms.yourdomain.com): " DOMAIN
fi

if [[ -z "$DOMAIN" ]]; then
    echo "Error: Domain name cannot be empty." >&2
    exit 1
fi

TARGET_ENV=".env.production"

if [[ -f "$TARGET_ENV" ]]; then
    echo "Warning: $TARGET_ENV already exists."
    read -rp "Do you want to overwrite it? (y/N): " CONFIRM
    if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
        echo "Aborted without overwriting $TARGET_ENV."
        exit 0
    fi
    cp "$TARGET_ENV" "${TARGET_ENV}.bak.$(date +%s)"
    echo "Backup saved to ${TARGET_ENV}.bak.*"
fi

echo "Generating cryptographically secure secrets..."

JWT_SECRET=$(openssl rand -hex 32)
MASTER_KEY=$(openssl rand -base64 32)
MIGRATOR_PW=$(openssl rand -hex 24)
RUNTIME_PW=$(openssl rand -hex 24)
REDIS_PW=$(openssl rand -hex 24)
ADMIN_PW=$(openssl rand -hex 16)

cat > "$TARGET_ENV" <<EOF
# Generated automatically by scripts/generate-keys.sh on $(date -u +"%Y-%m-%d %H:%M:%SZ")

APP_ENVIRONMENT=production
APP_NAME=LMS
APP_VERSION=1.0.0
APP_DEBUG=false

SERVER_HOST=0.0.0.0
SERVER_PORT=8000
SERVER_FORWARDED_ALLOW_IPS=127.0.0.1,172.16.0.0/12,10.0.0.0/8

API_PREFIX=/api/v1
API_CORS_ORIGINS=https://${DOMAIN}
API_TRUSTED_HOSTS=${DOMAIN},backend

DATABASE_HOST=postgres
DATABASE_PORT=5432
DATABASE_NAME=lms_db
DATABASE_MIGRATION_USER=lms_migrator
DATABASE_MIGRATION_PASSWORD=${MIGRATOR_PW}
DATABASE_RUNTIME_USER=lms_runtime
DATABASE_RUNTIME_PASSWORD=${RUNTIME_PW}
DATABASE_SSL_MODE=require
DATABASE_ECHO_SQL=false

REDIS_PASSWORD=${REDIS_PW}
REALTIME_ENABLED=true
REALTIME_BACKEND=redis
REALTIME_REDIS_URL=redis://:${REDIS_PW}@redis:6379/0

SECURITY_JWT_SECRET=${JWT_SECRET}
SECURITY_MASTER_ENCRYPTION_KEY=${MASTER_KEY}

STORAGE_MODE=local
STORAGE_LOCAL_PATH=/app/var/storage
STORAGE_MAX_UPLOAD_BYTES=104857600

MAIL_ENABLED=false
MAIL_SUPPRESS_SEND=false
MAIL_APP_URL=https://${DOMAIN}

LMS_ADMIN_PASSWORD=${ADMIN_PW}

LOG_LEVEL=INFO
LOG_FORMAT=json
EOF

chmod 600 "$TARGET_ENV"

echo "============================================================================="
echo " SUCCESS! Created hardened production configuration: $TARGET_ENV"
echo " Permissions set to 600 (owner read/write only)."
echo "============================================================================="
echo " Initial Super Admin Password: ${ADMIN_PW}"
echo " Domain Configured:            ${DOMAIN}"
echo "============================================================================="
echo "Save the Initial Super Admin Password in your secure password manager now."
echo "You can now run: docker compose up -d"

