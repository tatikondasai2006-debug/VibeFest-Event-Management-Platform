"""Event-specific custom field schema validation (server-side, admin-configured)."""

import re

ALLOWED_TYPES = ("text", "select", "checkbox")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,49}$")


def validate_custom_fields(raw) -> list[dict]:
    """Validate and normalise an event custom_fields definition list."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("Custom fields must be a list.")

    cleaned: list[dict] = []
    seen_keys: set[str] = set()
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"Custom field #{idx + 1} is not a valid object.")
        key = str(item.get("key", "")).strip()
        label = str(item.get("label", "")).strip()
        ftype = str(item.get("type", "text")).strip()
        required = bool(item.get("required", False))
        max_length = int(item.get("max_length", 200) or 200)
        options_raw = item.get("options") or []

        if not KEY_RE.match(key):
            raise ValueError(
                f"Custom field key '{key}' must be lowercase letters, digits, underscores "
                "(max 50 chars, starting with a letter)."
            )
        if key in seen_keys:
            raise ValueError(f"Duplicate custom field key '{key}'.")
        seen_keys.add(key)
        if not label or len(label) > 200:
            raise ValueError(f"Custom field '{key}' needs a label (max 200 characters).")
        if ftype not in ALLOWED_TYPES:
            raise ValueError(
                f"Custom field '{key}' has unsupported type '{ftype}'. "
                f"Allowed: {', '.join(ALLOWED_TYPES)}."
            )
        if not (1 <= max_length <= 500):
            raise ValueError(f"Custom field '{key}' max_length must be between 1 and 500.")

        options: list[str] = []
        if ftype == "select":
            if not isinstance(options_raw, list) or not options_raw:
                raise ValueError(f"Select field '{key}' requires at least one option.")
            for opt in options_raw:
                opt_s = str(opt).strip()
                if not opt_s or len(opt_s) > 200:
                    raise ValueError(f"Select field '{key}' has an invalid option.")
                options.append(opt_s)

        cleaned.append(
            {
                "key": key,
                "label": label,
                "type": ftype,
                "required": required,
                "max_length": max_length,
                "options": options,
            }
        )
    if len(cleaned) > 20:
        raise ValueError("An event can have at most 20 custom fields.")
    return cleaned
