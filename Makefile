.PHONY: up down build logs ps reset-db seed shell-db shell-api test

up:
	docker compose up --build -d
	@echo "API:      http://localhost:8420/docs"
	@echo "Frontend: http://localhost:5180"
	@echo "Postgres: localhost:5480"

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

ps:
	docker compose ps

# Borra TODO (contenedores + volumen de datos de Postgres) y arranca limpio.
reset-db:
	docker compose down -v
	docker compose up --build -d

seed:
	docker compose exec api python -m scripts.seed_db

shell-db:
	docker compose exec db psql -U $${POSTGRES_USER:-oleodata} -d $${POSTGRES_DB:-oleodata}

shell-api:
	docker compose exec api bash

test:
	docker compose exec api pytest -q
