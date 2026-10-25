import re

FIELDS = {
    "rule_id",
    "category",
    "severity",
    "file",
    "line",
    "description",
    "evidence",
    "recommendation",
}
VIOLATION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "rule_id": {"type": "STRING"},
        "category": {"type": "STRING"},
        "severity": {"type": "STRING", "enum": ["critical", "high", "medium", "low"]},
        "file": {"type": "STRING", "nullable": True},
        "line": {"type": "INTEGER", "nullable": True},
        "description": {"type": "STRING"},
        "evidence": {"type": "STRING"},
        "recommendation": {"type": "STRING"},
    },
    "required": sorted(FIELDS),
}


def normalize(text):
    return " ".join(text.split())


def validate_report(arguments, repository, tools):
    if not isinstance(arguments, dict) or set(arguments) != {"violations"}:
        raise ValueError("submit_report expects only a violations array")
    violations = arguments["violations"]
    if not isinstance(violations, list) or len(violations) > 100:
        raise ValueError("violations must be an array with at most 100 entries")
    if not tools.inventory_observed:
        raise ValueError("Discover the repository using list_files before concluding")
    if tools.files and not tools.observed:
        raise ValueError("Inspect relevant file content before concluding")
    result, seen = [], set()
    for item in violations:
        if not isinstance(item, dict) or set(item) != FIELDS:
            raise ValueError("Each violation must contain exactly all eight required fields")
        item = dict(item)
        for field in FIELDS - {"file", "line"}:
            if (
                not isinstance(item[field], str)
                or not item[field].strip()
                or len(item[field]) > 3000
            ):
                raise ValueError(f"{field} must be a nonempty string of at most 3000 characters")
            item[field] = tools.redact(item[field])
        if not re.fullmatch(r"[A-Z][A-Z0-9_-]*-\d{3}", item["rule_id"]):
            raise ValueError("Use stable rule IDs such as SEC-001 or CI-001")
        if item["severity"] not in {"critical", "high", "medium", "low"}:
            raise ValueError("severity must be critical, high, medium, or low")
        path, number = item["file"], item["line"]
        if path is None:
            if number is not None:
                raise ValueError("Repository-level findings require both file and line to be null")

            if tools.inventory_seen != set(tools.files):
                raise ValueError(
                    "Read all list_files pages before making repository-level absence claims"
                )
        else:
            if not isinstance(path, str) or path not in tools.files:
                raise ValueError(
                    "Finding file must exist in the snapshot; use null for missing files"
                )
            if type(number) is not int or number <= 0:
                raise ValueError("Existing-file findings require a positive, inspected line number")
            observed = tools.observed.get((path, number))
            if observed is None:
                raise ValueError(f"Read {path} at line {number} before citing it")
            evidence = normalize(item["evidence"])
            if not evidence or evidence not in normalize(observed):
                raise ValueError(
                    f"Evidence must be an exact excerpt from the inspected line {path}:{number}"
                )
        key = (item["rule_id"], path, number)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return {"repository": repository, "violations": result}
