# Taskora — Users App Checklist

## 1. Project Setup
- [x] Create users app
- [x] Register users app in Django settings
- [x] Configure custom User model
- [x] Configure AUTH_USER_MODEL

## 2. User Model
- [x] Define UUID primary key
- [x] Define email field
- [x] Define account status choices
- [x] Add email verification timestamp
- [x] Add locale and timezone fields
- [x] Add created_at and updated_at
- [x] Add soft-delete timestamp
- [x] Add staff and active flags
- [x] Configure model managers
- [x] Configure model metadata

## 3. User Managers
- [x] Implement UserQuerySet
- [x] Implement alive() and deleted()
- [x] Implement bulk soft_delete() and restore()
- [x] Implement CustomUserManager
- [x] Implement create_user()
- [x] Implement create_superuser()
- [x] Implement AllUsersManager

## 4. Database
- [x] Generate initial migration
- [x] Review generated SQL
- [x] Apply migrations
- [x] Verify database tables
- [x] Run Django system checks

## 5. Django Admin
- [x] Implement custom UserAdmin
- [x] Configure list_display
- [x] Configure list_filter
- [x] Configure search_fields
- [x] Configure ordering
- [x] Configure fieldsets
- [x] Configure add_fieldsets
- [x] Verify soft-deleted user visibility

## 6. Authentication
- [ ] Review authentication backend
- [x] Enforce account status restrictions
- [x] Verify email-based authentication
- [x] Review password validation
- [x] Verify inactive and suspended accounts
- [x] Implement cookie-based JWT authentication
- [x] Implement JWT access and refresh cookies
- [x] Implement CSRF protection
- [x] Add CSRF token endpoint
- [x] Implement registration and login throttling

## 7. Testing
- [ ] Add User model tests
- [ ] Add UserQuerySet tests
- [ ] Add manager tests
- [ ] Add soft-delete and restore tests
- [x] Add authentication tests
- [ ] Add Django Admin tests
- [x] Add registration and login serializer tests
- [x] Add registration and login API tests
- [x] Add throttling tests
- [x] Add CSRF tests

## 8. Documentation and Final Review
- [ ] Document User model decisions
- [ ] Review code quality and formatting
- [x] Run Django system checks
- [x] Run automated tests
- [x] Review Git changes for the latest authentication/CSRF commit
- [x] Commit authentication and CSRF changes
- [ ] Complete final Users app review
- [ ] Commit completed Users app changes
- [ ] Rebase users branch onto develop
- [ ] Merge users branch into develop
- [ ] Delete users branch after successful merge
