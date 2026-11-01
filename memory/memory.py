import json
import math
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


MEMORY_FILE = Path(__file__).parent / "memory.json"

MULTI_VALUE_CATEGORIES = {
    "interest",
    "likes",
    "loves",
    "dislikes",
    "enjoys",
    "project",
    "goal",
    "aspiration",
    "idea",
}

MEMORY_STATUSES = {
    "stated",
    "idea",
    "interest",
    "plan",
    "in_progress",
    "decision",
    "completed",
    "preference",
}

class MemoryStorageError(Exception):
    """Raised when memory data cannot be safely loaded or persisted."""


class MemoryValidationError(ValueError):
    """Raised when a requested memory edit does not satisfy the schema."""


class MemoryNotFoundError(LookupError):
    """Raised when a requested memory ID does not exist."""


def _timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _validate_memory(memory):
    if not isinstance(memory, dict):
        raise MemoryStorageError("Memory data must be a JSON object.")

    records = memory.get("memories")
    if not isinstance(records, list):
        raise MemoryStorageError("'memories' must be a list.")

    seen_ids = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise MemoryStorageError(
                f"Memory at index {index} must be a JSON object."
            )

        for field in (
            "id",
            "subject",
            "predicate",
            "key",
            "value",
            "category",
            "created_at",
            "updated_at",
            "source",
        ):
            if not isinstance(record.get(field), str) or not record[field].strip():
                raise MemoryStorageError(
                    f"Memory at index {index} has an invalid '{field}' field."
                )

        importance = record.get("importance")
        if (
            isinstance(importance, bool)
            or not isinstance(importance, (int, float))
            or not math.isfinite(importance)
            or not 0 <= importance <= 1
        ):
            raise MemoryStorageError(
                f"Memory at index {index} has an invalid 'importance' field."
            )

        if record["id"] in seen_ids:
            raise MemoryStorageError(
                f"Duplicate memory ID '{record['id']}' at index {index}."
            )
        seen_ids.add(record["id"])

        status = record.get("status")
        if status is not None and (
            not isinstance(status, str) or status not in MEMORY_STATUSES
        ):
            raise MemoryStorageError(
                f"Memory at index {index} has an invalid 'status' field."
            )

        history = record.get("history")
        if history is not None:
            if not isinstance(history, list):
                raise MemoryStorageError(
                    f"Memory at index {index} has an invalid 'history' field."
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
                    raise MemoryStorageError(
                        f"Memory at index {index} has an invalid history entry."
                    )

    try:
        json.dumps(memory, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise MemoryStorageError("Memory data is not valid JSON data.") from error


def _normalize_record(record, migrated_at):
    if not isinstance(record, dict):
        raise MemoryStorageError("Each memory must be a JSON object.")

    normalized = dict(record)
    legacy_key = normalized.get("key")
    predicate = normalized.get("predicate", legacy_key)

    if not isinstance(predicate, str) or not predicate.strip():
        raise MemoryStorageError("A memory must have a non-empty key or predicate.")
    if not isinstance(normalized.get("value"), str) or not normalized["value"].strip():
        raise MemoryStorageError("A memory must have a non-empty string value.")

    category = normalized.get("category", "other")
    if not isinstance(category, str) or not category.strip():
        raise MemoryStorageError("A memory must have a non-empty string category.")

    if not isinstance(normalized.get("id"), str) or not normalized["id"].strip():
        normalized["id"] = str(uuid.uuid4())
    normalized.setdefault("subject", "user")
    normalized.setdefault("predicate", predicate)
    normalized.setdefault("key", normalized["predicate"])
    normalized.setdefault("category", category)
    normalized.setdefault("importance", 0.5)
    normalized.setdefault("created_at", migrated_at)
    normalized.setdefault("updated_at", migrated_at)
    normalized.setdefault("source", "user")
    if not isinstance(normalized["id"], str):
        raise MemoryStorageError("A memory ID must be a string.")
    return normalized


def _normalize_memory(memory):
    if not isinstance(memory, dict):
        raise MemoryStorageError("Memory data must be a JSON object.")
    if "memories" not in memory or not isinstance(memory["memories"], list):
        raise MemoryStorageError("'memories' must be a list.")

    migrated_at = _timestamp()
    normalized = dict(memory)
    normalized_records = []
    seen_ids = set()
    for record in memory["memories"]:
        normalized_record = _normalize_record(record, migrated_at)
        if normalized_record["id"] in seen_ids:
            normalized_record["id"] = str(uuid.uuid4())
        seen_ids.add(normalized_record["id"])
        normalized_records.append(normalized_record)
    normalized["memories"] = normalized_records
    _validate_memory(normalized)
    return normalized


def _read_memory(path):
    try:
        with path.open("r", encoding="utf-8") as file:
            raw_memory = json.load(file)
    except FileNotFoundError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MemoryStorageError(f"Could not read memory file '{path}'.") from error

    if not isinstance(raw_memory, dict):
        raise MemoryStorageError("Memory file must contain a JSON object.")
    return raw_memory


def _read_existing_memory(path):
    try:
        return _read_memory(path)
    except FileNotFoundError:
        return None


def _write_atomically(memory, path):
    _validate_memory(memory)
    temporary_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = Path(file.name)
            json.dump(memory, file, indent=4, ensure_ascii=False, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
    except (OSError, TypeError, ValueError) as error:
        raise MemoryStorageError(f"Could not persist memory file '{path}'.") from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _create_migration_backup(path):
    backup_path = path.with_name(f"{path.name}.pre-v2.bak")
    suffix = 1
    while backup_path.exists():
        backup_path = path.with_name(f"{path.name}.pre-v2-{suffix}.bak")
        suffix += 1

    try:
        original = path.read_bytes()
        with backup_path.open("xb") as backup:
            backup.write(original)
            backup.flush()
            os.fsync(backup.fileno())
    except OSError as error:
        raise MemoryStorageError(
            f"Could not create a pre-migration backup for '{path}'."
        ) from error


def load_memory():
    """Load and normalize memories, preserving legacy fields and data."""
    path = Path(MEMORY_FILE)
    raw_memory = _read_existing_memory(path)
    if raw_memory is None:
        return {"memories": []}

    normalized = _normalize_memory(raw_memory)
    if normalized != raw_memory:
        _create_migration_backup(path)
        _write_atomically(normalized, path)
    return normalized


def save_memory(memory):
    """Validate and atomically persist the complete memory structure."""
    path = Path(MEMORY_FILE)
    normalized = _normalize_memory(memory)

    existing_memory = _read_existing_memory(path)
    if existing_memory is not None:
        normalized_existing = _normalize_memory(existing_memory)
        if normalized_existing != existing_memory:
            _create_migration_backup(path)

    _write_atomically(normalized, path)


def remember(key, value, category="other", importance=0.5, status="stated"):
    """Store a user memory, updating single-value keys and preserving multi-values."""
    key = str(key).strip()
    value = str(value).strip()
    category = str(category).strip().lower()
    status = str(status).strip().lower()

    if not key or not value:
        return
    if status not in MEMORY_STATUSES:
        raise MemoryStorageError(f"Unsupported memory status '{status}'.")
    if (
        isinstance(importance, bool)
        or not isinstance(importance, (int, float))
        or not math.isfinite(importance)
        or not 0 <= importance <= 1
    ):
        raise MemoryStorageError("Memory importance must be between 0 and 1.")

    memory = load_memory()
    now = _timestamp()
    new_memory = {
        "id": str(uuid.uuid4()),
        "subject": "user",
        "predicate": key,
        "key": key,
        "value": value,
        "category": category,
        "importance": importance,
        "created_at": now,
        "updated_at": now,
        "source": "user",
        "status": status,
    }

    if category in MULTI_VALUE_CATEGORIES:
        for stored_memory in memory["memories"]:
            stored_key = str(stored_memory.get("key", "")).strip().lower()
            stored_value = str(stored_memory.get("value", "")).strip().lower()
            stored_category = str(stored_memory.get("category", "")).strip().lower()

            if (
                stored_key == key.lower()
                and stored_value == value.lower()
                and stored_category == category
            ):
                stored_status = stored_memory.get("status", "stated")
                if stored_status == status:
                    return
                history = list(stored_memory.get("history", []))
                history.append(
                    {
                        "value": stored_memory["value"],
                        "status": stored_status,
                        "updated_at": stored_memory["updated_at"],
                    }
                )
                new_memory["id"] = stored_memory["id"]
                new_memory["created_at"] = stored_memory["created_at"]
                new_memory["history"] = history
                stored_memory.update(new_memory)
                save_memory(memory)
                return

        memory["memories"].append(new_memory)
        save_memory(memory)
        return

    for stored_memory in memory["memories"]:
        stored_key = str(stored_memory.get("key", "")).strip().lower()
        stored_category = str(stored_memory.get("category", "")).strip().lower()

        if stored_key == key.lower() and stored_category == category:
            if (
                stored_memory.get("value", "").strip().casefold()
                == value.casefold()
                and stored_memory.get("status", "stated") == status
            ):
                return

            if (
                stored_memory.get("status") == "decision"
                and status != "decision"
            ):
                return

            history = list(stored_memory.get("history", []))
            history.append(
                {
                    "value": stored_memory["value"],
                    "status": stored_memory.get("status", "stated"),
                    "updated_at": stored_memory["updated_at"],
                }
            )
            new_memory["history"] = history
            new_memory["id"] = stored_memory["id"]
            new_memory["created_at"] = stored_memory["created_at"]
            stored_memory.update(new_memory)
            save_memory(memory)
            return

    memory["memories"].append(new_memory)
    save_memory(memory)


def update_memory(memory_id, updates):
    if not isinstance(memory_id, str) or not memory_id.strip():
        raise MemoryValidationError("A valid memory ID is required.")
    if not isinstance(updates, dict) or not updates:
        raise MemoryValidationError("At least one memory field is required.")

    allowed_fields = {"subject", "key", "value", "category", "status", "importance"}
    if set(updates) - allowed_fields:
        raise MemoryValidationError("Unsupported memory field.")

    memory = load_memory()
    for record in memory["memories"]:
        if record["id"] != memory_id:
            continue

        updated = dict(record)
        for field in ("subject", "key", "value", "category", "status"):
            if field not in updates:
                continue
            value = updates[field]
            if not isinstance(value, str) or not value.strip():
                raise MemoryValidationError(
                    f"Memory {field} must be non-empty text."
                )
            value = value.strip()
            if len(value) > 2000:
                raise MemoryValidationError(
                    f"Memory {field} is too long."
                )
            if field == "status" and value not in MEMORY_STATUSES:
                raise MemoryValidationError(
                    f"Unsupported memory status '{value}'."
                )
            updated[field] = value

        if "importance" in updates:
            importance = updates["importance"]
            if (
                isinstance(importance, bool)
                or not isinstance(importance, (int, float))
                or not math.isfinite(importance)
                or not 0 <= importance <= 1
            ):
                raise MemoryValidationError(
                    "Memory importance must be between 0 and 1."
                )
            updated["importance"] = importance

        if "key" in updates:
            updated["predicate"] = updated["key"]

        previous_status = record.get("status", "stated")
        if (
            updated["value"] != record["value"]
            or updated.get("status", previous_status) != previous_status
        ):
            history = list(record.get("history", []))
            history.append({
                "value": record["value"],
                "status": previous_status,
                "updated_at": record["updated_at"],
            })
            updated["history"] = history

        updated["updated_at"] = _timestamp()
        memory["memories"][memory["memories"].index(record)] = updated
        save_memory(memory)
        return updated

    raise MemoryNotFoundError("Memory not found.")


def recall(key):
    """Retrieve the first memory matching a key."""
    key = str(key).strip().lower()
    memory = load_memory()

    for stored_memory in memory["memories"]:
        stored_key = str(stored_memory.get("key", "")).strip().lower()
        if stored_key == key:
            return stored_memory.get("value")

    return None


def recall_all(key):
    """Retrieve all memories matching a key."""
    key = str(key).strip().lower()
    memory = load_memory()
    return [
        stored_memory
        for stored_memory in memory["memories"]
        if str(stored_memory.get("key", "")).strip().lower() == key
    ]


def get_by_category(category):
    """Retrieve every memory belonging to a category."""
    category = str(category).strip().lower()
    memory = load_memory()
    return [
        stored_memory
        for stored_memory in memory["memories"]
        if str(stored_memory.get("category", "")).strip().lower() == category
    ]


def get_all_memories():
    """Return every stored memory."""
    return load_memory()["memories"]
