# Database Seed Data

This directory contains seed data definitions and scripts for initializing the Taskora database.

## Purpose

Seed data provides the initial records required for development, testing, and predefined application functionality.

Examples include:

- Default workspace settings
- Predefined roles and permissions
- System-level configuration records
- Reference data required by application modules

## Directory Structure

```text
seeds/
├── README.md
└── .gitkeep
```

As the project grows, seed scripts may be organized by application or environment.

## Seed Data Management

Taskora uses Django management commands and application-level data migrations to manage initial data.

The preferred approach depends on the type of data:

| Data Type | Recommended Approach |
|---|---|
| Required reference data | Django data migrations |
| Development sample data | Custom Django management commands |
| Test data | pytest fixtures and factories |
| Environment-specific configuration | Environment variables |

## Guidelines

- Seed scripts must be repeatable whenever possible.
- Avoid creating duplicate records when running seed commands multiple times.
- Never store passwords, API keys, or other secrets in seed files.
- Do not include real customer or production data in development seeds.
- Keep seed data consistent with Django models.
- Clearly document any required execution order.

## Important

Database seed scripts are not a replacement for Django migrations.

Database schema changes must be managed through Django migrations, while seed scripts are responsible for initializing application data.
