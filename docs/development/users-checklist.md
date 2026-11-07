# Taskora — Users App Development Checklist

## 1. Project Setup
- [x] Create users app
- [x] Register users app in Django settings
- [x] Configure custom User model
- [x] Configure AUTH_USER_MODEL
- [x] Configure app URLs
- [x] Configure app migrations

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
- [x] Implement email normalization
- [x] Implement soft_delete()
- [x] Implement restore()

## 3. User Managers
- [x] Implement UserQuerySet
- [x] Implement alive()
- [x] Implement deleted()
- [x] Implement bulk soft_delete()
- [x] Implement bulk restore()
- [x] Implement CustomUserManager
- [x] Implement create_user()
- [x] Implement create_superuser()
- [x] Implement AllUsersManager
- [x] Configure default_manager_name
- [x] Configure base_manager_name

## 4. Database
- [x] Generate initial migration
- [x] Review generated SQL
- [x] Apply migrations
- [x] Verify database tables
- [x] Run Django system checks
- [x] Verify migration consistency

## 5. Django Admin
- [x] Implement custom UserAdmin
- [x] Configure list_display
- [x] Configure list_filter
- [x] Configure search_fields
- [x] Configure ordering
- [x] Configure fieldsets
- [x] Configure add_fieldsets
- [x] Verify soft-deleted user visibility
- [x] Restrict admin access to superusers

## 6. Authentication
### Authentication Backend
- [x] Configure email-based authentication
- [x] Review authentication backend
- [x] Normalize email during authentication
- [x] Enforce account status restrictions
- [x] Verify inactive accounts
- [x] Verify suspended accounts
- [x] Verify deactivated accounts
- [x] Verify soft-deleted accounts
- [x] Review password validation
- [x] Configure strong password requirements

### JWT Authentication
- [x] Implement cookie-based JWT authentication
- [x] Implement JWT access token
- [x] Implement JWT refresh token
- [x] Configure HTTP-only cookies
- [x] Configure secure cookie settings
- [x] Implement CSRF protection
- [x] Add CSRF token endpoint
- [x] Implement refresh token rotation
- [x] Implement refresh token blacklisting

### Registration and Login
- [x] Implement user registration
- [x] Implement user login
- [x] Implement registration throttling
- [x] Implement login throttling

## 7. Authentication API Endpoints
- [x] POST /api/v1/auth/register/
- [x] POST /api/v1/auth/login/
- [x] POST /api/v1/auth/logout/
- [x] POST /api/v1/auth/refresh/
- [x] GET /api/v1/auth/csrf/

## 8. Email Verification
### Email Verification Flow
- [ ] Design email verification workflow
- [ ] Generate secure email verification tokens
- [ ] Configure token expiration
- [ ] Implement one-time-use tokens
- [ ] Implement email verification service
- [ ] Implement email verification email template
- [ ] Configure email sending service
- [ ] Implement email verification endpoint
- [ ] Update email_verified_at after successful verification
- [ ] Update account status after successful verification
- [ ] Handle already verified email addresses
- [ ] Handle expired verification tokens
- [ ] Handle invalid verification tokens
- [ ] Prevent token reuse
- [ ] Implement resend verification email endpoint
- [ ] Add throttling to resend verification endpoint
- [ ] Handle pending verification accounts

### Email Verification Endpoints
- [ ] POST /api/v1/auth/verify-email/
- [ ] POST /api/v1/auth/resend-verification/

## 9. Password Management
### Change Password
- [ ] Implement change password serializer
- [ ] Validate current password
- [ ] Validate new password strength
- [ ] Validate password confirmation
- [ ] Implement change password service
- [ ] Invalidate existing refresh tokens after password change
- [ ] Implement change password endpoint

### Forgot Password
- [ ] Implement forgot password serializer
- [ ] Generate secure password reset tokens
- [ ] Configure token expiration
- [ ] Implement password reset email template
- [ ] Implement password reset email service
- [ ] Prevent email enumeration
- [ ] Add throttling to forgot password endpoint

### Reset Password
- [ ] Implement reset password serializer
- [ ] Validate reset token
- [ ] Validate token expiration
- [ ] Validate new password strength
- [ ] Validate password confirmation
- [ ] Implement password reset service
- [ ] Invalidate used reset tokens
- [ ] Invalidate existing refresh tokens
- [ ] Implement reset password endpoint

### Password Management Endpoints
- [ ] POST /api/v1/auth/change-password/
- [ ] POST /api/v1/auth/forgot-password/
- [ ] POST /api/v1/auth/reset-password/

## 10. Email Management
### Change Email
- [ ] Implement change email serializer
- [ ] Validate current password
- [ ] Validate new email address
- [ ] Check email uniqueness across all users
- [ ] Require verification of new email address
- [ ] Preserve old email until new email is verified
- [ ] Implement email change service
- [ ] Handle expired email change tokens
- [ ] Handle duplicate email addresses
- [ ] Implement change email endpoint
- [ ] Implement email change confirmation endpoint

### Email Management Endpoints
- [ ] POST /api/v1/users/change-email/
- [ ] POST /api/v1/users/confirm-email-change/

## 11. User Profile Management
- [ ] Implement retrieve current user endpoint
- [ ] Implement update user profile endpoint
- [ ] Configure allowed editable profile fields
- [ ] Prevent unauthorized field modification
- [ ] Validate locale
- [ ] Validate timezone
- [ ] Implement profile serializers
- [ ] Implement profile services

### Profile Endpoints
- [ ] GET /api/v1/users/me/
- [ ] PATCH /api/v1/users/me/

## 12. Account Lifecycle Management
- [ ] Implement account deactivation endpoint
- [ ] Implement account reactivation workflow
- [ ] Implement account deletion endpoint
- [ ] Implement account restoration workflow
- [ ] Define account deletion policy
- [ ] Define email reuse policy after deletion
- [ ] Invalidate authentication tokens after account deactivation
- [ ] Invalidate authentication tokens after account deletion

### Account Lifecycle Endpoints
- [ ] POST /api/v1/users/deactivate/
- [ ] POST /api/v1/users/reactivate/
- [ ] DELETE /api/v1/users/me/

## 13. Security
- [x] Enforce CSRF protection for cookie-based authentication
- [x] Configure HTTP-only authentication cookies
- [x] Configure JWT token expiration
- [x] Implement refresh token blacklisting
- [x] Configure registration throttling
- [x] Configure login throttling
- [ ] Configure password change throttling
- [ ] Configure forgot password throttling
- [ ] Configure email verification throttling
- [ ] Configure resend verification throttling
- [ ] Prevent email enumeration
- [ ] Prevent token reuse
- [ ] Secure password reset tokens
- [ ] Secure email verification tokens
- [ ] Review authentication cookie configuration
- [ ] Review trusted proxy configuration
- [ ] Review authentication error messages
- [ ] Review token invalidation policies
- [ ] Review account enumeration risks

## 14. Testing
### Model Tests
- [x] Add User model tests
- [x] Add UserQuerySet tests
- [x] Add manager tests
- [x] Add soft-delete tests
- [x] Add restore tests

### Admin Tests
- [x] Add Django Admin tests
- [x] Test superuser-only admin access
- [x] Test soft-deleted user visibility

### Authentication Tests
- [x] Add authentication tests
- [x] Add registration serializer tests
- [x] Add login serializer tests
- [x] Add registration API tests
- [x] Add login API tests
- [x] Add throttling tests
- [x] Add CSRF tests
- [x] Add JWT refresh tests
- [x] Add logout tests

### Email Verification Tests
- [ ] Add verification token tests
- [ ] Add email verification service tests
- [ ] Add verification serializer tests
- [ ] Add verification API tests
- [ ] Add expired token tests
- [ ] Add token reuse tests
- [ ] Add resend verification tests

### Password Management Tests
- [ ] Add change password tests
- [ ] Add forgot password tests
- [ ] Add reset password tests
- [ ] Add invalid reset token tests
- [ ] Add expired reset token tests
- [ ] Add password reset throttling tests
- [ ] Add refresh token invalidation tests

### Email and Profile Tests
- [ ] Add change email tests
- [ ] Add email confirmation tests
- [ ] Add profile retrieval tests
- [ ] Add profile update tests
- [ ] Add unauthorized field modification tests

### Account Lifecycle Tests
- [ ] Add account deactivation tests
- [ ] Add account reactivation tests
- [ ] Add account deletion tests
- [ ] Add account restoration tests

## 15. API Documentation
- [ ] Document all authentication endpoints
- [ ] Document email verification endpoints
- [ ] Document password management endpoints
- [ ] Document email management endpoints
- [ ] Document profile management endpoints
- [ ] Document account lifecycle endpoints
- [ ] Define request schemas
- [ ] Define response schemas
- [ ] Document HTTP status codes
- [ ] Document validation errors
- [ ] Verify OpenAPI schema
- [ ] Review Swagger UI

## 16. Documentation and Final Review
- [ ] Document User model decisions
- [ ] Document manager behavior
- [ ] Document soft-delete policy
- [ ] Document account status lifecycle
- [ ] Document authentication architecture
- [ ] Document token and cookie policies
- [ ] Document email verification workflow
- [ ] Document password reset workflow
- [ ] Review code quality and formatting
- [ ] Review imports and naming conventions
- [ ] Review security implementation
- [ ] Run Django system checks
- [x] Run automated tests
- [x] Verify migration consistency
- [ ] Run full project test suite
- [ ] Complete final Users app review

## 17. Git and Integration
- [x] Commit custom User model and managers
- [x] Commit initial User migration
- [x] Commit Django Admin implementation
- [x] Commit registration API
- [x] Commit login API
- [x] Commit authentication tests
- [x] Commit cookie-based JWT authentication
- [x] Commit CSRF protection
- [x] Commit completed Users app changes
- [x] Merge users branch into develop
- [x] Verify tests on develop
- [x] Delete users branch after successful merge

---

## Current Status
- [x] Initial User model and infrastructure
- [x] User managers and soft-delete
- [x] Django Admin
- [x] Registration and login
- [x] Cookie-based JWT authentication
- [x] CSRF protection
- [x] Initial authentication test suite (100 tests passed)
- [ ] Email verification
- [ ] Change password
- [ ] Forgot password
- [ ] Reset password
- [ ] Change email
- [ ] User profile management
- [ ] Account lifecycle management
- [ ] Complete API documentation
- [ ] Final Users app review
