.PHONY: up down logs migrate demo demo-remove jobs test test-api test-web lint lint-api lint-web e2e fmt

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api web

migrate:
	docker compose exec api alembic upgrade head

demo:
	docker compose exec api python -m app.demo.seed

demo-remove:
	docker compose exec api python -m app.demo.seed --remove

jobs:
	docker compose exec api python -m app.workflow.jobs all

test: test-api test-web

test-api:
	docker compose exec api pytest -q

test-web:
	cd frontend && npm run test

lint: lint-api lint-web

lint-api:
	docker compose exec api ruff check .
	docker compose exec api ruff format --check .
	docker compose exec api mypy app

lint-web:
	cd frontend && npm run lint && npm run format:check && npm run typecheck

e2e:
	cd frontend && npx playwright test

fmt:
	docker compose exec api ruff format .
	docker compose exec api ruff check --fix .
	cd frontend && npm run format
