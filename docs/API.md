# AdmitOne — REST API Reference

Base URL: `http://127.0.0.1:8000/api/`

All endpoints except **register** and **token** require:
`Authorization: Bearer <access_token>`

## Auth

### POST `/api/auth/register/`  (public)
```json
{ "email": "new@yourcompany.com", "full_name": "First User", "phone": "9876543210", "password": "Str0ng!Pass" }
```
Returns user object + `access`/`refresh` tokens.

### POST `/api/auth/token/`  (public)
```json
{ "email": "admin@yourcompany.com", "password": "<your password>" }
```
Returns `access` (30 min) and `refresh` (7 days).

### POST `/api/auth/token/refresh/`
```json
{ "refresh": "<refresh_token>" }
```
With `ROTATE_REFRESH_TOKENS=True`, returns a **new refresh + access** pair and blacklists the old one.

### GET `/api/auth/me/`
The caller's own profile, their workspace, and their effective permissions.
```json
{
  "user": { "id": 1, "email": "admin@yourcompany.com", "full_name": "…",
            "role": "ADMIN", "organization": 1 },
  "organization": { "id": 1, "name": "…", "slug": "…", "timezone": "…",
                    "working_hours_start": "09:00", "working_hours_end": "17:00" },
  "permissions": ["approve_visitor", "badge_print", "blacklist_visitor",
                  "checkin_visitor", "checkout_visitor", "create_visitor",
                  "manage_buildings", "manage_departments", "manage_employees",
                  "manage_org", "manage_users", "scan_qr", "view_audit_logs",
                  "view_dashboard", "view_reports"]
}
```
`organization` is `null` for a user who has not finished onboarding.

`permissions` is derived server-side from the caller's role by the same
`user_permissions()` function every endpoint authorizes with. **It exists for
UI rendering only** — hiding a link the caller cannot follow. No endpoint reads
it, and every request re-derives the caller's permissions from their role, so
posting a permission list or a role of your own choosing changes nothing.
Clients must not treat it as a token or cache it as an authorization decision;
if it is wrong, the only consequence is a page showing the wrong links.

## Visitors

### GET `/api/visitors/`
List visitors in your organization, paginated at 20 per page.
Query params: `?page=2`, `?q=rahul` (searches name, phone or company).

### GET `/api/visitors/{id}/`
Retrieve one visitor owned by your organization. Visitor ids belonging to
another organization return `404` — not a redacted body.

A visitor record belongs to exactly one organization and is deduplicated by
phone number *within* that organization. The same phone number registered by a
second organization creates a separate record there: visitor PII (document
number, address, emergency contact, internal notes) is never shared across
tenants.

## Visits

### GET `/api/visits/?status=CHECKED_IN`
List visits, optionally filtered by status (`PENDING`, `APPROVED`, `REJECTED`, `CHECKED_IN`, `CHECKED_OUT`).

### POST `/api/visits/`
**Not supported — returns `405`.** Visits are created by the two domain endpoints below, which
enforce the `create_visitor` permission, the 10/min registration throttle, organization/host/building
ownership, purpose and time-window validation, and write an `AuditLog` entry. (The generic route was
removed: it persisted the model straight from the serializer and skipped all of that — finding F2.)

### POST `/api/visits/register/`
Creates a visitor and a `PENDING` visit in one call (pre-registration flow used by the SPA).
Requires `create_visitor` (ADMIN / RECEPTIONIST). Rate-limited to 10 requests/min per IP.
`host` and `building` must belong to your own organization.

### POST `/api/visits/walkin/`
Walk-in flow used by the SPA: same body shape as `/api/visits/register/`, but the visit is
created `APPROVED` immediately with a live, single-use QR pass (no host approval step).
Requires `create_visitor` (ADMIN / RECEPTIONIST). Rate-limited to 10 requests/min per IP.

### POST `/api/visits/{id}/approve/`
Approves the visit and issues a signed QR pass. Admin only. `403` if you lack `approve_visitor`.

### POST `/api/visits/{id}/reject/`
```json
{ "reason": "No slot available" }
```

### POST `/api/visits/{id}/checkin/`
Marks visitor inside. Fails if not APPROVED, or if visitor is blacklisted.

### POST `/api/visits/{id}/checkout/`
Marks visitor out. Fails unless status is `CHECKED_IN`.

Each action returns `{ "detail": "...", "visit": { ... } }` with the updated visit + embedded QR.

### POST `/api/visits/{id}/reissue/`
Regenerates the signed QR pass for an APPROVED visit whose pass has expired or
already been used. Rotates the token + HMAC signature and resets single-use
state, so the old pass immediately stops scanning. Requires `approve_visitor`.

### POST `/api/auth/logout/`
```json
{ "refresh": "<refresh_token>" }
```
Blacklists the presented refresh token (returns `205`). The still-valid access
token is discarded client-side by the SPA.

## Dashboard

### GET `/api/dashboard/summary/`
```json
{ "today": 4, "week": 12, "month": 30, "inside": 2, "pending": 1, "approved": 3, "avg_duration_minutes": 65 }
```

## Field-level privacy and credential scoping

Visitor and pass payloads are trimmed per role (audit follow-up):

| Fields | Capability | Roles |
|---|---|---|
| `address`, `emergency_contact`, `emergency_phone` | `view_visitor_pii` | ADMIN, RECEPTIONIST |
| `document_type`, `document_number` | `view_visitor_documents` | all three |
| `qr.token`, `qr.signature` (the admission credential) | `badge_print` | ADMIN, RECEPTIONIST |

A SECURITY caller therefore sees `qr: {expires_at, is_used, is_valid}` only, and
no home details. The same rule applies wherever the visitor or pass is nested.

Other behaviours worth knowing:

* `POST /api/visits/register/` and `/walkin/` return `warnings: [...]` when the
  chosen host already has a visitor in an overlapping slot (walk-ins exempt).
  The visit is still created; reception sees the clash.
* Walk-ins are stored with `source=WALK_IN`; desk pre-registrations with `STAFF`.
* `POST /api/auth/token/` is throttled per IP (20/min) in addition to the
  5-strike account lockout; `POST /api/auth/register/` runs Django's full
  password validators; e-mails are unique case-insensitively.
* `PATCH /api/organizations/me/` accepts `weekly_working_hours`
  (`{"0".."6": [{"start","end"}, ...]}`, empty list = closed) which the
  booking slot engine uses; invalid keys, times or overlapping windows are 400.
* `/api/hosts/` omits employees whose profile is `INACTIVE` or `ON_LEAVE`.
* `GET /api/dashboard/summary/` requires `view_reports` (all three roles).
* Access tokens live 15 minutes; refresh tokens rotate.

## Console management endpoints

Everything below is JWT-protected and tenant-scoped. A caller without a
workspace receives `403 {"detail": "Finish creating your workspace before
using this feature."}` rather than an empty list. Mutations write an
`AuditLog` row in the same transaction.

### Visits — filters, scan, cancel

`GET /api/visits/` accepts: `status` (single or comma list, e.g.
`PENDING,APPROVED`), `q` (visitor name/phone/company, purpose, host),
`date=today|YYYY-MM-DD`, `date_from`, `date_to`, `visitor`, `host`,
`building`, `inside=1`, `upcoming=1`, `ordering`
(`registered_at|visit_date|expected_arrival|checked_in_at`, prefix `-`
to reverse), `page`, `page_size`. Each row carries `approved_at`,
`rejected_at`, `rejection_reason`, `cancelled_at`, `cancelled_reason`,
`arriving_at`, `source`, `visit_type_label`, `department_name`,
`created_by_name`, `checked_in_by_name`, `checked_out_by_name` and `qr`.

| Method | Endpoint | Capability | Purpose |
|---|---|---|---|
| POST | `/api/visits/scan/` | `scan_qr` | Body `{"payload": "token\|signature"}` or `{"token","signature"}`; verifies the signed pass (signature, single-use, expiry, **same workspace**) and checks the visitor in. `{"dry_run": true}` verifies without redeeming. Failures return `400 {"ok": false, "detail", "visit"}` where `visit` is only populated for the caller's own workspace. |
| POST | `/api/visits/{id}/cancel/` | `approve_visitor` or `create_visitor` | Body `{"reason"}` (≤120 chars). PENDING/APPROVED → CANCELLED; the pass is voided and reminders dropped. |

### Visitors

| Method | Endpoint | Capability | Purpose |
|---|---|---|---|
| GET | `/api/visitors/` | any member | Adds `?q`, `?blacklisted=1|0`, `?ordering=full_name|-created_at|-visit_count|-last_visit_at`. Rows carry `is_blacklisted`, `blacklist_reason`, `visit_count`, `last_visit_at`. |
| PATCH | `/api/visitors/{id}/` | `create_visitor` | Edit profile fields (phone must stay unique per workspace → 400). |
| GET | `/api/visitors/{id}/visits/` | any member | Visit history (≤100 rows). |
| POST | `/api/visitors/{id}/blacklist/` | `blacklist_visitor` | Body `{"reason": SECURITY_CONCERN\|FAKE_DOCUMENTS\|MISCONDUCT\|PERMANENT_BAN, "comment"}` → 201. |
| DELETE | `/api/visitors/{id}/blacklist/` | `manage_org` | Lift every active ban. |
| GET | `/api/blacklist/` | any member | Active entries, `?q`, `?include_inactive=1`, paginated. |

### Workspace

| Method | Endpoint | Capability | Purpose |
|---|---|---|---|
| GET | `/api/organizations/me/` | any member | Full profile incl. `visitor_policies`, `security_policies`, `booking_path`. |
| PATCH | `/api/organizations/me/` | `manage_org` | Name, tagline, address, timezone (IANA, validated), working hours (end > start), policies (`reminder_offsets_hours`, `slot_duration_minutes`). `slug` is read-only. |
| GET/POST | `/api/buildings/` | read: member · write: `manage_buildings` | List / create. |
| PATCH/DELETE | `/api/buildings/{id}/` | `manage_buildings` | Update / delete (the last building cannot be deleted). |
| GET/POST | `/api/departments/` | read: member · write: `manage_departments` | Rows include `member_count`; names unique per workspace. |
| PATCH/DELETE | `/api/departments/{id}/` | `manage_departments` | Update / delete. |
| GET | `/api/time/` | any member | `{"now","today","timezone"}` in the organisation's timezone. |

### Team (ADMIN only — `manage_users`)

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/team/` | Members with employee profile; `?q`, `?role`. |
| POST | `/api/team/` | `{"email","full_name","role","password","phone?","designation?","employee_id?","department?","building?"}` creates the account + employee profile. Password is validated by Django's validators. |
| PATCH | `/api/team/{id}/` | Any of `full_name, phone, role, is_active, designation, employee_id, office_location, department, building, status, password`. Guards: you cannot change your own role or deactivate yourself; the last active admin cannot be demoted or deactivated. |
| DELETE | `/api/team/{id}/` | Deactivates (never deletes) the account. |

### Audit log (ADMIN only — `view_audit_logs`)

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/audit-logs/` | Paginated, `?q`, `?action`, `?entity_type`, `?actor=<user id>`, `?date_from`, `?date_to`. Append `&export=csv` for a CSV download. Read-only: no write route exists. |
| GET | `/api/audit-logs/actions/` | Distinct action names for filter menus. |

### Account

| Method | Endpoint | Purpose |
|---|---|---|
| PATCH | `/api/auth/me/profile/` | `{"full_name","phone"}` |
| POST | `/api/auth/change-password/` | `{"current_password","new_password"}` |

### Dashboard analytics

`GET /api/dashboard/summary/` now also returns `total`, `repeat_visitors`,
`first_time_visitors` and an `analytics` object computed database-side:
`daily_series` (14 days: `date, visits, checked_in`), `status_counts`,
`top_visitors`, `peak_hours`, `by_department`, `today_schedule`.

### Health

`GET /api/health/` → `200 {"status":"ok","database":"ok"}`, or
`503 {"status":"degraded","database":"error"}` when the database does not
answer.

## Visitor accounts (`/api/visitor/`)

Self-service visitors have their **own** account model (`visits.VisitorAccount`)
and bearer sessions; they are never staff users, so no console permission can
apply to them. Sessions last 14 days; sign-in has the same 5-attempt /
15-minute lockout as staff. A visitor only ever reaches visits whose per-tenant
`Visitor` record their account owns (`Visitor.account`).

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/visitor/auth/register/` | `{email, password, full_name, phone, company?, designation?}` → `201 {token, account}` |
| POST | `/api/visitor/auth/login/` | `{email, password}` → `{token, account}` |
| POST | `/api/visitor/auth/logout/` | Revoke the current session |
| GET / PATCH | `/api/visitor/me/` | Profile (`full_name, phone, company, designation`) |
| POST | `/api/visitor/change-password/` | `{current_password, new_password}` |
| GET | `/api/visitor/organizations/?q=` | Search organisations by name / slug / city (min 2 chars, signed in) |
| GET | `/api/visitor/organizations/{slug}/` | Booking form options for one organisation (same shape as the public booking context) |
| GET | `/api/visitor/bookings/` | All of the visitor's visits across organisations (portal shape + `organization_slug`) |
| POST | `/api/visitor/bookings/` | `{organization: slug, visit_type, purpose, purpose_other?, department?, building?, floor?, host?, visit_date, expected_arrival, expected_exit, notes?}` → `201 {message, visit}`; identity comes from the account. Creates a PENDING pre-booking and links the visitor record to the account. |
| GET | `/api/visitor/bookings/{id}/` | One visit |
| GET | `/api/visitor/bookings/{id}/availability/?date=` | Free slots with that visit's host |
| POST | `/api/visitor/bookings/{id}/reschedule/` | `{visit_date, expected_arrival, expected_exit}` |
| POST | `/api/visitor/bookings/{id}/cancel/` | `{reason?}` — voids any issued pass |
| POST | `/api/visitor/bookings/{id}/arriving/` | "I'm arriving" signal (notifies the host; never checks in) |

Hosts and slot availability for the booking form come from the public
`/api/public/booking/{slug}/hosts/` and `/availability/` endpoints.

## Quick test with curl

```bash
# get tokens
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@yourcompany.com","password":"<your password>"}' | python -c "import sys,json;print(json.load(sys.stdin)['access'])")

# list visits
curl -s http://127.0.0.1:8000/api/visits/?status=CHECKED_IN \
  -H "Authorization: Bearer $TOKEN"

# approve visit 1
curl -s -X POST http://127.0.0.1:8000/api/visits/1/approve/ \
  -H "Authorization: Bearer $TOKEN"
```

## Error conventions

- `400` — validation / workflow rule violation (e.g. "Visitor is blacklisted")
- `401` — missing / expired token
- `403` — authenticated but lacks the role permission
- `404` — unknown resource or outside your organization (org-scoped queries)
