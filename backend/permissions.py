import json
import os
import logging

from .gcs_utils import get_allowed_buckets

logger = logging.getLogger("uvicorn")

_permissions: dict | None = None
_permissions_mtime: float = 0
_PERMISSIONS_PATH = os.path.join(os.path.dirname(__file__), "permissions.json")


def load_permissions() -> dict:
    global _permissions, _permissions_mtime
    with open(_PERMISSIONS_PATH, "r") as f:
        _permissions = json.load(f)
    _permissions_mtime = os.path.getmtime(_PERMISSIONS_PATH)
    logger.info(f"Loaded permissions for {len(_permissions)} users")
    return _permissions


def _get_permissions() -> dict:
    global _permissions_mtime
    try:
        current_mtime = os.path.getmtime(_PERMISSIONS_PATH)
    except OSError:
        current_mtime = 0
    if _permissions is None or current_mtime != _permissions_mtime:
        load_permissions()
    return _permissions


def get_user_rules(email: str) -> list[str] | None:
    perms = _get_permissions()
    rules = perms.get(email)
    if isinstance(rules, list):
        return rules
    return None


def get_user_buckets(email: str) -> list[dict]:
    """Returns list of {"name": bucket, "prefixes": [...]} for the user."""
    rules = get_user_rules(email)
    if rules is None:
        return []

    allowed_buckets = get_allowed_buckets()

    if "*" in rules:
        return [{"name": b, "prefixes": []} for b in allowed_buckets]

    bucket_prefixes: dict[str, list[str]] = {}
    for rule in rules:
        if "/" in rule:
            rule_bucket, rule_prefix = rule.split("/", 1)
        else:
            rule_bucket = rule
            rule_prefix = ""

        if rule_bucket not in allowed_buckets:
            continue

        if rule_bucket not in bucket_prefixes:
            bucket_prefixes[rule_bucket] = []

        if rule_prefix:
            bucket_prefixes[rule_bucket].append(rule_prefix)
        else:
            # Full bucket access — empty list means no restriction
            bucket_prefixes[rule_bucket] = []

    result = []
    for bucket_name, prefixes in bucket_prefixes.items():
        result.append({"name": bucket_name, "prefixes": prefixes})
    return result


def check_user_access(email: str, bucket_name: str, prefix: str = "") -> bool:
    rules = get_user_rules(email)
    if rules is None:
        return False

    if "*" in rules:
        return True

    for rule in rules:
        if "/" in rule:
            rule_bucket, rule_prefix = rule.split("/", 1)
        else:
            rule_bucket = rule
            rule_prefix = ""

        if rule_bucket == bucket_name:
            if not rule_prefix:
                # Full bucket access
                return True
            if prefix.startswith(rule_prefix):
                return True

    return False
