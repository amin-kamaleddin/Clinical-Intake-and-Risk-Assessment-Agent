import re
from datetime import datetime, date


# ── Individual validators ──────────────────────────────────────────────────────
# Each returns (is_valid: bool, result: cleaned_value | error_message)

def validate_date_of_birth(value: str):
    try:
        dob = datetime.strptime(value.strip(), "%d/%m/%Y").date()
        if not (date(1900, 1, 1) <= dob < date.today()):
            return False, "Please enter a valid date of birth."
        return True, dob.strftime("%d/%m/%Y")
    except ValueError:
        return False, "Invalid format. Please use DD/MM/YYYY."


def validate_postal_code(value: str):
    value = value.strip().upper().replace(" ", "")
    if re.match(r'^[A-Z]\d[A-Z]\d[A-Z]\d$', value):
        return True, value
    return False, "Invalid postal code. Please use the format A#A#A#, for example K2C2K9."


def validate_email(value: str):
    value = value.strip()
    if "@" in value and "." in value.split("@")[-1]:
        return True, value
    return False, "Invalid email address."


def validate_address(value: str):
    province_map = {
        "ON": "Ontario",
        "BC": "British Columbia",
        "AB": "Alberta",
        "SK": "Saskatchewan",
        "MB": "Manitoba",
        "QC": "Quebec",
        "NB": "New Brunswick",
        "NS": "Nova Scotia",
        "PE": "Prince Edward Island",
        "NL": "Newfoundland and Labrador",
        "YT": "Yukon",
        "NT": "Northwest Territories",
        "NU": "Nunavut",
    }
    province_names = {v.lower(): v for v in province_map.values()}

    value = value.strip()
    if not value:
        return False, "Please provide a complete address."

    parts = [p.strip() for p in value.split(",")]
    if len(parts) < 2:
        return False, "Please include street, city, and province."

    formatted = []
    for i, part in enumerate(parts):
        if i == len(parts) - 1:
            key_upper = part.strip().upper()
            key_lower = part.strip().lower()
            if key_upper in province_map:
                formatted.append(province_map[key_upper])
            elif key_lower in province_names:
                formatted.append(province_names[key_lower])
            else:
                formatted.append(part.strip().title())
        else:
            formatted.append(part.strip().title())

    return True, ", ".join(formatted)


def validate_phone(value: str):
    digits = re.sub(r'\D', '', value)
    if 10 <= len(digits) <= 15:
        return True, digits
    return False, "Phone number must be 10 digits (or include country code)."


def validate_boolean(value: str):
    v = value.lower().strip()
    if v.startswith(("yes", "y", "true")):
        return True, True
    if v.startswith(("no", "n", "false")):
        return True, False
    return False, "Please answer yes or no."


def validate_doctor_name(value: str):
    if value.strip().lower() == "unknown":
        return True, "unknown"
    return True, value.strip().upper()


# ── Validator registry ─────────────────────────────────────────────────────────
# NOTE: the "address" key must match the state field name exactly.

FIELD_VALIDATORS = {
    "date_of_birth":      validate_date_of_birth,
    "postal_code":        validate_postal_code,
    "email":              validate_email,
    "address":            validate_address,
    "phone":              validate_phone,
    "has_family_doctor":  validate_boolean,
    "has_psychiatrist":   validate_boolean,
    "family_doctor_name": validate_doctor_name,
    "psychiatrist_name":  validate_doctor_name,
}
