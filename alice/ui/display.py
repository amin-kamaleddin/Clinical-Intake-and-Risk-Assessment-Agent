import html

from core.state import AliceState


FIELD_LABELS: dict[str, dict[str, str]] = {
    "general_information": {
        "name":               "Full Name",
        "gender":             "Gender",
        "date_of_birth":      "Date of Birth",
        "address":            "Address",
        "postal_code":        "Postal Code",
        "email":              "Email",
        "phone":              "Phone",
        "has_family_doctor":  "Has Family Doctor",
        "family_doctor_name": "Family Doctor Name",
        "has_psychiatrist":   "Has Psychiatrist",
        "psychiatrist_name":  "Psychiatrist Name",
    },
    "current_concerns": {
        "primary_problems": "Primary Problems",
        "goals":            "Goals",
    },
}


def format_display(alice_state: AliceState | None) -> str:
    """Render the collected-information panel as an HTML string."""
    if not alice_state or not alice_state.get("current_section"):
        return """
        <div class="empty-info">
            Select a section above to begin
        </div>
        """

    section = alice_state["current_section"]
    data    = alice_state[section]
    labels  = FIELD_LABELS.get(section, {})
    title   = section.replace("_", " ").title()

    def should_show(field: str) -> bool:
        if field == "family_doctor_name" and data.get("has_family_doctor") is False:
            return False
        if field == "psychiatrist_name"  and data.get("has_psychiatrist")  is False:
            return False
        return True

    visible_fields = {f: l for f, l in labels.items() if should_show(f)}

    total      = len(visible_fields)
    filled     = sum(1 for f in visible_fields if data.get(f) is not None)
    percentage = int((filled / total) * 100) if total else 0

    fields_html = ""
    for field, label in visible_fields.items():
        value      = data.get(field)
        safe_label = html.escape(str(label))

        if value is None:
            value_html = '<div class="field-empty">—</div>'

        elif isinstance(value, bool):
            badge_class = "yes-badge" if value else "no-badge"
            badge_text  = "Yes"       if value else "No"
            value_html  = f'<span class="boolean-badge {badge_class}">{badge_text}</span>'

        else:
            safe_value = html.escape(str(value))
            value_html = f'<div class="field-value">{safe_value}</div>'

        fields_html += f"""
        <div class="info-field">
            <div class="field-label">{safe_label}</div>
            {value_html}
        </div>
        """

    safe_title = html.escape(title)

    return f"""
    <div class="information-panel">
        <div class="information-header">
            <div class="information-title">{safe_title}</div>
            <div class="information-count">{filled}/{total}</div>
        </div>

        <div class="progress-track">
            <div class="progress-value" style="width:{percentage}%;"></div>
        </div>

        {fields_html}
    </div>
    """
