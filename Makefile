.PHONY: up up-infra up-app up-full down migrate seed seed-eval seed-demo test eval lint format

up: up-infra

up-infra:
	docker compose up -d postgres redis minio

up-app:
	docker compose up -d backend worker frontend

up-full:
	docker compose --profile observability up -d

down:
	docker compose down

migrate:
	python -m alembic -c alembic/alembic.ini upgrade head

seed:
	python -m scripts.seed_workspaces

seed-eval:
	python -m scripts.seed_eval_cases

seed-demo:
	python -m scripts.seed_demo

test:
	python -m pytest tests -v

eval:
	python -m pytest tests/eval -v

lint:
	python -m ruff check src tests scripts alembic

format:
	python -m ruff format src tests scripts alembic

