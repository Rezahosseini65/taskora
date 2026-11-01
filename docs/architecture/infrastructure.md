# Taskora — Infrastructure Architecture

## 1. Introduction

This document describes the infrastructure architecture of Taskora, including application runtime, containerization, database, caching, background processing, networking, and deployment components.

The infrastructure is designed to provide a consistent development environment and a foundation for production deployment.

## 2. Infrastructure Overview

Taskora uses Docker Compose to manage its development infrastructure.

The main infrastructure components are:

- Django: Backend application and REST API.
- PostgreSQL: Primary relational database.
- Redis: Cache and Celery message broker.
- Celery Worker: Asynchronous task execution.
- Celery Beat: Periodic task scheduling.
- Nginx: Reverse proxy and HTTP entry point.

### Component Communication

```text
                    Client
                      |
                      v
                    Nginx
                      |
                      v
                Django Backend
                 /     |     \
                v      v      v
           PostgreSQL Redis  Celery
                             Worker
                               |
                               v
                            Redis
```

Celery Beat publishes scheduled tasks through the configured message broker. Celery workers consume and execute those tasks.

## 3. Containerization

Docker is used to package and run infrastructure components consistently.

Docker Compose manages the services and their dependencies.

The main configuration files are:

```text
docker-compose.yml
docker-compose.prod.yml
```

- `docker-compose.yml`: Development environment configuration.
- `docker-compose.prod.yml`: Reserved for production deployment configuration.

Production configuration is currently a placeholder and must be completed before production deployment.

## 4. Backend Container

The backend runs using a custom Docker image defined in:

```text
docker/django/Dockerfile
```

Python dependencies are managed with uv.

The project uses a dependency lock file to ensure reproducible dependency installation:

```text
backend/pyproject.toml
backend/uv.lock
```

The Django application runs inside the container and uses environment-specific settings.

## 5. Database Infrastructure

### PostgreSQL

PostgreSQL is the primary persistent data store.

Database connection settings are provided through environment variables.

The development database is managed as a Docker Compose service.

Database-related resources are organized under:

```text
database/
├── backups/
├── schema/
└── seeds/
```

### Database Schema Management

Django models and migrations are the source of truth for the application database schema.

The DBML and SQL files under `database/schema/` are design and reference artifacts.

### Backup Strategy

Database backups are stored separately from application source code.

Backup files must not be committed to the Git repository.

The backup and restore procedures are documented in:

```text
database/backups/README.md
```

## 6. Redis Infrastructure

Redis is used for multiple infrastructure purposes.

The current configuration separates Redis logical databases by responsibility:

| Redis Database | Purpose |
|---|---|
| DB 0 | Celery message broker |
| DB 1 | Celery result backend |
| DB 2 | Django cache |

Redis connection details are provided through environment variables.

Redis is managed as a Docker Compose service in the development environment.

## 7. Background Processing

Celery provides asynchronous task processing.

### Celery Worker

Workers consume messages from the configured Redis broker and execute background tasks.

### Celery Beat

Celery Beat schedules periodic tasks and publishes them to the message broker.

### Result Backend

The Celery result backend is configured to use Redis.

Django Celery Results and Django Celery Beat are also included in the backend dependencies for database-backed task results and scheduling capabilities when required.

The actual task execution and scheduling configuration should be kept consistent across environments.

## 8. Reverse Proxy and Networking

Nginx is included as the reverse proxy layer.

Its Docker configuration is maintained under:

```text
docker/nginx/
├── Dockerfile
└── default.conf
```

Nginx is responsible for routing incoming HTTP requests to the appropriate backend service and can serve as the entry point for static and media resources according to the deployment configuration.

Internal infrastructure services should communicate through the Docker Compose network.

Database and Redis services should not be exposed publicly in production.

## 9. Environment Configuration

Environment-specific configuration is provided through environment variables.

The project uses:

```text
.env
.env.example
```

- `.env`: Local environment configuration containing actual values and secrets.
- `.env.example`: Template containing the required environment variable names and example values.

The `.env` file must never be committed to version control.

Sensitive production values must be provided through a secure environment configuration or secrets management mechanism.

### Django Settings

Django settings are separated by environment:

```text
backend/config/settings/
├── base.py
├── development.py
├── production.py
└── test.py
```

Shared configuration belongs in `base.py`, while environment-specific behavior belongs in the corresponding settings module.

## 10. Development Environment

The development environment is designed to run through Docker Compose.

Developers can use the root Makefile to execute common infrastructure and Django management commands.

Typical operations include:

- Starting and stopping services.
- Rebuilding containers.
- Viewing service logs.
- Running database migrations.
- Opening Django and database shells.
- Collecting static files.

The development environment should remain reproducible across developer machines.

## 11. Production Environment

Production deployment configuration is maintained separately from development configuration.

Before production deployment, the following areas must be completed and verified:

- Production Docker Compose services.
- Secure environment and secret management.
- HTTPS configuration and TLS certificates.
- Production-grade Django application server.
- Nginx production configuration.
- Database persistence and backup procedures.
- Redis persistence and availability requirements.
- Static and media file handling.
- Logging, monitoring, and health checks.
- Resource limits and restart policies.
- Database migration and deployment procedures.

The current production configuration files are placeholders and must not be considered production-ready.

## 12. CI/CD

GitLab is used for repository hosting.

The project contains reserved configuration files for future CI/CD implementation:

```text
.gitlab-ci.yml
.gitlab/
└── ci/
    ├── build.yml
    ├── deploy.yml
    └── test.yml
```

These files are currently placeholders.

CI/CD pipelines will be implemented after the testing strategy and deployment requirements are established.

## 13. Infrastructure Security

Infrastructure security principles include:

- Never commit secrets or credentials.
- Restrict database and Redis access to trusted services.
- Use HTTPS in production.
- Disable Django debug mode in production.
- Configure allowed hosts explicitly.
- Apply appropriate CORS policies.
- Use secure production database credentials.
- Keep dependencies updated.
- Maintain regular database backups.

## 14. Future Improvements

Potential infrastructure improvements include:

- Automated CI/CD pipelines.
- Centralized logging.
- Application performance monitoring.
- Infrastructure metrics and alerting.
- Automated backup scheduling.
- Object storage for uploaded media.
- Production deployment automation.
- Horizontal scaling of application and worker services.

---

**Document Status:** Initial Infrastructure Design  
**Project:** Taskora  
**Containerization:** Docker Compose  
**Primary Database:** PostgreSQL  
**Cache and Message Broker:** Redis  
**Background Processing:** Celery  
**Reverse Proxy:** Nginx