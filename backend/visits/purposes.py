"""Domain constants for the public pre-booking flow.

Static choices (visit type + per-type purpose lists) live in Python/Django —
never in React. The backend validates the submitted purpose against these,
so the API is the source of truth regardless of what a client sends.
"""

from visits.models import VisitType

# Reliable English labels that match the model choice values.
VISIT_TYPE_LABELS = {
    VisitType.BUSINESS_MEETING: "Business Meeting",
    VisitType.INTERVIEW: "Interview",
    VisitType.CAMPUS_PLACEMENT: "Campus / Placement",
    VisitType.CLIENT_MEETING: "Client Meeting",
    VisitType.VENDOR_DELIVERY: "Vendor / Delivery",
    VisitType.TRAINING_WORKSHOP: "Training / Workshop",
    VisitType.GUEST: "Guest",
    VisitType.OTHER: "Other",
}

# Purpose options shown per visit type. Every list ends with "Other", which
# unlocks free-text input (validated to prevent abuse).
PURPOSES_BY_VISIT_TYPE = {
    VisitType.BUSINESS_MEETING: [
        "Client Meeting",
        "Project Discussion",
        "Partnership",
        "Review Meeting",
    ],
    VisitType.INTERVIEW: [
        "Technical Interview",
        "HR Interview",
        "Final Interview",
        "Assessment",
    ],
    VisitType.CAMPUS_PLACEMENT: [
        "Placement Drive",
        "Interview",
        "Assessment",
        "Orientation",
    ],
    VisitType.CLIENT_MEETING: [
        "Client Meeting",
        "Project Discussion",
        "Status Review",
        "Onboarding",
    ],
    VisitType.VENDOR_DELIVERY: [
        "Delivery",
        "Maintenance",
        "Installation",
        "Service",
    ],
    VisitType.TRAINING_WORKSHOP: [
        "Training",
        "Workshop",
        "Seminar",
        "Onboarding",
    ],
    VisitType.GUEST: ["Personal Visit", "Family Visit", "Official Guest"],
    VisitType.OTHER: ["Other"],
}

OTHER_LABEL = "Other"

# Free-text purpose (when "Other" is picked) must be within this length.
PURPOSE_OTHER_MAX = 120


def purposes_for(visit_type):
    """Purpose labels allowed for a visit type (already ends with Other)."""
    labels = list(PURPOSES_BY_VISIT_TYPE.get(visit_type, []))
    if OTHER_LABEL not in labels:
        labels.append(OTHER_LABEL)
    return labels