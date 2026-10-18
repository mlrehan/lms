#!/bin/sh
set -e

echo "=== Initializing PostgreSQL Database Roles and Privileges ==="

# Check if a dedicated runtime user is configured and distinct from POSTGRES_USER
if [ -n "$DATABASE_RUNTIME_USER" ] && [ "$DATABASE_RUNTIME_USER" != "$POSTGRES_USER" ]; then
    echo "Creating dedicated least-privilege runtime role: $DATABASE_RUNTIME_USER"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
        DO \$\$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$DATABASE_RUNTIME_USER') THEN
                CREATE ROLE "$DATABASE_RUNTIME_USER" WITH LOGIN PASSWORD '$DATABASE_RUNTIME_PASSWORD';
            ELSE
                ALTER ROLE "$DATABASE_RUNTIME_USER" WITH PASSWORD '$DATABASE_RUNTIME_PASSWORD';
            END IF;
        END
        \$\$;

        GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO "$DATABASE_RUNTIME_USER";
        GRANT USAGE ON SCHEMA public TO "$DATABASE_RUNTIME_USER";
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "$DATABASE_RUNTIME_USER";
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "$DATABASE_RUNTIME_USER";

        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "$DATABASE_RUNTIME_USER";
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO "$DATABASE_RUNTIME_USER";
EOSQL
    echo "Least-privilege role $DATABASE_RUNTIME_USER configured successfully."
else
    echo "Runtime user is identical to migration user ($POSTGRES_USER); skipping separate role creation."
fi

