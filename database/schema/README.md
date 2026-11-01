# Database Schema Documentation

This directory contains the database schema design documentation for Taskora.

## Files

| File | Description |
|---|---|
| `taskora.dbml` | Main database schema definition written in DBML format. |
| `taskora.sql` | PostgreSQL SQL representation of the database schema. |

## DBML

The `taskora.dbml` file is the primary reference for the database diagram.

It can be imported into [dbdiagram.io](https://dbdiagram.io/) to visualize, review, and modify the database structure.

## PostgreSQL SQL

The `taskora.sql` file contains the PostgreSQL representation of the schema, including tables, columns, constraints, and relationships supported by the exported diagram.

This file is maintained as a reference and is not intended to be executed automatically during application startup.

## Django Migrations

Django migrations are the authoritative mechanism for managing database schema changes in Taskora.

The database models and their migrations will be maintained within their respective Django applications.

The DBML and SQL files serve as design references and should be kept consistent with the actual Django models and migrations.

## Maintenance Guidelines

- Update the DBML file whenever the database design changes.
- Regenerate the PostgreSQL SQL export when necessary.
- Review schema changes before implementing them in Django models.
- Do not manually modify the production database schema outside the Django migration workflow.
- Keep database design documentation synchronized with the application architecture.