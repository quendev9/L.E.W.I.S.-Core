import json
import math
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from memory.memory import MEMORY_STATUSES


PROJECT_MEMORY_FILE = Path(__file__).with_name("project_memory.json")


class ProjectMemoryStorageError(Exception):
    """Raised when project memory cannot be safely loaded or persisted."""


def _utc_now():
    return datetime.now(timezone.utc).isoformat(
        timespec="microseconds"
    ).replace(
        "+00:00", "Z"
    )


def _normalize_project_memory(data):
    if not isinstance(data, dict):
        raise ProjectMemoryStorageError(
            "Project memory file must contain an object."
        )

    normalized = dict(data)
    projects = normalized.setdefault("projects", {})
    if not isinstance(projects, dict):
        raise ProjectMemoryStorageError(
            "Project memory 'projects' must be an object."
        )

    migrated_at = _utc_now()
    seen_ids = set()
    for project_name, project_bucket in projects.items():
        if not isinstance(project_name, str) or not project_name.strip():
            raise ProjectMemoryStorageError(
                "Project names must be non-empty strings."
            )
        if not isinstance(project_bucket, dict):
            raise ProjectMemoryStorageError(
                f"Project '{project_name}' must contain an object."
            )

        project_bucket.setdefault("name", project_name)
        project_bucket.setdefault("facts", [])
        facts = project_bucket["facts"]
        if not isinstance(facts, list):
            raise ProjectMemoryStorageError(
                f"Facts for project '{project_name}' must be a list."
            )

        for index, fact in enumerate(facts):
            if not isinstance(fact, dict):
                raise ProjectMemoryStorageError(
                    f"Fact {index} for project '{project_name}' must be an object."
                )

            fact.setdefault("id", str(uuid.uuid4()))
            fact.setdefault("subject", "unknown")
            fact.setdefault("predicate", "fact")
            fact.setdefault("category", "project")
            fact.setdefault("importance", 0.5)
            fact.setdefault("created_at", migrated_at)
            fact.setdefault("updated_at", migrated_at)
            fact.setdefault("source", "project")
            if "status" not in fact:
                fact["status"] = (
                    "decision"
                    if fact.get("category") == "decision"
                    else "stated"
                )

            for field in (
                "id",
                "subject",
                "predicate",
                "value",
                "category",
                "created_at",
                "updated_at",
                "source",
                "status",
            ):
                if not isinstance(fact.get(field), str) or not fact[field].strip():
                    raise ProjectMemoryStorageError(
                        f"Fact {index} for project '{project_name}' has an "
                        f"invalid '{field}' field."
                    )

            importance = fact["importance"]
            if (
                isinstance(importance, bool)
                or not isinstance(importance, (int, float))
                or not math.isfinite(importance)
                or not 0 <= importance <= 1
            ):
                raise ProjectMemoryStorageError(
                    f"Fact {index} for project '{project_name}' has an "
                    "invalid 'importance' field."
                )

            if (
                not isinstance(fact["status"], str)
                or fact["status"] not in MEMORY_STATUSES
            ):
                raise ProjectMemoryStorageError(
                    f"Fact {index} for project '{project_name}' has an "
                    "invalid 'status' field."
                )

            if fact["id"] in seen_ids:
                raise ProjectMemoryStorageError(
                    f"Duplicate project-memory ID '{fact['id']}'."
                )
            seen_ids.add(fact["id"])

            history = fact.get("history")
            if history is not None:
                if not isinstance(history, list):
                    raise ProjectMemoryStorageError(
                        f"Fact {index} has an invalid 'history' field."
                    )
                for entry in history:
                    if (
                        not isinstance(entry, dict)
                        or not isinstance(entry.get("value"), str)
                        or not entry["value"].strip()
                        or not isinstance(entry.get("status"), str)
                        or entry["status"] not in MEMORY_STATUSES
                        or not isinstance(entry.get("updated_at"), str)
                        or not entry["updated_at"].strip()
                    ):
                        raise ProjectMemoryStorageError(
                            f"Fact {index} has an invalid history entry."
                        )

    try:
        json.dumps(normalized, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ProjectMemoryStorageError(
            "Project memory data is not valid JSON data."
        ) from error
    return normalized


def _read_project_memory():
    try:
        with PROJECT_MEMORY_FILE.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {"projects": {}}
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProjectMemoryStorageError(
            f"Could not read project memory file '{PROJECT_MEMORY_FILE}'."
        ) from error

    return _normalize_project_memory(data)


def _write_project_memory(data):
    normalized = _normalize_project_memory(data)
    temp_path = None
    try:
        PROJECT_MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=PROJECT_MEMORY_FILE.parent,
            prefix=f".{PROJECT_MEMORY_FILE.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(
                normalized,
                handle,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, PROJECT_MEMORY_FILE)
    except (OSError, TypeError, ValueError) as error:
        raise ProjectMemoryStorageError(
            f"Could not persist project memory file '{PROJECT_MEMORY_FILE}'."
        ) from error
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def _normalize_project_name(project_name):
    value = str(project_name or "").strip()
    return value or "ATLAS"


def _project_bucket(data, project_name):
    target = project_name.casefold()
    for name, bucket in data["projects"].items():
        if name.casefold() == target:
            return name, bucket
    return project_name, None


def remember_project_fact(
    project_name,
    subject,
    predicate,
    value,
    category="project",
    importance=0.9,
    status="stated",
    correction=False,
):
    project_name = _normalize_project_name(project_name)
    values = {
        "subject": subject,
        "predicate": predicate,
        "value": value,
        "category": category,
        "status": status,
    }
    for field, field_value in values.items():
        if not isinstance(field_value, str) or not field_value.strip():
            raise ValueError(f"Project fact '{field}' must be a non-empty string.")

    status = status.strip().lower()
    if (
        isinstance(importance, bool)
        or not isinstance(importance, (int, float))
        or not math.isfinite(importance)
        or not 0 <= importance <= 1
    ):
        raise ValueError("Project fact importance must be between 0 and 1.")
    if status not in MEMORY_STATUSES:
        raise ValueError(f"Unsupported project fact status '{status}'.")
    if not isinstance(correction, bool):
        raise ValueError("Project fact correction flag must be a boolean.")

    subject = subject.strip()
    predicate = predicate.strip()
    value = value.strip()
    category = category.strip().lower()

    data = _read_project_memory()
    bucket_name, project_bucket = _project_bucket(data, project_name)
    if project_bucket is None:
        project_bucket = {"name": project_name, "facts": []}
        data["projects"][project_name] = project_bucket

    now = _utc_now()
    fact = {
        "id": str(uuid.uuid4()),
        "subject": subject,
        "predicate": predicate,
        "value": value,
        "category": category,
        "importance": importance,
        "created_at": now,
        "updated_at": now,
        "source": "user",
        "status": status,
    }

    for existing in project_bucket["facts"]:
        same_slot = (
            existing["subject"].casefold() == subject.casefold()
            and existing["predicate"].casefold() == predicate.casefold()
            and existing["category"].casefold() == category
        )
        same_value = existing["value"].casefold() == value.casefold()
        if same_slot and same_value and existing["status"] == status:
            return existing

        if not same_slot:
            continue
        if existing["status"] == "decision" and status != "decision":
            return existing
        if same_value:
            history = list(existing.get("history", []))
            history.append(
                {
                    "value": existing["value"],
                    "status": existing["status"],
                    "updated_at": existing["updated_at"],
                }
            )
            fact["id"] = existing["id"]
            fact["created_at"] = existing["created_at"]
            fact["history"] = history
            project_bucket["facts"][
                project_bucket["facts"].index(existing)
            ] = fact
            project_bucket["updated_at"] = now
            _write_project_memory(data)
            return fact

        if not correction and predicate.casefold() != "name":
            continue

        history = list(existing.get("history", []))
        history.append(
            {
                "value": existing["value"],
                "status": existing["status"],
                "updated_at": existing["updated_at"],
            }
        )
        fact["id"] = existing["id"]
        fact["created_at"] = existing["created_at"]
        fact["history"] = history
        project_bucket["facts"][
            project_bucket["facts"].index(existing)
        ] = fact
        project_bucket["updated_at"] = now
        _write_project_memory(data)
        return fact

    project_bucket["facts"].append(fact)
    project_bucket["updated_at"] = now
    _write_project_memory(data)
    return fact


def get_project_facts(project_name=None):
    data = _read_project_memory()
    if project_name is None:
        facts = []
        for project_bucket in data["projects"].values():
            facts.extend(project_bucket["facts"])
        return facts

    _, project_bucket = _project_bucket(
        data,
        _normalize_project_name(project_name),
    )
    return list(project_bucket["facts"]) if project_bucket else []


def list_project_memory():
    """Return saved project names and their stored facts."""
    data = _read_project_memory()
    return [
        {
            "name": name,
            "facts": list(bucket["facts"]),
            "updated_at": bucket.get("updated_at"),
        }
        for name, bucket in data["projects"].items()
    ]


def search_project_facts(query, project_name=None, limit=10):
    if not isinstance(query, str) or not query.strip() or limit <= 0:
        return []

    needle = query.strip().lower()
    matches = []
    for fact in get_project_facts(project_name=project_name):
        haystack = " ".join(
            [
                str(fact.get("subject", "")),
                str(fact.get("predicate", "")),
                str(fact.get("value", "")),
            ]
        ).lower()
        if needle in haystack:
            matches.append(fact)
        if len(matches) >= limit:
            break
    return matches
