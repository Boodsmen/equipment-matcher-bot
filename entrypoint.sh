#!/bin/bash
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Importing CSV data..."
python scripts/import_csv.py

echo "Starting bot..."
exec python bot.py
