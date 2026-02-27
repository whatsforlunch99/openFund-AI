#!/usr/bin/env bash
#
# Create the PostgreSQL database "openfund" for OpenFund-AI.
# Run from project root:  ./scripts/create_db.sh
#
# If createdb is not in your PATH (e.g. "command not found: createdb"),
# this script tries common Homebrew PostgreSQL paths first.
#
set -e

export PATH="/opt/homebrew/opt/postgresql@16/bin:/opt/homebrew/opt/postgresql@15/bin:/opt/homebrew/opt/postgresql@14/bin:/opt/homebrew/opt/postgresql/bin:/usr/local/opt/postgresql@16/bin:/usr/local/opt/postgresql@15/bin:/usr/local/opt/postgresql/bin:$PATH"

DB_NAME="openfund"

if command -v createdb &>/dev/null; then
  if createdb "$DB_NAME" 2>/dev/null; then
    echo "Created database: $DB_NAME"
    exit 0
  fi
  if psql -lqt 2>/dev/null | cut -d \| -f 1 | grep -qw "$DB_NAME"; then
    echo "Database $DB_NAME already exists."
    exit 0
  fi
fi

if command -v psql &>/dev/null; then
  if psql -h localhost -d postgres -c "CREATE DATABASE $DB_NAME;" 2>/dev/null; then
    echo "Created database: $DB_NAME"
    exit 0
  fi
fi

echo "Could not create database '$DB_NAME'."
echo "Add PostgreSQL to your PATH, then run one of:"
echo "  createdb $DB_NAME"
echo "  psql -h localhost -d postgres -c \"CREATE DATABASE $DB_NAME;\""
echo ""
echo "Homebrew PostgreSQL (add to ~/.zshrc or run before createdb):"
echo '  export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"   # or postgresql@15, postgresql'
exit 1
