# Organizations App — Design Document

**Project:** Taskora  
**App:** `organizations`  
**Related App:** `workspaces`  
**Status:** Design in Progress

## 1. Overview

The `organizations` app is responsible for managing organizations, organization memberships, invitations, membership requests, and organization-level access control.

The `workspaces` app will be implemented as a separate Django application responsible for managing workspaces, workspace memberships, workspace invitations, membership requests, and workspace-level access control.

An organization can have multiple workspaces. Each workspace belongs to exactly one organization.

Organization and workspace membership management follow similar policy and role structures, but their roles and memberships are independent.

The implementation will follow Django best practices, PostgreSQL integrity constraints, UUID-based identifiers, and transactional service-layer operations.

## 2. Organization Model

### Proposed Fields

| Field | Type | Description |
|---|---|---|
| `id` | UUIDField | Primary key |
| `name` | CharField(160) | Organization name |
| `slug` | SlugField(160) | Globally unique slug |
| `description` | TextField | Optional organization description |
| `created_by` | ForeignKey(User) | Original organization creator |
| `settings` | JSONField | Organization settings, defaults to `{}` |
| `membership_policy` | Choices | `private`, `request`, `public` |
| `created_at` | DateTimeField | Creation timestamp |
| `updated_at` | DateTimeField | Last update timestamp |
| `deleted_at` | DateTimeField | Soft deletion timestamp |

### Business Rules

- Organization IDs must use UUIDs.
- Organizations must support soft deletion and restoration.
- Soft-deleting an organization must not immediately delete its related data.
- Soft-deleted organizations must not appear in normal active organization queries.
- Organization names must be unique case-insensitively after trimming whitespace.
- Organization slugs must be globally unique, including across soft-deleted organizations.
- Slug changes must follow a controlled process.
- `created_by` represents the original creator and must remain separate from the current owner.
- The creator relationship must not cause an organization to be deleted when the creator account is deleted.
- Organization creation and initial owner membership creation must happen within a single atomic transaction.

## 3. OrganizationMembership Model

### Proposed Fields

| Field | Type | Description |
|---|---|---|
| `organization` | ForeignKey | Related organization |
| `user` | ForeignKey | Related user |
| `role` | Choices | `owner`, `admin`, `member` |
| `status` | Choices | `active`, `suspended`, `left` |
| `joined_at` | DateTimeField | Timestamp of the latest join |
| `created_at` | DateTimeField | Membership record creation timestamp |

### Business Rules

- The combination of `organization` and `user` must be unique.
- Membership records must not be physically deleted when users leave an organization.
- Leaving an organization changes membership status to `left`.
- Rejoining must reactivate the existing organization membership record.
- `joined_at` must be updated when a user rejoins.
- Users with active membership must not be allowed to submit another membership request for the same scope.
- Suspended and left memberships must remain distinguishable from active memberships.

### Organization Roles

- `owner`: Full organization-level control, including ownership transfer and organization settings.
- `admin`: Organization-level administrative permissions.
- `member`: Standard organization membership.

Organization roles are independent of workspace roles. No role is automatically inherited between these two levels.

### Ownership Rules

- Every active organization must have exactly one active owner.
- An owner cannot leave or suspend their membership without transferring ownership first.
- Ownership can only be transferred to another active organization member.
- After ownership transfer, the previous owner becomes an `admin` by default.
- Ownership transfer must be performed within a single atomic transaction.
- An owner's account must not be soft-deleted or suspended before ownership has been transferred.
- A simple unique constraint can guarantee at most one active owner, but it cannot independently guarantee exactly one active owner. This invariant must be enforced through transactional services and, if necessary, additional database-level mechanisms.

## 4. Workspace Architecture

The `workspaces` app will be implemented as a separate Django application.

An organization can have multiple workspaces, while each workspace belongs to exactly one organization.

### Workspace Model

Proposed fields:

| Field | Type | Description |
|---|---|---|
| `id` | UUIDField | Primary key |
| `organization` | ForeignKey | Parent organization |
| `name` | CharField | Workspace name |
| `slug` | SlugField | Workspace slug |
| `description` | TextField | Optional description |
| `settings` | JSONField | Workspace settings, defaults to `{}` |
| `membership_policy` | Choices | `private`, `request`, `public` |
| `created_by` | ForeignKey(User) | Workspace creator |
| `created_at` | DateTimeField | Creation timestamp |
| `updated_at` | DateTimeField | Last update timestamp |
| `deleted_at` | DateTimeField | Soft deletion timestamp |

Workspace-specific uniqueness rules and indexes will be finalized during model implementation.

### Workspace Membership Model

Each workspace has its own independent membership records.

Proposed fields:

| Field | Type | Description |
|---|---|---|
| `workspace` | ForeignKey | Related workspace |
| `user` | ForeignKey | Related user |
| `role` | Choices | `owner`, `admin`, `member` |
| `status` | Choices | `active`, `suspended`, `left` |
| `joined_at` | DateTimeField | Timestamp of the latest join |
| `created_at` | DateTimeField | Membership record creation timestamp |

The combination of `workspace` and `user` must be unique.

Membership records must not be physically deleted when users leave a workspace.

### Workspace Roles

Workspace roles are:

- `owner`: Full workspace-level control, including ownership transfer and workspace settings.
- `admin`: Workspace-level administrative permissions.
- `member`: Standard workspace membership.

Workspace roles are completely independent of organization roles.

For example:

- A user may be an organization `admin` and a workspace `member`.
- A user may be an organization `member` and a workspace `admin`.
- A user may be an organization `member` and a workspace `owner`.

Changing a role at one level must not automatically change the role at another level.

Organization admins do not automatically become workspace admins.

### Workspace Ownership Rules

- Every active workspace must have exactly one active owner.
- A workspace owner must also be an active member of its parent organization.
- A workspace owner does not have to be the organization owner.
- Workspace ownership can only be transferred to another active member of the same organization who is eligible to own the workspace.
- After ownership transfer, the previous workspace owner becomes an `admin` by default.
- Workspace ownership transfer must happen within a single atomic transaction.
- A workspace owner cannot leave the parent organization before transferring ownership.
- If a user owns multiple workspaces, ownership of all those workspaces must be transferred before leaving the organization.
- Organization ownership and workspace ownership are independent.

## 5. Workspace Membership Policies

Each workspace has an independent membership policy.

| Policy | Behavior |
|---|---|
| `private` | Membership is only possible through an invitation |
| `request` | Users can request membership, subject to approval |
| `public` | Eligible users can join directly without approval |

### Organization Membership Requirement

Only active members of the parent organization can join a workspace.

A workspace's `public` policy does not allow users outside its parent organization to join.

The active organization membership requirement applies to:

- Direct workspace joining.
- Workspace membership requests.
- Workspace invitation acceptance.
- Workspace membership reactivation.

Workspace invitations and membership requests must verify that the target user is an active member of the parent organization before granting membership.

### Public Workspace Membership

- Eligible organization members can join directly.
- The initial role must always be `member`.
- The initial membership status must be `active`.
- Membership creation must go through a controlled service to prevent duplicate or inconsistent memberships.

### Membership Policy Changes

- Changing a workspace membership policy must not affect existing memberships.
- The new policy only applies to future membership operations.
- Existing invitations remain valid until they expire or are revoked.
- Changing the membership policy must not automatically revoke existing invitations.

## 6. Invitation Model

Invitations must support both organization-level and workspace-level membership.

The invitation model may reside in a shared domain app or be separated according to implementation requirements.

### Proposed Fields

| Field | Type | Description |
|---|---|---|
| `id` | UUIDField | Primary key |
| `organization` | ForeignKey | Target organization |
| `workspace` | ForeignKey | Optional workspace-level invitation |
| `email` | EmailField | Invited email address |
| `invited_by` | ForeignKey(User) | User who created the invitation |
| `token_hash` | TextField | Unique hashed invitation token |
| `role` | CharField(32) | Proposed membership role |
| `status` | Choices | `pending`, `accepted`, `expired`, `revoked` |
| `expires_at` | DateTimeField | Invitation expiration timestamp |
| `accepted_at` | DateTimeField | Invitation acceptance timestamp |
| `revoked_at` | DateTimeField | Invitation revocation timestamp |
| `created_at` | DateTimeField | Creation timestamp |

### Security and Business Rules

- Every invitation must target a specific email address.
- Only an account with a verified email matching the invitation email can accept the invitation.
- Raw invitation tokens must never be stored in the database. Only their hashes must be persisted.
- Expired or revoked invitations cannot be accepted.
- A workspace invitation must belong to the same organization referenced by the invitation.
- The `owner` role cannot be granted through an invitation.
- Only one pending invitation may exist for the same email address and scope.
- Creating a new invitation for the same email and scope must revoke the previous pending invitation.
- Revoking the previous invitation and creating the new invitation must happen atomically.
- Accepting a workspace invitation requires active membership in the parent organization.
- Invitation acceptance must use the appropriate membership service.

## 7. MembershipRequest Model

Membership requests must support organization-level and workspace-level membership.

### Proposed Fields

| Field | Type | Description |
|---|---|---|
| `id` | UUIDField | Primary key |
| `organization` | ForeignKey | Target organization |
| `workspace` | ForeignKey | Optional workspace-level request |
| `user` | ForeignKey(User) | Requesting user |
| `message` | TextField | Optional request message |
| `status` | Choices | `pending`, `approved`, `rejected`, `cancelled` |
| `reviewed_by` | ForeignKey(User) | User who reviewed the request |
| `reviewed_at` | DateTimeField | Review timestamp |
| `created_at` | DateTimeField | Creation timestamp |
| `updated_at` | DateTimeField | Last update timestamp |

### Business Rules

- A user may have at most one pending request for the same scope.
- Membership requests are only allowed when the target scope uses the `request` membership policy.
- Users with active membership cannot submit another request for the same scope.
- Rejected or cancelled requests must not prevent users from submitting a new request.
- Users may submit a new request immediately after rejection or cancellation. No cooldown period is required.
- Requesters cannot assign themselves the `owner` or `admin` role.
- The final membership role must be assigned by an authorized reviewer during approval.
- Approving a request must create or reactivate membership through the appropriate membership service.
- Rejected or cancelled requests cannot be directly approved.
- A workspace membership request is only valid while the requester has active membership in the parent organization.
- Workspace request approval must revalidate active organization membership.

## 8. Membership Suspension and Access Hierarchy

Suspension must be scoped to the selected membership level.

- **Organization:** Suspension applies to the entire organization.
- **Workspace:** Suspension applies only to the selected workspace and its child boards.
- **Board:** Suspension applies only to the selected board.

### Parent-Level Suspension

- Suspending an organization membership must block access to all workspaces and boards belonging to that organization.
- Suspending a workspace membership must block access to that workspace and its child boards.
- Suspending a board membership must block access only to that board.
- Suspending a parent-level membership must not modify the status of lower-level membership records.
- When a parent-level suspension is lifted, previously active lower-level memberships become effective again, unless they have been independently suspended or otherwise deactivated.

The effective access decision must consider membership status at every relevant level of the hierarchy.

### Organization-Level Suspension

When an organization membership is suspended:

- The organization membership status changes to `suspended`.
- Access to all workspaces and boards belonging to the organization is blocked.
- Workspace and board membership statuses must remain unchanged.
- Reactivating the organization membership restores effective access only to lower-level memberships that are still active.
- Organization suspension must not automatically reactivate or modify independently suspended or left workspace memberships.

## 9. Leaving an Organization

When a user voluntarily leaves an organization:

- The organization membership status changes to `left`.
- All active workspace memberships belonging to that user within the organization must change to `left`.
- Access to all workspaces and boards within that organization is revoked.
- Lower-level membership records must not be physically deleted.
- Workspace memberships with `suspended` or `left` status must retain their existing status.
- Rejoining the organization must not automatically reactivate previous workspace memberships.
- The user must join each workspace again according to its membership policy.
- The organization's `joined_at` timestamp must be updated upon rejoining.

All organization and workspace membership changes caused by leaving an organization must happen within a single atomic transaction.

### Workspace Ownership Requirement

A user who owns one or more workspaces must transfer ownership of every workspace they own before leaving the parent organization.

The new workspace owner must be an active member of the same organization.

If any required ownership transfer cannot be completed, the organization leave operation must fail without changing any membership statuses.

## 10. Ownership Transfer

### Organization Ownership

- Every active organization must have exactly one active owner.
- An owner must transfer ownership before leaving, suspending their membership, or having their account deleted or suspended.
- The new owner must already be an active member of the organization.
- Ownership transfer must be atomic.
- The previous owner becomes an `admin` by default.
- The organization must never be left without an active owner during the transfer process.

### Workspace Ownership

- Every active workspace must have exactly one active owner.
- The workspace owner must be an active member of the parent organization.
- The new owner must already be an active member of the same organization and workspace.
- Workspace ownership transfer must be atomic.
- The previous owner becomes an `admin` by default.
- A workspace must never be left without an active owner during the transfer process.
- Workspace ownership must be transferred before the current owner leaves the parent organization.

## 11. Organization and Workspace Membership Lifecycle

Organization and workspace memberships have independent lifecycle records, but access is subject to the parent-child hierarchy.

### Leaving a Workspace

- The workspace membership status changes to `left`.
- The membership record must not be physically deleted.
- A user who leaves a workspace must not have access to that workspace or its child boards.
- Rejoining must follow the workspace membership policy.
- Rejoining must reactivate the existing workspace membership record.
- The workspace `joined_at` timestamp must be updated upon rejoining.
- A workspace owner must transfer ownership before leaving.

### Rejoining an Organization

- The organization membership record must be reactivated.
- The organization `joined_at` timestamp must be updated.
- Previously left workspace memberships must remain `left`.
- Workspace access must not be restored automatically.
- The user must join each workspace again according to its membership policy.

## 12. Transactional Services and Concurrency

All important membership and ownership operations must be implemented through service-layer functions.

Operations that modify multiple related records must use database transactions.

The implementation must consider concurrent operations, including:

- Simultaneous organization joins.
- Simultaneous workspace joins.
- Concurrent ownership transfers.
- Concurrent invitation creation.
- Concurrent invitation acceptance.
- Organization leave operations involving multiple workspace memberships.
- Workspace ownership transfer during an organization leave operation.

Row-level locking with `select_for_update()` and appropriate database constraints must be used where necessary.

The locking strategy must be consistent across related services to minimize deadlocks and race conditions.

## 13. Pending Architecture Decisions

The following details still require further design decisions before implementation:

1. Exact `on_delete` behavior for User, Organization, Workspace, and Membership relationships.
2. Invitation and MembershipRequest model ownership and app placement.
3. Exact roles that can be assigned through invitations.
4. Invitation behavior when the invited user is already a member of the target scope.
5. Concurrency handling and race-condition prevention for simultaneous invitation creation.
6. Database-level enforcement of the exactly-one-active-owner invariant.
7. Organization and workspace soft-deletion behavior and their impact on membership and invitation operations.
8. Final PostgreSQL indexes and constraints.
9. Detailed authorization requirements for each service operation.
10. Workspace and Board model dependencies and migration ordering.
11. Board-level membership and access-control requirements.
12. Whether organization membership reactivation should be permitted for soft-deleted or suspended user accounts.

The following decisions are already finalized:

- Workspace is a separate Django application.
- An organization can have multiple workspaces.
- Every workspace belongs to exactly one organization.
- Every workspace has exactly one active owner.
- Workspace owners must be active members of the parent organization.
- Organization and workspace roles are completely independent.
- Workspace roles are `owner`, `admin`, and `member`.
- Workspace membership policies are `private`, `request`, and `public`.
- Only active organization members can join workspaces.
- Leaving an organization changes all active workspace memberships to `left`.
- Rejoining an organization does not automatically restore workspace memberships.
- Workspace owners must transfer ownership of all their workspaces before leaving the organization.

## 14. Implementation Status

- Organization and OrganizationMembership models have been implemented.
- Organization model constraints, managers, soft deletion, and restoration have been implemented.
- Organization membership services have been implemented, including creation, joining, leaving, ownership transfer, suspension, reactivation, and role changes.
- Organization model and service tests are passing.
- Organization admin registration has been implemented.
- Organization views and APIs are pending.
- Workspace architecture has been designed but not implemented yet.
- Workspace models, migrations, services, views, and APIs are pending.
- Invitation and MembershipRequest models and services are pending.
- Board-level membership and access-control implementation is pending.

---

**Document Status:** This document represents the current architecture and finalized domain decisions. It will be updated as implementation progresses and additional architecture decisions are made.