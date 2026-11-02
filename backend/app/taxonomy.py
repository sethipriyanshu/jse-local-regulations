"""Provisional discipline/category keys (PLAN.md §1.5), seeded by app.bootstrap."""

# Admins can edit labels later; bootstrap only inserts missing keys.
DISCIPLINES = [
    ("mechanical", "Mechanical"),
    ("electrical", "Electrical"),
    ("plumbing", "Plumbing"),
    ("fire_protection", "Fire Protection"),
    ("fuel_gas", "Fuel Gas"),
    ("energy", "Energy"),
    ("general", "General / Admin"),
]
CATEGORIES = [
    ("adopted_code", "Adopted code & edition"),
    ("local_amendment", "Local amendment"),
    ("permit_submittal", "Permit & submittal requirement"),
    ("plan_review", "Plan review requirement"),
    ("inspection", "Inspection requirement"),
    ("licensing", "Licensing & seal requirement"),
    ("utility", "Utility requirement"),
    ("environmental", "Environmental"),
    ("fees", "Fees"),
    ("pending_change", "Pending / proposed change"),
]
