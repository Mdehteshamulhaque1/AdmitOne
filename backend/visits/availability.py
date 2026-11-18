"""
Host availability + appointment slots for the Smart Pre-Booking flow.

Kept in the service layer (mirroring ``visits/services.py``) so the DRF
availability endpoint and the final booking submission run the exact same
rules — the database stays the authoritative source for conflicts.

Deliberately NOT a calendar-system: no external services, just Django ORM
queries against the existing ``Visit`` table.
"""

from datetime import time as time_class

from accounts.models import User
from organizations.models import Employee
from visits.models import Visit, VisitStatus

# Default appointment length. Can be overridden per organization through
# ``Organization.visitor_policies["appointment_duration_minutes"]``.
DEFAULT_SLOT_DURATION_MINUTES = 30
SLOT_DURATION_POLICY_KEY = "appointment_duration_minutes"

# Statuses that RESERVE a host's calendar window. Completed/declined flows
# (REJECTED, CHECKED_OUT, ARCHIVED) never block future slots.
BLOCKING_STATUSES = (
    VisitStatus.PENDING,
    VisitStatus.APPROVED,
    VisitStatus.CHECKED_IN,
)

# Hard sanity ceiling on slots returned for a single day.
MAX_SLOTS_PER_DAY = 96


def _to_time(value):
    """Normalize ``%H:%M`` strings / time objects to a ``datetime.time``."""
    if isinstance(value, time_class):
        return value
    if isinstance(value, str):
        try:
            hour, minute = value.strip().split(":")
            return time_class(int(hour), int(minute))
        except (ValueError, TypeError):
            return None
    return None


def _minutes_to_time(minutes):
    return time_class((minutes // 60) % 24, minutes % 60)


def organization_slot_duration(org):
    """Configurable appointment length (minutes) for an organization."""
    minutes = (org.visitor_policies or {}).get(SLOT_DURATION_POLICY_KEY)
    if isinstance(minutes, (int, float)) and 10 <= minutes <= 240:
        return int(minutes)
    return DEFAULT_SLOT_DURATION_MINUTES


def weekly_windows(org, day):
    """Working windows for ``day`` as a list of (start, end) ``time`` pairs.

    Empty list means the organization is closed that day.

    An unconfigured ``Organization.weekly_working_hours`` falls back to the
    plain daily ``working_hours_start``/``working_hours_end`` for EVERY
    weekday (preserves the existing pre-booking behavior). Once a weekly
    config exists it is authoritative: a weekday that is missing or mapped to
    ``None``/``[]`` is closed; multiple ranges per day encode lunch/other
    breaks.
    """
    schedule = org.weekly_working_hours or {}
    start = _to_time(org.working_hours_start) or time_class(9, 0)
    end = _to_time(org.working_hours_end) or time_class(18, 0)
    if not schedule:
        return [] if end <= start else [(start, end)]
    windows = []
    for item in schedule.get(str(day.weekday())) or []:
        ws = _to_time(item.get("start"))
        we = _to_time(item.get("end"))
        if ws is not None and we is not None and we > ws:
            windows.append((ws, we))
    return windows


def iter_appointment_slots(start, end, duration):
    """Grid-aligned slots inside ``[start, end)`` sized ``duration`` minutes."""
    start_min = start.hour * 60 + start.minute
    end_min = end.hour * 60 + end.minute
    duration = int(duration)
    if duration <= 0 or start_min >= end_min:
        return []
    slots = []
    for cur in range(start_min, end_min, duration):
        if cur + duration > end_min:
            break
        slots.append((_minutes_to_time(cur), _minutes_to_time(cur + duration)))
    return slots


def intervals_overlap(a_start, a_end, b_start, b_end):
    """Standard interval-overlap test: a_start < b_end AND b_start < a_end."""
    return a_start < b_end and b_start < a_end


def host_blocks_for(org, host, day, exclude_visit_pk=None):
    """Active time windows already reserved by a host on ``day``.

    Only the org's own visits for this host/date are fetched (no full-table
    scans, no N+1). Returns (arrival, exit) pairs from the DB.
    """
    qs = Visit.objects.filter(
        organization=org,
        host=host,
        visit_date=day,
        status__in=BLOCKING_STATUSES,
    ).values_list("expected_arrival", "expected_exit")
    if exclude_visit_pk is not None:
        qs = qs.exclude(pk=exclude_visit_pk)
    return list(qs)


def resolve_booking_host(org, host_id, department_id=None):
    """The bookable host for ``host_id`` or ``None``.

    Mirrors the employee rules used at booking time so availability can never
    be fetched for an out-of-org, inactive, or wrong-department host.
    """
    host = User.objects.filter(
        pk=host_id, organization_id=org.pk, is_active=True
    ).first()
    if host is None:
        return None
    employee = getattr(host, "employee_profile", None)
    if department_id is not None:
        if (
            employee is None
            or employee.organization_id != org.pk
            or employee.status != Employee.Status.ACTIVE
            or employee.department_id != department_id
        ):
            return None
    elif employee is not None and employee.status == Employee.Status.INACTIVE:
        return None
    return host


def get_host_availability(org, host, day, department=None):
    """Available appointment slots for ``host`` on ``day``.

    Only slots that (a) fall inside the day's working windows and (b) do not
    overlap an existing active visit for that host are returned.
    """
    duration = organization_slot_duration(org)
    blocks = host_blocks_for(org, host, day) if host is not None else []
    slots = []
    for win_start, win_end in weekly_windows(org, day):
        for start, end in iter_appointment_slots(win_start, win_end, duration):
            if any(intervals_overlap(start, end, bs, be) for bs, be in blocks):
                continue
            slots.append({"start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")})
            if len(slots) >= MAX_SLOTS_PER_DAY:
                return slots
    return slots


def validate_booking_slot(org, host, day, arrival, exit_time, exclude_visit_pk=None):
    """``(ok, reason)`` — may ``[arrival, exit_time)`` be booked right now.

    ``host`` may be ``None``: working-hours rules still apply, conflict checks
    do not. This is called BOTH before write work and again inside the locked
    transaction at submission time, closing the check-then-act race.
    """
    windows = weekly_windows(org, day)
    if not windows:
        return False, "This day is not a working day."
    if not any(ws <= arrival and exit_time <= we for ws, we in windows):
        return False, "The selected time is outside working hours."
    if host is None:
        return True, ""
    blocks = host_blocks_for(org, host, day, exclude_visit_pk)
    for block_start, block_end in blocks:
        if intervals_overlap(arrival, exit_time, block_start, block_end):
            return (
                False,
                "This time slot is no longer available. Please select another time.",
            )
    return True, ""