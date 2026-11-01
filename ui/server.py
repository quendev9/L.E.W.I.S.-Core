import json
import os
import queue
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psutil


# ---------------------------------------------------------
# PATHS
# ---------------------------------------------------------

UI_DIR = Path(__file__).parent
PROJECT_DIR = UI_DIR.parent

sys.path.insert(0, str(PROJECT_DIR))


# ---------------------------------------------------------
# LEWIS IMPORTS
# ---------------------------------------------------------

from core.event_logger import get_events, log_event
from memory.conversations import (
    create_conversation,
    delete_conversation,
    get_active_conversation_id,
    get_conversation,
    list_conversations,
    rename_conversation,
    search_messages,
    set_active_conversation,
    update_conversation_metadata,
)

try:
    from core.lewis import Lewis
    LEWIS_AVAILABLE = True
except Exception as error:
    LEWIS_AVAILABLE = False
    print("LEWIS CORE IMPORT ERROR:", type(error).__name__)

try:
    from memory.memory import (
        MemoryNotFoundError,
        MemoryStorageError,
        MemoryValidationError,
        get_all_memories,
        update_memory,
    )
    MEMORY_AVAILABLE = True
except Exception:
    MEMORY_AVAILABLE = False

try:
    from memory.project_memory import list_project_memory
    PROJECT_MEMORY_AVAILABLE = True
except Exception:
    PROJECT_MEMORY_AVAILABLE = False

try:
    import ai.model
    AI_AVAILABLE = True
except Exception:
    AI_AVAILABLE = False

try:
    from voice.speech_input import listen_once
    VOICE_INPUT_AVAILABLE = True
except Exception as error:
    VOICE_INPUT_AVAILABLE = False
    listen_once = None
    print("LEWIS VOICE INPUT IMPORT ERROR:", type(error).__name__, str(error))

try:
    from voice.speech_output import speak, stop_speaking, was_stop_requested
    VOICE_OUTPUT_AVAILABLE = True
except Exception as error:
    VOICE_OUTPUT_AVAILABLE = False
    speak = None
    stop_speaking = None
    was_stop_requested = None
    print("LEWIS VOICE OUTPUT IMPORT ERROR:", type(error).__name__, str(error))


# ---------------------------------------------------------
# LEWIS INSTANCE
# ---------------------------------------------------------

lewis = None

if LEWIS_AVAILABLE:
    try:
        lewis = Lewis()
    except Exception as error:
        print("LEWIS INITIALIZATION ERROR:", type(error).__name__)
        lewis = None
        LEWIS_AVAILABLE = False


# ---------------------------------------------------------
# SERVER STATE AND LOCKS
# ---------------------------------------------------------

START_TIME = time.time()

# Only one request may process a message through the shared
# Lewis instance at a time.
core_lock = threading.Lock()

# Only one microphone session may run at a time.
voice_lock = threading.Lock()

# Protect shared status and voice-result values.
state_lock = threading.Lock()
voice_output_lock = threading.Lock()

voice_stop_event = threading.Event()
voice_interrupt_event = threading.Event()
push_to_talk_stop_event = threading.Event()
pending_speech = queue.Queue(maxsize=20)
active_voice_output_cancel_event = None


class _VoiceOutputCancellation:
    def __init__(self, *events):
        self.events = events

    def is_set(self):
        return any(event.is_set() for event in self.events)


def _set_active_voice_output_cancel_event(event):
    global active_voice_output_cancel_event

    with voice_output_lock:
        active_voice_output_cancel_event = event


def _clear_active_voice_output_cancel_event(event):
    global active_voice_output_cancel_event

    with voice_output_lock:
        if active_voice_output_cancel_event is event:
            active_voice_output_cancel_event = None


def _request_voice_output_stop():
    with voice_output_lock:
        cancel_event = active_voice_output_cancel_event
        if cancel_event is not None:
            cancel_event.set()

    if VOICE_OUTPUT_AVAILABLE and stop_speaking is not None:
        stop_speaking()

server_state = {
    "activity": "READY",
    "voice_available": VOICE_INPUT_AVAILABLE,
    "voice_enabled": True,
    "listening": False,
    "speaking": False,
    "voice_output_pending": False,
    "processing": False,
    "voice_session_active": False,
    "voice_session_stopping": False,
    "push_to_talk_active": False,
    "push_to_talk_processing": False,
    "voice_event_id": 0,
    "voice_response_id": 0,
    "last_transcript": "",
    "last_response": "",
    "last_error": "",
}


def update_state(**changes):
    with state_lock:
        server_state.update(changes)
        if server_state["voice_session_stopping"]:
            server_state["activity"] = "STOPPING"
        elif server_state["speaking"]:
            server_state["activity"] = "SPEAKING"
        elif (
            server_state["processing"] or
            server_state["push_to_talk_processing"]
        ):
            server_state["activity"] = "PROCESSING"
        elif (
            server_state["listening"] or
            server_state["push_to_talk_active"]
        ):
            server_state["activity"] = "LISTENING"
        else:
            server_state["activity"] = "READY"


def get_state_snapshot():
    with state_lock:
        return dict(server_state)


# ---------------------------------------------------------
# MEMORY
# ---------------------------------------------------------

def get_memory_count():
    if not MEMORY_AVAILABLE:
        return None

    try:
        return len(get_all_memories())
    except Exception as error:
        print("LEWIS MEMORY STATUS ERROR:", type(error).__name__)
        return None


# ---------------------------------------------------------
# SYSTEM DATA
# ---------------------------------------------------------

def get_system_data():
    cpu = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory()

    return {
        "cpu": round(cpu, 1),
        "ram": round(memory.percent, 1),
        "ram_used_gb": round(memory.used / (1024 ** 3), 2),
        "ram_total_gb": round(memory.total / (1024 ** 3), 2),
    }


# ---------------------------------------------------------
# LEWIS STATUS
# ---------------------------------------------------------

def get_status():
    state = get_state_snapshot()
    memory_count = get_memory_count()
    ai_info = ai.model.get_ai_provider_info() if AI_AVAILABLE else None

    return {
        "core": (
            "ONLINE" if LEWIS_AVAILABLE and lewis else "OFFLINE"
        ),
        "ai": (
            "CONFIGURED"
            if ai_info and ai_info["configured"]
            else "NOT CONFIGURED" if AI_AVAILABLE else "OFFLINE"
        ),
        "ai_provider": (
            ai_info["provider"] if ai_info else "Unavailable"
        ),
        "ai_model": ai_info["model"] if ai_info else None,
        "ai_selection": (
            ai_info["selection"] if ai_info else None
        ),
        "ai_models": (
            ai.model.get_available_ai_models() if AI_AVAILABLE else []
        ),
        "memory": (
            "ACTIVE" if memory_count is not None
            else "ERROR" if MEMORY_AVAILABLE else "OFFLINE"
        ),
        "tools": "NOT CONNECTED",
        "memory_count": memory_count,
        "uptime": int(time.time() - START_TIME),
        "system": get_system_data(),
        "activity": state["activity"],
        "processing": state["processing"],
        "voice_available": state["voice_available"],
        "voice_output_available": VOICE_OUTPUT_AVAILABLE,
        "voice_enabled": state["voice_enabled"],
        "listening": state["listening"],
        "speaking": state["speaking"],
        "voice_output_pending": state["voice_output_pending"],
        "voice_session_active": state["voice_session_active"],
        "voice_session_stopping": state["voice_session_stopping"],
        "push_to_talk_active": state["push_to_talk_active"],
        "push_to_talk_processing": state["push_to_talk_processing"],
        "voice_event_id": state["voice_event_id"],
        "voice_response_id": state["voice_response_id"],
        "last_transcript": state["last_transcript"],
        "last_response": state["last_response"],
        "last_error": state["last_error"],
    }


# ---------------------------------------------------------
# JSON HELPERS
# ---------------------------------------------------------

def send_json(handler, data, status=200):
    payload = json.dumps(data).encode("utf-8")

    handler.send_response(status)
    handler.send_header(
        "Content-Type",
        "application/json; charset=utf-8",
    )
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()

    try:
        handler.wfile.write(payload)
    except (BrokenPipeError, ConnectionResetError):
        pass


def read_json_body(handler):
    try:
        content_length = int(handler.headers.get("Content-Length", "0"))

        if content_length <= 0 or content_length > 100_000:
            return None

        body = handler.rfile.read(content_length)
        data = json.loads(body.decode("utf-8"))

        return data if isinstance(data, dict) else None

    except (ValueError, UnicodeError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------
# CORE PROCESSING
# ---------------------------------------------------------

def process_with_lewis(user_input):
    if not LEWIS_AVAILABLE or lewis is None:
        raise RuntimeError("LEWIS Core is unavailable.")

    with core_lock:
        update_state(processing=True)

        try:
            response = lewis.process(user_input)

            if response is None:
                response = "LEWIS Core returned no response."

            return str(response)

        finally:
            update_state(processing=False)


# ---------------------------------------------------------
# VOICE WORKER
# ---------------------------------------------------------

def _speak_session_text(text, stop_event):
    if stop_event.is_set():
        return

    speech_cancel_event = threading.Event()
    _set_active_voice_output_cancel_event(speech_cancel_event)

    def playback_started():
        update_state(
            processing=False,
            speaking=True,
            voice_output_pending=False,
        )
        log_event("VOICE OUTPUT STARTED")

    try:
        update_state(
            processing=True,
            speaking=False,
            voice_output_pending=True,
        )
        completed = speak(
            text,
            cancel_event=_VoiceOutputCancellation(
                speech_cancel_event,
                stop_event,
            ),
            on_playback_start=playback_started,
        )
    finally:
        _clear_active_voice_output_cancel_event(speech_cancel_event)
        update_state(
            processing=False,
            speaking=False,
            voice_output_pending=False,
        )

    if not completed and not stop_event.is_set():
        update_state(last_error="Speech output could not be completed.")
        log_event("VOICE OUTPUT FAILED")
    log_event("VOICE OUTPUT FINISHED")


def _speak_pending_text(stop_event):
    try:
        text = pending_speech.get_nowait()
    except queue.Empty:
        return False

    try:
        _speak_session_text(text, stop_event)
    finally:
        pending_speech.task_done()

    return True


def voice_worker(stop_event):
    try:
        log_event("VOICE LISTENING STARTED")

        while not stop_event.is_set():
            voice_interrupt_event.clear()

            if _speak_pending_text(stop_event):
                continue

            if stop_event.is_set():
                break

            try:
                transcript = listen_once(
                    stop_event=stop_event,
                    interrupt_event=voice_interrupt_event,
                    on_capture_start=lambda: update_state(listening=True),
                )
            finally:
                update_state(listening=False)

            if stop_event.is_set():
                break

            if not transcript or not transcript.strip():
                log_event("VOICE INPUT EMPTY OR TIMED OUT")
                if not voice_interrupt_event.is_set():
                    stop_event.wait(0.5)
                continue

            transcript = transcript.strip()
            with state_lock:
                server_state["voice_event_id"] += 1
                event_id = server_state["voice_event_id"]
            update_state(
                last_transcript=transcript,
                last_response="",
                voice_response_id=0,
            )
            log_event("VOICE INPUT RECOGNIZED")

            response = process_with_lewis(transcript)
            update_state(
                last_response=response,
                voice_response_id=event_id,
            )
            log_event("VOICE RESPONSE GENERATED")

            state = get_state_snapshot()
            if (
                state["voice_enabled"]
                and VOICE_OUTPUT_AVAILABLE
                and not stop_event.is_set()
            ):
                _speak_session_text(response, stop_event)

    except Exception as error:
        print("LEWIS VOICE ERROR:", type(error).__name__)
        log_event("VOICE OPERATION FAILED")

        update_state(
            listening=False,
            speaking=False,
            last_error=(
                "Voice operation failed: "
                f"{type(error).__name__}. Check the server terminal."
            ),
        )

    finally:
        update_state(
            listening=False,
            speaking=False,
            voice_output_pending=False,
            voice_session_active=False,
            voice_session_stopping=False,
            push_to_talk_active=False,
            push_to_talk_processing=False,
        )
        voice_lock.release()


def start_voice_listening():
    if not VOICE_INPUT_AVAILABLE or listen_once is None:
        return False, "Voice input modules are unavailable."

    if not LEWIS_AVAILABLE or lewis is None:
        return False, "LEWIS Core is unavailable."

    if not voice_lock.acquire(blocking=False):
        return False, "A voice operation is already running."

    try:
        voice_stop_event.clear()
        voice_interrupt_event.clear()
        while True:
            try:
                pending_speech.get_nowait()
                pending_speech.task_done()
            except queue.Empty:
                break
        update_state(
            voice_session_active=True,
            voice_session_stopping=False,
            push_to_talk_active=False,
            push_to_talk_processing=False,
            listening=False,
            speaking=False,
            voice_output_pending=False,
            last_error="",
            last_transcript="",
            last_response="",
        )
        worker = threading.Thread(
            target=voice_worker,
            args=(voice_stop_event,),
            name="LEWIS-Voice-Worker",
            daemon=True,
        )
        worker.start()
        return True, "Voice session started."

    except Exception:
        voice_lock.release()
        update_state(
            listening=False,
            speaking=False,
            voice_session_active=False,
            voice_session_stopping=False,
            last_error="Could not start the voice worker.",
        )
        return False, "Could not start the voice worker."


def stop_voice_session():
    with state_lock:
        if not server_state["voice_session_active"]:
            return False
        voice_stop_event.set()
        server_state["voice_session_stopping"] = True
        server_state["activity"] = "STOPPING"

    voice_interrupt_event.set()
    _request_voice_output_stop()
    log_event("VOICE SESSION STOP REQUESTED")
    return True


def push_to_talk_worker(stop_event):
    try:
        log_event("PUSH-TO-TALK LISTENING STARTED")
        transcript = listen_once(
            stop_event=stop_event,
            on_capture_start=lambda: update_state(listening=True),
            return_on_silence=False,
        )
        transcript = transcript.strip() if transcript else ""
        update_state(
            listening=False,
            push_to_talk_active=False,
            push_to_talk_processing=True,
        )

        if not transcript:
            update_state(
                last_error="No speech was captured.",
                push_to_talk_processing=False,
            )
            log_event("PUSH-TO-TALK CAPTURE EMPTY")
            return

        with state_lock:
            server_state["voice_event_id"] += 1
            event_id = server_state["voice_event_id"]

        update_state(
            last_transcript=transcript,
            last_response="",
            voice_response_id=0,
            last_error="",
        )
        log_event("VOICE INPUT RECOGNIZED")

        response = process_with_lewis(transcript)
        update_state(
            last_response=response,
            voice_response_id=event_id,
        )
        log_event("VOICE RESPONSE GENERATED")

        state = get_state_snapshot()
        if state["voice_enabled"] and VOICE_OUTPUT_AVAILABLE:
            _speak_session_text(response, threading.Event())
    except Exception as error:
        print("LEWIS PUSH-TO-TALK ERROR:", type(error).__name__)
        log_event("PUSH-TO-TALK OPERATION FAILED")
        update_state(
            last_error=(
                "Push-to-talk failed: "
                f"{type(error).__name__}. Check the server terminal."
            )
        )
    finally:
        update_state(
            push_to_talk_active=False,
            push_to_talk_processing=False,
            listening=False,
            speaking=False,
            voice_output_pending=False,
        )
        voice_lock.release()


def start_push_to_talk():
    if not VOICE_INPUT_AVAILABLE or listen_once is None:
        return False, "Voice input modules are unavailable."

    if not LEWIS_AVAILABLE or lewis is None:
        return False, "LEWIS Core is unavailable."

    if not voice_lock.acquire(blocking=False):
        return False, "A voice operation is already running."

    try:
        push_to_talk_stop_event.clear()
        update_state(
            push_to_talk_active=True,
            push_to_talk_processing=False,
            voice_session_active=False,
            voice_session_stopping=False,
            listening=False,
            speaking=False,
            voice_output_pending=False,
            last_error="",
            last_transcript="",
            last_response="",
            voice_response_id=0,
        )
        worker = threading.Thread(
            target=push_to_talk_worker,
            args=(push_to_talk_stop_event,),
            name="LEWIS-Push-To-Talk-Worker",
            daemon=True,
        )
        worker.start()
        return True, "Push-to-talk capture started."
    except Exception:
        voice_lock.release()
        update_state(
            push_to_talk_active=False,
            listening=False,
            speaking=False,
            last_error="Could not start push-to-talk capture.",
        )
        return False, "Could not start push-to-talk capture."


def stop_push_to_talk():
    with state_lock:
        if not server_state["push_to_talk_active"]:
            return False
        push_to_talk_stop_event.set()

    update_state(
        push_to_talk_active=False,
        push_to_talk_processing=True,
    )
    log_event("PUSH-TO-TALK RELEASED")
    return True


# ---------------------------------------------------------
# HTTP REQUEST HANDLER
# ---------------------------------------------------------

class LewisHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        return

    # -----------------------------------------------------
    # GET
    # -----------------------------------------------------

    def do_GET(self):
        request = urlsplit(self.path)
        path = request.path
        query = parse_qs(request.query)

        if path == "/api/status":
            send_json(self, get_status())
            return

        if path == "/api/logs":
            send_json(self, {"logs": get_events()})
            return

        if path == "/api/conversations":
            conversations = list_conversations()
            send_json(
                self,
                {
                    "conversations": [
                        {
                            "id": item["id"],
                            "title": item["title"],
                            "updated_at": item["updated_at"],
                            "project": item.get("project"),
                            "folder": item.get("folder"),
                            "pinned": item.get("pinned", False),
                        }
                        for item in conversations
                    ],
                    "active_id": get_active_conversation_id(),
                },
            )
            return

        if path == "/api/conversations/search":
            search_term = query.get("q", [""])[0].strip()
            if not search_term:
                send_json(self, {"results": []})
                return
            if len(search_term) > 200:
                send_json(self, {"error": "Search text is too long."}, 400)
                return
            try:
                send_json(
                    self,
                    {"results": search_messages(search_term, limit=50)},
                )
            except Exception as error:
                print("LEWIS CONVERSATION SEARCH ERROR:", type(error).__name__)
                send_json(
                    self,
                    {"error": "Could not search conversation history."},
                    500,
                )
            return

        if path == "/api/memory":
            if not MEMORY_AVAILABLE:
                send_json(self, {"error": "Memory module is unavailable."}, 503)
                return
            search_term = query.get("q", [""])[0].strip().casefold()
            category = query.get("category", [""])[0].strip().casefold()
            if len(search_term) > 200:
                send_json(self, {"error": "Search text is too long."}, 400)
                return
            try:
                records = get_all_memories()
                categories = sorted({
                    str(item.get("category", "")).strip()
                    for item in records
                    if str(item.get("category", "")).strip()
                })
                filtered = [
                    item for item in records
                    if (not category or
                        str(item.get("category", "")).casefold() == category)
                    and (
                        not search_term or search_term in " ".join(
                            str(item.get(field, ""))
                            for field in (
                                "subject", "key", "predicate", "value",
                                "category", "status",
                            )
                        ).casefold()
                    )
                ]
                send_json(
                    self,
                    {
                        "memories": filtered,
                        "categories": categories,
                        "total": len(records),
                    },
                )
            except Exception as error:
                print("LEWIS MEMORY WORKSPACE ERROR:", type(error).__name__)
                send_json(
                    self,
                    {"error": "Could not read LEWIS memory."},
                    500,
                )
            return

        if path == "/api/memory/activity":
            send_json(
                self,
                {
                    "events": [
                        event for event in get_events()
                        if "MEMORY" in str(event.get("message", "")).upper()
                    ],
                    "scope": "current server session",
                },
            )
            return

        if path == "/api/projects":
            if not PROJECT_MEMORY_AVAILABLE:
                send_json(
                    self,
                    {"error": "Project memory is unavailable."},
                    503,
                )
                return
            search_term = query.get("q", [""])[0].strip().casefold()
            project_name = query.get("project", [""])[0].strip().casefold()
            if len(search_term) > 200:
                send_json(self, {"error": "Search text is too long."}, 400)
                return
            try:
                all_projects = list_project_memory()
                conversations_by_project = {}
                for conversation in list_conversations():
                    name = conversation.get("project")
                    if not isinstance(name, str) or not name.strip():
                        continue
                    conversations_by_project.setdefault(
                        name.casefold(),
                        {"name": name, "conversations": []},
                    )["conversations"].append({
                        "id": conversation["id"],
                        "title": conversation["title"],
                        "updated_at": conversation["updated_at"],
                    })

                projects_by_name = {
                    project["name"].casefold(): project
                    for project in all_projects
                }
                for name_key, linked in conversations_by_project.items():
                    project = projects_by_name.get(name_key)
                    if project is None:
                        project = {
                            "name": linked["name"],
                            "facts": [],
                            "updated_at": None,
                        }
                        all_projects.append(project)
                        projects_by_name[name_key] = project
                    project["conversations"] = linked["conversations"]

                project_names = [
                    project["name"] for project in all_projects
                ]
                projects = all_projects
                if project_name:
                    projects = [
                        project for project in projects
                        if project["name"].casefold() == project_name
                    ]
                for project in projects:
                    if search_term:
                        if search_term.casefold() not in project["name"].casefold():
                            project["facts"] = [
                                fact for fact in project["facts"]
                                if search_term in " ".join(
                                    str(fact.get(field, ""))
                                    for field in (
                                        "subject", "predicate", "value",
                                        "category", "status",
                                    )
                                ).casefold()
                            ]
                            project["conversations"] = [
                                conversation
                                for conversation in project.get("conversations", [])
                                if search_term in conversation["title"].casefold()
                            ]
                send_json(
                    self,
                    {
                        "projects": projects,
                        "project_names": project_names,
                    },
                )
            except Exception as error:
                print("LEWIS PROJECT MEMORY WORKSPACE ERROR:", type(error).__name__)
                send_json(
                    self,
                    {"error": "Could not read project memory."},
                    500,
                )
            return

        if path.startswith("/api/conversations/"):
            conversation_id = path[len("/api/conversations/"):]
            conversation = get_conversation(conversation_id)
            if conversation is None:
                send_json(self, {"error": "Conversation not found."}, 404)
            else:
                send_json(self, {"conversation": conversation})
            return

        if path in ("/", "/index.html"):
            self.serve_file(UI_DIR / "index.html", "text/html")
            return

        if path == "/style.css":
            self.serve_file(UI_DIR / "style.css", "text/css")
            return

        if path == "/app.js":
            self.serve_file(
                UI_DIR / "app.js",
                "application/javascript",
            )
            return

        if path == "/lewis-logo.svg":
            self.serve_file(UI_DIR / "lewis-logo.svg", "image/svg+xml")
            return

        send_json(self, {"error": "Not found"}, 404)

    # -----------------------------------------------------
    # POST
    # -----------------------------------------------------

    def do_POST(self):
        path = self.path.split("?", 1)[0]

        if path == "/api/chat":
            self.handle_chat()
            return

        if path == "/api/ai/model":
            self.handle_ai_model_selection()
            return

        if path == "/api/ai/test":
            self.handle_ai_connection_test()
            return

        if path == "/api/memory/update":
            self.handle_memory_update()
            return

        if path == "/api/conversations":
            self.handle_conversation_create()
            return

        if path == "/api/conversations/select":
            self.handle_conversation_select()
            return

        if path == "/api/conversations/rename":
            self.handle_conversation_rename()
            return

        if path == "/api/conversations/metadata":
            self.handle_conversation_metadata()
            return

        if path == "/api/conversations/delete":
            self.handle_conversation_delete()
            return

        if path == "/api/voice/listen":
            self.handle_voice_listen()
            return

        if path == "/api/voice/session/start":
            self.handle_voice_listen()
            return

        if path == "/api/voice/session/stop":
            self.handle_voice_session_stop()
            return

        if path == "/api/voice/ptt/start":
            self.handle_push_to_talk_start()
            return

        if path == "/api/voice/ptt/stop":
            self.handle_push_to_talk_stop()
            return

        if path == "/api/voice/speak":
            self.handle_voice_speak()
            return

        if path == "/api/voice/stop":
            self.handle_voice_stop()
            return

        if path == "/api/voice/settings":
            self.handle_voice_settings()
            return

        send_json(self, {"error": "Not found"}, 404)

    # -----------------------------------------------------
    # TEXT CHAT
    # -----------------------------------------------------

    def handle_memory_update(self):
        data = read_json_body(self)
        if data is None or not isinstance(data.get("updates"), dict):
            send_json(self, {"error": "Provide a memory ID and update fields."}, 400)
            return
        if not MEMORY_AVAILABLE:
            send_json(self, {"error": "Memory module is unavailable."}, 503)
            return

        memory_id = data.get("id")
        if not isinstance(memory_id, str) or not memory_id.strip():
            send_json(self, {"error": "Provide a valid memory ID."}, 400)
            return
        updates = data["updates"]
        allowed = {"subject", "key", "value", "category", "status", "importance"}
        if not updates or set(updates) - allowed:
            send_json(self, {"error": "The memory fields are invalid."}, 400)
            return

        try:
            record = update_memory(memory_id, updates)
        except MemoryValidationError as error:
            send_json(self, {"error": str(error)}, 400)
            return
        except MemoryNotFoundError:
            send_json(self, {"error": "Memory not found."}, 404)
            return
        except MemoryStorageError as error:
            print("LEWIS MEMORY UPDATE ERROR:", type(error).__name__)
            send_json(self, {"error": "Could not save this memory."}, 500)
            return
        except Exception as error:
            print("LEWIS MEMORY UPDATE ERROR:", type(error).__name__)
            send_json(self, {"error": "Could not save this memory."}, 500)
            return

        log_event("MEMORY UPDATED")
        send_json(self, {"memory": record})

    def handle_conversation_create(self):
        data = read_json_body(self)
        if data is None:
            send_json(self, {"error": "Invalid JSON."}, 400)
            return
        if not LEWIS_AVAILABLE or lewis is None:
            send_json(self, {"error": "LEWIS Core is unavailable."}, 503)
            return

        title = data.get("title", "New conversation")
        if not isinstance(title, str) or len(title.strip()) > 120:
            send_json(self, {"error": "Conversation title is invalid."}, 400)
            return

        try:
            conversation = create_conversation(
                title=title.strip() or "New conversation",
                project=lewis.active_project,
            )
            lewis.active_conversation_id = conversation["id"]
            send_json(self, {"conversation": conversation}, 201)
        except Exception as error:
            print("LEWIS CONVERSATION CREATE ERROR:", type(error).__name__)
            send_json(
                self,
                {"error": "Could not create a conversation."},
                500,
            )

    def handle_conversation_select(self):
        data = read_json_body(self)
        if data is None or not isinstance(data.get("id"), str):
            send_json(self, {"error": "Provide a conversation ID."}, 400)
            return
        if not LEWIS_AVAILABLE or lewis is None:
            send_json(self, {"error": "LEWIS Core is unavailable."}, 503)
            return

        conversation = get_conversation(data["id"])
        if conversation is None:
            send_json(self, {"error": "Conversation not found."}, 404)
            return

        try:
            set_active_conversation(conversation["id"])
            lewis.active_conversation_id = conversation["id"]
            lewis.active_project = conversation.get("project")
            send_json(self, {"conversation": conversation})
        except Exception as error:
            print("LEWIS CONVERSATION SELECT ERROR:", type(error).__name__)
            send_json(
                self,
                {"error": "Could not open the conversation."},
                500,
            )

    def handle_conversation_rename(self):
        data = read_json_body(self)

        if data is None:
            send_json(self, {"error": "Invalid JSON."}, 400)
            return

        conversation_id = data.get("id")
        title = data.get("title")

        if not isinstance(conversation_id, str) or not conversation_id.strip():
            send_json(self, {"error": "Provide a conversation ID."}, 400)
            return

        if (
            not isinstance(title, str)
            or not title.strip()
            or len(title.strip()) > 120
        ):
            send_json(
                self,
                {"error": "Title must contain 1–120 characters."},
                400,
            )
            return

        try:
            conversation = rename_conversation(
                conversation_id,
                title.strip(),
            )
            send_json(self, {"conversation": conversation})
        except ValueError:
            send_json(self, {"error": "Conversation not found."}, 404)
        except Exception as error:
            print("LEWIS CONVERSATION RENAME ERROR:", type(error).__name__)
            send_json(
                self,
                {"error": "Could not rename the conversation."},
                500,
            )

    def handle_conversation_metadata(self):
        data = read_json_body(self)
        if data is None or not isinstance(data.get("updates"), dict):
            send_json(self, {"error": "Provide a conversation ID and settings."}, 400)
            return

        conversation_id = data.get("id")
        updates = data["updates"]
        allowed = {"pinned", "folder", "project"}
        if (
            not isinstance(conversation_id, str)
            or not conversation_id.strip()
            or not updates
            or set(updates) - allowed
        ):
            send_json(self, {"error": "Conversation settings are invalid."}, 400)
            return

        if "pinned" in updates and not isinstance(updates["pinned"], bool):
            send_json(self, {"error": "Pinned must be true or false."}, 400)
            return

        for field, limit in (("folder", 80), ("project", 120)):
            value = updates.get(field)
            if field not in updates or (field == "project" and value is None):
                continue
            if not isinstance(value, str) or len(value.strip()) > limit:
                send_json(
                    self,
                    {"error": f"{field.capitalize()} must be at most {limit} characters."},
                    400,
                )
                return

        try:
            conversation = update_conversation_metadata(
                conversation_id,
                updates,
            )
            if (
                LEWIS_AVAILABLE
                and lewis is not None
                and get_active_conversation_id() == conversation_id
                and "project" in updates
            ):
                lewis.active_project = conversation.get("project")
            send_json(self, {"conversation": conversation})
        except ValueError as error:
            if str(error).startswith("Could not find conversation"):
                send_json(self, {"error": "Conversation not found."}, 404)
                return
            send_json(self, {"error": str(error)}, 400)
        except Exception as error:
            print("LEWIS CONVERSATION ORGANIZATION ERROR:", type(error).__name__)
            send_json(
                self,
                {"error": "Could not update conversation settings."},
                500,
            )

    def handle_conversation_delete(self):
        data = read_json_body(self)

        if data is None:
            send_json(self, {"error": "Invalid JSON."}, 400)
            return

        conversation_id = data.get("id")

        if not isinstance(conversation_id, str) or not conversation_id.strip():
            send_json(self, {"error": "Provide a conversation ID."}, 400)
            return

        if not LEWIS_AVAILABLE or lewis is None:
            send_json(self, {"error": "LEWIS Core is unavailable."}, 503)
            return

        try:
            result = delete_conversation(conversation_id)
            active_id = result["active_conversation_id"]

            lewis.active_conversation_id = active_id

            if active_id:
                active_conversation = get_conversation(active_id)
                lewis.active_project = (
                    active_conversation.get("project")
                    if active_conversation
                    else None
                )
            else:
                lewis.active_project = None

            send_json(self, result)
        except ValueError:
            send_json(self, {"error": "Conversation not found."}, 404)
        except Exception as error:
            print("LEWIS CONVERSATION DELETE ERROR:", type(error).__name__)
            send_json(
                self,
                {"error": "Could not delete the conversation."},
                500,
            )

    def handle_ai_model_selection(self):
        data = read_json_body(self)

        if data is None:
            send_json(self, {"error": "Invalid JSON."}, 400)
            return

        if not AI_AVAILABLE:
            send_json(self, {"error": "AI module is unavailable."}, 503)
            return

        try:
            selection = ai.model.set_ai_selection(
                data.get("provider"),
                data.get("model"),
            )
        except ValueError as error:
            send_json(self, {"error": str(error)}, 400)
            return

        log_event(
            "AI MODEL SELECTED - "
            f"{selection['provider']} / {selection['model']}"
        )
        send_json(self, {"selection": selection})

    def handle_ai_connection_test(self):
        if not AI_AVAILABLE:
            send_json(self, {"error": "AI module is unavailable."}, 503)
            return
        if not core_lock.acquire(blocking=False):
            send_json(
                self,
                {"error": "Wait for the current LEWIS request before testing the provider."},
                409,
            )
            return

        try:
            state = get_state_snapshot()
            if (
                state["voice_session_active"]
                or state["push_to_talk_active"]
                or state["push_to_talk_processing"]
            ):
                send_json(
                    self,
                    {"error": "Stop voice interaction before testing the provider."},
                    409,
                )
                return

            update_state(processing=True)
            log_event("AI PROVIDER TEST STARTED")
            try:
                result = ai.model.test_ai_connection()
            except Exception as error:
                print("LEWIS AI PROVIDER TEST ERROR:", type(error).__name__)
                log_event("AI PROVIDER TEST FAILED")
                send_json(
                    self,
                    {
                        "error": (
                            "The provider test failed. Check the server "
                            "terminal for the failure type."
                        )
                    },
                    502,
                )
                return
            finally:
                update_state(processing=False)

            log_event("AI PROVIDER TEST SUCCEEDED")
            send_json(
                self,
                {
                    "ok": True,
                    "provider": result["provider"],
                    "model": result["model"],
                },
            )
        finally:
            core_lock.release()

    def handle_chat(self):
        data = read_json_body(self)

        if data is None:
            send_json(self, {"error": "Invalid JSON."}, 400)
            return

        user_input = data.get("message", "")

        if not isinstance(user_input, str):
            send_json(self, {"error": "Message must be text."}, 400)
            return

        user_input = user_input.strip()

        if not user_input:
            send_json(self, {"error": "Message cannot be empty."}, 400)
            return

        if len(user_input) > 10_000:
            send_json(self, {"error": "Message is too long."}, 400)
            return

        if not LEWIS_AVAILABLE or lewis is None:
            send_json(
                self,
                {"error": "LEWIS Core is unavailable."},
                503,
            )
            return

        log_event("USER INPUT RECEIVED")
        log_event("REQUEST PROCESSING")

        try:
            response = process_with_lewis(user_input)

        except Exception as error:
            print("LEWIS PROCESS ERROR:", type(error).__name__)
            log_event("LEWIS PROCESS FAILED")

            send_json(
                self,
                {"error": "LEWIS Core encountered an internal error."},
                500,
            )
            return

        log_event("LEWIS PROCESS COMPLETED")
        send_json(self, {"response": response})
        log_event("RESPONSE DELIVERED")

    # -----------------------------------------------------
    # START VOICE LISTENING
    # -----------------------------------------------------

    def handle_voice_listen(self):
        success, message = start_voice_listening()

        if not success:
            send_json(self, {"error": message}, 409)
            return

        send_json(
            self,
            {
                "message": message,
                "activity": get_state_snapshot()["activity"],
                "voice_session_active": True,
            },
            202,
        )

    def handle_push_to_talk_start(self):
        success, message = start_push_to_talk()

        if not success:
            send_json(self, {"error": message}, 409)
            return

        send_json(
            self,
            {
                "message": message,
                "push_to_talk_active": get_state_snapshot()[
                    "push_to_talk_active"
                ],
            },
            202,
        )

    def handle_push_to_talk_stop(self):
        if not stop_push_to_talk():
            send_json(
                self,
                {
                    "message": "Push-to-talk capture has already ended.",
                    "push_to_talk_active": False,
                },
            )
            return

        send_json(
            self,
            {
                "message": "Push-to-talk released; finalizing captured speech.",
                "push_to_talk_active": False,
            },
            202,
        )

    def handle_voice_session_stop(self):
        if not VOICE_INPUT_AVAILABLE:
            send_json(
                self,
                {"error": "Voice input modules are unavailable."},
                503,
            )
            return

        state = get_state_snapshot()
        speech_was_active = (
            state["speaking"] or state["voice_output_pending"]
        )

        if not stop_voice_session():
            send_json(
                self,
                {
                    "message": "No voice session is running.",
                    "activity": get_state_snapshot()["activity"],
                    "voice_session_active": False,
                },
            )
            return

        send_json(
            self,
            {
                "message": "Voice session stopping.",
                "activity": "STOPPING",
                "voice_session_active": True,
                "speech_stop_requested": speech_was_active,
            },
            202,
        )

    # -----------------------------------------------------
    # SPEAK TEXT THROUGH LEWIS VOICE
    # -----------------------------------------------------

    def handle_voice_speak(self):
        data = read_json_body(self)

        if data is None:
            send_json(self, {"error": "Invalid JSON."}, 400)
            return

        text = data.get("text", "")

        if not isinstance(text, str) or not text.strip():
            send_json(self, {"error": "Text cannot be empty."}, 400)
            return

        text = text.strip()

        if len(text) > 10_000:
            send_json(self, {"error": "Text is too long."}, 400)
            return

        if not VOICE_OUTPUT_AVAILABLE:
            send_json(
                self,
                {"error": "Voice output modules are unavailable."},
                503,
            )
            return

        state = get_state_snapshot()

        if not state["voice_enabled"]:
            send_json(self, {"error": "Voice output is disabled."}, 409)
            return

        if state["voice_session_active"]:
            if state["voice_session_stopping"]:
                send_json(
                    self,
                    {"error": "The voice session is stopping."},
                    409,
                )
                return

            try:
                pending_speech.put_nowait(text)
            except queue.Full:
                send_json(
                    self,
                    {"error": "The voice response queue is full."},
                    429,
                )
                return

            voice_interrupt_event.set()
            send_json(
                self,
                {
                    "message": "Speech response queued for the voice session.",
                    "queued": True,
                },
                202,
            )
            return

        # A live microphone or output operation owns the voice device.
        if (
            state["speaking"] or
            state["voice_output_pending"] or
            state["listening"]
        ):
            send_json(
                self,
                {"error": "A voice operation is already running."},
                409,
            )
            return

        if not voice_lock.acquire(blocking=False):
            send_json(
                self,
                {"error": "A voice operation is already running."},
                409,
            )
            return

        speech_cancel_event = threading.Event()
        _set_active_voice_output_cancel_event(speech_cancel_event)

        def speech_worker():
            def playback_started():
                update_state(
                    processing=False,
                    speaking=True,
                    voice_output_pending=False,
                )
                log_event("VOICE OUTPUT STARTED")

            try:
                update_state(
                    processing=True,
                    speaking=False,
                    voice_output_pending=True,
                    last_error="",
                )
                completed = speak(
                    text,
                    cancel_event=speech_cancel_event,
                    on_playback_start=playback_started,
                )
                if not completed and not was_stop_requested():
                    update_state(
                        last_error="Speech output could not be completed."
                    )
                    log_event("VOICE OUTPUT FAILED")

            except Exception as error:
                print("LEWIS SPEECH ERROR:", type(error).__name__)
                update_state(
                    last_error=(
                        "Speech output failed: "
                        f"{type(error).__name__}."
                    ),
                )

            finally:
                _clear_active_voice_output_cancel_event(speech_cancel_event)
                update_state(
                    processing=False,
                    speaking=False,
                    voice_output_pending=False,
                )

        update_state(
            processing=True,
            speaking=False,
            voice_output_pending=True,
            last_error="",
        )

        def reserved_speech_worker():
            try:
                speech_worker()
            finally:
                voice_lock.release()

        try:
            threading.Thread(
                target=reserved_speech_worker,
                name="LEWIS-Speech-Worker",
                daemon=True,
            ).start()
        except Exception:
            voice_lock.release()
            _clear_active_voice_output_cancel_event(speech_cancel_event)
            update_state(
                processing=False,
                speaking=False,
                voice_output_pending=False,
            )
            send_json(
                self,
                {"error": "Could not start speech output."},
                500,
            )
            return

        send_json(self, {"message": "Speech output started."}, 202)

    # -----------------------------------------------------
    # STOP SPEECH OUTPUT
    # -----------------------------------------------------

    def handle_voice_stop(self):
        if not VOICE_OUTPUT_AVAILABLE:
            send_json(
                self,
                {"error": "Voice output modules are unavailable."},
                503,
            )
            return

        try:
            state = get_state_snapshot()
            speech_was_active = (
                state["speaking"] or state["voice_output_pending"]
            )
            _request_voice_output_stop()
            send_json(
                self,
                {
                    "message": (
                        "Speech stop requested."
                        if speech_was_active
                        else "No speech was active."
                    ),
                    "speech_stop_requested": speech_was_active,
                },
            )
        except Exception as error:
            print("LEWIS STOP SPEECH ERROR:", type(error).__name__)
            send_json(self, {"error": "Could not stop speech output."}, 500)

    # -----------------------------------------------------
    # VOICE SETTINGS
    # -----------------------------------------------------

    def handle_voice_settings(self):
        data = read_json_body(self)

        if data is None or not isinstance(data.get("enabled"), bool):
            send_json(
                self,
                {"error": "Provide an 'enabled' boolean."},
                400,
            )
            return

        update_state(voice_enabled=data["enabled"])

        log_event(
            "VOICE OUTPUT ENABLED"
            if data["enabled"]
            else "VOICE OUTPUT DISABLED"
        )

        send_json(
            self,
            {"voice_enabled": data["enabled"]},
        )

    # -----------------------------------------------------
    # STATIC FILES
    # -----------------------------------------------------

    def serve_file(self, path, content_type):
        if not path.exists():
            send_json(self, {"error": "File not found."}, 404)
            return

        content = path.read_bytes()

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()

        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass


# ---------------------------------------------------------
# START SERVER
# ---------------------------------------------------------

def main():
    log_event("LEWIS HUD SERVER INITIALIZED")

    if LEWIS_AVAILABLE and lewis:
        log_event("LEWIS CORE CONNECTED")
    else:
        log_event("LEWIS CORE UNAVAILABLE")

    log_event(
        "MEMORY MODULE CONNECTED"
        if MEMORY_AVAILABLE
        else "MEMORY MODULE UNAVAILABLE"
    )

    log_event(
        "AI MODULE DETECTED"
        if AI_AVAILABLE
        else "AI MODULE UNAVAILABLE"
    )

    log_event(
        "VOICE INPUT CONNECTED"
        if VOICE_INPUT_AVAILABLE
        else "VOICE INPUT UNAVAILABLE"
    )
    log_event(
        "VOICE OUTPUT CONNECTED"
        if VOICE_OUTPUT_AVAILABLE
        else "VOICE OUTPUT UNAVAILABLE"
    )

    log_event("SYSTEM TELEMETRY ONLINE")

    server = ThreadingHTTPServer(
        ("127.0.0.1", 8000),
        LewisHandler,
    )

    print()
    print("========================================")
    print("           LEWIS HUD SERVER")
    print("========================================")
    print()
    print("LEWIS HUD ONLINE")
    print("Open: http://127.0.0.1:8000")
    print("Press CTRL+C to shut down.")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print("LEWIS HUD SERVER OFFLINE")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()