# Spec 0001 — Task sharing between users

**Status:** Draft
**Owner:** (you)
**Scope:** Let a user share a single task with another user in the same org, with a
read-only or edit permission.

> A small, deliberately-imperfect spec to try keel's `spec-review` on. It has a few
> gaps a multi-model review should catch — leave them in and see what surfaces.

## Goal

A task owner can grant another user in their org access to one task, as either
`viewer` (read-only) or `editor` (can change task fields but not delete). Shares are
revocable. This unblocks small-team collaboration without exposing whole task lists.

## Non-goals

- Sharing an entire task list (separate spec later).
- Sharing across orgs (explicitly forbidden — see security policy).
- Public / link-based sharing.

## Data model

New table `task_shares`:

| Column | Type | Notes |
|--------|------|-------|
| `id` | uuid pk | |
| `task_id` | uuid | the shared task |
| `grantee_user_id` | uuid | who it's shared with |
| `permission` | text | `viewer` or `editor` |
| `created_at` | timestamptz | |

## API

- `POST /tasks/:id/share` — body `{ granteeUserId, permission }`. Creates a share.
  Returns `201` with the share.
- `DELETE /tasks/:id/share/:shareId` — revokes a share. Returns `204`.
- `GET /tasks/:id/shares` — lists shares on a task.

## Behavior

- Only the task owner may create or revoke shares.
- A `viewer` may read the task; an `editor` may also update its fields.
- When a task is deleted, its shares go away.

## Open questions

- What happens if you share a task with someone who already has a share?
- Should the grantee be notified?
