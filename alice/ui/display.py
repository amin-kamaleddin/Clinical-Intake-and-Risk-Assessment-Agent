import html

from ui.schema import (
    SECTION_TITLES,
    FIELD_LABELS,
    COMPUTED_FIELDS,
    normalize_state_schema,
)


def should_show_field(field, data):
    """Hide conditional detail fields when their controlling answer is False."""
    conditional_fields = {
        "family_doctor_name": ("has_family_doctor", False),
        "psychiatrist_name": ("has_psychiatrist", False),
        "assessment_details": ("previously_assessed", False),
        "hospital_details": ("hospital_admission", False),
        "self_harm_details": ("self_harm_history", False),
        "current_medications": ("has_current_medications", False),
        "past_medication_details": ("has_past_medications", False),
        "medical_conditions": ("has_medical_conditions", False),
        "surgical_history": ("has_surgical_history", False),
        "medication_allergies": ("has_medication_allergies", False),
        "family_psychiatric_history_details": (
            "has_family_psychiatric_history",
            False,
        ),
        "legal_case_details": ("active_legal_cases", False),
    }

    dependency = conditional_fields.get(field)
    if dependency is None:
        return True

    parent_field, hidden_value = dependency
    return data.get(parent_field) is not hidden_value


def format_display(alice_state):
    if not alice_state:
        return """
        <div class="empty-info">
            Select a section above to begin
        </div>
        """

    alice_state = normalize_state_schema(alice_state)
    section = alice_state.get("current_section")

    if not section:
        return """
        <div class="empty-info">
            Select a section above to begin
        </div>
        """

    data = alice_state.get(section, {})
    labels = FIELD_LABELS.get(section, {})
    title = SECTION_TITLES.get(section, section.replace("_", " ").title())

    visible_fields = {
        field: label
        for field, label in labels.items()
        if should_show_field(field, data)
        and not (
            field in COMPUTED_FIELDS.get(section, set())
            and data.get(field) is None
        )
    }

    progress_fields = [
        field
        for field in visible_fields
        if field not in COMPUTED_FIELDS.get(section, set())
    ]

    total = len(progress_fields)
    filled = sum(1 for field in progress_fields if data.get(field) is not None)
    percentage = int((filled / total) * 100) if total else 0

    fields_html = ""
    for field, label in visible_fields.items():
        value = data.get(field)
        safe_label = html.escape(str(label))

        if value is None:
            value_html = '<div class="field-empty">&mdash;</div>'

        elif isinstance(value, bool):
            badge_class = "yes-badge" if value else "no-badge"
            badge_text = "Yes" if value else "No"
            value_html = (
                f'<span class="boolean-badge {badge_class}">{badge_text}</span>'
            )

        elif field in {"phq9_total", "gad7_total"}:
            safe_value = html.escape(str(value))
            value_html = f'<div class="score-value">{safe_value}</div>'

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
            <div>
                <div class="information-kicker">CURRENT SECTION</div>
                <div class="information-title">{safe_title}</div>
            </div>
            <div class="information-count">{filled}/{total}</div>
        </div>

        <div class="progress-track">
            <div class="progress-value" style="width:{percentage}%;"></div>
        </div>

        {fields_html}
    </div>
    """
