# Database Backup and Restore

This directory is intended for storing PostgreSQL database backup files for Taskora.

## Purpose

Database backups help protect application data and support database recovery in case of data loss, corruption, or infrastructure failure.

## Backup Format

PostgreSQL backups may be stored in the following formats:

| Format | Description |
|---|---|
| `.sql` | Plain-text SQL dump |
| `.dump` | PostgreSQL custom-format backup |
| `.backup` | Backup file using a custom naming convention |

## Creating a Backup

A PostgreSQL custom-format backup can be created using `pg_dump`:

```bash
docker compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > database/backups/taskora.dump
```

## Restoring a Backup

A custom-format backup can be restored using `pg_restore`:

```bash
cat database/backups/taskora.dump | docker compose exec -T db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists
```

**Warning:** Restoring a backup can overwrite or remove existing database objects. Always verify the target database and backup file before restoring.

## Backup Guidelines

- Create backups regularly.
- Verify backup files after creation.
- Test restoration periodically.
- Store production backups securely outside the application repository.
- Never commit real database backups or customer data to Git.
- Encrypt backups containing sensitive information.
- Define a retention policy for old backups.

## Important

The `backups/` directory is for local development and temporary backup operations.

Production backups should be stored in a secure, access-controlled external storage location.
