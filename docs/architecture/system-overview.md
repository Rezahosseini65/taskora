# Taskora — System Overview

## 1. Introduction

Taskora is a web-based SaaS platform for project management and team collaboration. It aims to help teams organize projects, manage tasks, coordinate activities, and collaborate efficiently in a centralized workspace.

The platform is designed to support multiple teams and organizations while maintaining clear boundaries between their data and resources.

## 2. Project Goals

The primary goals of Taskora are:

- Provide centralized project and task management.
- Support team collaboration and communication.
- Organize users, teams, projects, and workspaces.
- Provide secure authentication and authorization.
- Support scalable background processing.
- Maintain a modular and maintainable backend architecture.
- Provide a foundation for future integrations and features.

## 3. System Architecture

Taskora follows a modular monolith architecture.

The backend is implemented using Django and Django REST Framework. PostgreSQL is the primary relational database, while Redis is used for caching and Celery message brokering.

The application is containerized using Docker Compose.

### High-Level Components

- **Client Application:** The frontend application that communicates with the backend through REST APIs.
- **Nginx:** Acts as a reverse proxy and entry point for HTTP requests.
- **Django Backend:** Handles business logic, authentication, authorization, and API requests.
- **PostgreSQL:** Stores persistent application data.
- **Redis:** Provides caching and message brokering.
- **Celery Workers:** Execute asynchronous background tasks.
- **Celery Beat:** Schedules periodic background tasks.

## 4. Technology Stack

| Component | Technology |
|---|---|
| Backend Language | Python |
| Backend Framework | Django |
| API Framework | Django REST Framework |
| Primary Database | PostgreSQL |
| Cache | Redis |
| Task Queue | Celery |
| Task Scheduler | Celery Beat |
| Reverse Proxy | Nginx |
| Containerization | Docker |
| Container Orchestration | Docker Compose |
| Dependency Management | uv |
| Version Control | Git |
| Repository Hosting | GitLab |

## 5. Backend Structure

The backend is organized around Django applications and shared infrastructure modules.

```text
backend/
├── apps/
├── common/
│   ├── exceptions/
│   ├── middleware/
│   ├── models/
│   ├── permissions/
│   └── utils/
├── config/
│   └── settings/
├── manage.py
├── pyproject.toml
└── uv.lock
```

### Core Directories

- `apps/`: Contains independent business-domain Django applications.
- `common/`: Contains reusable components shared across applications.
- `config/`: Contains Django project configuration, settings, URLs, and application entry points.

## 6. Data Storage

PostgreSQL is the primary data store.

Redis is used for application caching and Celery infrastructure.

Database schema design documents are maintained separately under:

```text
database/
├── backups/
├── schema/
└── seeds/
```

Django models and migrations are the source of truth for the actual application database schema. DBML and SQL files serve as design and reference artifacts.

## 7. Background Processing

Taskora uses Celery for asynchronous task execution.

Redis acts as the message broker and result backend.

Celery Beat is responsible for scheduling periodic tasks.

Potential background workloads include:

- Sending notifications and emails.
- Processing scheduled operations.
- Performing resource-intensive tasks.
- Running periodic maintenance operations.

## 8. Security Considerations

The system follows these security principles:

- Sensitive configuration values are provided through environment variables.
- Secret files such as `.env` are excluded from version control.
- Authentication and authorization are handled by the backend.
- CORS policies are explicitly configured.
- Production deployment must use secure transport and appropriate security headers.
- Database access is restricted to application infrastructure.

## 9. Development and Deployment

The development environment is managed through Docker Compose.

The backend dependencies are managed with uv.

Environment-specific Django settings are separated into:

- `development.py`
- `production.py`
- `test.py`

Production deployment configuration is maintained separately from the development environment and will be completed as the deployment architecture evolves.

## 10. Future Considerations

The architecture is intended to evolve with the product.

Potential future improvements include:

- Frontend application integration.
- API versioning.
- Advanced permission and role management.
- Real-time collaboration features.
- Monitoring and observability.
- Automated testing and CI/CD pipelines.
- Horizontal scaling of background workers and application services.

---

**Document Status:** Initial Architecture Overview  
**Project:** Taskora  
**Architecture Style:** Modular Monolith