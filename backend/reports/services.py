"""Shared dashboard analytics and timezone helpers.

Single source of truth for KPIs, chart data, report queries and CSV
export. The server-rendered dashboard, the REST API and the CSV export
endpoint all consume these helpers so business numbers can never drift.
"""

import csv
from datetime import timedelta

from django.db.models import Count
from django.http import HttpResponse
from django.utils import timezone

from accounts.utils import org_localdate
from visits.models import Visit, VisitStatus, Visitor

STATUS_COLORS = {
    "PENDING": "#f59e0b",
    "APPROVED": "#3b82f6",
    "REJECTED": "#ef4444",
    "CHECKED_IN": "#22c55e",
    "CHECKED_OUT": "#64748b",
    "CANCELLED": "#a855f7",
    "ARCHIVED": "#94a3b8",
}


# ----------------------------------------------------------- dashboard data


def build_dashboard_data(user):
    """Return ``(kpis, charts)`` dicts for the dashboard.

    ``kpis`` keys: today, week, month, inside, pending, approved,
    avg_duration_minutes, repeat, first_time, total, checked_out, rejected.

    ``charts`` keys: status_counts/labels/colors, peak_labels/values,
    dept_labels/values, repeat_vals.
    """
    org = getattr(user, "organization", None)
    visits = Visit.objects.filter(organization=org) if org else Visit.objects.none()
    now = timezone.now()
    today = org_localdate(user)

    status_counts = {s: visits.filter(status=s).count() for s in VisitStatus.values}

    # One pass over the completed visits, not exists() + count() + a second
    # pass. The two previous queries were only there to decide whether the
    # loop below had anything to do.
    #
    # The sum stays in Python on purpose. ``duration_minutes`` is a property
    # derived from the check-in/check-out timestamps, not a column, so a plain
    # Avg() is not possible without ExpressionWrapper over the datetimes --
    # and that would change the number:
    #     sum(floor(d_i)) // n   !=   floor(mean(d_i))
    # Two 90s and 30s visits give 0 minutes one way and 1 the other. The KPI
    # is a displayed number people have already seen, so the arithmetic is
    # preserved exactly.
    duration_total = duration_count = 0
    for completed in visits.filter(checked_in_at__isnull=False, checked_out_at__isnull=False):
        duration_total += completed.duration_minutes
        duration_count += 1
    avg_duration_minutes = duration_total // duration_count if duration_count else 0

    peak_buckets = {f"{h:02d}:00": 0 for h in range(8, 20)}
    for v in visits.filter(registered_at__gte=now - timedelta(days=30)).exclude(
        expected_arrival__isnull=True
    ):
        bucket = f"{v.expected_arrival.hour:02d}:00"
        if bucket in peak_buckets:
            peak_buckets[bucket] += 1

    dept_rows = (
        visits.exclude(host__employee_profile__isnull=True)
        .exclude(host__employee_profile__department__isnull=True)
        .values("host__employee_profile__department__name")
        .annotate(total=Count("id"))
        .order_by("-total")[:8]
    )
    dept_labels = [r["host__employee_profile__department__name"] or "—" for r in dept_rows]
    dept_values = [r["total"] for r in dept_rows]

    if org:
        # Tenant key, not a join: repeat/first-time counts must only see the
        # organization's own visitor records.
        repeat = (
            Visitor.objects.filter(organization=org)
            .annotate(n=Count("visits"))
            .filter(n__gt=1)
            .count()
        )
        first_time = (
            Visitor.objects.filter(organization=org)
            .annotate(n=Count("visits"))
            .filter(n=1)
            .count()
        )
    else:
        repeat = first_time = 0

    kpis = {
        "today": visits.filter(visit_date=today).count(),
        "week": visits.filter(registered_at__gte=now - timedelta(days=7)).count(),
        "month": visits.filter(registered_at__gte=now - timedelta(days=30)).count(),
        "inside": status_counts[VisitStatus.CHECKED_IN],
        "pending": status_counts[VisitStatus.PENDING],
        "approved": status_counts[VisitStatus.APPROVED],
        "avg_duration_minutes": avg_duration_minutes,
        "repeat": repeat,
        "first_time": first_time,
        "total": visits.count(),
        "checked_out": status_counts[VisitStatus.CHECKED_OUT],
        "rejected": status_counts[VisitStatus.REJECTED],
        "trend": _registration_trend(visits, today),
    }

    charts = {
        "status_counts": list(status_counts.values()),
        "status_labels": [VisitStatus(label).label for label in VisitStatus.values],
        "status_colors": [STATUS_COLORS[s] for s in VisitStatus.values],
        "peak_labels": list(peak_buckets.keys()),
        "peak_values": list(peak_buckets.values()),
        "dept_labels": dept_labels,
        "dept_values": dept_values,
        "repeat_vals": [first_time, repeat],
    }
    return kpis, charts


def _registration_trend(visits, today):
    """Percentage change in registrations between yesterday and today.

    Both dates are organisation-local ``date`` objects so the result
    matches the displayed "Visitors today" KPI regardless of the
    server's UTC clock.
    """
    yesterday = today - timedelta(days=1)
    today_count = visits.filter(visit_date=today).count()
    yesterday_count = visits.filter(visit_date=yesterday).count()
    if not yesterday_count:
        return 0
    return round((today_count - yesterday_count) / yesterday_count * 100)


# ----------------------------------------------------------- shared report


def report_queryset(user, period="daily", dept=""):
    """Org-scoped, date-filtered visits for daily/weekly/monthly reports.

    ``dept`` is an optional department id string. Invalid values are
    silently ignored (same as the server-rendered console).
    """
    org = getattr(user, "organization", None)
    qs = (
        Visit.objects.filter(organization=org)
        .select_related("visitor", "host", "building", "host__employee_profile__department")
        if org
        else Visit.objects.none()
    )
    now = timezone.now()
    if period == "weekly":
        qs = qs.filter(registered_at__gte=now - timedelta(days=7))
    elif period == "monthly":
        qs = qs.filter(registered_at__gte=now - timedelta(days=30))
    elif period == "all":
        pass  # full history
    else:
        qs = qs.filter(visit_date=org_localdate(user))
    if dept:
        try:
            qs = qs.filter(host__employee_profile__department_id=int(dept))
        except (TypeError, ValueError):
            pass
    return qs


# --------------------------------------------------------------- CSV export


def _csv_safe(value):
    """Neutralize spreadsheet-formula injection (CWE-1236)."""
    if value is None:
        return ""
    text = str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def visit_csv_export(visits, period):
    """Return a CSV ``HttpResponse`` for *visits*.

    Used by both the server-rendered console report and the JWT-
    protected ``/api/reports/export/`` endpoint so there is a single
    business-logic path for CSV generation.
    """
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="admitone-{period}-{timezone.localdate()}.csv"'
    )
    response.write("\ufeff")  # UTF-8 BOM so Excel renders CJK correctly
    writer = csv.writer(response)
    writer.writerow(
        [
            "Visitor",
            "Phone",
            "Company",
            "Purpose",
            "Host",
            "Department",
            "Building",
            "Visit Date",
            "Status",
            "Registered",
            "Checked In",
            "Checked Out",
            "Duration (min)",
        ]
    )
    for v in visits:
        writer.writerow(
            [
                _csv_safe(v.visitor.full_name),
                _csv_safe(v.visitor.phone),
                _csv_safe(v.visitor.company),
                _csv_safe(v.purpose),
                _csv_safe(v.host.full_name) if v.host else "",
                _csv_safe(v.host.employee_profile.department.name)
                if v.host and hasattr(v.host, "employee_profile") and v.host.employee_profile and v.host.employee_profile.department
                else "",
                _csv_safe(v.building.name) if v.building else "",
                v.visit_date,
                v.status,
                v.registered_at.strftime("%Y-%m-%d %H:%M"),
                v.checked_in_at.strftime("%Y-%m-%d %H:%M") if v.checked_in_at else "",
                v.checked_out_at.strftime("%Y-%m-%d %H:%M") if v.checked_out_at else "",
                v.duration_minutes,
            ]
        )
    return response


def audit_csv_export(logs, period="all"):
    """Return a CSV ``HttpResponse`` for audit-log rows.

    Uses the same ``_csv_safe`` guard as ``visit_csv_export`` so exported
    cells can never be mistaken for spreadsheet formulas.
    """
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="admitone-audit-{period}-{timezone.localdate()}.csv"'
    )
    response.write("\ufeff")  # UTF-8 BOM so Excel renders CJK correctly
    writer = csv.writer(response)
    writer.writerow(
        [
            "Timestamp",
            "Actor",
            "Role",
            "Action",
            "Entity",
            "Entity ID",
            "Details",
            "IP Address",
        ]
    )
    for log in logs:
        writer.writerow(
            [
                log.created_at.strftime("%Y-%m-%d %H:%M"),
                _csv_safe(log.user.full_name) if log.user else "System",
                _csv_safe(log.user.role) if log.user else "",
                _csv_safe(log.action),
                _csv_safe(log.entity_type),
                _csv_safe(log.entity_id),
                _csv_safe(log.details),
                _csv_safe(log.ip_address),
            ]
        )
    return response


# ----------------------------------------------------------- SPA analytics


def dashboard_analytics(user, days=14):
    """Chart-ready aggregates for the SPA dashboard and reports pages.

    Everything is computed by the database (``GROUP BY``), so the SPA no longer
    has to download the whole visit table and bucket it client-side.  All
    series are scoped to the caller's workspace; a tenantless caller gets
    empty series rather than a cross-tenant leak.

    Returns a dict with:

    * ``daily_series`` - one ``{date, visits, checked_in}`` row per day for the
      last ``days`` days (inclusive of today, organisation-local), zero-filled.
    * ``status_counts`` - ``{STATUS: count}`` for every ``VisitStatus``.
    * ``top_visitors`` - the eight most frequent visitors ``{name, visits}``.
    * ``peak_hours`` - visits per expected-arrival hour (08:00-19:00) over the
      last 30 days, ``{hour, visits}``.
    * ``by_department`` - visits per host department ``{name, visits}`` (top 8).
    * ``today_schedule`` - counts for the organisation-local day:
      ``{expected, arrived, inside, left}``.
    """
    from django.db.models import Q

    org = getattr(user, "organization", None)
    if org is None:
        empty_status = {s: 0 for s in VisitStatus.values}
        return {
            "daily_series": [],
            "status_counts": empty_status,
            "top_visitors": [],
            "peak_hours": [],
            "by_department": [],
            "today_schedule": {"expected": 0, "arrived": 0, "inside": 0, "left": 0},
        }

    visits = Visit.objects.filter(organization=org)
    today = org_localdate(user)
    now = timezone.now()

    # --- daily series (by visit_date, organisation-local) -------------------
    start = today - timedelta(days=days - 1)
    rows = (
        visits.filter(visit_date__gte=start, visit_date__lte=today)
        .values("visit_date")
        .annotate(
            visits=Count("id"),
            checked_in=Count("id", filter=Q(checked_in_at__isnull=False)),
        )
    )
    by_day = {r["visit_date"]: r for r in rows}
    daily_series = []
    for i in range(days):
        day = start + timedelta(days=i)
        row = by_day.get(day)
        daily_series.append(
            {
                "date": day.isoformat(),
                "visits": row["visits"] if row else 0,
                "checked_in": row["checked_in"] if row else 0,
            }
        )

    # --- status counts -------------------------------------------------------
    status_rows = visits.values("status").annotate(total=Count("id"))
    status_counts = {s: 0 for s in VisitStatus.values}
    for r in status_rows:
        if r["status"] in status_counts:
            status_counts[r["status"]] = r["total"]

    # --- top visitors --------------------------------------------------------
    top_rows = (
        visits.values("visitor_id", "visitor__full_name")
        .annotate(total=Count("id"))
        .order_by("-total", "visitor__full_name")[:8]
    )
    top_visitors = [
        {"id": r["visitor_id"], "name": r["visitor__full_name"], "visits": r["total"]}
        for r in top_rows
    ]

    # --- peak hours (last 30 days, by expected arrival hour) -----------------
    peak = {h: 0 for h in range(8, 20)}
    for r in (
        visits.filter(registered_at__gte=now - timedelta(days=30))
        .values("expected_arrival")
    ):
        t = r["expected_arrival"]
        if t is not None and t.hour in peak:
            peak[t.hour] += 1
    peak_hours = [{"hour": f"{h:02d}:00", "visits": n} for h, n in peak.items()]

    # --- by department -------------------------------------------------------
    dept_rows = (
        visits.exclude(host__employee_profile__department__isnull=True)
        .values("host__employee_profile__department__name")
        .annotate(total=Count("id"))
        .order_by("-total")[:8]
    )
    by_department = [
        {"name": r["host__employee_profile__department__name"], "visits": r["total"]}
        for r in dept_rows
    ]

    # --- today ---------------------------------------------------------------
    todays = visits.filter(visit_date=today)
    today_schedule = {
        "expected": todays.filter(
            status__in=[VisitStatus.PENDING, VisitStatus.APPROVED]
        ).count(),
        "arrived": todays.filter(checked_in_at__isnull=False).count(),
        "inside": visits.filter(status=VisitStatus.CHECKED_IN).count(),
        "left": todays.filter(status=VisitStatus.CHECKED_OUT).count(),
    }

    return {
        "daily_series": daily_series,
        "status_counts": status_counts,
        "top_visitors": top_visitors,
        "peak_hours": peak_hours,
        "by_department": by_department,
        "today_schedule": today_schedule,
    }
