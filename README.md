# 🛡️ SecureGate

<p align="center">
  <img src="https://raw.githubusercontent.com/Mdehteshamulhaque1/Secure_Gate/main/docs/securegate-logo.svg" alt="SecureGate Logo" width="96" />
</p>

<h1 align="center">SecureGate</h1>

<p align="center">
  <strong>Visitor Management & Secure Gate Access Platform</strong>
</p>

<p align="center">
  Register visitors, manage approvals, issue signed one-time QR passes, verify entry at the gate, track visitors inside, and keep an auditable operational history.
</p>

<p align="center">
  <a href="https://github.com/Mdehteshamulhaque1/Secure_Gate">
    <img src="https://img.shields.io/badge/GitHub-Repository-181717?style=flat-square&logo=github" alt="GitHub">
  </a>
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.11">
  <img src="https://img.shields.io/badge/Django-5.2-092E20?style=flat-square&logo=django&logoColor=white" alt="Django 5.2">
  <img src="https://img.shields.io/badge/DRF-3.15-A30000?style=flat-square" alt="DRF">
  <img src="https://img.shields.io/badge/React-19-20232A?style=flat-square&logo=react&logoColor=61DAFB" alt="React 19">
  <img src="https://img.shields.io/badge/TypeScript-5.7-3178C6?style=flat-square&logo=typescript&logoColor=white" alt="TypeScript">
  <img src="https://img.shields.io/badge/Vite-6-646CFF?style=flat-square&logo=vite&logoColor=white" alt="Vite">
  <img src="https://img.shields.io/badge/PostgreSQL-Supabase-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/Mdehteshamulhaque1/Secure_Gate/main/docs/securegate-workflow.svg" alt="SecureGate Workflow" width="900" />
</p>

---

## ✨ What is SecureGate?

SecureGate is a full-stack visitor and gate-access management system built around a controlled visitor lifecycle:

**Register → Approve → Issue QR → Verify → Check In → Check Out → Audit**

The application combines a Django REST backend with a React/TypeScript SPA and a PostgreSQL database hosted on Supabase.

It is designed as a production-style application rather than a simple CRUD demo, with organization-scoped data, RBAC, throttling, account lockout, signed QR passes, email delivery, audit logging, reporting, and deployment automation.

---

## 🚀 Core Capabilities

### 👤 Visitor management
- Pre-register visitors before arrival
- Register walk-in visitors
- Search and paginate the visitor directory
- Store contact, company and designation information
- Capture identity-document metadata and uploads
- Record vehicle details
- Store emergency-contact information
- Add special notes
- Detect and manage blacklisted visitors

### ✅ Approval workflow
- Visits begin in `PENDING`
- Authorized users can approve or reject pending visits
- Approval generates a signed QR pass
- Approval can trigger QR email delivery to the visitor
- Rejection stores a reason for traceability

### 🎫 Secure QR passes
- HMAC-SHA256 signatures
- Bound to the visit, organization and opaque token
- 120-minute validity window
- Single-use enforcement
- Duplicate/replay scans rejected
- Tampered signatures rejected
- Expired passes rejected

### 🚪 Gate operations
- Security-focused check-in/check-out workflow
- QR verification before QR-based admission
- Blacklisted visitors are denied entry
- Concurrent scan/action safety through database row locking
- Manual operational check-in can still be used where permitted

### 📊 Dashboard & reporting
- Visitors today
- Weekly and monthly volume
- Visitors currently inside
- Pending and approved visits
- Checked-out and rejected visits
- Average visit duration
- Visit-trend visualization
- Top-visitor visualization
- Recent visit activity
- Status breakdowns
- CSV report export

### 🏢 Organization management
- Organization workspace creation
- Buildings, floors and gates
- Departments
- Employees and hosts
- Organization timezone
- Working hours
- Security and visitor policy JSON configuration

### 🧾 Auditability
Important operations write audit records containing the actor, action, entity, details, IP address and timestamp.

---

## 🔐 How the QR security model works

A QR pass is issued only after a visit reaches `APPROVED`.

The backend signs:

```text
visit_id | organization_id | token
```

using Django's `SECRET_KEY` with HMAC-SHA256.

The QR encodes:

```text
token | signature
```

At verification time SecureGate checks:

1. The token exists.
2. The signature matches the server-generated HMAC.
3. The pass has not already been used.
4. The pass has not expired.
5. The associated visit is in the expected state for QR admission.

A successful QR check-in marks the pass as used inside the same transaction that changes the visit state, preventing concurrent double-use.

---

## 🔄 Visitor lifecycle

```text
                    ┌─────────────┐
                    │   Visitor   │
                    │  Registered │
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │   PENDING   │
                    └──────┬──────┘
                           │
                ┌──────────┴──────────┐
                │                     │
             Reject                Approve
                │                     │
                ▼                     ▼
          ┌───────────┐         ┌────────────┐
          │ REJECTED  │         │  APPROVED  │
          └───────────┘         └─────┬──────┘
                                      │
                                  QR issued
                                      │
                                      ▼
                               ┌─────────────┐
                               │ CHECKED_IN  │
                               └──────┬──────┘
                                      │
                                      ▼
                               ┌─────────────┐
                               │ CHECKED_OUT │
                               └──────┬──────┘
                                      │
                                      ▼
                               ┌─────────────┐
                               │   ARCHIVED  │
                               └─────────────┘
```

---

## 🏗️ Architecture

```text
                           SecureGate
                               │
              ┌────────────────┴────────────────┐
              │                                 │
              ▼                                 ▼
      React 19 + TypeScript              Django 5.2 + DRF
          Vite + Tailwind                     + SimpleJWT
              │                                 │
              │           REST / JWT             │
              └────────────────┬────────────────┘
                               │
                               ▼
                        PostgreSQL / Supabase
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
      Visitor data         Visit / QR         Audit / Reports
```

### Application layers

| Layer | Implementation |
|---|---|
| Frontend | React 19 + TypeScript 5.7 + Vite 6 |
| UI | Tailwind CSS 4 + Radix primitives |
| Data fetching | TanStack React Query |
| Forms | React Hook Form |
| Validation | Zod |
| Charts | Recharts |
| Motion | Framer Motion |
| Icons | Lucide React |
| Backend | Django 5.2 |
| API | Django REST Framework 3.15 |
| Authentication | SimpleJWT |
| Password hashing | Argon2 |
| Database | PostgreSQL |
| Managed DB host | Supabase |
| Backend hosting | Render |
| Frontend hosting | Vercel |
| CI | GitHub Actions |

---

## ⚛️ Frontend

The SPA contains public marketing/authentication routes and protected dashboard routes.

### Public routes

```text
/
├── Landing page
├── /login
└── /signup
```

### Onboarding

```text
/onboarding
└── Create organization / workspace
```

A newly registered user without an organization is redirected into onboarding. Creating a workspace promotes the creator to `ADMIN` and creates a default building plus an employee profile.

### Protected dashboard

```text
/dashboard
├── Dashboard            KPIs, 14-day flow, today's schedule, recent activity
├── Visits               filterable, paginated visit log + visit detail drawer
├── Visitor directory    search, sort, profile drawer, edit, blacklist, new visit
├── Register visit       pre-registration or walk-in (instant pass, print)
├── Approvals            approve / reject queue, recent decisions
├── Gate scanner         camera + hardware-scanner + manual pass entry, inside-now, expected-today
├── Blacklist            active bans; admins lift them
├── Reports              daily series, status mix, peak hours, departments, CSV exports
├── Audit log            filterable trail with CSV export
├── Team                 add members, roles, reset passwords, deactivate
└── Settings             workspace profile & hours, buildings, departments, my account
```

The console follows the operating-system theme and offers light, dark and
system modes (persisted per device); the marketing page is always dark.

### Visitor self-service (one page)

```text
/visitor  (also /book, /book/<slug>, /my-visit)
  1. Your account      sign up or sign in (separate visitor account, not a staff user)
  2. Where             search the organisation, or arrive via /book/<slug> with it pre-selected
  3. Visit details     visit type, purpose, department, person to meet, building/floor
  4. When              date + free slots of that host inside working hours
  5. Review            summary, notes, submit -> PENDING booking stored for the organisation
  6. Confirmed         reference, what happens next
  My visits            status, QR pass once approved, "I'm arriving", reschedule, cancel
```

### Dashboard

- KPI cards
- 14-day visit-flow chart
- Top-visitor visualization
- Recent visits
- Loading/skeleton states
- Retry/error states
- Quick links to approvals and visitor registration

### Visitors

- Search by name, phone or company
- Server-side pagination
- Visitor table
- Visitor status
- Blacklist indicator
- Visitor drawer
- Related visits
- Active QR pass visibility

### Register Visit

- Multi-field visitor form
- Visit details
- Host selection
- Building selection
- Expected arrival/exit
- Zod validation
- React Hook Form
- Pre-registration path
- Walk-in path

### Approvals

- Pending/recent approval queues
- Approve action
- Reject action with reason
- Query invalidation after state changes

### Gate scanner (Security)

- Camera QR scanning in the browser (html5-qrcode, loaded on demand), plus
  USB/Bluetooth barcode-scanner keyboard capture and manual code entry
- Every scan goes through `POST /api/visits/scan/`: signature, single-use,
  expiry and same-workspace checks, then check-in in one transaction
- Clear "Entry granted / Entry denied" result card with the visitor, reason
  and a recent-scan history
- Inside-now roster with check-out; expected-today roster with manual
  check-in for approved visits only (pending visits are flagged, not admitted)
- Role-gated access for `SECURITY` and `ADMIN`

### Blacklist, Team, Audit log, Settings

- Blacklist: security adds entries with a reason; only admins lift them
- Team: add members with a role and initial password, change roles, reset
  passwords, deactivate (last-admin and self-change guards)
- Audit log: filter by text, action, actor and date; CSV export
- Settings: workspace identity, timezone, working hours, reminder offsets,
  slot length, buildings, departments, public booking link, own profile and
  password

### Reports

- Current reporting KPIs
- Status breakdown
- Visit log
- Monthly CSV export
- Full CSV export
- Export status feedback

---

## 🐍 Backend

Django is organized into domain-focused applications.

| App | Responsibility |
|---|---|
| `accounts` | Custom email user, roles, lockout, authentication backend and permissions |
| `api` | DRF endpoints, serializers, throttling and API tests |
| `organizations` | Organization, buildings, floors, gates, departments, employees and audit log |
| `visits` | Visitor, Visit, QRPass, Blacklist, workflow services, QR generation and email |
| `reports` | Dashboard data, report querysets, trends and CSV export |
| `config` | Environment configuration, routing, middleware, WSGI/ASGI |

### Scheduled jobs

Run on a schedule (cron, systemd timer or a Render cron job); none needs a
message broker:

```text
python manage.py send_visit_reminders      # every 5–30 min: due reminder e-mails
python manage.py archive_old_visits        # daily: CHECKED_OUT -> ARCHIVED after 30 days
python manage.py purge_expired_sessions    # daily: drop expired visitor portal/account sessions
```

### Shared service layer

The visit lifecycle is implemented in `backend/visits/services.py` and reused by every API endpoint (staff console, visitor accounts, public booking) so there is exactly one implementation of each transition.

Core operations include:

```text
register_visit()
approve_visit()
reject_visit()
check_in()
check_out()
archive_old_visits()
```

Workflow transitions are protected with database transactions and `select_for_update()` where state consistency matters.

---

## 👥 RBAC

SecureGate uses three primary roles.

| Role | Main capabilities |
|---|---|
| `ADMIN` | Organization management, visitor operations, approvals, gate operations, reports, audit access |
| `RECEPTIONIST` | Visitor creation and reception operations, badge printing, reports |
| `SECURITY` | QR scanning, check-in/check-out, blacklist operations, reports |

Frontend navigation and backend permissions both enforce role restrictions.

Backend permissions include capabilities such as:

```text
create_visitor
approve_visitor
checkin_visitor
checkout_visitor
manage_org
manage_buildings
manage_departments
manage_employees
manage_users
view_reports
view_audit_logs
blacklist_visitor
badge_print
scan_qr
```

---

## 🗄️ Data model

```text
User
 │
 └── Organization
      ├── Building
      │    ├── Floor
      │    └── Gate
      │
      ├── Department
      │    └── Employee
      │
      ├── Visitor
      │    └── Visit
      │         └── QRPass
      │
      ├── Blacklist
      │
      └── AuditLog
```

### Key entities

#### User
Email-based custom user with role, organization, failed-login counters, lockout information, verification state and notification preferences.

#### Organization
Workspace-level configuration including identity, location, timezone, working hours and policy JSON.

#### Visitor
Identity/contact profile plus document, vehicle, emergency-contact and notes data.

#### Visit
A single visit instance with UUID, organization, building, host, purpose, scheduled arrival/exit and lifecycle timestamps.

#### QRPass
One-to-one with a visit and stores the signed token, expiration and usage state.

#### Blacklist
Organization-level visitor blocking with reason, comment, actor and active state.

#### AuditLog
Operational history with action, entity, actor, details, IP and timestamp.

---

## 🔌 REST API

### Authentication

| Method | Endpoint | Access |
|---|---|---|
| POST | `/api/auth/register/` | Public |
| POST | `/api/auth/token/` | Public |
| POST | `/api/auth/token/refresh/` | Public with refresh token |
| POST | `/api/auth/logout/` | Authenticated — blacklists the refresh token |
| GET | `/api/auth/me/` | Authenticated |

### Visitor / visit operations

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/visits/register/` | Pre-register visitor + visit (PENDING) |
| POST | `/api/visits/walkin/` | Register walk-in (APPROVED + pass) |
| GET | `/api/visitors/` | Visitor directory (`q`, `blacklisted`, `ordering`; annotated with visit counts) |
| PATCH | `/api/visitors/{id}/` | Edit a visitor profile |
| GET | `/api/visitors/{id}/visits/` | A visitor's visit history |
| POST / DELETE | `/api/visitors/{id}/blacklist/` | Blacklist (SECURITY/ADMIN) / lift (ADMIN) |
| GET | `/api/blacklist/` | Active blacklist entries |
| GET | `/api/visits/` | Paginated visit feed with `status`, `q`, `date=today`, `date_from/to`, `visitor`, `host`, `inside`, `upcoming`, `ordering` |
| POST | `/api/visits/scan/` | Verify a scanned QR pass and check in (`dry_run` to verify only) |
| POST | `/api/visits/{id}/approve/` | Approve + issue QR |
| POST | `/api/visits/{id}/reject/` | Reject visit |
| POST | `/api/visits/{id}/checkin/` | Manual check in |
| POST | `/api/visits/{id}/checkout/` | Check out |
| POST | `/api/visits/{id}/reissue/` | Regenerate an expired/used QR pass |
| POST | `/api/visits/{id}/cancel/` | Cancel a pending/approved visit (voids the pass) |

### Organization data

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/organizations/` | Create workspace (caller becomes ADMIN) |
| GET / PATCH | `/api/organizations/me/` | Workspace profile, timezone, working hours, policies (PATCH = ADMIN) |
| GET | `/api/hosts/` | Available hosts |
| GET / POST / PATCH / DELETE | `/api/buildings/` | Buildings (writes = ADMIN) |
| GET / POST / PATCH / DELETE | `/api/departments/` | Departments (writes = ADMIN) |
| GET / POST / PATCH / DELETE | `/api/team/` | Workspace members, roles, password resets, deactivation (ADMIN) |
| GET | `/api/audit-logs/` | Filterable audit trail, `?export=csv` (ADMIN) |
| PATCH | `/api/auth/me/profile/` | Edit own name / phone |
| POST | `/api/auth/change-password/` | Change own password |
| GET | `/api/time/` | Organisation-local date/time |

### Analytics / exports

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/dashboard/summary/` | KPI summary |
| GET | `/api/reports/export/?period=daily` | CSV export |
| GET | `/api/reports/export/?period=weekly` | CSV export |
| GET | `/api/reports/export/?period=monthly` | CSV export |
| GET | `/api/reports/export/?period=all` | Full CSV export |
| GET | `/api/health/` | Public health probe |

---

## 🔒 Security controls

### Authentication & credentials
- Email-based custom user model
- Argon2 password hashing
- JWT access + refresh tokens
- Refresh token rotation
- Blacklisting of rotated refresh tokens
- Shared lockout state across authentication paths

### Login protection
```text
5 failed attempts
      ↓
15-minute temporary lock
      ↓
Successful login resets counters
```

### API protection
- Anonymous: `100/hour`
- Authenticated: `1000/hour`
- Visit registration: `10/minute/IP`
- Default DRF permission: `IsAuthenticated`
- Pagination default: 20
- Maximum page size: 1000

### HTTP / browser security
- HTTPS redirect in production
- Secure cookies
- HSTS
- HSTS preload
- Content-Security-Policy middleware
- `frame-ancestors 'none'`
- Content-type sniffing protection
- Referrer policy
- CORS allowlist
- Environment-driven CSRF trusted origins

### Multi-tenant isolation
- API querysets are organization-scoped
- Host and building lists are organization-scoped
- Visit action service checks the acting user's organization
- Visitor deduplication is constrained to the current organization

### Data minimisation
- Home address and emergency contact: ADMIN and RECEPTIONIST only (`view_visitor_pii`)
- Identity-document type/number: all roles (gate verifies ID)
- Raw QR credential (token + signature): ADMIN and RECEPTIONIST only (`badge_print`); SECURITY sees pass status only
- Staff sign-in throttled per IP on top of the account lockout
- Access tokens expire after 15 minutes; refresh tokens rotate and are blacklisted

### Audit trail immutability
- Database trigger (`organizations.0006`) rejects any update to recorded facts; on PostgreSQL it also rejects deletes
- The only post-insert writes allowed are the `SET_NULL` cascades when an actor or workspace is removed
- Application code never updates or deletes audit rows; the admin denies it too

### Input and file validation
- DRF serializer validation
- Zod validation in the SPA
- Visitor document uploads restricted to:
  - PDF
  - JPG
  - JPEG
  - PNG

---

## ⚡ Performance & reliability

The codebase includes several practical optimizations:

- `select_related("visitor", "host", "building")` for visit listings
- Database indexes on visit status/date and organization/state combinations
- Bounded pagination
- PostgreSQL connection reuse with health checks
- React Query caching and invalidation
- Lazy loading for the landing page
- 30-second API request timeout to prevent indefinite UI spinners
- Transactional workflow state changes
- Row-level locking for sensitive concurrent actions

---

## 📁 Repository structure

```text
Secure_Gate/
├── backend/
│   ├── accounts/
│   ├── api/
│   ├── config/
│   ├── organizations/
│   ├── reports/
│   ├── visits/
│   ├── templates/
│   ├── manage.py
│   ├── requirements.txt
│   ├── .env.example
│   └── e2e_smoke.py
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── landing/
│   │   │   ├── layout/
│   │   │   ├── ui/
│   │   │   ├── visitors/
│   │   │   ├── widgets/
│   │   │   └── logo.tsx
│   │   ├── hooks/
│   │   ├── lib/
│   │   │   ├── api.ts
│   │   │   ├── auth.tsx
│   │   │   ├── queries.ts
│   │   │   ├── types.ts
│   │   │   └── utils.ts
│   │   └── pages/
│   │       ├── auth/
│   │       ├── landing.tsx
│   │       ├── onboarding.tsx
│   │       ├── dashboard.tsx
│   │       ├── visitors.tsx
│   │       ├── register-visit.tsx
│   │       ├── approvals.tsx
│   │       ├── security.tsx
│   │       ├── reports.tsx
│   │       └── error.tsx
│   ├── package.json
│   └── vercel.json
│
├── docs/
│   └── database/
│
├── supabase/
│   └── migrations/
│
├── .github/
│   └── workflows/
│       └── ci.yml
│
├── render.yaml
├── pyproject.toml
├── README.md
└── docs/
    ├── PLAN.md
    ├── ARCHITECTURE.md
    ├── API.md
    └── DEPLOYMENT.md
```

---

## 🧪 Testing & CI

GitHub Actions runs checks on pushes to `main` and on pull requests.

### Backend pipeline

```text
checkout
   ↓
Python 3.11
   ↓
pip install
   ↓
django check
   ↓
unit tests
   ↓
e2e smoke tests
   ↓
collectstatic
   ↓
production deploy check
```

### Frontend pipeline

```text
checkout
   ↓
Node 22
   ↓
npm ci
   ↓
TypeScript typecheck
   ↓
Vite production build
```

Run locally:

### Backend

```bash
cd backend
python manage.py check
python manage.py test
python manage.py test e2e_smoke
python manage.py collectstatic --noinput
```

### Frontend

```bash
cd frontend
npm install
npm run typecheck
npm run build
```

---

## 💻 Local development

### Requirements

- Python 3.11
- Node.js 22
- npm
- Git
- PostgreSQL for production-like local development

SQLite is supported as the local fallback when `DATABASE_URL` is not supplied.

### 1. Clone

```bash
git clone https://github.com/Mdehteshamulhaque1/Secure_Gate.git
cd Secure_Gate
```

### 2. Backend

```bash
cd backend

python -m venv venv
```

Windows:

```bash
venv\Scripts\activate
```

macOS/Linux:

```bash
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Copy environment configuration:

```bash
copy .env.example .env
```

Or on macOS/Linux:

```bash
cp .env.example .env
```

Apply migrations:

```bash
python manage.py migrate
```

Create an admin account when required:

```bash
python manage.py createsuperuser
```

Run Django:

```bash
python manage.py runserver
```

### 3. Frontend

```bash
cd ../frontend
npm install
npm run dev
```

---

## 🌐 Deployment

SecureGate's repository contains deployment configuration for:

### Backend — Render

```text
GitHub main
    ↓
Render
    ↓
pip install
    ↓
collectstatic
    ↓
Django migrate
    ↓
Gunicorn
    ↓
/api/health/
```

The repository contains `render.yaml` with:

- Python 3.11
- `backend` root directory
- automatic deployment
- pre-deploy migrations
- Gunicorn
- health check on `/api/health/`

### Frontend — Vercel

The React/Vite application is deployed from `frontend/`.

The frontend reads the backend URL from the `VITE_API_BASE_URL` build-time environment variable. For the full step-by-step deployment walkthrough, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

### Database — Supabase

Supabase is used as a managed PostgreSQL host.

Django owns the schema and migrations; Supabase is used for PostgreSQL infrastructure rather than Supabase Auth or PostgREST.

---

## 🔑 Environment variables

### Backend

```env
SECRET_KEY=
DJANGO_ENV=development
DJANGO_DEBUG=False
ALLOWED_HOSTS=
DATABASE_URL=

CSRF_TRUSTED_ORIGINS=
CORS_ALLOWED_ORIGINS=

EMAIL_BACKEND=
EMAIL_HOST=
EMAIL_PORT=
EMAIL_USE_TLS=
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
DEFAULT_FROM_EMAIL=
```

### Frontend

```env
VITE_API_BASE_URL=
```

For production, keep secrets out of Git and configure them in the hosting provider.

---

## 📧 QR email delivery

When a visit is approved, SecureGate can generate an HTML email containing the QR pass.

The email flow is intentionally non-blocking:

```text
Approve visit
     ↓
Create QR pass
     ↓
Commit approved state
     ↓
Attempt email delivery
     ↓
Success → confirmation message
Failure → warning logged, approval remains valid
```

This prevents an SMTP outage from blocking the underlying approval transaction.

For production SMTP, configure the `EMAIL_*` variables on Render.

---

## 🖥️ Django admin

The backend serves no operator pages of its own: every staff and visitor
workflow lives in the React app and talks to the REST API. The only
server-rendered surface is Django's built-in admin at `/admin/`, for
superusers doing data maintenance.

---

## 🧭 Engineering decisions

### Django owns the database schema
Django migrations are the source of truth for the database schema.

### Supabase is PostgreSQL infrastructure
The application does not depend on Supabase Auth or Supabase Storage.

### Shared workflow services
Visit state transitions live in a shared service layer rather than being duplicated across controllers.

### Stateless SPA authentication
The React application uses JWT authentication through the Django API.

### API-only backend
Django serves JSON (plus the built-in admin). Staff, visitors and the public booking form all use the React app, so there is one UI to maintain and one permission model to test.

### Real data only
The repository no longer ships a demo-data seeding command or a fake production dataset.

---

## 🛠️ Project status

Implemented core flows include:

- Email/password registration and JWT login
- Organization onboarding
- Organization-scoped visitor management
- Pre-registration
- Walk-ins
- Approval/rejection workflow
- Signed QR generation
- QR email delivery
- Single-use QR enforcement
- Security check-in/check-out
- Blacklist enforcement
- Dashboard metrics
- Visitor search/pagination
- Reports and CSV export
- RBAC
- Audit logging
- Rate limiting
- Refresh-token rotation
- Production configuration
- Render/Vercel/Supabase deployment configuration
- GitHub Actions CI

Future extension areas include QR re-issue/self-service for expired passes, optional SMS delivery, richer audit exports and additional hardening/automation.

---

## 📌 Why this project matters

SecureGate demonstrates practical full-stack engineering beyond basic CRUD:

```text
Authentication
      +
Authorization
      +
Multi-tenancy
      +
Transactional workflows
      +
Cryptographic QR verification
      +
Auditability
      +
Reporting
      +
Cloud deployment
      +
CI/CD
```

The result is a visitor-access workflow that models real operational constraints and security requirements in one application.

---

## 👨‍💻 Author

**Md Ehteshamul Haque**

Computer Science & Engineering

**Focus:** Python Backend Development · Django · REST APIs · PostgreSQL

---

<p align="center">
  <img src="https://raw.githubusercontent.com/Mdehteshamulhaque1/Secure_Gate/main/docs/securegate-logo.svg" alt="SecureGate" width="58" />
</p>

<p align="center">
  <strong>Secure access. Clear workflows. Complete traceability.</strong>
</p>

<p align="center">
  <sub>Built with Django, React, PostgreSQL and a security-first architecture.</sub>
</p>
