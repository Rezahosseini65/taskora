# Taskora

**A modern SaaS project management platform built with Django and PostgreSQL.**

Taskora is an actively developed project focused on building a scalable and maintainable project management platform. It follows a **Modular Monolith architecture** and uses modern backend technologies to provide a solid foundation for team collaboration, task management, and workflow automation.

> **Project Status:** Under active development.

## Overview

Taskora aims to provide teams with a centralized platform for organizing projects, managing tasks, and collaborating efficiently.

The project emphasizes clean architecture, maintainability, security, and scalability from the beginning.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Backend programming language |
| Django | Web framework |
| Django REST Framework | REST API development |
| PostgreSQL | Primary relational database |
| Redis | Message broker and caching infrastructure |
| Celery | Asynchronous task processing |
| Celery Beat | Periodic task scheduling |
| Docker & Docker Compose | Containerization and services |
| uv | Python dependency management |
| Nginx | Reverse proxy |
| Git & GitHub | Version control |

## Architecture

Taskora follows a **Modular Monolith** architecture.

The backend is organized into independent Django applications, each responsible for a specific business domain. This approach keeps the codebase modular while avoiding the operational complexity of premature microservices.

Key architectural components include:

- Domain-oriented Django applications
- Shared infrastructure and common utilities
- PostgreSQL for persistent data
- Redis for caching and asynchronous processing infrastructure
- Celery workers for background tasks
- Celery Beat for scheduled tasks
- Transactional Outbox pattern for reliable event dispatching

## Current Development Progress

The following foundations have been implemented:

- Docker-based development environment
- Django project configuration with separate development, production, and test settings
- Custom user model and user management
- User registration and authentication API foundations
- JWT authentication with HttpOnly cookie support
- CSRF protection for cookie-based authentication
- Redis-based email verification OTP services
- Temporary verification lockout and resend cooldown mechanisms
- Asynchronous email delivery infrastructure
- Transactional Outbox core implementation
- Event handler registry and Outbox dispatcher
- Periodic Outbox processing using Celery Beat
- Initial application tests and architecture documentation

**Note:** Some authentication and email verification components are still being integrated into the complete registration and verification workflow.

## Project Structure

```text
taskora/
├── backend/
│   ├── apps/
│   │   ├── users/
│   │   └── outbox/
│   ├── common/
│   │   ├── authentication/
│   │   ├── exceptions/
│   │   ├── middleware/
│   │   ├── models/
│   │   └── utils/
│   ├── config/
│   │   └── settings/
│   ├── manage.py
│   ├── pyproject.toml
│   └── uv.lock
├── database/
├── docker/
├── docs/
├── scripts/
├── docker-compose.yml
├── docker-compose.prod.yml
├── Makefile
├── README.md
└── .env.example
```

## Getting Started

### Prerequisites

Make sure you have the following installed:

- Git
- Docker
- Docker Compose

### 1. Clone the repository

```bash
git clone https://github.com/Rezahosseini65/taskora.git

cd taskora
```

### 2. Configure environment variables

Create your local environment file:

```bash
cp .env.example .env
```

Review the environment variables and configure them for your local environment.

**Never commit your actual `.env` file or expose secrets.**

### 3. Start the development environment

```bash
docker compose up --build -d
docker compose ps
```

### 4. Apply database migrations

```bash
docker compose exec web python manage.py migrate
```

### 5. Check the application

```bash
docker compose exec web python manage.py check
```

The Django development server is available at:

```text
http://localhost:8000/
```

## Running Tests

Run the Django test suite inside the web container:

```bash
docker compose exec web python manage.py test
```

To run tests for a specific application:

```bash
docker compose exec web python manage.py test apps.users

docker compose exec web python manage.py test apps.outbox
```

## Roadmap

Taskora is being developed incrementally. Planned areas of development include:

- [x] Initial project infrastructure
- [x] Custom user model and authentication foundations
- [x] Redis-based OTP services
- [x] Transactional Outbox infrastructure
- [ ] Complete email verification workflow
- [ ] Project and workspace management
- [ ] Task management
- [ ] Team management and role-based access control
- [ ] Kanban boards
- [ ] Multi-tenancy
- [ ] Real-time collaboration
- [ ] Workflow automation
- [ ] Production deployment and monitoring

## Contributing

Taskora is currently under active development.

Contributions, suggestions, and feedback are welcome. If you find a bug or have an idea for improvement, feel free to open an issue.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---

**Built with Python, Django, and a focus on clean architecture.**
