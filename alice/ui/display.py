from core.state import AliceState


# ── Human-readable field labels ────────────────────────────────────────────────
# Used by format_display to render the info panel on the right.

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
    """
    Render the collected-information panel as an HTML string.
    Shows a progress bar, then one row per visible field.
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

    # ── Hide conditional fields that don't apply ───────────────────────────────
    def should_show(field: str) -> bool:
        if field == "family_doctor_name" and data.get("has_family_doctor") is False:
            return False
        if field == "psychiatrist_name"  and data.get("has_psychiatrist")  is False:
            return False
        return True

    visible = {f: l for f, l in labels.items() if should_show(f)}

    total  = len(visible)
    filled = sum(1 for f in visible if data.get(f) is not None)
    pct    = int((filled / total) * 100) if total else 0

    # ── Render each field row ──────────────────────────────────────────────────
    fields_html = ""
    for field, label in visible.items():
        value = data.get(field)

        if value is None:
            val_html = '<div style="font-size:13px;color:#cbd5e0;font-style:italic;">—</div>'

        elif isinstance(value, bool):
            color    = "#0F6E56" if value else "#718096"
            bg       = "#e6f4ef" if value else "#f1f5f9"
            text     = "Yes"     if value else "No"
            val_html = (
                f'<span style="font-size:12px;color:{color};background:{bg};'
                f'font-weight:600;padding:2px 10px;border-radius:999px;">{text}</span>'
            )

        else:
            val_html = f'<div style="font-size:14px;color:#1e293b;font-weight:500;">{value}</div>'

        fields_html += f"""
        <div style="padding:11px 0;border-bottom:1px solid #e8f0fb;">
            <div style="font-size:10px;color:#94a3b8;letter-spacing:0.6px;
                        text-transform:uppercase;margin-bottom:5px;">{label}</div>
            {val_html}
        </div>
        """

    return f"""
    <div style="font-family:'Inter',sans-serif;padding:4px 8px;">
        <div style="display:flex;align-items:center;justify-content:space-between;
                    margin-bottom:12px;padding-bottom:12px;border-bottom:2px solid #dbeafe;">
            <div style="font-size:13px;font-weight:600;color:#1e40af;">{title}</div>
            <div style="font-size:11px;color:#94a3b8;">{filled}/{total}</div>
        </div>
        <div style="background:#e2e8f0;border-radius:999px;height:5px;margin-bottom:16px;">
            <div style="background:linear-gradient(90deg,#185FA5,#3b82f6);height:5px;
                        border-radius:999px;width:{pct}%;"></div>
        </div>
        {fields_html}
    </div>
    """
