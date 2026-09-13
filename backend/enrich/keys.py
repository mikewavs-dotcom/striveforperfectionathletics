_PLACEHOLDER_PREFIX = "replace-with-"


def is_configured(api_key: str) -> bool:
    stripped = api_key.strip()
    if stripped == "":
        return False
    return not stripped.lower().startswith(_PLACEHOLDER_PREFIX)
