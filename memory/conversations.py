import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


CONVERSATIONS_FILE = Path(__file__).with_name("conversations.json")


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _read_json(path):
    if not path.exists():
        return {"conversations": [], "active_conversation_id": None}

    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"Conversation data in {path} is not a JSON object.")

    conversations = data.get("conversations", [])
    if not isinstance(conversations, list):
        raise ValueError("Conversation data must store an array of conversations.")

    return data


def _write_json(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def load_conversations():
    return _read_json(CONVERSATIONS_FILE)


def save_conversations(data):
    if not isinstance(data, dict):
        raise ValueError("Conversation payload must be a dictionary.")
    _write_json(data, CONVERSATIONS_FILE)


def _normalize_conversation(conversation):
    if not isinstance(conversation, dict):
        raise ValueError("Each conversation must be a dictionary.")

    conversation = dict(conversation)
    conversation.setdefault("id", str(uuid.uuid4()))
    conversation.setdefault("title", "New conversation")
    conversation.setdefault("project", None)
    conversation.setdefault("created_at", _utc_now())
    conversation.setdefault("updated_at", conversation["created_at"])
    conversation.setdefault("summary", None)
    conversation.setdefault("summary_coverage", {
        "start_index": 0,
        "end_index": 0,
        "latest_message_id": None,
        "covered_message_ids": [],
    })
    conversation.setdefault("messages", [])

    if not isinstance(conversation["messages"], list):
        raise ValueError("Conversation messages must be a list.")

    return conversation

def list_conversations():
    data = load_conversations()
    conversations = data.get("conversations", [])
    return [_normalize_conversation(item) for item in conversations]


def get_conversation(conversation_id):
    for conversation in list_conversations():
        if conversation.get("id") == conversation_id:
            return conversation
    return None


def get_active_conversation_id():
    data = load_conversations()
    return data.get("active_conversation_id")


def set_active_conversation(conversation_id):
    data = load_conversations()
    if conversation_id is not None and get_conversation(conversation_id) is None:
        raise ValueError(f"Unknown conversation ID: {conversation_id}")
    data["active_conversation_id"] = conversation_id
    save_conversations(data)
    return conversation_id


def create_conversation(title="New conversation", project=None):
    data = load_conversations()
    conversation = {
        "id": str(uuid.uuid4()),
        "title": title or "New conversation",
        "project": project,
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "summary": None,
        "summary_coverage": {
            "start_index": 0,
            "end_index": 0,
            "latest_message_id": None,
            "covered_message_ids": [],
        },
        "messages": [],
    }
    conversation = _normalize_conversation(conversation)
    data.setdefault("conversations", []).append(conversation)
    data["active_conversation_id"] = conversation["id"]
    save_conversations(data)
    return conversation


def rename_conversation(conversation_id, new_title):
    data = load_conversations()
    for index, conversation in enumerate(data.get("conversations", [])):
        if conversation.get("id") == conversation_id:
            conversation["title"] = new_title or conversation.get("title") or "New conversation"
            conversation["updated_at"] = _utc_now()
            save_conversations(data)
            return conversation
    raise ValueError(f"Could not find conversation '{conversation_id}'.")


def update_conversation_metadata(conversation_id, updates):
    if not isinstance(conversation_id, str) or not conversation_id.strip():
        raise ValueError("A valid conversation ID is required.")
    if not isinstance(updates, dict) or not updates:
        raise ValueError("At least one conversation setting is required.")

    allowed_fields = {"pinned", "folder", "project"}
    if set(updates) - allowed_fields:
        raise ValueError("Unsupported conversation setting.")

    normalized_updates = {}
    if "pinned" in updates:
        if not isinstance(updates["pinned"], bool):
            raise ValueError("Pinned must be true or false.")
        normalized_updates["pinned"] = updates["pinned"]

    for field in ("folder", "project"):
        if field not in updates:
            continue
        value = updates[field]
        if field == "project" and value is None:
            normalized_updates[field] = None
            continue
        if not isinstance(value, str):
            raise ValueError(f"{field.capitalize()} must be text.")
        value = value.strip()
        limit = 80 if field == "folder" else 120
        if len(value) > limit:
            raise ValueError(
                f"{field.capitalize()} must be {limit} characters or fewer."
            )
        normalized_updates[field] = value or None

    data = load_conversations()
    for conversation in data.get("conversations", []):
        if conversation.get("id") != conversation_id:
            continue
        conversation.update(normalized_updates)
        conversation["updated_at"] = _utc_now()
        save_conversations(data)
        return _normalize_conversation(conversation)

    raise ValueError(f"Could not find conversation '{conversation_id}'.")


def delete_conversation(conversation_id):
    if not isinstance(conversation_id, str) or not conversation_id.strip():
        raise ValueError("A valid conversation ID is required.")

    data = load_conversations()
    conversations = data.get("conversations", [])

    target = next(
        (
            conversation
            for conversation in conversations
            if conversation.get("id") == conversation_id
        ),
        None,
    )

    if target is None:
        raise ValueError(f"Could not find conversation '{conversation_id}'.")

    data["conversations"] = [
        conversation
        for conversation in conversations
        if conversation.get("id") != conversation_id
    ]

    if data.get("active_conversation_id") == conversation_id:
        remaining = data["conversations"]

        if remaining:
            remaining.sort(
                key=lambda conversation: str(
                    conversation.get("updated_at", "")
                ),
                reverse=True,
            )
            data["active_conversation_id"] = remaining[0].get("id")
        else:
            data["active_conversation_id"] = None

    save_conversations(data)

    return {
        "deleted_id": conversation_id,
        "active_conversation_id": data.get("active_conversation_id"),
    }

def add_message(conversation_id, role, content, **metadata):
    if not isinstance(role, str) or not role.strip():
        raise ValueError("Message role must be a non-empty string.")
    if not isinstance(content, str):
        raise ValueError("Message content must be a string.")

    data = load_conversations()
    conversations = data.get("conversations", [])
    target = None
    for conversation in conversations:
        if conversation.get("id") == conversation_id:
            target = conversation
            break

    if target is None:
        raise ValueError(f"Unknown conversation ID: {conversation_id}")

    message = {
        "id": metadata.pop("message_id", str(uuid.uuid4())),
        "role": role,
        "content": content,
        "timestamp": metadata.pop("timestamp", _utc_now()),
        "project": metadata.pop("project", target.get("project")),
    }
    message.update(metadata)

    target.setdefault("messages", []).append(message)
    target["updated_at"] = _utc_now()
    save_conversations(data)
    return message


def update_summary(conversation_id, summary, covered_message_ids=None, start_index=0, end_index=None, latest_message_id=None):
    data = load_conversations()
    conversations = data.get("conversations", [])
    target = None
    for conversation in conversations:
        if conversation.get("id") == conversation_id:
            target = conversation
            break

    if target is None:
        raise ValueError(f"Unknown conversation ID: {conversation_id}")

    messages = target.get("messages", [])
    end_index = len(messages) if end_index is None else end_index
    covered = list(covered_message_ids or [])

    target["summary"] = summary
    target["summary_coverage"] = {
        "start_index": start_index,
        "end_index": max(start_index, end_index),
        "latest_message_id": latest_message_id,
        "covered_message_ids": covered,
    }
    target["updated_at"] = _utc_now()
    save_conversations(data)
    return target["summary_coverage"]


def search_messages(query, conversation_id=None, project=None, limit=10):
    if not isinstance(query, str) or not query.strip():
        return []

    needle = query.strip().lower()
    results = []
    for conversation in list_conversations():
        if conversation_id and conversation.get("id") != conversation_id:
            continue
        if project and conversation.get("project") not in (None, project):
            continue

        for message in conversation.get("messages", []):
            content = str(message.get("content", ""))
            if needle in content.lower():
                results.append({
                    "conversation_id": conversation.get("id"),
                    "title": conversation.get("title"),
                    "project": conversation.get("project"),
                    "message": message,
                })
                if len(results) >= limit:
                    return results

    return results
