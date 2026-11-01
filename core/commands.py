
from memory.conversations import (
    create_conversation,
    get_conversation,
    list_conversations,
    rename_conversation,
    search_messages,
    set_active_conversation,
)


def _normalize_title(value):
    value = str(value or "").strip()
    return value or "New conversation"


def _activate_conversation(lewis, conversation):
    """Update the active runtime and persist the selected conversation."""

    conversation_id = conversation["id"]

    set_active_conversation(conversation_id)
    lewis.active_conversation_id = conversation_id
    lewis.active_project = conversation.get("project")


def handle_deterministic_command(lewis, user_input):
    text = str(user_input or "").strip()

    if not text:
        return None

    lowered = text.lower()

    if lowered in {
        "lewis, stop speaking",
        "lewis stop speaking",
        "stop speaking",
        "halt",
    }:
        lewis.state = "idle"
        return "Understood. I will stop speaking."

    if lowered.startswith("start a new conversation"):
        title = _normalize_title(
            text[len("start a new conversation"):].strip(" .")
        )

        conversation = create_conversation(
            title=title,
            project=lewis.active_project,
        )
        _activate_conversation(lewis, conversation)

        return f"Started a new conversation: {conversation['title']}"

    if (
        lowered.startswith("open our conversation about ")
        or lowered.startswith("open this conversation")
    ):
        if "about" in lowered:
            topic = text.split("about", 1)[1].strip().strip("? .")

            for conversation in list_conversations():
                haystack = " ".join([
                    conversation.get("title", ""),
                    conversation.get("project") or "",
                ]).lower()

                if topic.lower() in haystack:
                    _activate_conversation(lewis, conversation)
                    return f"Opened conversation: {conversation['title']}"

            return (
                f"I couldn't find a matching conversation about '{topic}'."
            )

        if lewis.active_conversation_id:
            current = get_conversation(lewis.active_conversation_id)

            if current:
                return f"Current conversation: {current['title']}"

        return "No active conversation is selected."

    if lowered.startswith("switch to "):
        target = text[len("switch to "):].strip(" .?")

        for conversation in list_conversations():
            haystack = " ".join([
                conversation.get("title", ""),
                conversation.get("project") or "",
            ]).lower()

            if target.lower() in haystack:
                _activate_conversation(lewis, conversation)
                return f"Switched to {conversation['title']}"

        lewis.active_project = target.upper()
        return f"Project set to {target.upper()}."

    if lowered.startswith("rename conversation "):
        title = _normalize_title(
            text[len("rename conversation "):].strip(" .?")
        )

        if lewis.active_conversation_id:
            rename_conversation(lewis.active_conversation_id, title)
            return f"Conversation renamed to {title}."

        return "There is no active conversation to rename."

    if lowered.startswith("what did we decide about "):
        topic = text[len("what did we decide about "):].strip("? .")

        if lewis.active_conversation_id:
            matches = search_messages(
                topic,
                conversation_id=lewis.active_conversation_id,
                limit=5,
            )

            if matches:
                recent = matches[0]["message"]
                return (
                    f"Based on the conversation, "
                    f"{recent.get('role', 'user')}: "
                    f"{recent.get('content', '')}"
                )

        return (
            f"I couldn't find a recorded decision about "
            f"'{topic}' in the active conversation."
        )

    return None