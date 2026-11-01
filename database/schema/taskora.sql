CREATE TYPE "account_status" AS ENUM (
  'pending_verification',
  'active',
  'suspended',
  'deactivated'
);

CREATE TYPE "membership_status" AS ENUM (
  'invited',
  'active',
  'suspended',
  'left'
);

CREATE TYPE "resource_visibility" AS ENUM (
  'private',
  'workspace',
  'organization',
  'public'
);

CREATE TYPE "board_role" AS ENUM (
  'admin',
  'editor',
  'commenter',
  'viewer'
);

CREATE TYPE "workspace_role" AS ENUM (
  'owner',
  'admin',
  'member',
  'guest'
);

CREATE TYPE "invitation_status" AS ENUM (
  'pending',
  'accepted',
  'revoked',
  'expired'
);

CREATE TYPE "card_priority" AS ENUM (
  'none',
  'low',
  'medium',
  'high',
  'urgent'
);

CREATE TYPE "automation_status" AS ENUM (
  'active',
  'paused',
  'disabled'
);

CREATE TYPE "delivery_status" AS ENUM (
  'pending',
  'processing',
  'delivered',
  'failed',
  'cancelled'
);

CREATE TYPE "subscription_status" AS ENUM (
  'trialing',
  'active',
  'past_due',
  'paused',
  'cancelled',
  'incomplete',
  'expired'
);

CREATE TABLE "users" (
  "id" uuid PRIMARY KEY,
  "email" varchar UNIQUE NOT NULL,
  "password_hash" text,
  "status" account_status NOT NULL DEFAULT 'pending_verification',
  "email_verified_at" timestamp,
  "last_login_at" timestamp,
  "locale" varchar(20) NOT NULL DEFAULT 'en',
  "timezone" varchar(64) NOT NULL DEFAULT 'UTC',
  "created_at" timestamp NOT NULL,
  "updated_at" timestamp NOT NULL,
  "deleted_at" timestamp
);

CREATE TABLE "user_profiles" (
  "user_id" uuid PRIMARY KEY,
  "full_name" varchar(160),
  "display_name" varchar(80),
  "bio" text,
  "avatar_key" text,
  "job_title" varchar(120),
  "department" varchar(120),
  "phone" varchar(40),
  "created_at" timestamp NOT NULL,
  "updated_at" timestamp NOT NULL
);

CREATE TABLE "user_identities" (
  "id" uuid PRIMARY KEY,
  "user_id" uuid NOT NULL,
  "provider" varchar(40) NOT NULL,
  "provider_subject" varchar(255) NOT NULL,
  "provider_email" varchar,
  "created_at" timestamp NOT NULL,
  "last_used_at" timestamp
);

CREATE TABLE "user_sessions" (
  "id" uuid PRIMARY KEY,
  "user_id" uuid NOT NULL,
  "refresh_token_hash" text UNIQUE NOT NULL,
  "user_agent" text,
  "ip_address" varchar(45),
  "expires_at" timestamp NOT NULL,
  "revoked_at" timestamp,
  "created_at" timestamp NOT NULL
);

CREATE TABLE "user_mfa_methods" (
  "id" uuid PRIMARY KEY,
  "user_id" uuid NOT NULL,
  "method" varchar(24) NOT NULL,
  "secret_ciphertext" text,
  "credential_data" json,
  "verified_at" timestamp,
  "created_at" timestamp NOT NULL
);

CREATE TABLE "organizations" (
  "id" uuid PRIMARY KEY,
  "name" varchar(160) NOT NULL,
  "slug" varchar(160) UNIQUE NOT NULL,
  "created_by" uuid,
  "settings" json NOT NULL,
  "created_at" timestamp NOT NULL,
  "updated_at" timestamp NOT NULL,
  "deleted_at" timestamp
);

CREATE TABLE "organization_memberships" (
  "organization_id" uuid NOT NULL,
  "user_id" uuid NOT NULL,
  "role" varchar(32) NOT NULL DEFAULT 'member',
  "status" membership_status NOT NULL DEFAULT 'active',
  "joined_at" timestamp,
  "created_at" timestamp NOT NULL,
  PRIMARY KEY ("organization_id", "user_id")
);

CREATE TABLE "invitations" (
  "id" uuid PRIMARY KEY,
  "organization_id" uuid NOT NULL,
  "workspace_id" uuid,
  "email" varchar NOT NULL,
  "invited_by" uuid,
  "token_hash" text UNIQUE NOT NULL,
  "role" varchar(32) NOT NULL DEFAULT 'member',
  "status" invitation_status NOT NULL DEFAULT 'pending',
  "expires_at" timestamp NOT NULL,
  "accepted_at" timestamp,
  "revoked_at" timestamp,
  "created_at" timestamp NOT NULL
);

CREATE TABLE "roles" (
  "id" uuid PRIMARY KEY,
  "organization_id" uuid,
  "name" varchar(80) NOT NULL,
  "scope" varchar(24) NOT NULL,
  "is_system" boolean NOT NULL DEFAULT false,
  "created_at" timestamp NOT NULL
);

CREATE TABLE "permissions" (
  "code" varchar(100) PRIMARY KEY,
  "description" text NOT NULL,
  "resource_type" varchar(40) NOT NULL
);

CREATE TABLE "role_permissions" (
  "role_id" uuid NOT NULL,
  "permission_code" varchar(100) NOT NULL,
  PRIMARY KEY ("role_id", "permission_code")
);

CREATE TABLE "workspaces" (
  "id" uuid PRIMARY KEY,
  "organization_id" uuid NOT NULL,
  "name" varchar(160) NOT NULL,
  "slug" varchar(160) NOT NULL,
  "description" text,
  "created_by" uuid,
  "settings" json NOT NULL,
  "created_at" timestamp NOT NULL,
  "updated_at" timestamp NOT NULL,
  "archived_at" timestamp
);

CREATE TABLE "workspace_memberships" (
  "workspace_id" uuid NOT NULL,
  "organization_id" uuid NOT NULL,
  "user_id" uuid NOT NULL,
  "role" workspace_role NOT NULL DEFAULT 'member',
  "status" membership_status NOT NULL DEFAULT 'active',
  "created_at" timestamp NOT NULL,
  "joined_at" timestamp,
  PRIMARY KEY ("workspace_id", "user_id")
);

CREATE TABLE "boards" (
  "id" uuid PRIMARY KEY,
  "organization_id" uuid NOT NULL,
  "workspace_id" uuid NOT NULL,
  "name" varchar(160) NOT NULL,
  "description" text,
  "visibility" resource_visibility NOT NULL DEFAULT 'workspace',
  "created_by" uuid,
  "background" json NOT NULL,
  "settings" json NOT NULL,
  "is_archived" boolean NOT NULL DEFAULT false,
  "created_at" timestamp NOT NULL,
  "updated_at" timestamp NOT NULL,
  "deleted_at" timestamp
);

CREATE TABLE "board_memberships" (
  "board_id" uuid NOT NULL,
  "workspace_id" uuid NOT NULL,
  "user_id" uuid NOT NULL,
  "role" board_role NOT NULL DEFAULT 'editor',
  "added_by" uuid,
  "created_at" timestamp NOT NULL,
  PRIMARY KEY ("board_id", "user_id")
);

CREATE TABLE "board_preferences" (
  "board_id" uuid NOT NULL,
  "user_id" uuid NOT NULL,
  "is_starred" boolean NOT NULL DEFAULT false,
  "is_watched" boolean NOT NULL DEFAULT false,
  "last_viewed_at" timestamp,
  PRIMARY KEY ("board_id", "user_id")
);

CREATE TABLE "lists" (
  "id" uuid PRIMARY KEY,
  "board_id" uuid NOT NULL,
  "name" varchar(160) NOT NULL,
  "position" decimal(30,12) NOT NULL,
  "is_archived" boolean NOT NULL DEFAULT false,
  "wip_limit" int,
  "created_at" timestamp NOT NULL,
  "updated_at" timestamp NOT NULL,
  "deleted_at" timestamp
);

CREATE TABLE "cards" (
  "id" uuid PRIMARY KEY,
  "board_id" uuid NOT NULL,
  "list_id" uuid NOT NULL,
  "title" varchar(500) NOT NULL,
  "description" text,
  "position" decimal(30,12) NOT NULL,
  "priority" card_priority NOT NULL DEFAULT 'none',
  "start_at" timestamp,
  "due_at" timestamp,
  "is_completed" boolean NOT NULL DEFAULT false,
  "completed_at" timestamp,
  "is_archived" boolean NOT NULL DEFAULT false,
  "created_by" uuid,
  "cover_attachment_id" uuid,
  "metadata" json NOT NULL,
  "created_at" timestamp NOT NULL,
  "updated_at" timestamp NOT NULL,
  "deleted_at" timestamp
);

CREATE TABLE "card_assignees" (
  "card_id" uuid NOT NULL,
  "board_id" uuid NOT NULL,
  "user_id" uuid NOT NULL,
  "assigned_by" uuid,
  "assigned_at" timestamp NOT NULL,
  PRIMARY KEY ("card_id", "user_id")
);

CREATE TABLE "labels" (
  "id" uuid PRIMARY KEY,
  "board_id" uuid NOT NULL,
  "name" varchar(100) NOT NULL,
  "color" varchar(24) NOT NULL DEFAULT 'gray',
  "created_at" timestamp NOT NULL
);

CREATE TABLE "card_labels" (
  "card_id" uuid NOT NULL,
  "board_id" uuid NOT NULL,
  "label_id" uuid NOT NULL,
  PRIMARY KEY ("card_id", "label_id")
);

CREATE TABLE "card_dependencies" (
  "card_id" uuid NOT NULL,
  "depends_on_card_id" uuid NOT NULL,
  "dependency_type" varchar(24) NOT NULL DEFAULT 'blocks',
  "created_by" uuid,
  "created_at" timestamp NOT NULL,
  PRIMARY KEY ("card_id", "depends_on_card_id")
);

CREATE TABLE "checklists" (
  "id" uuid PRIMARY KEY,
  "card_id" uuid NOT NULL,
  "title" varchar(180) NOT NULL,
  "position" decimal(30,12) NOT NULL,
  "created_at" timestamp NOT NULL
);

CREATE TABLE "checklist_items" (
  "id" uuid PRIMARY KEY,
  "checklist_id" uuid NOT NULL,
  "title" varchar(500) NOT NULL,
  "position" decimal(30,12) NOT NULL,
  "is_completed" boolean NOT NULL DEFAULT false,
  "completed_at" timestamp,
  "completed_by" uuid,
  "assigned_to_user_id" uuid,
  "due_at" timestamp,
  "created_at" timestamp NOT NULL,
  "updated_at" timestamp NOT NULL
);

CREATE TABLE "comments" (
  "id" uuid PRIMARY KEY,
  "card_id" uuid NOT NULL,
  "user_id" uuid,
  "body" text NOT NULL,
  "edited_at" timestamp,
  "deleted_at" timestamp,
  "created_at" timestamp NOT NULL,
  "updated_at" timestamp NOT NULL
);

CREATE TABLE "card_watchers" (
  "card_id" uuid NOT NULL,
  "user_id" uuid NOT NULL,
  "created_at" timestamp NOT NULL,
  PRIMARY KEY ("card_id", "user_id")
);

CREATE TABLE "comment_mentions" (
  "comment_id" uuid NOT NULL,
  "mentioned_user_id" uuid NOT NULL,
  PRIMARY KEY ("comment_id", "mentioned_user_id")
);

CREATE TABLE "attachments" (
  "id" uuid PRIMARY KEY,
  "organization_id" uuid NOT NULL,
  "uploaded_by" uuid,
  "storage_key" text UNIQUE NOT NULL,
  "original_filename" text NOT NULL,
  "mime_type" varchar(160),
  "size_bytes" bigint NOT NULL,
  "checksum_sha256" char(64),
  "created_at" timestamp NOT NULL,
  "deleted_at" timestamp
);

CREATE TABLE "attachment_links" (
  "id" uuid PRIMARY KEY,
  "attachment_id" uuid NOT NULL,
  "card_id" uuid,
  "comment_id" uuid,
  "created_at" timestamp NOT NULL
);

CREATE TABLE "custom_field_definitions" (
  "id" uuid PRIMARY KEY,
  "board_id" uuid NOT NULL,
  "name" varchar(120) NOT NULL,
  "field_type" varchar(24) NOT NULL,
  "options" json NOT NULL,
  "is_required" boolean NOT NULL DEFAULT false,
  "position" decimal(30,12) NOT NULL,
  "created_at" timestamp NOT NULL
);

CREATE TABLE "card_custom_field_values" (
  "card_id" uuid NOT NULL,
  "board_id" uuid NOT NULL,
  "field_id" uuid NOT NULL,
  "value" json NOT NULL,
  "updated_by" uuid,
  "updated_at" timestamp NOT NULL,
  PRIMARY KEY ("card_id", "field_id")
);

CREATE TABLE "activity_events" (
  "id" BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  "organization_id" uuid NOT NULL,
  "workspace_id" uuid,
  "board_id" uuid,
  "card_id" uuid,
  "actor_user_id" uuid,
  "event_type" varchar(100) NOT NULL,
  "payload" json NOT NULL,
  "request_id" uuid,
  "created_at" timestamp NOT NULL
);

CREATE TABLE "audit_logs" (
  "id" BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  "organization_id" uuid NOT NULL,
  "actor_user_id" uuid,
  "action" varchar(120) NOT NULL,
  "resource_type" varchar(80) NOT NULL,
  "resource_id" uuid,
  "before_data" json,
  "after_data" json,
  "ip_address" varchar(45),
  "user_agent" text,
  "correlation_id" uuid,
  "created_at" timestamp NOT NULL
);

CREATE TABLE "notification_preferences" (
  "user_id" uuid NOT NULL,
  "event_type" varchar(100) NOT NULL,
  "in_app" boolean NOT NULL DEFAULT true,
  "email" boolean NOT NULL DEFAULT true,
  "push" boolean NOT NULL DEFAULT false,
  PRIMARY KEY ("user_id", "event_type")
);

CREATE TABLE "notifications" (
  "id" uuid PRIMARY KEY,
  "user_id" uuid NOT NULL,
  "organization_id" uuid,
  "event_type" varchar(100) NOT NULL,
  "title" varchar(240) NOT NULL,
  "body" text,
  "resource_type" varchar(40),
  "resource_id" uuid,
  "payload" json NOT NULL,
  "read_at" timestamp,
  "created_at" timestamp NOT NULL
);

CREATE TABLE "notification_deliveries" (
  "id" uuid PRIMARY KEY,
  "notification_id" uuid NOT NULL,
  "channel" varchar(16) NOT NULL,
  "status" delivery_status NOT NULL DEFAULT 'pending',
  "attempts" int NOT NULL DEFAULT 0,
  "next_attempt_at" timestamp,
  "delivered_at" timestamp,
  "last_error" text,
  "provider_message_id" text,
  "created_at" timestamp NOT NULL
);

CREATE TABLE "automation_rules" (
  "id" uuid PRIMARY KEY,
  "board_id" uuid NOT NULL,
  "name" varchar(160) NOT NULL,
  "description" text,
  "status" automation_status NOT NULL DEFAULT 'active',
  "trigger_definition" json NOT NULL,
  "condition_definition" json NOT NULL,
  "action_definition" json NOT NULL,
  "created_by" uuid,
  "created_at" timestamp NOT NULL,
  "updated_at" timestamp NOT NULL
);

CREATE TABLE "automation_executions" (
  "id" uuid PRIMARY KEY,
  "rule_id" uuid NOT NULL,
  "trigger_event_id" bigint,
  "status" delivery_status NOT NULL DEFAULT 'pending',
  "input_payload" json NOT NULL,
  "output_payload" json,
  "error_message" text,
  "started_at" timestamp,
  "finished_at" timestamp,
  "created_at" timestamp NOT NULL
);

CREATE TABLE "outbox_events" (
  "id" uuid PRIMARY KEY,
  "event_type" varchar(150) NOT NULL,
  "aggregate_type" varchar(100) NOT NULL,
  "aggregate_id" uuid NOT NULL,
  "payload" json NOT NULL,
  "status" varchar(20) NOT NULL DEFAULT 'pending',
  "occurred_at" timestamp NOT NULL,
  "available_at" timestamp NOT NULL,
  "attempts" int NOT NULL DEFAULT 0,
  "locked_at" timestamp,
  "locked_by" varchar(255),
  "published_at" timestamp,
  "last_error" text,
  "created_at" timestamp NOT NULL,
  "updated_at" timestamp NOT NULL
);

CREATE TABLE "board_templates" (
  "id" uuid PRIMARY KEY,
  "organization_id" uuid,
  "name" varchar(160) NOT NULL,
  "description" text,
  "definition" json NOT NULL,
  "created_by" uuid,
  "is_public" boolean NOT NULL DEFAULT false,
  "created_at" timestamp NOT NULL
);

CREATE TABLE "saved_views" (
  "id" uuid PRIMARY KEY,
  "workspace_id" uuid NOT NULL,
  "user_id" uuid NOT NULL,
  "name" varchar(120) NOT NULL,
  "view_type" varchar(24) NOT NULL,
  "filters" json NOT NULL,
  "sort_definition" json NOT NULL,
  "is_shared" boolean NOT NULL DEFAULT false,
  "created_at" timestamp NOT NULL
);

CREATE TABLE "recurring_card_rules" (
  "id" uuid PRIMARY KEY,
  "board_id" uuid NOT NULL,
  "list_id" uuid NOT NULL,
  "template_card" json NOT NULL,
  "recurrence_rule" varchar(200) NOT NULL,
  "timezone" varchar(64) NOT NULL DEFAULT 'UTC',
  "next_run_at" timestamp NOT NULL,
  "is_active" boolean NOT NULL DEFAULT true,
  "created_by" uuid
);

CREATE TABLE "api_keys" (
  "id" uuid PRIMARY KEY,
  "organization_id" uuid NOT NULL,
  "created_by" uuid,
  "name" varchar(120) NOT NULL,
  "key_prefix" varchar(16) NOT NULL,
  "secret_hash" text UNIQUE NOT NULL,
  "scopes" text NOT NULL,
  "last_used_at" timestamp,
  "expires_at" timestamp,
  "revoked_at" timestamp,
  "created_at" timestamp NOT NULL
);

CREATE TABLE "integrations" (
  "id" uuid PRIMARY KEY,
  "organization_id" uuid NOT NULL,
  "provider" varchar(80) NOT NULL,
  "external_account_id" varchar(255),
  "config_ciphertext" text,
  "connected_by" uuid,
  "connected_at" timestamp NOT NULL,
  "revoked_at" timestamp
);

CREATE TABLE "webhooks" (
  "id" uuid PRIMARY KEY,
  "organization_id" uuid NOT NULL,
  "endpoint_url" text NOT NULL,
  "secret_hash" text NOT NULL,
  "event_types" text NOT NULL,
  "is_active" boolean NOT NULL DEFAULT true,
  "created_by" uuid,
  "created_at" timestamp NOT NULL
);

CREATE TABLE "webhook_deliveries" (
  "id" uuid PRIMARY KEY,
  "webhook_id" uuid NOT NULL,
  "event_id" bigint,
  "status" delivery_status NOT NULL DEFAULT 'pending',
  "attempt_count" int NOT NULL DEFAULT 0,
  "response_code" int,
  "response_body" text,
  "next_attempt_at" timestamp,
  "delivered_at" timestamp,
  "created_at" timestamp NOT NULL
);

CREATE TABLE "plans" (
  "id" uuid PRIMARY KEY,
  "code" varchar(60) UNIQUE NOT NULL,
  "name" varchar(120) NOT NULL,
  "description" text,
  "amount_minor" bigint NOT NULL,
  "currency" char(3) NOT NULL,
  "billing_interval" varchar(12) NOT NULL,
  "limits" json NOT NULL,
  "features" json NOT NULL,
  "is_active" boolean NOT NULL DEFAULT true,
  "created_at" timestamp NOT NULL
);

CREATE TABLE "organization_billing_accounts" (
  "organization_id" uuid PRIMARY KEY,
  "provider" varchar(40) NOT NULL,
  "provider_customer_id" varchar(255) NOT NULL,
  "billing_email" varchar,
  "tax_id" text,
  "address" json NOT NULL,
  "created_at" timestamp NOT NULL
);

CREATE TABLE "subscriptions" (
  "id" uuid PRIMARY KEY,
  "organization_id" uuid NOT NULL,
  "plan_id" uuid NOT NULL,
  "provider_subscription_id" varchar(255),
  "status" subscription_status NOT NULL,
  "quantity" int NOT NULL DEFAULT 1,
  "current_period_start" timestamp,
  "current_period_end" timestamp,
  "trial_ends_at" timestamp,
  "cancel_at_period_end" boolean NOT NULL DEFAULT false,
  "cancelled_at" timestamp,
  "created_at" timestamp NOT NULL,
  "updated_at" timestamp NOT NULL
);

CREATE TABLE "invoices" (
  "id" uuid PRIMARY KEY,
  "organization_id" uuid NOT NULL,
  "subscription_id" uuid,
  "provider_invoice_id" varchar(255) UNIQUE,
  "invoice_number" varchar(80),
  "status" varchar(24) NOT NULL,
  "currency" char(3) NOT NULL,
  "subtotal_minor" bigint NOT NULL,
  "tax_minor" bigint NOT NULL DEFAULT 0,
  "total_minor" bigint NOT NULL,
  "due_at" timestamp,
  "paid_at" timestamp,
  "hosted_invoice_url" text,
  "created_at" timestamp NOT NULL
);

CREATE TABLE "payments" (
  "id" uuid PRIMARY KEY,
  "invoice_id" uuid NOT NULL,
  "provider_payment_id" varchar(255) UNIQUE,
  "amount_minor" bigint NOT NULL,
  "currency" char(3) NOT NULL,
  "status" varchar(24) NOT NULL,
  "processed_at" timestamp,
  "failure_code" varchar(80),
  "created_at" timestamp NOT NULL
);

CREATE UNIQUE INDEX ON "user_identities" ("provider", "provider_subject");

CREATE UNIQUE INDEX ON "user_identities" ("user_id", "provider");

CREATE INDEX ON "organization_memberships" ("user_id", "status");

CREATE INDEX ON "invitations" ("workspace_id", "organization_id");

CREATE INDEX ON "invitations" ("organization_id", "email", "status");

CREATE UNIQUE INDEX ON "roles" ("organization_id", "scope", "name");

CREATE UNIQUE INDEX ON "roles" ("id", "organization_id");

CREATE UNIQUE INDEX ON "workspaces" ("organization_id", "slug");

CREATE UNIQUE INDEX ON "workspaces" ("id", "organization_id");

CREATE UNIQUE INDEX ON "workspace_memberships" ("workspace_id", "organization_id", "user_id");

CREATE INDEX ON "workspace_memberships" ("user_id", "status");

CREATE UNIQUE INDEX ON "boards" ("id", "workspace_id");

CREATE UNIQUE INDEX ON "boards" ("id", "organization_id");

CREATE INDEX ON "boards" ("workspace_id", "created_at");

CREATE UNIQUE INDEX ON "board_memberships" ("board_id", "workspace_id", "user_id");

CREATE INDEX ON "board_memberships" ("user_id", "board_id");

CREATE UNIQUE INDEX ON "lists" ("id", "board_id");

CREATE INDEX ON "lists" ("board_id", "position");

CREATE UNIQUE INDEX ON "cards" ("id", "board_id");

CREATE INDEX ON "cards" ("list_id", "position");

CREATE INDEX ON "cards" ("board_id", "due_at");

CREATE INDEX ON "card_assignees" ("user_id", "card_id");

CREATE UNIQUE INDEX ON "labels" ("id", "board_id");

CREATE UNIQUE INDEX ON "labels" ("board_id", "name");

CREATE INDEX ON "card_labels" ("label_id", "card_id");

CREATE INDEX ON "card_dependencies" ("depends_on_card_id", "card_id");

CREATE UNIQUE INDEX ON "checklists" ("id", "card_id");

CREATE INDEX ON "checklist_items" ("checklist_id", "position", "id");

CREATE INDEX ON "comments" ("card_id", "created_at");

CREATE UNIQUE INDEX ON "attachment_links" ("attachment_id", "card_id");

CREATE UNIQUE INDEX ON "attachment_links" ("attachment_id", "comment_id");

CREATE UNIQUE INDEX ON "custom_field_definitions" ("id", "board_id");

CREATE UNIQUE INDEX ON "custom_field_definitions" ("board_id", "name");

CREATE INDEX ON "activity_events" ("organization_id", "created_at");

CREATE INDEX ON "activity_events" ("card_id", "created_at");

CREATE INDEX ON "audit_logs" ("organization_id", "created_at");

CREATE INDEX ON "notifications" ("user_id", "created_at");

CREATE UNIQUE INDEX ON "notification_deliveries" ("notification_id", "channel");

CREATE INDEX ON "notification_deliveries" ("status", "next_attempt_at");

CREATE INDEX ON "automation_executions" ("status", "created_at");

CREATE INDEX ON "outbox_events" ("status", "available_at", "occurred_at");

CREATE INDEX ON "outbox_events" ("status", "locked_at");

CREATE INDEX ON "outbox_events" ("aggregate_type", "aggregate_id", "occurred_at");

CREATE INDEX ON "outbox_events" ("published_at");

CREATE UNIQUE INDEX ON "saved_views" ("workspace_id", "user_id", "name");

CREATE INDEX ON "recurring_card_rules" ("next_run_at", "is_active");

CREATE UNIQUE INDEX ON "integrations" ("organization_id", "provider", "external_account_id");

CREATE INDEX ON "webhook_deliveries" ("status", "next_attempt_at");

CREATE UNIQUE INDEX ON "organization_billing_accounts" ("provider", "provider_customer_id");

ALTER TABLE "user_profiles" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "user_identities" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "user_sessions" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "user_mfa_methods" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "organizations" ADD FOREIGN KEY ("created_by") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "organization_memberships" ADD FOREIGN KEY ("organization_id") REFERENCES "organizations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "organization_memberships" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "invitations" ADD FOREIGN KEY ("organization_id") REFERENCES "organizations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "invitations" ADD FOREIGN KEY ("invited_by") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "roles" ADD FOREIGN KEY ("organization_id") REFERENCES "organizations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "role_permissions" ADD FOREIGN KEY ("role_id") REFERENCES "roles" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "role_permissions" ADD FOREIGN KEY ("permission_code") REFERENCES "permissions" ("code") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "workspaces" ADD FOREIGN KEY ("organization_id") REFERENCES "organizations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "workspaces" ADD FOREIGN KEY ("created_by") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "workspace_memberships" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "boards" ADD FOREIGN KEY ("created_by") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "board_memberships" ADD FOREIGN KEY ("added_by") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "board_preferences" ADD FOREIGN KEY ("board_id") REFERENCES "boards" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "board_preferences" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "lists" ADD FOREIGN KEY ("board_id") REFERENCES "boards" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "cards" ADD FOREIGN KEY ("created_by") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "card_assignees" ADD FOREIGN KEY ("assigned_by") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "labels" ADD FOREIGN KEY ("board_id") REFERENCES "boards" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "card_dependencies" ADD FOREIGN KEY ("card_id") REFERENCES "cards" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "card_dependencies" ADD FOREIGN KEY ("depends_on_card_id") REFERENCES "cards" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "card_dependencies" ADD FOREIGN KEY ("created_by") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "checklists" ADD FOREIGN KEY ("card_id") REFERENCES "cards" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "checklist_items" ADD FOREIGN KEY ("checklist_id") REFERENCES "checklists" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "checklist_items" ADD FOREIGN KEY ("completed_by") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "checklist_items" ADD FOREIGN KEY ("assigned_to_user_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "comments" ADD FOREIGN KEY ("card_id") REFERENCES "cards" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "comments" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "card_watchers" ADD FOREIGN KEY ("card_id") REFERENCES "cards" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "card_watchers" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "comment_mentions" ADD FOREIGN KEY ("comment_id") REFERENCES "comments" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "comment_mentions" ADD FOREIGN KEY ("mentioned_user_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "attachments" ADD FOREIGN KEY ("organization_id") REFERENCES "organizations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "attachments" ADD FOREIGN KEY ("uploaded_by") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "attachment_links" ADD FOREIGN KEY ("attachment_id") REFERENCES "attachments" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "attachment_links" ADD FOREIGN KEY ("card_id") REFERENCES "cards" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "attachment_links" ADD FOREIGN KEY ("comment_id") REFERENCES "comments" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "custom_field_definitions" ADD FOREIGN KEY ("board_id") REFERENCES "boards" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "card_custom_field_values" ADD FOREIGN KEY ("updated_by") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "activity_events" ADD FOREIGN KEY ("organization_id") REFERENCES "organizations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "activity_events" ADD FOREIGN KEY ("workspace_id") REFERENCES "workspaces" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "activity_events" ADD FOREIGN KEY ("board_id") REFERENCES "boards" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "activity_events" ADD FOREIGN KEY ("card_id") REFERENCES "cards" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "activity_events" ADD FOREIGN KEY ("actor_user_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "audit_logs" ADD FOREIGN KEY ("organization_id") REFERENCES "organizations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "audit_logs" ADD FOREIGN KEY ("actor_user_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "notification_preferences" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "notifications" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "notifications" ADD FOREIGN KEY ("organization_id") REFERENCES "organizations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "notification_deliveries" ADD FOREIGN KEY ("notification_id") REFERENCES "notifications" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "automation_rules" ADD FOREIGN KEY ("board_id") REFERENCES "boards" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "automation_rules" ADD FOREIGN KEY ("created_by") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "automation_executions" ADD FOREIGN KEY ("rule_id") REFERENCES "automation_rules" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "automation_executions" ADD FOREIGN KEY ("trigger_event_id") REFERENCES "activity_events" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "board_templates" ADD FOREIGN KEY ("organization_id") REFERENCES "organizations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "board_templates" ADD FOREIGN KEY ("created_by") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "saved_views" ADD FOREIGN KEY ("workspace_id") REFERENCES "workspaces" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "saved_views" ADD FOREIGN KEY ("user_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "recurring_card_rules" ADD FOREIGN KEY ("board_id") REFERENCES "boards" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "recurring_card_rules" ADD FOREIGN KEY ("created_by") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "api_keys" ADD FOREIGN KEY ("organization_id") REFERENCES "organizations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "api_keys" ADD FOREIGN KEY ("created_by") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "integrations" ADD FOREIGN KEY ("organization_id") REFERENCES "organizations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "integrations" ADD FOREIGN KEY ("connected_by") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "webhooks" ADD FOREIGN KEY ("organization_id") REFERENCES "organizations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "webhooks" ADD FOREIGN KEY ("created_by") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "webhook_deliveries" ADD FOREIGN KEY ("webhook_id") REFERENCES "webhooks" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "webhook_deliveries" ADD FOREIGN KEY ("event_id") REFERENCES "activity_events" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "organization_billing_accounts" ADD FOREIGN KEY ("organization_id") REFERENCES "organizations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "subscriptions" ADD FOREIGN KEY ("organization_id") REFERENCES "organizations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "subscriptions" ADD FOREIGN KEY ("plan_id") REFERENCES "plans" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "invoices" ADD FOREIGN KEY ("organization_id") REFERENCES "organizations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "invoices" ADD FOREIGN KEY ("subscription_id") REFERENCES "subscriptions" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "payments" ADD FOREIGN KEY ("invoice_id") REFERENCES "invoices" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "workspace_memberships" ADD FOREIGN KEY ("workspace_id", "organization_id") REFERENCES "workspaces" ("id", "organization_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "workspace_memberships" ADD FOREIGN KEY ("organization_id", "user_id") REFERENCES "organization_memberships" ("organization_id", "user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "invitations" ADD FOREIGN KEY ("workspace_id", "organization_id") REFERENCES "workspaces" ("id", "organization_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "boards" ADD FOREIGN KEY ("workspace_id", "organization_id") REFERENCES "workspaces" ("id", "organization_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "board_memberships" ADD FOREIGN KEY ("board_id", "workspace_id") REFERENCES "boards" ("id", "workspace_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "board_memberships" ADD FOREIGN KEY ("workspace_id", "user_id") REFERENCES "workspace_memberships" ("workspace_id", "user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "cards" ADD FOREIGN KEY ("list_id", "board_id") REFERENCES "lists" ("id", "board_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "card_assignees" ADD FOREIGN KEY ("card_id", "board_id") REFERENCES "cards" ("id", "board_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "card_assignees" ADD FOREIGN KEY ("board_id", "user_id") REFERENCES "board_memberships" ("board_id", "user_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "card_labels" ADD FOREIGN KEY ("card_id", "board_id") REFERENCES "cards" ("id", "board_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "card_labels" ADD FOREIGN KEY ("label_id", "board_id") REFERENCES "labels" ("id", "board_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "card_custom_field_values" ADD FOREIGN KEY ("card_id", "board_id") REFERENCES "cards" ("id", "board_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "card_custom_field_values" ADD FOREIGN KEY ("field_id", "board_id") REFERENCES "custom_field_definitions" ("id", "board_id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "recurring_card_rules" ADD FOREIGN KEY ("list_id", "board_id") REFERENCES "lists" ("id", "board_id") DEFERRABLE INITIALLY IMMEDIATE;
