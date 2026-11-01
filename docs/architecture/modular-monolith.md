# Taskora — Modular Monolith Architecture

## 1. Introduction

Taskora uses a Modular Monolith architecture for its backend.

In this architectural style, the application is deployed as a single backend system while its internal codebase is divided into independent business modules.

Each module is responsible for a specific business domain and should maintain clear boundaries from other modules.

The goal is to combine the simplicity of a monolithic deployment with the maintainability and separation of concerns found in modular systems.

## 2. Architectural Goals

The main goals of this architecture are:

- Maintain clear business-domain boundaries.
- Reduce coupling between Django applications.
- Improve code organization and maintainability.
- Enable independent development of business modules.
- Simplify deployment and infrastructure management.
- Support future growth without requiring an early transition to microservices.

## 3. Project Structure

The backend follows this high-level structure:

```text
backend/
├── apps/
│   ├── __init__.py
│   └── [business applications]
├── common/
│   ├── exceptions/
│   ├── middleware/
│   ├── models/
│   ├── permissions/
│   └── utils/
├── config/
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   ├── production.py
│   │   └── test.py
│   ├── celery.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── manage.py
├── pyproject.toml
└── uv.lock
```

Business applications will be added under `apps/` as the domain model evolves.

## 4. Module Responsibilities

Each business application should represent a clearly defined domain.

Potential modules include:

| Module | Responsibility |
|---|---|
| Users | User accounts and profile management |
| Organizations | Organization and workspace management |
| Teams | Team membership and management |
| Projects | Project lifecycle and configuration |
| Tasks | Task creation, assignment, and tracking |
| Comments | Discussions and task comments |
| Notifications | User notifications |
| Activity | Tracking important system activities |

These are proposed business boundaries, not necessarily implemented applications.

## 5. Module Boundaries

Each module should:

- Own its business logic.
- Define and maintain its own data models.
- Expose clear interfaces for other modules.
- Avoid directly modifying another module's internal implementation.
- Keep its API and business rules close to its domain.
- Minimize dependencies on unrelated modules.

Cross-module communication should use explicit interfaces, services, or other well-defined integration mechanisms.

## 6. Shared Components

The `common/` package contains reusable infrastructure and utilities.

Its responsibilities include:

- Shared abstract models.
- Common exceptions.
- Reusable middleware.
- Shared permission utilities.
- General-purpose helper functions.

The common package must not become a place for unrelated business logic.

Business-specific rules should remain inside their corresponding applications.

## 7. Dependency Management

Dependencies between modules should follow these principles:

1. Avoid circular dependencies.
2. Prefer explicit interfaces over direct access to internal implementation.
3. Keep dependencies between business modules minimal.
4. Place genuinely shared infrastructure in `common/`.
5. Keep configuration and application registration in `config/`.

The dependency direction should remain understandable and predictable.

## 8. Database Ownership

Each business module is responsible for its own Django models and business-level data rules.

All modules share the same PostgreSQL database.

Database relationships between modules must be designed carefully to avoid unnecessary coupling.

Django migrations are the source of truth for database schema changes.

## 9. API Organization

The backend exposes APIs through Django REST Framework.

Each business module should organize its API components within its own application.

Depending on module complexity, an application may contain:

- Serializers.
- Views or viewsets.
- URL configuration.
- Permissions.
- Filters.
- API-specific services.

API routing is integrated through the central project URL configuration.

## 10. Background Tasks

Modules may define their own Celery tasks for asynchronous operations.

Background tasks should remain associated with the business domain that owns the operation.

Shared task infrastructure is configured centrally through the Celery application.

## 11. Testing Strategy

Each module should be testable independently.

The testing strategy should include:

- Unit tests for business logic.
- Model tests for data constraints and behavior.
- API tests for endpoint behavior.
- Integration tests for interactions between modules.

Tests should verify both individual module behavior and important cross-module workflows.

## 12. Evolution Strategy

The modular monolith is the initial architectural choice for Taskora.

Microservices are not an initial requirement.

If future scaling or organizational needs justify separating a module into an independent service, its existing boundaries should make that transition easier.

Such a transition should be based on measurable technical or business requirements rather than architectural trends.

---

**Document Status:** Initial Architecture Design  
**Project:** Taskora  
**Backend Architecture:** Modular Monolith  
**Database:** Shared PostgreSQL