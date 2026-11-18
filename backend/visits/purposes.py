"""Visitor categories and purposes.

Two layers:

* **Static visit types** (``VisitType`` on the model) stay the reporting
  backbone: every purpose maps to one of them.
* **Per-workspace catalogue** -- ``Organization.visitor_policies["visitor_catalogue"]``
  holds the dropdown lists a visitor sees: the visitor categories (Student,
  Parent, Recruiter, ...) and, per category, the purposes with their visit
  type. Admins edit it in Settings; a workspace without one gets the
  training-centre defaults below, so the booking form always has sensible
  options. The backend validates a submitted (category, purpose) pair against
  this catalogue, so the API, not the client, is the source of truth.
"""

from copy import deepcopy

from visits.models import VisitType

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

OTHER_LABEL = "Other"
PURPOSE_OTHER_MAX = 120

#: Default catalogue, modelled on a training centre (students, parents,
#: recruiters, vendors). Each purpose carries the visit type used for
#: reporting and the kind of room it usually needs (a hint for staff when
#: they assign one).
TRAINING_CENTRE_CATALOGUE = {
    "categories": [
        {
            "key": "STUDENT",
            "label": "Student / trainee",
            "purposes": [
                {"label": "Course enquiry / demo class", "visit_type": VisitType.TRAINING_WORKSHOP, "room_type": "RECEPTION"},
                {"label": "Training session (daily attendance)", "visit_type": VisitType.TRAINING_WORKSHOP, "room_type": "CLASSROOM"},
                {"label": "Lab practice", "visit_type": VisitType.TRAINING_WORKSHOP, "room_type": "LAB"},
                {"label": "Mock interview", "visit_type": VisitType.INTERVIEW, "room_type": "INTERVIEW_CABIN"},
                {"label": "Company interview", "visit_type": VisitType.INTERVIEW, "room_type": "INTERVIEW_CABIN"},
                {"label": "Pool placement drive", "visit_type": VisitType.CAMPUS_PLACEMENT, "room_type": "PLACEMENT_HALL"},
                {"label": "Grooming / soft-skills class", "visit_type": VisitType.TRAINING_WORKSHOP, "room_type": "GROOMING_ROOM"},
                {"label": "Assessment / test", "visit_type": VisitType.INTERVIEW, "room_type": "LAB"},
                {"label": "Fee payment / admission", "visit_type": VisitType.OTHER, "room_type": "OFFICE"},
                {"label": "Certificate collection", "visit_type": VisitType.OTHER, "room_type": "OFFICE"},
                {"label": "Casual visit", "visit_type": VisitType.GUEST, "room_type": "RECEPTION"},
                {"label": OTHER_LABEL, "visit_type": VisitType.OTHER, "room_type": ""},
            ],
        },
        {
            "key": "PARENT",
            "label": "Parent / guardian",
            "purposes": [
                {"label": "Counselling session", "visit_type": VisitType.GUEST, "room_type": "RECEPTION"},
                {"label": "Fee payment / admission", "visit_type": VisitType.OTHER, "room_type": "OFFICE"},
                {"label": "Progress discussion", "visit_type": VisitType.BUSINESS_MEETING, "room_type": "MEETING_ROOM"},
                {"label": "Casual visit", "visit_type": VisitType.GUEST, "room_type": "RECEPTION"},
                {"label": OTHER_LABEL, "visit_type": VisitType.OTHER, "room_type": ""},
            ],
        },
        {
            "key": "RECRUITER",
            "label": "Recruiter / company",
            "purposes": [
                {"label": "Pool placement drive", "visit_type": VisitType.CAMPUS_PLACEMENT, "room_type": "PLACEMENT_HALL"},
                {"label": "Interview panel", "visit_type": VisitType.INTERVIEW, "room_type": "INTERVIEW_CABIN"},
                {"label": "Guest lecture / seminar", "visit_type": VisitType.TRAINING_WORKSHOP, "room_type": "SEMINAR_HALL"},
                {"label": "Partnership meeting", "visit_type": VisitType.CLIENT_MEETING, "room_type": "MEETING_ROOM"},
                {"label": OTHER_LABEL, "visit_type": VisitType.OTHER, "room_type": ""},
            ],
        },
        {
            "key": "VENDOR",
            "label": "Vendor / delivery",
            "purposes": [
                {"label": "Delivery", "visit_type": VisitType.VENDOR_DELIVERY, "room_type": "RECEPTION"},
                {"label": "Maintenance / repair", "visit_type": VisitType.VENDOR_DELIVERY, "room_type": ""},
                {"label": "Installation", "visit_type": VisitType.VENDOR_DELIVERY, "room_type": ""},
                {"label": OTHER_LABEL, "visit_type": VisitType.OTHER, "room_type": ""},
            ],
        },
        {
            "key": "OTHER",
            "label": "Other visitor",
            "purposes": [
                {"label": "Business meeting", "visit_type": VisitType.BUSINESS_MEETING, "room_type": "MEETING_ROOM"},
                {"label": "Casual visit", "visit_type": VisitType.GUEST, "room_type": "RECEPTION"},
                {"label": OTHER_LABEL, "visit_type": VisitType.OTHER, "room_type": ""},
            ],
        },
    ]
}

# Legacy per-visit-type purposes (public booking before categories existed).
PURPOSES_BY_VISIT_TYPE = {
    VisitType.BUSINESS_MEETING: ["Client Meeting", "Project Discussion", "Partnership", "Review Meeting"],
    VisitType.INTERVIEW: ["Technical Interview", "HR Interview", "Final Interview", "Assessment"],
    VisitType.CAMPUS_PLACEMENT: ["Placement Drive", "Interview", "Assessment", "Orientation"],
    VisitType.CLIENT_MEETING: ["Client Meeting", "Project Discussion", "Status Review", "Onboarding"],
    VisitType.VENDOR_DELIVERY: ["Delivery", "Maintenance", "Installation", "Service"],
    VisitType.TRAINING_WORKSHOP: ["Training", "Workshop", "Seminar", "Onboarding"],
    VisitType.GUEST: ["Personal Visit", "Family Visit", "Official Guest"],
    VisitType.OTHER: ["Other"],
}


def purposes_for(visit_type):
    """Purpose labels allowed for a visit type (always ends with Other)."""
    labels = list(PURPOSES_BY_VISIT_TYPE.get(visit_type, []))
    if OTHER_LABEL not in labels:
        labels.append(OTHER_LABEL)
    return labels


# ------------------------------------------------------------- catalogue


def validate_catalogue(value):
    """Shape-check a catalogue; returns the cleaned dict or raises ValueError."""
    if not isinstance(value, dict) or not isinstance(value.get("categories"), list):
        raise ValueError("visitor_catalogue must be an object with a 'categories' list.")
    cleaned, keys = [], set()
    for cat in value["categories"]:
        if not isinstance(cat, dict):
            raise ValueError("Each category must be an object.")
        key = str(cat.get("key", "")).strip().upper().replace(" ", "_")[:40]
        label = str(cat.get("label", "")).strip()[:80]
        if not key or not label:
            raise ValueError("Each category needs a key and a label.")
        if key in keys:
            raise ValueError(f"Duplicate category key {key!r}.")
        keys.add(key)
        purposes, seen = [], set()
        for p in cat.get("purposes", []) or []:
            if not isinstance(p, dict):
                raise ValueError(f"Category {label}: each purpose must be an object.")
            plabel = str(p.get("label", "")).strip()[:120]
            vtype = str(p.get("visit_type", VisitType.OTHER)).strip().upper()
            rtype = str(p.get("room_type", "") or "").strip().upper()
            if not plabel:
                raise ValueError(f"Category {label}: a purpose is missing its label.")
            if vtype not in VisitType.values:
                raise ValueError(f"Category {label}: {plabel!r} has an unknown visit type {vtype!r}.")
            if plabel.lower() in seen:
                raise ValueError(f"Category {label}: duplicate purpose {plabel!r}.")
            seen.add(plabel.lower())
            purposes.append({"label": plabel, "visit_type": vtype, "room_type": rtype})
        if not any(p["label"] == OTHER_LABEL for p in purposes):
            purposes.append({"label": OTHER_LABEL, "visit_type": VisitType.OTHER, "room_type": ""})
        cleaned.append({"key": key, "label": label, "purposes": purposes})
    if not cleaned:
        raise ValueError("At least one visitor category is required.")
    return {"categories": cleaned}


def catalogue_for(org):
    """The workspace's catalogue, or the training-centre defaults."""
    raw = (getattr(org, "visitor_policies", None) or {}).get("visitor_catalogue")
    if raw:
        try:
            return validate_catalogue(raw)
        except ValueError:
            pass
    return deepcopy(TRAINING_CENTRE_CATALOGUE)


def categories_for(org):
    return [{"key": c["key"], "label": c["label"]} for c in catalogue_for(org)["categories"]]


def purposes_for_category(org, category_key):
    """Purpose entries for a category key, or ``None`` if the key is unknown."""
    for cat in catalogue_for(org)["categories"]:
        if cat["key"] == str(category_key or "").strip().upper():
            return cat["purposes"]
    return None


def resolve_purpose(org, category_key, purpose_label):
    """Return the purpose entry for (category, label) or ``None``."""
    entries = purposes_for_category(org, category_key)
    if entries is None:
        return None
    wanted = str(purpose_label or "").strip().lower()
    for entry in entries:
        if entry["label"].lower() == wanted:
            return entry
    return None
