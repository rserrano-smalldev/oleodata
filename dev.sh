#!/usr/bin/env bash
# Wrapper de comandos habituales para no tener que recordar la sintaxis de
# docker compose en cada sesión de desarrollo. Uso: ./dev.sh <comando>
set -euo pipefail
cd "$(dirname "$0")"

cmd="${1:-help}"

case "$cmd" in
  up)
    docker compose up --build -d
    echo "API:      http://localhost:${API_PORT:-8420}/docs"
    echo "Frontend: http://localhost:${FRONTEND_PORT:-5180}"
    echo "Postgres: localhost:${DB_PORT:-5480}"
    ;;
  down)
    docker compose down
    ;;
  logs)
    docker compose logs -f "${2:-}"
    ;;
  ps)
    docker compose ps
    ;;
  reset-db)
    echo "Esto borra el volumen oleodata_pgdata (todos los datos). Ctrl+C para cancelar."
    sleep 3
    docker compose down -v
    docker compose up --build -d
    ;;
  seed)
    docker compose exec api python -m scripts.seed_db
    ;;
  test)
    docker compose exec api pytest -q
    ;;
  shell-db)
    docker compose exec db psql -U "${POSTGRES_USER:-oleodata}" -d "${POSTGRES_DB:-oleodata}"
    ;;
  shell-api)
    docker compose exec api bash
    ;;
  *)
    cat <<EOF
Uso: ./dev.sh <comando>

  up         Construye y levanta todo (db, api, frontend) en segundo plano
  down       Para los contenedores (conserva los datos)
  logs [srv] Sigue los logs de todos los servicios o de uno concreto
  ps         Estado de los contenedores
  reset-db   BORRA el volumen de Postgres y arranca completamente limpio
  seed       Vuelve a ejecutar el seed de catálogos (idempotente)
  test       Ejecuta la suite de tests dentro del contenedor de la API
  shell-db   Abre psql dentro del contenedor de la base de datos
  shell-api  Abre una shell dentro del contenedor de la API
EOF
    ;;
esac
