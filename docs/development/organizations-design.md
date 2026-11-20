# Organizations App — Design Document

**Project:** Taskora  
**App:** `organizations`  
**Status:** Design in Progress

## 1. Overview

The `organizations` app is responsible for managing organizations, organization memberships, invitations, membership requests, and organization-level access control.

The design should support both organization-level and workspace-level membership management, with a consistent permission and membership policy model.

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
- Organization slugs must be globally unique.
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
- Rejoining must reactivate the existing membership record.
- `joined_at` must be updated when a user rejoins.
- Users with active membership must not be allowed to submit another membership request for the same scope.
- Suspended and left memberships must remain distinguishable from active memberships.

### Ownership Rules

- Every active organization must have exactly one active owner.
- An owner cannot leave or suspend their membership without transferring ownership first.
- Ownership can only be transferred to another active organization member.
- After ownership transfer, the previous owner becomes an `admin` by default.
- Ownership transfer must be performed within a single atomic transaction.
- An owner's account must not be soft-deleted or suspended before ownership has been transferred.
- A simple unique constraint can guarantee at most one active owner, but it cannot independently guarantee exactly one active owner. This invariant must be enforced through transactional services and, if necessary, additional database-level mechanisms.

## 4. Invitation Model

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

## 5. MembershipRequest Model

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
- Approving a request must create or reactivate membership through the membership service layer.
- Rejected or cancelled requests cannot be directly approved.

## 6. Membership Policies

The same membership policy model must be supported at both Organization and Workspace levels.

| Policy | Behavior |
|---|---|
| `private` | Membership is only possible through an invitation |
| `request` | Users can request membership, subject to administrator approval |
| `public` | Users can join directly without an invitation or approval |

### Public Membership

- Users can join directly.
- The initial role must always be `member`.
- The initial membership status must be `active`.
- Membership creation must go through a controlled service to prevent duplicate or inconsistent memberships.

### Membership Policy Changes

- Changing an organization's or workspace's membership policy must not affect existing memberships.
- The new policy only applies to future membership operations.
- Existing invitations remain valid until they expire or are revoked.
- Changing the membership policy must not automatically revoke existing invitations.

## 7. Membership Suspension and Access Hierarchy

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

## 8. Leaving an Organization

When a user voluntarily leaves an organization:

- The organization membership status changes to `left`.
- Access to all workspaces and boards within that organization is revoked.
- Lower-level membership records must not be physically deleted.
- If the user rejoins the organization, previous lower-level access is restored only when the corresponding workspace and board memberships are still active.
- The organization's `joined_at` timestamp must be updated upon rejoining.

## 9. Ownership Transfer

- Every active organization must have exactly one active owner.
- An owner must transfer ownership before leaving, suspending their membership, or having their account deleted or suspended.
- The new owner must already be an active member of the organization.
- Ownership transfer must be atomic.
- The previous owner becomes an `admin` by default.
- The organization must never be left without an active owner during the transfer process.

## 10. Pending Architecture Decisions

The following details still require further design decisions before implementation:

1. Exact `on_delete` behavior for User and Membership relationships.
2. Workspace and Board model dependencies and migration ordering.
3. Exact roles that can be assigned through invitations.
4. Invitation behavior when the invited user is already a member of the target scope.
5. Concurrency handling and race-condition prevention for simultaneous invitation creation.
6. Database-level enforcement of the exactly-one-active-owner invariant.
7. Organization soft-deletion behavior and its impact on membership and invitation operations.
8. Final PostgreSQL indexes and constraints.
9. Transactional service methods and authorization requirements for each operation.

---

**Implementation Status:** No models or services have been implemented based on this document yet. This document represents the current design decisions and will be updated as the architecture is finalized.