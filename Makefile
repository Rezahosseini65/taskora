# Taskora - Development Commands

.PHONY: help up down restart build rebuild ps logs logs-web logs-db logs-redis migrate makemigrations createsuperuser shell dbshell collectstatic

# Default target
.DEFAULT_GOAL := help

# Display available commands
help:
	@echo "Taskora Development Commands"
	@echo "----------------------------"
	@echo "make up              - Start development services"
	@echo "make down            - Stop development services"
	@echo "make restart         - Restart development services"
	@echo "make build           - Build Docker images"
	@echo "make rebuild         - Rebuild images without cache"
	@echo "make ps              - Show running containers"
	@echo "make logs            - Follow all service logs"
	@echo "make logs-web        - Follow Django logs"
	@echo "make logs-db         - Follow PostgreSQL logs"
	@echo "make logs-redis      - Follow Redis logs"
	@echo "make migrate         - Apply Django migrations"
	@echo "make makemigrations  - Create Django migrations"
	@echo "make createsuperuser - Create Django superuser"
	@echo "make shell           - Open Django shell"
	@echo "make dbshell         - Open PostgreSQL shell"
	@echo "make collectstatic   - Collect static files"

# Docker Compose commands
up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose restart

build:
	docker compose build

rebuild:
	docker compose build --no-cache

ps:
	docker compose ps

# Logs
logs:
	docker compose logs -f

logs-web:
	docker compose logs -f web

logs-db:
	docker compose logs -f db

logs-redis:
	docker compose logs -f redis

# Django commands
migrate:
	docker compose exec web python manage.py migrate

makemigrations:
	docker compose exec web python manage.py makemigrations

createsuperuser:
	docker compose exec web python manage.py createsuperuser

shell:
	docker compose exec web python manage.py shell

collectstatic:
	docker compose exec web python manage.py collectstatic --noinput

# PostgreSQL shell
dbshell:
	docker compose exec db psql -U "$${POSTGRES_USER}" -d "$${POSTGRES_DB}"