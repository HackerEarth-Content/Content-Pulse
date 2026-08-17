RUN := docker compose run --rm --no-deps api

.PHONY: up down logs migrate revision seed test

up:       ; docker compose up -d && docker compose logs -f api web
down:     ; docker compose down
logs:     ; docker compose logs -f
migrate:  ; $(RUN) uv run alembic upgrade head
revision: ; $(RUN) uv run alembic revision --autogenerate -m "$(m)"
seed:     ; $(RUN) uv run python -m scripts.seed --import /legacy.sqlite3
test:     ; $(RUN) uv run pytest -q
