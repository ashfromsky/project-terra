#!/usr/bin/env bash
# ==============================================================================
# PROJECT TERRA — PostgreSQL Multi-Database Initialization Script
# Executed on first container boot by the official PostgreSQL entrypoint.
# Creates separate, isolated databases for Core and GHS.
# ==============================================================================

set -euo pipefail

echo "[PROJECT-TERRA-INIT] Initializing isolated PostgreSQL databases..."

# 1. Create terra_core and terra_ghs databases
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE terra_core'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'terra_core')\gexec

    SELECT 'CREATE DATABASE terra_ghs'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'terra_ghs')\gexec

    GRANT ALL PRIVILEGES ON DATABASE terra_core TO "$POSTGRES_USER";
    GRANT ALL PRIVILEGES ON DATABASE terra_ghs TO "$POSTGRES_USER";
EOSQL

# 2. Grant public schema permissions in terra_core
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "terra_core" <<-EOSQL
    GRANT ALL ON SCHEMA public TO "$POSTGRES_USER";
EOSQL

# 3. Grant public schema permissions in terra_ghs
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "terra_ghs" <<-EOSQL
    GRANT ALL ON SCHEMA public TO "$POSTGRES_USER";
EOSQL

echo "[PROJECT-TERRA-INIT] Database initialization complete: terra_core and terra_ghs created successfully."
