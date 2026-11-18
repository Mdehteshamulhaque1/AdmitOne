export const NAV_LINKS = [
  { label: "Features", href: "#features" },
  { label: "Solutions", href: "#solutions" },
  { label: "Resources", href: "#resources" },
]

export const TRUST_BADGES = ["No credit card", "Role-based access controls", "Audit trail on every action"]

export const TRUST_LOGOS = [
  "Corporate offices",
  "Hospitals",
  "Coworking spaces",
  "Manufacturing sites",
  "Data centers",
  "Universities",
  "Event venues",
  "Retail locations",
] as const

export const FEATURES = [
  {
    title: "Organization-based data isolation",
    description:
      "Every visitor, visit, pass and audit row belongs to one workspace. Queries are scoped by tenant, never by a join that could leak.",
    accent: "#818cf8",
  },
  {
    title: "Three roles: ADMIN, RECEPTIONIST and SECURITY",
    description:
      "Admins manage the workspace and approvals, reception registers visitors, security runs the gate. Nothing more, nothing less.",
    accent: "#7c3aed",
  },
  {
    title: "Role-based permission checks",
    description:
      "Each API endpoint re-derives the caller's capabilities from their role. The interface only hides what the server already refuses.",
    accent: "#8b5cf6",
  },
  {
    title: "Login failure tracking and account lockout",
    description:
      "Five failed attempts lock an account for fifteen minutes, on every login path, for staff and visitor accounts alike.",
    accent: "#f59e0b",
  },
  {
    title: "Transaction-based visit approval and rejection",
    description:
      "Approve and reject run inside a database transaction with a row lock, so two decisions can never race.",
    accent: "#22c55e",
  },
  {
    title: "HMAC-SHA256 signed QR passes",
    description:
      "Each pass is signed over the visit, the workspace and an opaque token with a dedicated key. A forged or edited code fails verification.",
    accent: "#a78bfa",
  },
  {
    title: "Single-use QR verification",
    description:
      "A pass is consumed on its first successful scan. Replays, expired passes and passes from another workspace are rejected.",
    accent: "#38bdf8",
  },
  {
    title: "Database locking and conditional updates to prevent duplicate QR check-ins",
    description:
      "The redemption is a conditional UPDATE under a row lock, so two simultaneous scans of the same pass admit exactly one person.",
    accent: "#f472b6",
  },
  {
    title: "Blacklisted visitor restrictions",
    description:
      "Security can blacklist a visitor with a reason; approvals and check-ins are blocked until an admin lifts the entry.",
    accent: "#ef4444",
  },
  {
    title: "Audit logging",
    description:
      "Registrations, decisions, scans, gate events, settings changes and exports are recorded with actor, time and IP.",
    accent: "#a3e635",
  },
  {
    title: "QR email delivery",
    description:
      "On approval the pass is emailed to the visitor as an inline QR image, and kept in their visitor account.",
    accent: "#fb923c",
  },
] as const

export const BENEFITS = [
  {
    value: 24,
    suffix: "/7",
    label: "automated audit trail",
    description: "Every registration, approval, check-in and check-out is timestamped and searchable.",
  },
  {
    value: 0,
    suffix: "",
    label: "printed badges needed",
    description: "Visitors carry a signed QR pass on their own device and scan it at the gate.",
  },
  {
    value: 1,
    suffix: "",
    label: "scan to check in",
    description: "A single gate scan verifies the pass, records the entry and opens the visit.",
  },
  {
    value: 30,
    suffix: " days",
    label: "of auto-archived records",
    description: "Completed visits are archived after 30 days and stay retrievable for your records.",
  },
] as const

export const WORKFLOW = [
  { title: "Visitor registration", description: "The visitor creates an account and books, or reception registers them at the desk.", icon: "user" },
  { title: "Admin approval or rejection", description: "Staff review who is coming, why and when, then approve or reject with a reason.", icon: "check" },
  { title: "Signed QR pass generation", description: "Approval issues an HMAC-SHA256 signed, single-use, time-boxed QR pass and emails it.", icon: "qr" },
  { title: "QR verification at security gate", description: "Security scans the pass; signature, expiry, single-use and workspace are checked.", icon: "scan" },
  { title: "Visitor check-in", description: "A valid scan consumes the pass and records the entry in one transaction.", icon: "login" },
  { title: "Visitor check-out", description: "Security checks the visitor out; time on site is recorded.", icon: "logout" },
  { title: "Audit history and reporting", description: "Every step lands in the audit trail; dashboards and CSV exports report on it.", icon: "audit" },
] as const

export const FAQS = [
  {
    question: "How does the QR check-in work?",
    answer:
      "When a host approves a visit, AdmitOne issues a cryptographically signed QR pass for that specific visit. The visitor shows it at the gate, security scans it, and the entry is verified, timestamped and logged instantly. No printing, no manual register.",
  },
  {
    question: "Is my visitor data secure?",
    answer:
      "Access is role-based — administrator, reception and security roles each get scoped permissions. Every action is written to a timestamped audit log, and data is protected in transit over HTTPS. Access rights and buildings are scoped to your organization.",
  },
  {
    question: "How do I get started?",
    answer:
      "There's nothing to install. You create a workspace, add your buildings and team members, and start registering visitors. Hosts approve requests, security checks people in, and reports are one click away.",
  },
  {
    question: "Can visitors be added at the gate?",
    answer:
      "Yes. Reception can register a walk-in visitor on the spot. For pre-arranged visits, the signed QR pass is emailed to the visitor when their email address is on file, or shown directly to security at the gate.",
  },
  {
    question: "What about my existing tools?",
    answer:
      "AdmitOne provides a JWT-secured REST API used by the app itself, plus CSV exports of your full visit log for spreadsheets or BI tools. Exported data is always your actual visit records.",
  },
] as const
