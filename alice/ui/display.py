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


def format_display(alice_state):
    """
    Render the collected-information panel as an HTML string.
    All styles are INLINE so they render correctly inside Gradio 6's
    sandboxed gr.HTML component (external CSS classes do not reach here).
    """
    if not alice_state or not alice_state.get("current_section"):
        return """
        <div style="font-family:'Inter',sans-serif;padding:20px;
                    text-align:center;color:#94a3b8;font-size:13px;font-style:italic;">
            Select a section above to begin
        </div>
        """

    section = alice_state["current_section"]
    data    = alice_state[section]
    labels  = FIELD_LABELS.get(section, {})
    title   = section.replace("_", " ").title()

    def should_show(field):
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
            value_html = '<div style="font-size:13px;color:#cbd5e0;font-style:italic;">&mdash;</div>'

        elif isinstance(value, bool):
            color = "#0F6E56" if value else "#718096"
            bg    = "#e6f4ef" if value else "#f1f5f9"
            text  = "Yes"     if value else "No"
            value_html = (
                f'<span style="display:inline-block;font-size:12px;color:{color};'
                f'background:{bg};font-weight:600;padding:2px 10px;border-radius:999px;">{text}</span>'
            )

        else:
            safe_value = html.escape(str(value))
            value_html = (
                f'<div style="font-size:14px;color:#1e293b;font-weight:500;'
                f'overflow-wrap:anywhere;">{safe_value}</div>'
            )

        fields_html += (
            '<div style="padding:11px 0;border-bottom:1px solid #e8f0fb;">'
            f'<div style="font-size:10px;color:#94a3b8;letter-spacing:0.6px;'
            f'text-transform:uppercase;margin-bottom:5px;">{safe_label}</div>'
            f'{value_html}</div>'
        )

    safe_title = html.escape(title)

    return (
        '<div style="font-family:\'Inter\',sans-serif;padding:4px 8px;">'
            '<div style="display:flex;align-items:center;justify-content:space-between;'
            'margin-bottom:12px;padding-bottom:12px;border-bottom:2px solid #dbeafe;">'
                f'<div style="font-size:13px;font-weight:600;color:#1e40af;">{safe_title}</div>'
                f'<div style="font-size:11px;color:#94a3b8;">{filled}/{total}</div>'
            '</div>'
            '<div style="background:#e2e8f0;border-radius:999px;height:5px;'
            'margin-bottom:16px;overflow:hidden;">'
                f'<div style="background:linear-gradient(90deg,#185FA5,#3b82f6);'
                f'height:5px;border-radius:999px;width:{percentage}%;"></div>'
            '</div>'
            f'{fields_html}'
        '</div>'
    )
