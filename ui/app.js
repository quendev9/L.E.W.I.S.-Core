const input = document.getElementById("commandInput");
const sendButton = document.getElementById("sendButton");
const messages = document.getElementById("messages");
const hud = document.querySelector(".hud");
const expandChatButton = document.getElementById("expandChatButton");
const openFocusHistoryButton =
    document.getElementById("openFocusHistoryButton");
const coreOrb = document.getElementById("coreOrb");
const voiceCard = document.querySelector(".voice-card");

const voiceSessionStartButton = document.getElementById("voiceSessionStart");
const voiceSessionStopButton = document.getElementById("voiceSessionStop");
const pushToTalkButton = document.getElementById("pushToTalkButton");
const voiceSessionToggleButtons =
    document.querySelectorAll("[data-voice-toggle]");
const quickVoiceSessionButton =
    document.querySelector(".action-card[data-voice-toggle]");
const voiceToggle = document.getElementById("voiceToggle");
const stopSpeakingButton = document.getElementById("stopSpeakingButton");
const conversationState = document.querySelector(".conversation-state");
const toggleFocusModeButton = document.getElementById("toggleFocusMode");
const toggleThemeButton = document.getElementById("toggleTheme");
const toggleLeftPanelButton = document.getElementById("toggleLeftPanel");
const toggleRightPanelButton = document.getElementById("toggleRightPanel");
const toggleSidePanelsButton = document.getElementById("toggleSidePanels");
const aiModelSelect = document.getElementById("aiModelSelect");
const applyAIModelButton = document.getElementById("applyAIModelButton");
const aiModelSelectionStatus = document.getElementById("aiModelSelectionStatus");

// Existing NEW button stays in the conversation header.
const newConversationButton = document.getElementById("newConversationButton");

// Conversation drawer elements.
const conversationDrawer = document.getElementById("conversationDrawer");
const conversationDrawerBackdrop = document.getElementById("conversationDrawerBackdrop");
const conversationList = document.getElementById("conversationList");
const conversationCount = document.getElementById("conversationCount");
const conversationDrawerStatus = document.getElementById("conversationDrawerStatus");
const closeConversationDrawerButton = document.getElementById("closeConversationDrawerButton");
const conversationNavLink = document.querySelector('.nav-item[href="#conversation"]');
const conversationSearchInput = document.getElementById("conversationSearchInput");
const workspaceView = document.getElementById("workspaceView");
const workspaceBackdrop = document.getElementById("workspaceBackdrop");
const workspaceContent = document.getElementById("workspaceContent");
const workspaceTitle = document.getElementById("workspaceTitle");
const workspaceDescription = document.getElementById("workspaceDescription");
const workspaceStatus = document.getElementById("workspaceStatus");
const closeWorkspaceButton = document.getElementById("closeWorkspaceButton");

// ==================================================
// HUD STATE
// ==================================================

let requestInProgress = false;
let voiceEnabled = true;
let voiceAvailable = false;
let voiceOutputAvailable = false;
let voiceOutputPending = false;
let voiceControlRequestInProgress = false;
let voiceSessionOperation = null;
let voiceSessionActive = false;
let voiceSessionStopping = false;
let pushToTalkActive = false;
let pushToTalkProcessing = false;
let pushToTalkPressed = false;
let pushToTalkPointerId = null;
let pushToTalkOperationInProgress = false;
let voiceSpeaking = false;
let speechStopPending = false;
let coreProcessing = false;
let statusRequestId = 0;
let chatRequestId = 0;
let aiModelSelectionDirty = false;
let aiModelSelectionSaving = false;
let lastVoiceEventId = 0;
let lastVoiceResponseId = 0;
let taskStartedAt = null;
let activeConversationId = null;
let hasActiveProjectContext = false;
let lastActivityState = "READY";
let conversationListReady = false;
let conversationActionInProgress = false;
let conversationDrawerOpen = false;
let conversationRequestId = 0;
let conversationListRequestId = 0;
let conversationDrawerReturnFocus = null;
let conversationSearchRequestId = 0;
let conversationSearchTimer = null;
let workspaceRequestId = 0;
let workspaceSearchTimer = null;
let activeWorkspaceName = null;
let workspaceReturnFocus = null;
let focusModePanelState = hud?.classList.contains("focus-mode")
    ? {
        leftCollapsed: hud.classList.contains("left-panel-collapsed"),
        rightCollapsed: hud.classList.contains("right-panel-collapsed")
    }
    : null;
const HUD_PREFERENCES_KEY = "lewis-hud-preferences";
let hudPreferences = {
    orbMotion: true,
    soundPreviewEnabled: false,
    soundMuted: false,
    soundVolume: 35,
    soundProfile: "soft"
};
let interfaceAudioContext = null;

// ==================================================
// MESSAGE SYSTEM
// ==================================================

function appendInlineMarkdown(parent, source) {
    const tokenPattern = /(`[^`\n]+`|\*\*[^*]+\*\*|__[^_]+__|~~[^~]+~~|\*[^*\n]+\*|_[^_\n]+_|\[[^\]]+\]\([^)]+\))/g;
    let cursor = 0;

    for (const match of source.matchAll(tokenPattern)) {
        parent.appendChild(document.createTextNode(source.slice(cursor, match.index)));

        const token = match[0];
        let element;

        if (token.startsWith("`")) {
            element = document.createElement("code");
            element.textContent = token.slice(1, -1);
        } else if (token.startsWith("**") || token.startsWith("__")) {
            element = document.createElement("strong");
            appendInlineMarkdown(element, token.slice(2, -2));
        } else if (token.startsWith("~~")) {
            element = document.createElement("del");
            appendInlineMarkdown(element, token.slice(2, -2));
        } else if (token.startsWith("*") || token.startsWith("_")) {
            element = document.createElement("em");
            appendInlineMarkdown(element, token.slice(1, -1));
        } else {
            const link = token.match(/^\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)$/);
            let destination = null;

            try {
                if (link) destination = new URL(link[2], window.location.href);
            } catch {
                destination = null;
            }

            if (
                !link ||
                !destination ||
                !["https:", "http:", "mailto:"].includes(destination.protocol)
            ) {
                parent.appendChild(document.createTextNode(token));
                cursor = match.index + token.length;
                continue;
            }

            element = document.createElement("a");
            element.href = destination.href;
            element.target = "_blank";
            element.rel = "noopener noreferrer";
            appendInlineMarkdown(element, link[1]);
        }

        parent.appendChild(element);
        cursor = match.index + token.length;
    }

    parent.appendChild(document.createTextNode(source.slice(cursor)));
}

function renderMarkdown(target, value) {
    const lines = String(value ?? "").replace(/\r\n?/g, "\n").split("\n");
    let index = 0;

    while (index < lines.length) {
        if (!lines[index].trim()) {
            index += 1;
            continue;
        }

        const fence = lines[index].match(/^\s*```(?:[\w+-]+)?\s*$/);

        if (fence) {
            index += 1;
            const codeLines = [];

            while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) {
                codeLines.push(lines[index]);
                index += 1;
            }

            if (index < lines.length) index += 1;

            const pre = document.createElement("pre");
            const code = document.createElement("code");
            code.textContent = codeLines.join("\n");
            pre.appendChild(code);
            target.appendChild(pre);
            continue;
        }

        const heading = lines[index].match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);

        if (heading) {
            const element = document.createElement(`h${Math.min(4, heading[1].length + 1)}`);
            appendInlineMarkdown(element, heading[2]);
            target.appendChild(element);
            index += 1;
            continue;
        }

        const listItem = lines[index].match(/^\s*(?:[-*+]\s+|\d+[.)]\s+)(.+)$/);

        if (listItem) {
            const ordered = /^\s*\d+[.)]/.test(lines[index]);
            const list = document.createElement(ordered ? "ol" : "ul");

            while (index < lines.length) {
                const item = lines[index].match(/^\s*(?:[-*+]\s+|\d+[.)]\s+)(.+)$/);

                if (!item || /^\s*\d+[.)]/.test(lines[index]) !== ordered) break;

                const li = document.createElement("li");
                appendInlineMarkdown(li, item[1]);
                list.appendChild(li);
                index += 1;
            }

            target.appendChild(list);
            continue;
        }

        if (/^\s*>\s?/.test(lines[index])) {
            const quote = document.createElement("blockquote");

            while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
                const paragraph = document.createElement("p");
                appendInlineMarkdown(paragraph, lines[index].replace(/^\s*>\s?/, ""));
                quote.appendChild(paragraph);
                index += 1;
            }

            target.appendChild(quote);
            continue;
        }

        const paragraph = document.createElement("p");
        const paragraphLines = [];

        while (
            index < lines.length &&
            lines[index].trim() &&
            !/^\s{0,3}(?:#{1,6}\s|```)/.test(lines[index]) &&
            !/^\s*(?:[-*+]\s+|\d+[.)]\s+|>)/.test(lines[index])
        ) {
            paragraphLines.push(lines[index]);
            index += 1;
        }

        appendInlineMarkdown(paragraph, paragraphLines.join(" "));
        target.appendChild(paragraph);
    }
}

function addMessage(sender, text) {
    if (!messages) return;

    // Remove the empty-state message when the first real message arrives.
    messages.querySelector(".empty-conversation")?.remove();

    const message = document.createElement("div");
    message.className = "message";

    const senderElement = document.createElement("div");
    senderElement.className = "message-label";
    senderElement.textContent = sender;

    const textElement = document.createElement("div");
    textElement.className = "message-text";
    renderMarkdown(textElement, text);

    message.append(senderElement, textElement);
    messages.appendChild(message);
    messages.scrollTop = messages.scrollHeight;
    syncFocusTranscriptSizing();
}

function showEmptyConversation() {
    if (!messages) return;

    updateActiveProject(null);
    messages.replaceChildren();

    const empty = document.createElement("p");
    empty.className = "empty-conversation";
    empty.textContent = "No messages yet. Start a conversation below.";
    messages.appendChild(empty);
    syncFocusTranscriptSizing();
}

function updateActiveProject(project) {
    const activeProject =
        typeof project === "string" && project.trim() ? project.trim() : null;

    hasActiveProjectContext = Boolean(activeProject);
    setText("activeProjectName", activeProject || "No project linked");
    setText(
        "activeProjectDetail",
        activeProject
            ? "Linked to this conversation."
            : "This conversation has no project context."
    );
    setText("activeProjectTop", activeProject || "No project");
    updateAdaptiveHudContext();
}

function updateAdaptiveHudContext() {
    if (!hud) return;

    if (hud.classList.contains("focus-mode")) {
        hud.dataset.context = "focus";
        return;
    }

    const orbState = coreOrb?.dataset.state || "idle";
    const activity = String(lastActivityState || "").toUpperCase();
    const voiceActive =
        voiceSessionActive ||
        pushToTalkActive ||
        pushToTalkProcessing ||
        voiceSpeaking ||
        voiceOutputPending ||
        ["listening", "speaking", "interrupting"].includes(orbState);
    const toolActivity =
        activity.includes("TOOL") &&
        ["EXECUTION", "RUNNING", "FAILED", "ERROR", "COMPLETE"].some(
            (state) => activity.includes(state)
        );
    const systemMonitoring =
        activity.includes("MONITOR") ||
        activity.includes("DIAGNOSTIC") ||
        !hud.classList.contains("right-panel-collapsed");

    const context = voiceActive
        ? "voice"
        : toolActivity || orbState === "tool-execution"
            ? "tool-execution"
            : requestInProgress || coreProcessing || orbState === "thinking"
                ? "processing"
                : systemMonitoring
                    ? "system-monitoring"
                    : hasActiveProjectContext
                    ? "project"
                    : "casual";
    hud.dataset.context = context;
}

function syncFocusTranscriptSizing() {
    if (!hud || !messages) return;
    hud.classList.toggle(
        "focus-transcript-expanded",
        hud.classList.contains("focus-mode") &&
            messages.querySelectorAll(".message").length > 6
    );
}

function formatUptime(seconds) {
    if (typeof seconds !== "number" || !Number.isFinite(seconds)) {
        return "Unavailable";
    }

    const totalSeconds = Math.max(0, Math.floor(seconds));
    const days = Math.floor(totalSeconds / 86_400);
    const hours = Math.floor((totalSeconds % 86_400) / 3_600);
    const minutes = Math.floor((totalSeconds % 3_600) / 60);

    return days
        ? `${days}d ${hours}h`
        : hours
            ? `${hours}h ${minutes}m`
            : `${minutes}m`;
}

function setConversationState(state) {
    if (conversationState) {
        conversationState.textContent = String(state).toUpperCase();
        conversationState.dataset.state = String(state).toLowerCase();
    }

    setText("conversationStatus", String(state).toUpperCase());
}

function updateClock() {
    const clock = document.getElementById("systemClock");
    if (!clock) return;

    const now = new Date();

    clock.replaceChildren(
        document.createTextNode(
            now.toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit"
            })
        )
    );

    const date = document.createElement("small");
    date.textContent = now.toLocaleDateString([], {
        month: "short",
        day: "numeric",
        year: "numeric"
    });

    clock.appendChild(date);
}

function setOrbState(state) {
    if (!coreOrb) return;

    coreOrb.dataset.state = state;
    updateAdaptiveHudContext();

    const label = document.getElementById("orbStatusLabel");
    const labels = {
        idle: "STANDBY",
        listening: "LISTENING",
        thinking: "PROCESSING",
        speaking: "SPEAKING",
        interrupting: "INTERRUPTING",
        "tool-execution": "TOOL EXECUTION"
    };

    coreOrb.setAttribute(
        "aria-label",
        `LEWIS assistant ${labels[state] || labels.idle}`
    );

    if (label) label.textContent = labels[state] || labels.idle;
}

// ==================================================
// API HELPER
// ==================================================

async function apiRequest(url, options = {}) {
    const response = await fetch(url, {
        cache: "no-store",
        ...options,
        headers: {
            ...(options.body ? { "Content-Type": "application/json" } : {}),
            ...(options.headers || {})
        }
    });

    let data;

    try {
        data = await response.json();
    } catch {
        data = {};
    }

    if (!response.ok) {
        throw new Error(data.error || `Request failed (${response.status})`);
    }

    return data;
}

function syncConversationControls() {
    const voiceCaptureBusy =
        voiceSessionActive ||
        pushToTalkActive ||
        pushToTalkProcessing ||
        pushToTalkPressed ||
        pushToTalkOperationInProgress;
    const busy =
        requestInProgress ||
        coreProcessing ||
        voiceCaptureBusy ||
        Boolean(voiceSessionOperation) ||
        conversationActionInProgress;

    if (input) {
        input.disabled = voiceCaptureBusy;
    }

    if (sendButton) {
        sendButton.disabled = requestInProgress || voiceCaptureBusy;
    }

    if (newConversationButton) {
        newConversationButton.disabled = busy || !conversationListReady;
    }

    if (conversationDrawer) {
        conversationDrawer.setAttribute(
            "aria-busy",
            String(conversationActionInProgress)
        );
    }

    conversationList?.querySelectorAll(
        ".conversation-list-open, .conversation-rename-button, " +
        ".conversation-delete-button, .conversation-pin-button, " +
        ".conversation-organize-button, .conversation-rename-input, " +
        ".conversation-rename-save, .conversation-rename-cancel"
    ).forEach((control) => {
        control.disabled = busy;
    });
}

function setConversationDrawerStatus(message, isError = false) {
    if (!conversationDrawerStatus) return;

    conversationDrawerStatus.textContent = message || "";
    conversationDrawerStatus.dataset.state = isError ? "error" : "normal";
}

function openConversationDrawer() {
    if (!conversationDrawer) {
        // The drawer markup has not been added yet.
        addMessage("SYSTEM", "The conversation drawer is not present in ui/index.html yet.");
        return;
    }

    conversationDrawerReturnFocus = document.activeElement;
    if (conversationSearchInput) {
        conversationSearchInput.value = "";
    }
    conversationSearchRequestId += 1;
    conversationDrawerOpen = true;
    conversationDrawer.hidden = false;
    conversationDrawer.setAttribute("aria-hidden", "false");
    conversationDrawer.removeAttribute("inert");

    if (conversationDrawerBackdrop) {
        conversationDrawerBackdrop.hidden = false;
    }

    document.body.classList.add("conversation-drawer-open");

    if (conversationNavLink) {
        conversationNavLink.setAttribute("aria-expanded", "true");
    }

    setConversationDrawerStatus("");
    closeConversationDrawerButton?.focus();

    refreshConversationList(activeConversationId).catch((error) => {
        console.error("LEWIS CONVERSATION LIST ERROR:", error);
        setConversationDrawerStatus(
            `Could not load conversations: ${error.message}`,
            true
        );
    });
}

function closeConversationDrawer() {
    conversationDrawerOpen = false;

    if (conversationDrawer) {
        conversationDrawer.hidden = true;
        conversationDrawer.setAttribute("aria-hidden", "true");
        conversationDrawer.setAttribute("inert", "");
    }

    if (conversationDrawerBackdrop) {
        conversationDrawerBackdrop.hidden = true;
    }

    document.body.classList.remove("conversation-drawer-open");

    if (conversationNavLink) {
        conversationNavLink.setAttribute("aria-expanded", "false");
    }

    const returnFocus = conversationDrawerReturnFocus;
    conversationDrawerReturnFocus = null;
    if (returnFocus instanceof HTMLElement && returnFocus.isConnected) {
        returnFocus.focus();
    } else {
        conversationNavLink?.focus();
    }
}

function displayConversation(conversation) {
    if (!conversation || typeof conversation.id !== "string") return;

    activeConversationId = conversation.id;
    updateActiveProject(conversation.project);

    if (!messages) return;

    messages.replaceChildren();

    const history = Array.isArray(conversation.messages)
        ? conversation.messages
        : [];

    if (!history.length) {
        showEmptyConversation();
    } else {
        history.forEach((entry) => {
            const role = String(entry.role || "").toLowerCase();
            const sender =
                role === "user" ? "YOU" :
                role === "assistant" ? "LEWIS" :
                "SYSTEM";

            addMessage(sender, entry.content || "");
        });
    }

    renderConversationListActiveState();
}

function createConversationListItem(conversation) {
    const item = document.createElement("article");
    item.className = "conversation-list-item";

    const mainButton = document.createElement("button");
    mainButton.type = "button";
    mainButton.className = "conversation-list-open";
    mainButton.dataset.conversationId = conversation.id;

    const title = document.createElement("span");
    title.className = "conversation-list-title";
    title.textContent = conversation.title || "New conversation";

    const metadata = document.createElement("small");
    metadata.className = "conversation-list-meta";

    const updatedAt = conversation.updated_at
        ? new Date(conversation.updated_at)
        : null;

    const updatedLabel =
        updatedAt && !Number.isNaN(updatedAt.getTime())
            ? updatedAt.toLocaleString([], {
                month: "short",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit"
            })
            : "Saved conversation";
    metadata.textContent = [
        conversation.pinned ? "PINNED" : "",
        conversation.folder || "",
        conversation.project || "",
        updatedLabel
    ].filter(Boolean).join(" · ");

    mainButton.append(title, metadata);
    mainButton.addEventListener("click", () => {
        selectConversationFromDrawer(conversation.id);
    });

    const actions = document.createElement("div");
    actions.className = "conversation-list-actions";

    const pinButton = document.createElement("button");
    pinButton.type = "button";
    pinButton.className = "conversation-pin-button";
    pinButton.textContent = conversation.pinned ? "UNPIN" : "PIN";
    pinButton.setAttribute(
        "aria-label",
        `${conversation.pinned ? "Unpin" : "Pin"} ${title.textContent}`
    );
    pinButton.addEventListener("click", () => {
        saveConversationMetadata(conversation, {
            pinned: !conversation.pinned
        });
    });

    const organizeButton = document.createElement("button");
    organizeButton.type = "button";
    organizeButton.className = "conversation-organize-button";
    organizeButton.textContent = "ORGANIZE";
    organizeButton.setAttribute(
        "aria-label",
        `Organize ${title.textContent}`
    );
    organizeButton.addEventListener("click", () => {
        openConversationOrganizationEditor(
            conversation,
            item,
            mainButton,
            actions
        );
    });

    const renameButton = document.createElement("button");
    renameButton.type = "button";
    renameButton.className = "conversation-rename-button";
    renameButton.textContent = "RENAME";
    renameButton.title = `Rename ${title.textContent}`;
    renameButton.addEventListener("click", () => {
        openConversationRenameEditor(conversation, item, mainButton, actions);
    });

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "conversation-delete-button";
    deleteButton.textContent = "DELETE";
    deleteButton.title = `Delete ${title.textContent}`;
    deleteButton.addEventListener("click", () => {
        deleteConversationFromDrawer(conversation);
    });

    actions.append(pinButton, organizeButton, renameButton, deleteButton);
    item.append(mainButton, actions);

    if (conversation.id === activeConversationId) {
        item.classList.add("active");
        mainButton.setAttribute("aria-current", "true");
    }

    return item;
}

function renderConversationList(conversations) {
    if (!conversationList) return;

    if (conversationCount) {
        conversationCount.textContent = `${conversations.length} SAVED`;
    }

    conversationList.replaceChildren();

    if (!conversations.length) {
        const empty = document.createElement("p");
        empty.className = "conversation-list-empty";
        empty.textContent = "No saved conversations yet.";
        conversationList.appendChild(empty);
        return;
    }

    conversations.forEach((conversation) => {
        conversationList.appendChild(createConversationListItem(conversation));
    });
}

function renderConversationListActiveState() {
    if (!conversationList) return;

    conversationList.querySelectorAll(".conversation-list-item").forEach((item) => {
        const button = item.querySelector(".conversation-list-open");
        const active = button?.dataset.conversationId === activeConversationId;

        item.classList.toggle("active", Boolean(active));

        if (button) {
            if (active) {
                button.setAttribute("aria-current", "true");
            } else {
                button.removeAttribute("aria-current");
            }
        }
    });
}

async function refreshConversationList(selectedId = null) {
    const listRequestId = ++conversationListRequestId;
    const data = await apiRequest("/api/conversations");

    if (listRequestId !== conversationListRequestId) return;

    if (!Array.isArray(data.conversations)) {
        throw new Error("The server returned an invalid conversation list.");
    }

    const ordered = [...data.conversations].sort((left, right) =>
        Number(Boolean(right.pinned)) - Number(Boolean(left.pinned)) ||
        String(right.updated_at || "").localeCompare(String(left.updated_at || ""))
    );

    if (conversationDrawerOpen && conversationSearchInput?.value.trim()) {
        conversationListReady = true;
        syncConversationControls();
        await searchConversationHistory();
        return;
    }

    renderConversationList(ordered);
    conversationListReady = true;
    syncConversationControls();

    const targetId = selectedId || data.active_id || activeConversationId;

    if (!targetId) {
        activeConversationId = null;
        updateActiveProject(null);
        showEmptyConversation();
        renderConversationListActiveState();
        return;
    }

    // A response from an earlier refresh must not overwrite a newer selection.
    const requestId = ++conversationRequestId;

    const response = await apiRequest(
        `/api/conversations/${encodeURIComponent(targetId)}`
    );

    if (
        requestId !== conversationRequestId ||
        listRequestId !== conversationListRequestId
    ) return;

    displayConversation(response.conversation);
}

async function createConversationFromHUD() {
    if (
        !newConversationButton ||
        newConversationButton.disabled ||
        conversationActionInProgress
    ) {
        return;
    }

    conversationActionInProgress = true;
    syncConversationControls();

    try {
        const data = await apiRequest("/api/conversations", {
            method: "POST",
            body: JSON.stringify({})
        });

        const conversationId = data.conversation?.id;
        if (!conversationId) {
            throw new Error("The server did not return the new conversation ID.");
        }

        await refreshConversationList(conversationId);
        closeConversationDrawer();
        input?.focus();
    } catch (error) {
        console.error("LEWIS CONVERSATION CREATE ERROR:", error);
        setConversationDrawerStatus(
            `Could not create a conversation: ${error.message}`,
            true
        );
        addMessage("SYSTEM", `Could not create a conversation: ${error.message}`);
    } finally {
        conversationActionInProgress = false;
        syncConversationControls();
    }
}

async function selectConversationFromDrawer(selectedId) {
    if (
        !selectedId ||
        selectedId === activeConversationId ||
        conversationActionInProgress
    ) {
        if (selectedId === activeConversationId) closeConversationDrawer();
        return;
    }

    if (requestInProgress) {
        setConversationDrawerStatus(
            "Wait for the current message to finish before switching conversations.",
            true
        );
        return;
    }

    conversationActionInProgress = true;
    syncConversationControls();
    setConversationDrawerStatus("Opening conversation...");

    try {
        const data = await apiRequest("/api/conversations/select", {
            method: "POST",
            body: JSON.stringify({ id: selectedId })
        });

        if (!data.conversation) {
            throw new Error("The server did not return the selected conversation.");
        }

        // Invalidate outstanding conversation fetches before rendering this one.
        conversationRequestId += 1;
        displayConversation(data.conversation);
        await refreshConversationList(selectedId);
        closeConversationDrawer();
        input?.focus();
    } catch (error) {
        console.error("LEWIS CONVERSATION SELECT ERROR:", error);
        setConversationDrawerStatus(
            `Could not open that conversation: ${error.message}`,
            true
        );
    } finally {
        conversationActionInProgress = false;
        syncConversationControls();
    }
}

function openConversationRenameEditor(conversation, item, mainButton, actions) {
    if (conversationActionInProgress || requestInProgress) return;

    const editor = document.createElement("form");
    editor.className = "conversation-rename-editor";

    const titleInput = document.createElement("input");
    titleInput.className = "conversation-rename-input";
    titleInput.type = "text";
    titleInput.maxLength = 120;
    titleInput.value = String(conversation.title || "New conversation");
    titleInput.setAttribute("aria-label", "Conversation title");
    titleInput.required = true;

    const saveButton = document.createElement("button");
    saveButton.className = "conversation-rename-save";
    saveButton.type = "submit";
    saveButton.textContent = "SAVE";

    const cancelButton = document.createElement("button");
    cancelButton.className = "conversation-rename-cancel";
    cancelButton.type = "button";
    cancelButton.textContent = "CANCEL";

    editor.append(titleInput, saveButton, cancelButton);
    mainButton.hidden = true;
    actions.hidden = true;
    item.insertBefore(editor, mainButton);

    const closeEditor = () => {
        editor.remove();
        mainButton.hidden = false;
        actions.hidden = false;
    };

    cancelButton.addEventListener("click", () => {
        closeEditor();
        setConversationDrawerStatus("");
        mainButton.focus();
    });

    editor.addEventListener("submit", async (event) => {
        event.preventDefault();

        const title = titleInput.value.trim();
        if (!title) {
            titleInput.setCustomValidity("A conversation title cannot be empty.");
            titleInput.reportValidity();
            return;
        }

        titleInput.setCustomValidity("");
        if (title.length > 120) {
            setConversationDrawerStatus(
                "Conversation titles must be 120 characters or fewer.",
                true
            );
            titleInput.focus();
            return;
        }

        if (title === String(conversation.title || "New conversation")) {
            closeEditor();
            setConversationDrawerStatus("");
            return;
        }

        conversationActionInProgress = true;
        syncConversationControls();
        setConversationDrawerStatus("Saving title...");

        try {
            const data = await apiRequest("/api/conversations/rename", {
                method: "POST",
                body: JSON.stringify({ id: conversation.id, title })
            });

            if (!data.conversation || data.conversation.id !== conversation.id) {
                throw new Error("The server did not confirm the renamed conversation.");
            }

            await refreshConversationList(activeConversationId);
            setConversationDrawerStatus("Conversation title updated.");
        } catch (error) {
            console.error("LEWIS CONVERSATION RENAME ERROR:", error);
            setConversationDrawerStatus(
                `Could not rename conversation: ${error.message}`,
                true
            );
        } finally {
            conversationActionInProgress = false;
            syncConversationControls();
        }
    });

    titleInput.focus();
    titleInput.select();
}

async function deleteConversationFromDrawer(conversation) {
    if (conversationActionInProgress || requestInProgress) {
        if (requestInProgress) {
            setConversationDrawerStatus(
                "Wait for the current message to finish before deleting a conversation.",
                true
            );
        }
        return;
    }

    const title = String(conversation.title || "New conversation");
    const confirmed = window.confirm(
        `Delete "${title}" and its conversation history?\n\n` +
        "This cannot be undone. LEWIS's long-term memory will not be deleted."
    );

    if (!confirmed) return;

    conversationActionInProgress = true;
    syncConversationControls();
    setConversationDrawerStatus("Deleting conversation...");

    try {
        const data = await apiRequest("/api/conversations/delete", {
            method: "POST",
            body: JSON.stringify({ id: conversation.id })
        });

        const nextActiveId =
            data.active_conversation_id ||
            data.conversation?.id ||
            null;

        // Prevent any older request from rendering a conversation that was deleted.
        conversationRequestId += 1;

        if (conversation.id === activeConversationId) {
            activeConversationId = null;

            if (nextActiveId) {
                await refreshConversationList(nextActiveId);
            } else {
                await refreshConversationList(null);
            }
        } else {
            await refreshConversationList(activeConversationId);
        }

        setConversationDrawerStatus("Conversation deleted. Long-term memory was preserved.");
    } catch (error) {
        console.error("LEWIS CONVERSATION DELETE ERROR:", error);
        setConversationDrawerStatus(
            `Could not delete conversation: ${error.message}`,
            true
        );
    } finally {
        conversationActionInProgress = false;
        syncConversationControls();
    }
}

function renderConversationSearchResults(results, searchTerm) {
    if (!conversationList) return;
    conversationList.replaceChildren();

    if (!results.length) {
        const empty = document.createElement("p");
        empty.className = "conversation-list-empty";
        empty.textContent = `No messages match "${searchTerm}".`;
        conversationList.appendChild(empty);
        return;
    }

    results.forEach((result) => {
        const message = result.message || {};
        const button = document.createElement("button");
        button.type = "button";
        button.className = "conversation-search-result";
        button.disabled = conversationActionInProgress || requestInProgress;

        const title = document.createElement("strong");
        title.textContent = result.title || "Untitled conversation";
        const content = String(message.content || "");
        const matchIndex = content.toLowerCase().indexOf(searchTerm.toLowerCase());
        const start = Math.max(0, matchIndex - 60);
        const end = Math.min(content.length, matchIndex + searchTerm.length + 100);
        const excerpt = document.createElement("span");
        excerpt.textContent =
            `${start ? "… " : ""}${content.slice(start, end)}` +
            `${end < content.length ? " …" : ""}`;
        const meta = document.createElement("span");
        meta.textContent = [
            String(message.role || "message").toUpperCase(),
            result.project || "No project"
        ].join(" · ");

        button.append(title, excerpt, meta);
        button.addEventListener("click", () => {
            selectConversationFromDrawer(result.conversation_id);
        });
        conversationList.appendChild(button);
    });
}

async function searchConversationHistory() {
    const searchTerm = conversationSearchInput?.value.trim() || "";
    const requestId = ++conversationSearchRequestId;
    window.clearTimeout(conversationSearchTimer);

    if (!searchTerm) {
        setConversationDrawerStatus("");
        await refreshConversationList(activeConversationId);
        return;
    }

    try {
        const data = await apiRequest(
            `/api/conversations/search?q=${encodeURIComponent(searchTerm)}`
        );
        if (requestId !== conversationSearchRequestId) return;
        if (!Array.isArray(data.results)) {
            throw new Error("The server returned invalid search results.");
        }

        renderConversationSearchResults(data.results, searchTerm);
        setConversationDrawerStatus(
            `${data.results.length} matching message${data.results.length === 1 ? "" : "s"}.`
        );
    } catch (error) {
        if (requestId !== conversationSearchRequestId) return;
        console.error("LEWIS CONVERSATION SEARCH ERROR:", error);
        setConversationDrawerStatus(
            `Could not search conversation history: ${error.message}`,
            true
        );
    }
}

if (conversationSearchInput) {
    conversationSearchInput.addEventListener("input", () => {
        window.clearTimeout(conversationSearchTimer);
        conversationSearchTimer = window.setTimeout(
            searchConversationHistory,
            180
        );
    });
}

async function saveConversationMetadata(conversation, updates) {
    if (conversationActionInProgress || requestInProgress) return false;
    conversationActionInProgress = true;
    syncConversationControls();
    setConversationDrawerStatus("Saving conversation settings...");

    try {
        const data = await apiRequest("/api/conversations/metadata", {
            method: "POST",
            body: JSON.stringify({ id: conversation.id, updates })
        });
        if (data.conversation?.id !== conversation.id) {
            throw new Error("The server did not confirm these settings.");
        }
        if (activeConversationId === conversation.id) {
            displayConversation(data.conversation);
        }
        await refreshConversationList(activeConversationId);
        setConversationDrawerStatus("Conversation settings saved.");
        return true;
    } catch (error) {
        console.error("LEWIS CONVERSATION ORGANIZATION ERROR:", error);
        setConversationDrawerStatus(
            `Could not save conversation settings: ${error.message}`,
            true
        );
        return false;
    } finally {
        conversationActionInProgress = false;
        syncConversationControls();
    }
}

function openConversationOrganizationEditor(conversation, item, mainButton, actions) {
    if (conversationActionInProgress || requestInProgress) return;

    const editor = document.createElement("form");
    editor.className = "conversation-organization-editor";
    const folderLabel = document.createElement("label");
    folderLabel.textContent = "FOLDER";
    const folderInput = document.createElement("input");
    folderInput.type = "text";
    folderInput.maxLength = 80;
    folderInput.value = String(conversation.folder || "");
    folderInput.setAttribute("aria-label", "Conversation folder");
    folderLabel.appendChild(folderInput);

    const projectLabel = document.createElement("label");
    projectLabel.textContent = "PROJECT";
    const projectInput = document.createElement("input");
    projectInput.type = "text";
    projectInput.maxLength = 120;
    projectInput.value = String(conversation.project || "");
    projectInput.setAttribute("aria-label", "Linked project");
    projectInput.placeholder = "Clear to unlink";
    projectLabel.appendChild(projectInput);

    const saveButton = document.createElement("button");
    saveButton.type = "submit";
    saveButton.textContent = "SAVE";
    const cancelButton = document.createElement("button");
    cancelButton.type = "button";
    cancelButton.textContent = "CANCEL";
    cancelButton.addEventListener("click", () => {
        editor.remove();
        actions.hidden = false;
        mainButton.hidden = false;
    });

    editor.append(folderLabel, projectLabel, saveButton, cancelButton);
    editor.addEventListener("submit", async (event) => {
        event.preventDefault();
        const saved = await saveConversationMetadata(conversation, {
            folder: folderInput.value.trim(),
            project: projectInput.value.trim() || null
        });
        if (!saved) return;
        editor.remove();
        actions.hidden = false;
        mainButton.hidden = false;
    });

    mainButton.hidden = true;
    actions.hidden = true;
    item.appendChild(editor);
    folderInput.focus();
}

function setActiveNavigation(link) {
    document.querySelectorAll(".nav-item.active").forEach((activeLink) => {
        activeLink.classList.remove("active");
        activeLink.removeAttribute("aria-current");
    });
    link?.classList.add("active");
    link?.setAttribute("aria-current", "page");
}

function setWorkspaceStatus(message = "", isError = false) {
    if (!workspaceStatus) return;
    workspaceStatus.textContent = message;
    workspaceStatus.dataset.state = isError ? "error" : "normal";
}

function createWorkspaceElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = String(text);
    return element;
}

function renderMemoryRecords(records) {
    const target = workspaceContent?.querySelector("#memoryRecords");
    if (!target) return;
    target.replaceChildren();

    if (!records.length) {
        target.appendChild(createWorkspaceElement(
            "p",
            "workspace-empty",
            "No stored memories match these filters."
        ));
        return;
    }

    records.forEach((record) => {
        const card = createWorkspaceElement("article", "workspace-record");
        card.appendChild(createWorkspaceElement(
            "h3",
            "",
            record.key || record.predicate || "Saved memory"
        ));
        card.appendChild(createWorkspaceElement("p", "", record.value || ""));
        const meta = createWorkspaceElement("div", "workspace-record-meta");
        [
            record.category,
            record.status || "stated",
            record.subject || "user",
            `${Array.isArray(record.history) ? record.history.length : 0} prior versions`
        ].filter(Boolean).forEach((value) => {
            meta.appendChild(createWorkspaceElement("span", "", value));
        });
        card.appendChild(meta);
        const editButton = createWorkspaceElement(
            "button",
            "workspace-button workspace-record-edit",
            "EDIT MEMORY"
        );
        editButton.type = "button";
        editButton.addEventListener("click", () => {
            openMemoryEditor(record, card);
        });
        card.appendChild(editButton);
        target.appendChild(card);
    });
}

function openMemoryEditor(record, card) {
    if (card.querySelector(".memory-edit-form")) return;
    const form = createWorkspaceElement("form", "memory-edit-form");
    const fields = {};
    const addTextField = (field, labelText, value) => {
        const label = createWorkspaceElement("label", "memory-edit-field");
        label.appendChild(createWorkspaceElement("span", "", labelText));
        const input = document.createElement(field === "value" ? "textarea" : "input");
        if (field !== "value") input.type = "text";
        input.name = field;
        input.value = String(value ?? "");
        input.maxLength = 2000;
        input.required = true;
        label.appendChild(input);
        fields[field] = input;
        form.appendChild(label);
    };

    addTextField("subject", "SUBJECT", record.subject || "user");
    addTextField("key", "MEMORY KEY", record.key || record.predicate || "");
    addTextField("value", "VALUE", record.value || "");
    addTextField("category", "CATEGORY", record.category || "other");

    const statusLabel = createWorkspaceElement("label", "memory-edit-field");
    statusLabel.appendChild(createWorkspaceElement("span", "", "STATUS"));
    const statusSelect = document.createElement("select");
    statusSelect.name = "status";
    [
        "stated",
        "idea",
        "interest",
        "plan",
        "in_progress",
        "decision",
        "completed",
        "preference"
    ].forEach((status) => {
        const option = document.createElement("option");
        option.value = status;
        option.textContent = status.replaceAll("_", " ");
        option.selected = status === (record.status || "stated");
        statusSelect.appendChild(option);
    });
    statusLabel.appendChild(statusSelect);
    fields.status = statusSelect;
    form.appendChild(statusLabel);

    const importanceLabel = createWorkspaceElement("label", "memory-edit-field");
    importanceLabel.appendChild(createWorkspaceElement("span", "", "IMPORTANCE (0–1)"));
    const importanceInput = document.createElement("input");
    importanceInput.type = "number";
    importanceInput.name = "importance";
    importanceInput.min = "0";
    importanceInput.max = "1";
    importanceInput.step = "0.1";
    importanceInput.value = String(record.importance ?? 0.5);
    importanceInput.required = true;
    importanceLabel.appendChild(importanceInput);
    fields.importance = importanceInput;
    form.appendChild(importanceLabel);

    const actions = createWorkspaceElement("div", "memory-edit-actions");
    const saveButton = createWorkspaceElement("button", "workspace-button", "SAVE MEMORY");
    saveButton.type = "submit";
    const cancelButton = createWorkspaceElement("button", "workspace-button", "CANCEL");
    cancelButton.type = "button";
    const status = createWorkspaceElement("span", "workspace-note");
    status.setAttribute("role", "status");
    actions.append(saveButton, cancelButton, status);
    form.appendChild(actions);
    card.appendChild(form);
    cancelButton.addEventListener("click", () => form.remove());
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const importance = Number(fields.importance.value);
        if (!Number.isFinite(importance) || importance < 0 || importance > 1) {
            status.textContent = "Importance must be between 0 and 1.";
            return;
        }

        saveButton.disabled = true;
        status.textContent = "Saving to LEWIS Core...";
        const updates = {
            subject: fields.subject.value,
            key: fields.key.value,
            value: fields.value.value,
            category: fields.category.value,
            status: fields.status.value,
            importance
        };
        try {
            const result = await apiRequest("/api/memory/update", {
                method: "POST",
                body: JSON.stringify({ id: record.id, updates })
            });
            if (result.memory?.id !== record.id) {
                throw new Error("The server did not confirm the memory update.");
            }
            const searchInput = workspaceContent.querySelector("#memorySearchInput");
            const categoryFilter =
                workspaceContent.querySelector("#memoryCategoryFilter");
            await loadMemoryWorkspace(
                searchInput?.value || "",
                categoryFilter?.value || ""
            );
            setWorkspaceStatus(
                "Memory updated. The previous value is retained in its history."
            );
        } catch (error) {
            console.error("LEWIS MEMORY UPDATE ERROR:", error);
            saveButton.disabled = false;
            status.textContent = `Could not save memory: ${error.message}`;
        }
    });
}

function renderMemoryWorkspace(data) {
    if (!workspaceContent.querySelector("#memoryRecords")) {
        workspaceContent.innerHTML = `
            <div class="workspace-toolbar">
                <label class="workspace-search">
                    <span>SEARCH SAVED MEMORY</span>
                    <input id="memorySearchInput" type="search" maxlength="200"
                        placeholder="Search facts, values, or subjects..." autocomplete="off">
                </label>
                <label class="workspace-filter">
                    <span>CATEGORY</span>
                    <select id="memoryCategoryFilter">
                        <option value="">All categories</option>
                    </select>
                </label>
            </div>
            <p id="memoryWorkspaceCount" class="workspace-note"></p>
            <p class="workspace-note">Edits are saved to LEWIS Core and previous values are retained in record history. Memory deletion is intentionally unavailable here.</p>
            <div id="memoryRecords" class="workspace-records"></div>
        `;

        const categorySelect =
            workspaceContent.querySelector("#memoryCategoryFilter");
        data.categories.forEach((category) => {
            const option = document.createElement("option");
            option.value = category;
            option.textContent = category;
            categorySelect.appendChild(option);
        });
        categorySelect.value = workspaceContent.dataset.memoryCategory || "";
        const searchInput =
            workspaceContent.querySelector("#memorySearchInput");
        searchInput.value = workspaceContent.dataset.memoryQuery || "";
        searchInput.addEventListener("input", () => {
            workspaceContent.dataset.memoryQuery = searchInput.value;
            scheduleMemorySearch();
        });
        categorySelect.addEventListener("change", () => {
            workspaceContent.dataset.memoryCategory = categorySelect.value;
            loadMemoryWorkspace(searchInput.value, categorySelect.value);
        });
    }

    workspaceContent.querySelector("#memoryWorkspaceCount").textContent =
        `${data.memories.length} shown · ${data.total} stored`;
    renderMemoryRecords(data.memories);
}

function scheduleMemorySearch() {
    window.clearTimeout(workspaceSearchTimer);
    workspaceSearchTimer = window.setTimeout(() => {
        const searchInput = workspaceContent?.querySelector("#memorySearchInput");
        const category = workspaceContent?.querySelector("#memoryCategoryFilter");
        loadMemoryWorkspace(searchInput?.value || "", category?.value || "");
    }, 180);
}

async function loadMemoryWorkspace(searchTerm = "", category = "") {
    const requestId = ++workspaceRequestId;
    setWorkspaceStatus("Loading saved memory...");
    try {
        const params = new URLSearchParams();
        if (searchTerm.trim()) params.set("q", searchTerm.trim());
        if (category) params.set("category", category);
        const data = await apiRequest(`/api/memory?${params.toString()}`);
        if (requestId !== workspaceRequestId || activeWorkspaceName !== "memory") {
            return;
        }
        if (!Array.isArray(data.memories) || !Array.isArray(data.categories)) {
            throw new Error("The server returned invalid memory data.");
        }
        setWorkspaceStatus();
        renderMemoryWorkspace(data);
    } catch (error) {
        if (requestId !== workspaceRequestId) return;
        console.error("LEWIS MEMORY WORKSPACE ERROR:", error);
        setWorkspaceStatus(`Could not load memory: ${error.message}`, true);
    }
}

function renderProjectFacts(projects) {
    const target = workspaceContent?.querySelector("#projectRecords");
    if (!target) return;
    target.replaceChildren();
    const projectsWithData = projects.filter(
        (project) =>
            project.facts.length ||
            (Array.isArray(project.conversations) && project.conversations.length)
    );

    if (!projectsWithData.length) {
        target.appendChild(createWorkspaceElement(
            "p",
            "workspace-empty",
            projects.length
                ? "No project facts match this search."
                : "No project facts are stored in LEWIS Core."
        ));
        return;
    }

    projectsWithData.forEach((project) => {
        const section = createWorkspaceElement("section", "workspace-project");
        const heading = createWorkspaceElement("div", "workspace-project-heading");
        heading.appendChild(createWorkspaceElement("h3", "", project.name));
        heading.appendChild(createWorkspaceElement(
            "span",
            "workspace-record-meta",
            `${project.facts.length} fact${project.facts.length === 1 ? "" : "s"} · ${(project.conversations || []).length} conversation${(project.conversations || []).length === 1 ? "" : "s"}`
        ));
        section.appendChild(heading);
        const cards = createWorkspaceElement("div", "workspace-records");
        project.facts.forEach((fact) => {
            const card = createWorkspaceElement("article", "workspace-record");
            card.appendChild(createWorkspaceElement(
                "h3",
                "",
                `${fact.subject || "Project"} · ${fact.predicate || "Fact"}`
            ));
            card.appendChild(createWorkspaceElement("p", "", fact.value || ""));
            const meta = createWorkspaceElement("div", "workspace-record-meta");
            [fact.category, fact.status].filter(Boolean).forEach((value) => {
                meta.appendChild(createWorkspaceElement("span", "", value));
            });
            card.appendChild(meta);
            cards.appendChild(card);
        });
        if (project.facts.length) {
            section.appendChild(cards);
        }
        if (project.conversations?.length) {
            section.appendChild(createWorkspaceElement(
                "h4",
                "workspace-subheading",
                "RELATED CONVERSATIONS"
            ));
            const related = createWorkspaceElement("div", "workspace-related-list");
            project.conversations.forEach((conversation) => {
                const button = createWorkspaceElement(
                    "button",
                    "workspace-button",
                    conversation.title || "Untitled conversation"
                );
                button.type = "button";
                button.addEventListener("click", () => {
                    selectConversationFromDrawer(conversation.id);
                    closeWorkspaceView();
                });
                related.appendChild(button);
            });
            section.appendChild(related);
        }
        target.appendChild(section);
    });
}

function renderProjectsWorkspace(data) {
    if (!workspaceContent.querySelector("#projectRecords")) {
        workspaceContent.innerHTML = `
            <div class="workspace-toolbar">
                <label class="workspace-search">
                    <span>SEARCH PROJECT FACTS</span>
                    <input id="projectSearchInput" type="search" maxlength="200"
                        placeholder="Search stored project context..." autocomplete="off">
                </label>
                <label class="workspace-filter">
                    <span>PROJECT</span>
                    <select id="projectFilter">
                        <option value="">All saved projects</option>
                    </select>
                </label>
            </div>
            <p class="workspace-note">Projects are derived from saved LEWIS Core facts and linked conversations. Task tracking, milestones, project files, and project activity APIs are not available.</p>
            <div id="projectRecords"></div>
        `;

        const filter = workspaceContent.querySelector("#projectFilter");
        (data.project_names || []).forEach((name) => {
            const option = document.createElement("option");
            option.value = name;
            option.textContent = name;
            filter.appendChild(option);
        });
        filter.value = workspaceContent.dataset.projectName || "";
        const searchInput =
            workspaceContent.querySelector("#projectSearchInput");
        searchInput.value = workspaceContent.dataset.projectQuery || "";
        searchInput.addEventListener("input", () => {
            workspaceContent.dataset.projectQuery = searchInput.value;
            window.clearTimeout(workspaceSearchTimer);
            workspaceSearchTimer = window.setTimeout(
                () => loadProjectsWorkspace(searchInput.value, filter.value),
                180
            );
        });
        filter.addEventListener("change", () => {
            workspaceContent.dataset.projectName = filter.value;
            loadProjectsWorkspace(searchInput.value, filter.value);
        });
    }
    renderProjectFacts(data.projects);
}

async function loadProjectsWorkspace(searchTerm = "", projectName = "") {
    const requestId = ++workspaceRequestId;
    setWorkspaceStatus("Loading saved project context...");
    try {
        const params = new URLSearchParams();
        if (searchTerm.trim()) params.set("q", searchTerm.trim());
        if (projectName) params.set("project", projectName);
        const data = await apiRequest(`/api/projects?${params.toString()}`);
        if (requestId !== workspaceRequestId || activeWorkspaceName !== "projects") {
            return;
        }
        if (!Array.isArray(data.projects)) {
            throw new Error("The server returned invalid project memory.");
        }
        setWorkspaceStatus();
        renderProjectsWorkspace(data);
    } catch (error) {
        if (requestId !== workspaceRequestId) return;
        console.error("LEWIS PROJECT WORKSPACE ERROR:", error);
        setWorkspaceStatus(`Could not load project context: ${error.message}`, true);
    }
}

function renderModelsWorkspace(data) {
    const models = Array.isArray(data.ai_models) ? data.ai_models : [];
    workspaceContent.replaceChildren();
    const panel = createWorkspaceElement("section", "workspace-model-panel");
    panel.appendChild(createWorkspaceElement(
        "h3",
        "",
        `Active provider: ${data.ai_provider || "Unavailable"}`
    ));
    panel.appendChild(createWorkspaceElement(
        "p",
        "workspace-note",
        `${data.ai || "Provider status unavailable"} · Selection applies to new requests and is held in memory until the server restarts.`
    ));

    if (!models.length) {
        panel.appendChild(createWorkspaceElement(
            "p",
            "workspace-empty",
            "No providers are currently configured. Configure credentials in the server environment; keys are not handled or displayed in this HUD."
        ));
        workspaceContent.appendChild(panel);
        return;
    }

    const label = createWorkspaceElement("label", "", "Choose provider and model for new requests");
    const select = createWorkspaceElement("select", "workspace-model-select");
    select.setAttribute("aria-label", "AI provider and model");
    models.forEach((model) => {
        const option = document.createElement("option");
        option.value = model.provider;
        option.dataset.model = model.model;
        option.textContent = `${model.name} — ${model.model}`;
        option.selected =
            model.provider === data.ai_selection?.provider &&
            model.model === data.ai_selection?.model;
        select.appendChild(option);
    });
    label.appendChild(select);
    panel.appendChild(label);

    const apply = createWorkspaceElement("button", "workspace-button", "APPLY MODEL");
    apply.type = "button";
    apply.disabled = true;
    const selectionStatus = createWorkspaceElement("p", "workspace-note");
    selectionStatus.setAttribute("role", "status");
    const testButton = createWorkspaceElement(
        "button",
        "workspace-button",
        "TEST CONNECTION"
    );
    testButton.type = "button";
    const testStatus = createWorkspaceElement("p", "workspace-note");
    testStatus.setAttribute("role", "status");
    panel.append(apply, selectionStatus, testButton, testStatus);

    const syncSelection = () => {
        const selected = select.selectedOptions[0];
        const isCurrentSelection = selected && (
            selected.value === data.ai_selection?.provider &&
            selected.dataset.model === data.ai_selection?.model
        );
        apply.disabled = !selected || isCurrentSelection;
        testButton.disabled = !isCurrentSelection || data.ai !== "CONFIGURED";
    };
    select.addEventListener("change", syncSelection);
    apply.addEventListener("click", async () => {
        const selected = select.selectedOptions[0];
        if (!selected || apply.disabled) return;
        apply.disabled = true;
        selectionStatus.textContent = "Applying selection...";
        try {
            const result = await apiRequest("/api/ai/model", {
                method: "POST",
                body: JSON.stringify({
                    provider: selected.value,
                    model: selected.dataset.model
                })
            });
            if (!result.selection) {
                throw new Error("The server did not confirm the model selection.");
            }
            data.ai_selection = result.selection;
            selectionStatus.textContent =
                `Selected ${result.selection.provider} — ${result.selection.model}.`;
            await updateHUDStatus();
            syncSelection();
        } catch (error) {
            console.error("LEWIS AI MODEL WORKSPACE ERROR:", error);
            selectionStatus.textContent =
                `Could not apply model: ${error.message}`;
            syncSelection();
        }
    });
    testButton.addEventListener("click", async () => {
        if (testButton.disabled) return;
        testButton.disabled = true;
        testStatus.textContent = "Sending the fixed provider check...";
        try {
            const result = await apiRequest("/api/ai/test", {
                method: "POST",
                body: JSON.stringify({})
            });
            if (
                result.ok !== true ||
                result.provider !== data.ai_selection?.provider ||
                result.model !== data.ai_selection?.model
            ) {
                throw new Error("The server did not confirm the selected provider.");
            }
            testStatus.textContent =
                `${result.provider} responded using ${result.model}.`;
            await updateHUDStatus();
        } catch (error) {
            console.error("LEWIS AI PROVIDER TEST ERROR:", error);
            testStatus.textContent =
                `Connection test failed: ${error.message}`;
        } finally {
            syncSelection();
        }
    });
    workspaceContent.appendChild(panel);
    workspaceContent.appendChild(createWorkspaceElement(
        "p",
        "workspace-note",
        "The connection test sends a fixed short prompt to your selected provider and may count toward its usage or billing. API-key editing, usage monitoring, automatic routing, and local-model configuration are not available."
    ));
}

function renderSettingsWorkspace() {
    const cards = [
        {
            title: "Appearance",
            description: "Switch between the saved Soft Platinum and Graphite themes.",
            action: "theme",
            label: "SWITCH THEME"
        },
        {
            title: "Voice & Audio",
            description: "Open the existing microphone and voice-output controls.",
            action: "voice",
            label: "OPEN VOICE CONTROLS"
        },
        {
            title: "AI & Providers",
            description: "Choose an available provider/model. Selection is runtime-only.",
            action: "models",
            label: "OPEN AI MODELS"
        },
        {
            title: "Memory & Privacy",
            description: "Inspect and edit saved memory. Deletion is intentionally unavailable.",
            action: "memory",
            label: "VIEW MEMORY"
        },
        {
            title: "System",
            description: "Live system telemetry is available in the HUD overview. No additional system settings are exposed.",
            action: null,
            label: "NOT CONFIGURABLE"
        },
        {
            title: "Personalization",
            description: "No additional personalization settings are currently backed by configuration.",
            action: null,
            label: "NOT CONFIGURED"
        },
        {
            title: "Hardware",
            description: "ATLAS hardware integration is future work; no devices are claimed as connected.",
            action: null,
            label: "FUTURE INTEGRATION"
        }
    ];
    workspaceContent.replaceChildren();
    const grid = createWorkspaceElement("div", "workspace-settings-grid");
    cards.forEach((card) => {
        const section = createWorkspaceElement("section", "workspace-settings-card");
        section.appendChild(createWorkspaceElement("h3", "", card.title));
        section.appendChild(createWorkspaceElement("p", "", card.description));
        const button = createWorkspaceElement(
            "button",
            "workspace-button",
            card.label
        );
        button.type = "button";
        if (card.action) {
            button.dataset.settingsAction = card.action;
        } else {
            button.disabled = true;
        }
        section.appendChild(button);
        grid.appendChild(section);
    });
    workspaceContent.appendChild(grid);

    const preferencePanel = createWorkspaceElement(
        "section",
        "workspace-settings-preferences"
    );
    preferencePanel.innerHTML = `
        <h3>Display and sound preferences</h3>
        <p class="workspace-note">These preferences are saved in this browser. Sound is opt-in and limited to an on-demand preview; no sound plays during voice output.</p>
        <label class="workspace-preference-row">
            <input id="orbMotionPreference" type="checkbox">
            <span>Enable orb animation</span>
        </label>
        <label class="workspace-preference-row">
            <input id="soundPreviewPreference" type="checkbox">
            <span>Enable sound preview</span>
        </label>
        <label class="workspace-preference-row">
            <input id="soundMutePreference" type="checkbox">
            <span>Mute all HUD sound previews</span>
        </label>
        <label class="workspace-preference-field">
            <span>SOUND PROFILE</span>
            <select id="soundProfilePreference">
                <option value="soft">Soft platinum</option>
                <option value="clear">Clear graphite</option>
            </select>
        </label>
        <label class="workspace-preference-field">
            <span>PREVIEW VOLUME <output id="soundVolumeValue"></output></span>
            <input id="soundVolumePreference" type="range" min="0" max="100" step="1">
        </label>
        <button id="previewInterfaceSoundButton" class="workspace-button" type="button">PREVIEW SOUND</button>
        <p id="soundPreferenceStatus" class="workspace-note" role="status"></p>
    `;
    workspaceContent.appendChild(preferencePanel);

    const orbMotionInput = preferencePanel.querySelector("#orbMotionPreference");
    const soundEnabledInput =
        preferencePanel.querySelector("#soundPreviewPreference");
    const mutedInput = preferencePanel.querySelector("#soundMutePreference");
    const profileInput = preferencePanel.querySelector("#soundProfilePreference");
    const volumeInput = preferencePanel.querySelector("#soundVolumePreference");
    const volumeValue = preferencePanel.querySelector("#soundVolumeValue");
    const previewButton =
        preferencePanel.querySelector("#previewInterfaceSoundButton");
    const preferenceStatus =
        preferencePanel.querySelector("#soundPreferenceStatus");

    orbMotionInput.checked = hudPreferences.orbMotion;
    soundEnabledInput.checked = hudPreferences.soundPreviewEnabled;
    mutedInput.checked = hudPreferences.soundMuted;
    profileInput.value = hudPreferences.soundProfile;
    volumeInput.value = String(hudPreferences.soundVolume);
    volumeValue.textContent = `${hudPreferences.soundVolume}%`;

    const saveAndApplyPreferences = () => {
        saveHudPreferences();
        applyHudPreferences();
        previewButton.disabled =
            !hudPreferences.soundPreviewEnabled || hudPreferences.soundMuted;
    };
    orbMotionInput.addEventListener("change", () => {
        hudPreferences.orbMotion = orbMotionInput.checked;
        saveAndApplyPreferences();
    });
    soundEnabledInput.addEventListener("change", () => {
        hudPreferences.soundPreviewEnabled = soundEnabledInput.checked;
        saveAndApplyPreferences();
    });
    mutedInput.addEventListener("change", () => {
        hudPreferences.soundMuted = mutedInput.checked;
        saveAndApplyPreferences();
    });
    profileInput.addEventListener("change", () => {
        hudPreferences.soundProfile = profileInput.value;
        saveAndApplyPreferences();
    });
    volumeInput.addEventListener("input", () => {
        hudPreferences.soundVolume = Number(volumeInput.value);
        volumeValue.textContent = `${hudPreferences.soundVolume}%`;
        saveHudPreferences();
    });
    previewButton.disabled =
        !hudPreferences.soundPreviewEnabled || hudPreferences.soundMuted;
    previewButton.addEventListener("click", async () => {
        preferenceStatus.textContent = "";
        try {
            const played = await playInterfaceSoundPreview();
            preferenceStatus.textContent = played
                ? "Sound preview played."
                : "Preview is muted or voice output is active.";
        } catch (error) {
            console.error("LEWIS HUD SOUND PREVIEW ERROR:", error);
            preferenceStatus.textContent =
                `Could not play preview: ${error.message}`;
        }
    });

    const futureIntegrations = createWorkspaceElement(
        "section",
        "workspace-settings-preferences"
    );
    futureIntegrations.innerHTML = `
        <h3>Hardware and permission-based autonomy</h3>
        <p class="workspace-note">AXIS, DUM-E, and other hardware have no discovery or authorization API in this build. Their connection state is not known and no device is represented as connected.</p>
        <p class="workspace-note">Permission requests, background workflow execution, verification, and task history require a dedicated authorized backend. No autonomous execution controls are available.</p>
        <p class="workspace-note">The future lifecycle remains: Understand → Plan → Request Permission → Execute → Verify → Report. Execution is not enabled by this informational display.</p>
    `;
    workspaceContent.appendChild(futureIntegrations);
}

async function openWorkspace(name, navigationLink) {
    if (!workspaceView || !workspaceContent) return;
    closeConversationDrawer();
    activeWorkspaceName = name;
    workspaceRequestId += 1;
    window.clearTimeout(workspaceSearchTimer);
    workspaceReturnFocus = navigationLink || document.activeElement;
    setActiveNavigation(navigationLink);
    workspaceView.hidden = false;
    workspaceView.setAttribute("aria-hidden", "false");
    workspaceView.removeAttribute("inert");
    workspaceBackdrop.hidden = false;
    const descriptions = {
        memory: ["MEMORY", "Browse, search, and edit memories stored by LEWIS Core."],
        projects: ["PROJECTS", "Review saved project facts and linked conversations from LEWIS Core."],
        models: ["AI MODELS", "Select an available provider and model for new requests."],
        settings: ["SETTINGS", "Manage the appearance, voice, and provider settings currently supported."]
    };
    const [title, description] = descriptions[name] || ["WORKSPACE", ""];
    workspaceTitle.textContent = title;
    workspaceDescription.textContent = description;
    workspaceContent.replaceChildren();
    setWorkspaceStatus();
    closeWorkspaceButton?.focus();

    if (name === "memory") {
        await loadMemoryWorkspace(
            workspaceContent.dataset.memoryQuery || "",
            workspaceContent.dataset.memoryCategory || ""
        );
    } else if (name === "projects") {
        await loadProjectsWorkspace(
            workspaceContent.dataset.projectQuery || "",
            workspaceContent.dataset.projectName || ""
        );
    } else if (name === "models") {
        const requestId = ++workspaceRequestId;
        setWorkspaceStatus("Loading provider status...");
        try {
            const data = await apiRequest("/api/status");
            if (requestId !== workspaceRequestId || activeWorkspaceName !== "models") return;
            setWorkspaceStatus();
            renderModelsWorkspace(data);
        } catch (error) {
            if (requestId !== workspaceRequestId) return;
            console.error("LEWIS AI MODEL WORKSPACE ERROR:", error);
            setWorkspaceStatus(`Could not load provider status: ${error.message}`, true);
        }
    } else if (name === "settings") {
        renderSettingsWorkspace();
    }
}

function closeWorkspaceView() {
    if (!workspaceView || workspaceView.hidden) return;
    activeWorkspaceName = null;
    workspaceRequestId += 1;
    workspaceView.hidden = true;
    workspaceView.setAttribute("aria-hidden", "true");
    workspaceView.setAttribute("inert", "");
    workspaceBackdrop.hidden = true;
    const returnFocus = workspaceReturnFocus;
    workspaceReturnFocus = null;
    if (returnFocus instanceof HTMLElement && returnFocus.isConnected) {
        returnFocus.focus();
    }
}

closeWorkspaceButton?.addEventListener("click", closeWorkspaceView);
workspaceBackdrop?.addEventListener("click", closeWorkspaceView);
workspaceContent?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-settings-action]");
    if (!button) return;
    const action = button.dataset.settingsAction;
    if (action === "theme") {
        toggleThemeButton?.click();
    } else if (action === "voice") {
        closeWorkspaceView();
        const voiceSettings = document.getElementById("voiceSettings");
        if (voiceSettings) {
            voiceSettings.open = true;
            voiceSettings.scrollIntoView({ behavior: "smooth", block: "center" });
        }
    } else if (action === "models" || action === "memory") {
        const link = document.querySelector(
            `.nav-item[data-workspace="${action}"]`
        );
        openWorkspace(action, link);
    }
});

document.addEventListener("keydown", (event) => {
    if (!workspaceView || workspaceView.hidden) return;
    if (event.key === "Escape") {
        closeWorkspaceView();
        return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(workspaceView.querySelectorAll(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), a[href]'
    )).filter((element) => !element.hidden && element.getClientRects().length > 0);
    if (!focusable.length) {
        event.preventDefault();
        closeWorkspaceButton?.focus();
        return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
    }
});

// ==================================================
// CONVERSATION DRAWER EVENTS
// ==================================================

if (conversationNavLink) {
    conversationNavLink.setAttribute("aria-controls", "conversationDrawer");
    conversationNavLink.setAttribute("aria-expanded", "false");

    conversationNavLink.addEventListener("click", (event) => {
        event.preventDefault();
        closeWorkspaceView();
        setActiveNavigation(conversationNavLink);
        openConversationDrawer();
    });
}

closeConversationDrawerButton?.addEventListener(
    "click",
    closeConversationDrawer
);

conversationDrawerBackdrop?.addEventListener(
    "click",
    closeConversationDrawer
);

document.addEventListener("keydown", (event) => {
    if (!conversationDrawerOpen) return;

    if (event.key === "Escape") {
        closeConversationDrawer();
        return;
    }

    if (event.key === "Tab" && conversationDrawer) {
        const focusable = Array.from(
            conversationDrawer.querySelectorAll(
                'a[href], button:not([disabled]), input:not([disabled]), ' +
                'select:not([disabled]), [tabindex]:not([tabindex="-1"])'
            )
        ).filter((element) =>
            !element.hidden && element.getClientRects().length > 0
        );

        if (!focusable.length) {
            event.preventDefault();
            conversationDrawer.focus();
            return;
        }

        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (
            event.shiftKey &&
            (document.activeElement === first ||
                !conversationDrawer.contains(document.activeElement))
        ) {
            event.preventDefault();
            last.focus();
        } else if (
            !event.shiftKey &&
            (document.activeElement === last ||
                !conversationDrawer.contains(document.activeElement))
        ) {
            event.preventDefault();
            first.focus();
        }
    }
});

// ==================================================
// CHAT
// ==================================================

async function sendCommand(command) {
    requestInProgress = true;
    syncConversationControls();
    taskStartedAt = Date.now();
    setConversationState("PROCESSING");
    setOrbState("thinking");

    const requestId = ++chatRequestId;
    const requestConversationId = activeConversationId;
    const requestIsCurrent = () =>
        requestId === chatRequestId &&
        requestConversationId === activeConversationId;

    try {
        const data = await apiRequest("/api/chat", {
            method: "POST",
            body: JSON.stringify({ message: command })
        });

        const answer = data.response ?? "LEWIS returned an empty response.";

        if (requestIsCurrent()) {
            addMessage("LEWIS", answer);
        }

        if (requestIsCurrent() && voiceEnabled && answer.trim()) {
            await speakResponse(answer);
        }

        return answer;
    } catch (error) {
        console.error("LEWIS API ERROR:", error);

        if (requestIsCurrent()) {
            addMessage("SYSTEM", "LEWIS Core connection error: " + error.message);
            setConversationState("ERROR");
        }

        return null;
    } finally {
        if (requestId === chatRequestId) {
            requestInProgress = false;
            taskStartedAt = null;
            syncConversationControls();
            await updateHUDStatus();
        }
    }
}

async function handleCommand() {
    if (
        !input ||
        !sendButton ||
        input.disabled ||
        sendButton.disabled ||
        requestInProgress
    ) {
        return;
    }

    const command = input.value.trim();
    if (!command) return;

    addMessage("YOU", command);
    input.value = "";
    sendButton.disabled = true;

    if (
        (voiceSpeaking || voiceOutputPending) &&
        !speechStopPending
    ) {
        await stopSpeaking();
    }

    sendCommand(command).finally(() => {
        syncConversationControls();
        if (!input.disabled) input.focus();
    });
}

if (sendButton) {
    sendButton.addEventListener("click", handleCommand);
}

if (newConversationButton) {
    newConversationButton.addEventListener("click", createConversationFromHUD);
}

openFocusHistoryButton?.addEventListener("click", openConversationDrawer);

if (input) {
    input.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            handleCommand();
        }
    });
}

// ==================================================
// CHAT EXPAND / COLLAPSE
// ==================================================

if (expandChatButton && hud) {
    expandChatButton.addEventListener("click", () => {
        const expanded = hud.classList.toggle("chat-expanded");

        expandChatButton.textContent = expanded ? "COLLAPSE" : "EXPAND";
        expandChatButton.setAttribute("aria-expanded", String(expanded));

        if (input) input.focus();
    });
}

document.querySelectorAll(".action-card[data-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
        if (!input) return;

        input.value = button.dataset.prompt || "";
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
    });
});

voiceSessionToggleButtons.forEach((button) => {
    button.addEventListener("click", () => {
        if (voiceSessionActive) {
            stopVoiceSession();
        } else {
            startVoiceSession();
        }
    });
});

document.querySelectorAll(".nav-item").forEach((link) => {
    link.addEventListener("click", (event) => {
        if (link.getAttribute("aria-disabled") === "true" || link.disabled) {
            event.preventDefault();
            return;
        }

        const workspaceName = link.dataset.workspace;
        if (workspaceName) {
            event.preventDefault();
            openWorkspace(workspaceName, link);
            return;
        }

        setActiveNavigation(link);
        if (link.getAttribute("href") === "#home") {
            closeWorkspaceView();
            closeConversationDrawer();
            setFocusMode(true);
        }
    });
});

document.querySelectorAll('.brand[href="#home"]').forEach((link) => {
    link.addEventListener("click", () => {
        closeWorkspaceView();
        closeConversationDrawer();
        setFocusMode(true);
    });
});

// ==================================================
// CONTINUOUS VOICE SESSION
// ==================================================

function syncVoiceSessionControls() {
    const busy =
        voiceControlRequestInProgress ||
        pushToTalkOperationInProgress ||
        pushToTalkProcessing;

    const quickLabel =
        voiceSessionOperation === "starting" ? "STARTING..." :
        voiceSessionOperation === "stopping" ||
        (voiceSessionActive && voiceSessionStopping) ? "STOPPING..." :
        voiceSessionActive ? "STOP VOICE SESSION" :
        "START VOICE SESSION";

    voiceSessionToggleButtons.forEach((button) => {
        const label =
            button.querySelector("strong") ||
            button.querySelector(".voice-session-button-label");

        if (label) {
            label.textContent = button === quickVoiceSessionButton
                ? quickLabel
                : voiceSessionOperation === "starting"
                    ? "STARTING..."
                    : voiceSessionOperation === "stopping" ||
                        (voiceSessionActive && voiceSessionStopping)
                        ? "STOPPING..."
                        : voiceSessionActive
                            ? "STOP"
                            : "VOICE";
        }

        if (button === quickVoiceSessionButton) {
            const description = button.querySelector("small");
            if (description) {
                description.textContent =
                    voiceSessionOperation === "starting"
                        ? "Requesting microphone access..."
                        : voiceSessionOperation === "stopping" ||
                            voiceSessionStopping
                            ? "Waiting for the voice session to stop"
                            : voiceSessionActive
                                ? "End live microphone input"
                                : "Enable live microphone input";
            }
        }

        button.disabled =
            busy ||
            pushToTalkActive ||
            pushToTalkProcessing ||
            pushToTalkPressed ||
            voiceOutputPending ||
            (voiceSessionActive && voiceSessionStopping) ||
            (!voiceSessionActive &&
                (
                    requestInProgress ||
                    coreProcessing ||
                    !voiceAvailable ||
                    voiceSpeaking ||
                    voiceOutputPending
                ));

        button.setAttribute("aria-busy", String(busy));
        button.setAttribute("aria-pressed", String(voiceSessionActive));
        button.setAttribute(
            "aria-label",
            voiceSessionOperation === "starting"
                ? "Starting continuous voice session"
                : voiceSessionOperation === "stopping" || voiceSessionStopping
                    ? "Stopping continuous voice session"
                    : voiceSessionActive
                        ? "Stop continuous voice session"
                        : "Start continuous voice session"
        );
        button.title = voiceSessionActive
            ? "Stop the continuous voice session"
            : voiceAvailable
                ? "Start a continuous voice session"
                : "Voice dependencies are unavailable. Check the server terminal.";
    });

    if (voiceSessionStartButton) {
        voiceSessionStartButton.disabled =
            busy ||
            requestInProgress ||
            coreProcessing ||
            voiceSessionActive ||
            pushToTalkActive ||
            pushToTalkProcessing ||
            pushToTalkPressed ||
            !voiceAvailable ||
            voiceSpeaking ||
            voiceOutputPending;

        voiceSessionStartButton.textContent =
            voiceSessionOperation === "starting"
                ? "STARTING..."
                : "START VOICE SESSION";

        voiceSessionStartButton.setAttribute("aria-busy", String(busy));
    }

    if (voiceSessionStopButton) {
        voiceSessionStopButton.disabled =
            busy || !voiceSessionActive || voiceSessionStopping;

        voiceSessionStopButton.textContent =
            voiceSessionOperation === "stopping" ||
            (voiceSessionActive && voiceSessionStopping)
                ? "STOPPING..."
                : "STOP VOICE SESSION";

        voiceSessionStopButton.setAttribute("aria-busy", String(busy));
    }

    if (pushToTalkButton) {
        pushToTalkButton.disabled =
            !pushToTalkPressed &&
            (busy ||
                requestInProgress ||
                coreProcessing ||
                voiceSessionActive ||
                voiceSessionStopping ||
                !voiceAvailable ||
                voiceSpeaking ||
                voiceOutputPending);
        pushToTalkButton.textContent =
            pushToTalkOperationInProgress
                ? pushToTalkPressed
                    ? "STARTING..."
                    : "STOPPING..."
                : pushToTalkProcessing
                    ? "PROCESSING..."
                : pushToTalkPressed
                    ? "RELEASE TO SEND"
                    : pushToTalkActive
                        ? "STOP CAPTURE"
                        : "HOLD TO TALK";
        pushToTalkButton.setAttribute(
            "aria-label",
            pushToTalkPressed
                ? "Release to finish speech input"
                : pushToTalkProcessing
                    ? "Processing captured speech"
                : pushToTalkActive
                    ? "Stop push-to-talk capture"
                    : "Press and hold to talk"
        );
        pushToTalkButton.setAttribute(
            "aria-pressed",
            String(pushToTalkPressed)
        );
        pushToTalkButton.setAttribute(
            "aria-busy",
            String(pushToTalkOperationInProgress || pushToTalkProcessing)
        );
    }
}

async function startVoiceSession({ pushToTalk = false } = {}) {
    if (
        voiceControlRequestInProgress ||
        requestInProgress ||
        coreProcessing ||
        voiceSessionActive ||
        pushToTalkActive ||
        pushToTalkProcessing ||
        pushToTalkPressed ||
        !voiceAvailable ||
        voiceSpeaking ||
        voiceOutputPending
    ) {
        return;
    }

    voiceControlRequestInProgress = true;
    voiceSessionOperation = "starting";
    syncVoiceSessionControls();
    syncConversationControls();
    setConversationState("STARTING");

    try {
        const data = await apiRequest("/api/voice/session/start", {
            method: "POST",
            body: JSON.stringify({})
        });

        if (data.voice_session_active !== true) {
            throw new Error(
                data.message ||
                "The server did not confirm that the voice session started."
            );
        }

        voiceSessionActive = true;
        voiceSessionStopping = false;
        addMessage("SYSTEM", data.message || "Voice session started.");
    } catch (error) {
        console.error("LEWIS VOICE SESSION ERROR:", error);
        addMessage("SYSTEM", "Could not start voice session: " + error.message);
        setConversationState("ERROR");
    } finally {
        voiceControlRequestInProgress = false;
        voiceSessionOperation = null;
        syncVoiceSessionControls();
        await updateHUDStatus();
        if (
            pushToTalk &&
            !pushToTalkPressed &&
            voiceSessionActive &&
            !voiceSessionStopping
        ) {
            await stopVoiceSession();
        }
    }
}

async function startPushToTalk() {
    if (
        pushToTalkOperationInProgress ||
        requestInProgress ||
        coreProcessing ||
        !pushToTalkPressed ||
        !voiceAvailable ||
        voiceSessionActive ||
        pushToTalkProcessing ||
        voiceSpeaking ||
        voiceOutputPending
    ) {
        return;
    }

    pushToTalkOperationInProgress = true;
    syncVoiceSessionControls();
    syncConversationControls();

    try {
        const data = await apiRequest("/api/voice/ptt/start", {
            method: "POST",
            body: JSON.stringify({})
        });

        if (data.push_to_talk_active !== true) {
            throw new Error(
                data.message || "The server did not start push-to-talk capture."
            );
        }

        pushToTalkActive = true;
    } catch (error) {
        console.error("LEWIS PUSH-TO-TALK START ERROR:", error);
        pushToTalkPressed = false;
        pushToTalkActive = false;
        addMessage("SYSTEM", "Could not start push-to-talk: " + error.message);
        setConversationState("ERROR");
    } finally {
        pushToTalkOperationInProgress = false;
        syncVoiceSessionControls();
        syncConversationControls();
        await updateHUDStatus();
        if (!pushToTalkPressed && pushToTalkActive) {
            await stopPushToTalk();
        }
    }
}

async function stopPushToTalk() {
    if (
        pushToTalkOperationInProgress ||
        !pushToTalkActive
    ) {
        return;
    }

    pushToTalkOperationInProgress = true;
    syncVoiceSessionControls();
    syncConversationControls();

    try {
        const data = await apiRequest("/api/voice/ptt/stop", {
            method: "POST",
            body: JSON.stringify({})
        });

        pushToTalkActive = data.push_to_talk_active === true;
        addMessage("SYSTEM", data.message || "Push-to-talk released.");
    } catch (error) {
        console.error("LEWIS PUSH-TO-TALK STOP ERROR:", error);
        addMessage("SYSTEM", "Could not release push-to-talk: " + error.message);
    } finally {
        pushToTalkOperationInProgress = false;
        syncVoiceSessionControls();
        syncConversationControls();
        await updateHUDStatus();
    }
}

function beginPushToTalk(event) {
    if (event.cancelable) event.preventDefault();

    if (pushToTalkActive && !pushToTalkPressed) {
        stopPushToTalk();
        return;
    }

    if (
        !pushToTalkButton ||
        pushToTalkButton.disabled ||
        pushToTalkPressed
    ) {
        return;
    }

    pushToTalkPressed = true;
    pushToTalkPointerId =
        typeof event.pointerId === "number" ? event.pointerId : null;

    if (
        pushToTalkPointerId !== null &&
        pushToTalkButton.setPointerCapture
    ) {
        pushToTalkButton.setPointerCapture(pushToTalkPointerId);
    }

    syncVoiceSessionControls();
    syncConversationControls();
    startPushToTalk();
}

function endPushToTalk(event) {
    if (!pushToTalkPressed) return;

    if (
        typeof event?.pointerId === "number" &&
        pushToTalkPointerId !== null &&
        event.pointerId !== pushToTalkPointerId
    ) {
        return;
    }

    pushToTalkPressed = false;
    pushToTalkPointerId = null;
    syncVoiceSessionControls();
    syncConversationControls();

    if (!pushToTalkOperationInProgress && pushToTalkActive) {
        stopPushToTalk();
    }
}

if (pushToTalkButton) {
    pushToTalkButton.addEventListener("pointerdown", (event) => {
        if (event.isPrimary && event.button !== 0) return;
        beginPushToTalk(event);
    });
    pushToTalkButton.addEventListener("pointerup", endPushToTalk);
    pushToTalkButton.addEventListener("pointercancel", endPushToTalk);
    pushToTalkButton.addEventListener("lostpointercapture", endPushToTalk);
    pushToTalkButton.addEventListener("keydown", (event) => {
        if (
            (event.code === "Space" || event.code === "Enter") &&
            !event.repeat
        ) {
            beginPushToTalk(event);
        }
    });
    pushToTalkButton.addEventListener("keyup", (event) => {
        if (event.code === "Space" || event.code === "Enter") {
            endPushToTalk(event);
        }
    });
    pushToTalkButton.addEventListener("click", (event) => {
        event.preventDefault();
    });
}

window.addEventListener("blur", endPushToTalk);

if (voiceSessionStartButton) {
    voiceSessionStartButton.addEventListener("click", startVoiceSession);
}

async function stopVoiceSession() {
    if (
        voiceControlRequestInProgress ||
        !voiceSessionActive ||
        voiceSessionStopping
    ) {
        return;
    }

    voiceControlRequestInProgress = true;
    voiceSessionOperation = "stopping";
    syncVoiceSessionControls();
    setConversationState("STOPPING");

    try {
        const data = await apiRequest("/api/voice/session/stop", {
            method: "POST",
            body: JSON.stringify({})
        });

        if (data.speech_stop_requested === true) {
            speechStopPending = true;
            setOrbState("interrupting");
        }

        if (typeof data.voice_session_active === "boolean") {
            voiceSessionActive = data.voice_session_active;
        }

        voiceSessionStopping =
            data.voice_session_stopping === true ||
            data.activity === "STOPPING";

        addMessage("SYSTEM", data.message || "Voice session stopping.");
    } catch (error) {
        console.error("LEWIS VOICE SESSION STOP ERROR:", error);
        addMessage("SYSTEM", "Could not stop voice session: " + error.message);
        setConversationState("ERROR");
    } finally {
        voiceControlRequestInProgress = false;
        voiceSessionOperation = null;
        syncVoiceSessionControls();
        await updateHUDStatus();
    }
}

if (voiceSessionStopButton) {
    voiceSessionStopButton.addEventListener("click", stopVoiceSession);
}

// ==================================================
// VOICE OUTPUT — FISH AUDIO / FALLBACK
// ==================================================

async function speakResponse(text) {
    if (!voiceEnabled || !voiceOutputAvailable || !text || !text.trim()) return;

    try {
        await apiRequest("/api/voice/speak", {
            method: "POST",
            body: JSON.stringify({ text })
        });
        speechStopPending = false;
    } catch (error) {
        console.error("LEWIS VOICE OUTPUT ERROR:", error);
        addMessage("SYSTEM", "Speech output could not start: " + error.message);
    }
}

async function stopSpeaking() {
    try {
        const data = await apiRequest("/api/voice/stop", {
            method: "POST",
            body: JSON.stringify({})
        });

        speechStopPending = data.speech_stop_requested === true;
        if (speechStopPending) setOrbState("interrupting");
        if (data.message) addMessage("SYSTEM", data.message);
        await updateHUDStatus();
    } catch (error) {
        console.error("LEWIS STOP SPEECH ERROR:", error);
        addMessage("SYSTEM", "Could not stop speech: " + error.message);
    }
}

if (stopSpeakingButton) {
    stopSpeakingButton.addEventListener("click", stopSpeaking);
}

// ==================================================
// VOICE OUTPUT SETTING
// ==================================================

async function setVoiceEnabled(enabled) {
    try {
        const data = await apiRequest("/api/voice/settings", {
            method: "POST",
            body: JSON.stringify({ enabled })
        });

        voiceEnabled = typeof data.voice_enabled === "boolean"
            ? data.voice_enabled
            : enabled;

        if (voiceToggle) {
            voiceToggle.checked = voiceEnabled;
            voiceToggle.setAttribute("aria-checked", String(voiceEnabled));
        }

        addMessage(
            "SYSTEM",
            voiceEnabled
                ? "Spoken responses enabled."
                : "Spoken responses disabled."
        );
    } catch (error) {
        console.error("LEWIS VOICE SETTINGS ERROR:", error);

        if (voiceToggle) voiceToggle.checked = voiceEnabled;

        addMessage("SYSTEM", "Could not change voice settings: " + error.message);
    }
}

if (voiceToggle) {
    voiceToggle.checked = voiceEnabled;

    voiceToggle.addEventListener("change", () => {
        setVoiceEnabled(voiceToggle.checked);
    });
}

// ==================================================
// HUD HELPERS
// ==================================================

function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
}

function setMeter(id, percentage) {
    const element = document.getElementById(id);
    if (!element) return;

    const numericPercentage = Number(percentage);
    if (!Number.isFinite(numericPercentage)) return;

    const safePercentage = Math.max(0, Math.min(100, numericPercentage));
    element.style.height = `${safePercentage}%`;
}

function syncAIModelControls(data) {
    if (!aiModelSelect || !Array.isArray(data.ai_models)) return;

    const selection = data.ai_selection || {
        provider: data.ai_provider?.toLowerCase(),
        model: data.ai_model
    };

    aiModelSelect.dataset.activeProvider = selection.provider || "";
    aiModelSelect.dataset.activeModel = selection.model || "";

    if (!aiModelSelectionDirty) {
        const currentOptions = Array.from(aiModelSelect.options);
        const modelOptions = data.ai_models.length
            ? data.ai_models
            : [{ provider: "", name: "No configured AI providers", model: "" }];

        const optionsChanged =
            currentOptions.length !== modelOptions.length ||
            modelOptions.some((entry, index) =>
                currentOptions[index]?.value !== entry.provider ||
                currentOptions[index]?.dataset.model !== entry.model
            );

        if (optionsChanged) {
            const options = modelOptions.map((entry) => {
                const option = document.createElement("option");
                option.value = entry.provider;
                option.dataset.model = entry.model;
                option.textContent = entry.model
                    ? `${entry.name} — ${entry.model}`
                    : entry.name;
                option.disabled = !entry.model;
                return option;
            });

            aiModelSelect.replaceChildren(...options);
        }

        const selectedOption = Array.from(aiModelSelect.options).find(
            (option) =>
                option.value === selection.provider &&
                option.dataset.model === selection.model
        );

        if (selectedOption) selectedOption.selected = true;
    }

    aiModelSelect.disabled = data.ai_models.length === 0;

    const selectedOption = aiModelSelect.selectedOptions[0];
    const isDirty =
        aiModelSelectionDirty &&
        selectedOption &&
        (
            selectedOption.value !== selection.provider ||
            selectedOption.dataset.model !== selection.model
        );

    if (applyAIModelButton) {
        applyAIModelButton.disabled = !isDirty || aiModelSelectionSaving;
    }

    if (!aiModelSelectionDirty && aiModelSelectionStatus) {
        aiModelSelectionStatus.textContent = data.ai_models.length
            ? `Active: ${data.ai_provider} — ${data.ai_model}`
            : "Configure provider credentials to select an AI model.";
    }
}

// ==================================================
// LIVE HUD TELEMETRY
// ==================================================

async function updateHUDStatus() {
    const requestId = ++statusRequestId;

    try {
        const data = await apiRequest("/api/status");
        if (requestId !== statusRequestId) return;

        const coreOnline = String(data.core || "").toUpperCase() === "ONLINE";

        const systemStatusItem = document.getElementById("systemStatusItem");

        if (systemStatusItem) {
            systemStatusItem.dataset.status = coreOnline ? "online" : "offline";
            const statusText = systemStatusItem.querySelector("strong");
            if (statusText) statusText.textContent = data.core || "UNKNOWN";
        }

        // AI
        setText("aiStatus", data.ai || "UNKNOWN");
        setText("aiProviderName", data.ai_provider || "Unavailable");
        setText("providerCardName", data.ai_provider || "Unavailable");
        setText("providerCardModel", data.ai_model || "Model not reported");
        setText("providerCardStatus", data.ai || "UNKNOWN");
        syncAIModelControls(data);

        // MEMORY
        setText("memoryStatus", data.memory || "UNKNOWN");

        const memoryStatus = String(data.memory || "UNKNOWN").toUpperCase();

        setText(
            "memoryActivityStatus",
            memoryStatus === "ACTIVE"
                ? "Memory available"
                : memoryStatus === "ERROR"
                    ? "Memory status error"
                    : "Memory unavailable"
        );

        if (typeof data.memory_count === "number") {
            setText("memoryCount", data.memory_count);
        } else {
            setText("memoryCount", "Unavailable");
        }

        // Never leave stale measurements visible when telemetry is absent.
        const cpu = Number(data.system?.cpu);
        const ram = Number(data.system?.ram);
        setText(
            "cpuValue",
            Number.isFinite(cpu) ? `${cpu.toFixed(1)}%` : "Unavailable"
        );
        setText(
            "overviewCpuValue",
            Number.isFinite(cpu) ? `${cpu.toFixed(1)}%` : "Unavailable"
        );
        setMeter("cpuMeter", Number.isFinite(cpu) ? cpu : 0);
        setMeter("overviewCpuMeter", Number.isFinite(cpu) ? cpu : 0);
        setText(
            "ramValue",
            Number.isFinite(ram) ? `${ram.toFixed(1)}%` : "Unavailable"
        );
        setText(
            "overviewRamValue",
            Number.isFinite(ram) ? `${ram.toFixed(1)}%` : "Unavailable"
        );
        setMeter("ramMeter", Number.isFinite(ram) ? ram : 0);
        setMeter("overviewRamMeter", Number.isFinite(ram) ? ram : 0);

        setText("uptimeValue", formatUptime(data.uptime));

        // CORE DISPLAY
        setText("coreValue", data.core || "UNKNOWN");

        // VOICE STATUS
        const activity = String(data.activity || "READY").toUpperCase();
        const listening = Boolean(
            data.listening || data.push_to_talk_active
        );
        const speaking = Boolean(data.speaking);
        voiceAvailable = Boolean(data.voice_available);
        voiceOutputAvailable = Boolean(data.voice_output_available);
        voiceOutputPending = Boolean(data.voice_output_pending);
        voiceSessionActive = Boolean(data.voice_session_active);
        voiceSessionStopping = Boolean(data.voice_session_stopping);
        voiceSpeaking = speaking;
        pushToTalkProcessing = Boolean(data.push_to_talk_processing);
        coreProcessing =
            Boolean(data.processing) || pushToTalkProcessing;
        pushToTalkActive = Boolean(data.push_to_talk_active);
        lastActivityState = String(data.activity || "READY");
        const voiceInputActive =
            listening || voiceSessionActive || pushToTalkActive;
        const processing =
            requestInProgress ||
            coreProcessing ||
            activity === "PROCESSING";

        const speechActive = speaking || voiceOutputPending;
        if (speechStopPending && !speechActive) {
            speechStopPending = false;
        }

        let orbState = "idle";

        if (speechStopPending && speechActive) {
            orbState = "interrupting";
        } else if (speaking) {
            orbState = "speaking";
        } else if (listening) {
            orbState = "listening";
        } else if (processing) {
            orbState = "thinking";
        } else if (activity === "TOOL EXECUTION") {
            orbState = "tool-execution";
        }

        const displayedActivity = processing ? "PROCESSING" : activity;
        setText("activityStatus", displayedActivity);
        setText("overviewActivity", displayedActivity);
        setOrbState(orbState);
        updateAdaptiveHudContext();
        setConversationState(processing ? "PROCESSING" : activity);

        setText(
            "taskTitle",
            processing ? "Processing conversation" : "No active tasks"
        );
        setText(
            "taskDescription",
            processing ? "Waiting for LEWIS response" : "Waiting for a request"
        );
        setText(
            "taskDuration",
            taskStartedAt
                ? `${Math.max(0, Math.floor((Date.now() - taskStartedAt) / 1000))}s`
                : "—"
        );
        setText("taskCount", processing ? "1 running" : "0 running");
        setText(
            "footerTaskStatus",
            processing ? "Processing conversation..." : "No active task"
        );
        setText("footerTaskPercent", processing ? "In progress" : "—");

        const taskIndicator = document.getElementById("taskIndicator");
        if (taskIndicator) taskIndicator.dataset.active = String(processing);

        const progressTrack = document.querySelector(".progress-track");
        if (progressTrack) progressTrack.dataset.active = String(processing);

        const taskProgressBar = document.getElementById("taskProgressBar");
        if (taskProgressBar) taskProgressBar.style.width = processing ? "" : "0%";

        syncConversationControls();

        setText(
            "voiceStatus",
            !voiceAvailable
                ? "UNAVAILABLE"
                : speaking
                    ? "SPEAKING"
                    : voiceOutputPending
                        ? "PREPARING"
                        : pushToTalkProcessing
                            ? "PROCESSING"
                            : voiceInputActive
                                ? "LISTENING"
                                : "INACTIVE"
        );

        setText(
            "voiceCardStatus",
            !voiceAvailable
                ? "UNAVAILABLE"
                : speaking
                    ? "SPEAKING"
                    : voiceOutputPending
                        ? "PREPARING"
                        : pushToTalkProcessing
                            ? "PROCESSING"
                            : voiceInputActive
                                ? "ACTIVE"
                                : "INACTIVE"
        );

        setText(
            "voiceInputState",
            !voiceAvailable
                ? "Unavailable"
                : voiceInputActive
                    ? "Active"
                    : "Inactive"
        );

        setText(
            "voiceOutputStatus",
            !voiceOutputAvailable
                ? "Unavailable"
                : data.voice_enabled
                    ? speaking
                        ? "Speaking"
                        : voiceOutputPending
                            ? "Preparing speech"
                            : "On"
                    : "Off"
        );

        if (voiceCard) {
            voiceCard.dataset.active = String(
                voiceAvailable &&
                (
                    speaking ||
                    voiceOutputPending ||
                    pushToTalkProcessing ||
                    listening ||
                    voiceSessionActive ||
                    pushToTalkActive
                )
            );
        }

        syncVoiceSessionControls();

        if (stopSpeakingButton) {
            stopSpeakingButton.disabled =
                !(speaking || voiceOutputPending);
            stopSpeakingButton.textContent =
                speechStopPending ? "STOPPING..." : "STOP SPEECH";
        }

        if (voiceToggle && typeof data.voice_enabled === "boolean") {
            voiceEnabled = data.voice_enabled;
            voiceToggle.checked = voiceEnabled;
        }

        const voiceEventId = Number(data.voice_event_id) || 0;

        if (voiceEventId > lastVoiceEventId && data.last_transcript) {
            lastVoiceEventId = voiceEventId;
            addMessage("YOU (VOICE)", data.last_transcript);
        }

        const voiceResponseId = Number(data.voice_response_id) || 0;

        if (voiceResponseId > lastVoiceResponseId && data.last_response) {
            lastVoiceResponseId = voiceResponseId;
            addMessage("LEWIS", data.last_response);
        }

        setText("voiceError", data.last_error || "");

        document.body.classList.toggle("lewis-offline", !coreOnline);
    } catch (error) {
        if (requestId !== statusRequestId) return;

        console.error("LEWIS STATUS ERROR:", error);

        setText("coreStatus", "OFFLINE");
        setText("aiStatus", "OFFLINE");
        setText("aiProviderName", "Unavailable");
        setText("providerCardName", "Unavailable");
        setText("providerCardStatus", "OFFLINE");
        setText("memoryStatus", "OFFLINE");
        setText("memoryCount", "Unavailable");
        setText("coreValue", "OFFLINE");
        setText("voiceStatus", "UNAVAILABLE");
        setText("voiceCardStatus", "UNAVAILABLE");
        setText("voiceInputState", "Unavailable");
        setText("voiceOutputStatus", "Unavailable");
        setText("activityStatus", "UNAVAILABLE");
        setText("overviewActivity", "UNAVAILABLE");
        setText("overviewCpuValue", "Unavailable");
        setText("overviewRamValue", "Unavailable");
        setText("uptimeValue", "Unavailable");
        setMeter("overviewCpuMeter", 0);
        setMeter("overviewRamMeter", 0);

        voiceAvailable = false;
        voiceOutputAvailable = false;
        voiceOutputPending = false;
        voiceSessionActive = false;
        voiceSessionStopping = false;
        voiceSpeaking = false;
        coreProcessing = false;
        pushToTalkActive = false;
        pushToTalkProcessing = false;
        speechStopPending = false;
        lastActivityState = "UNAVAILABLE";
        setOrbState("idle");
        updateAdaptiveHudContext();

        syncVoiceSessionControls();
        syncConversationControls();
        setText("memoryActivityStatus", "Status unavailable");
        setText("cpuValue", "Unavailable");
        setText("ramValue", "Unavailable");
        setMeter("cpuMeter", 0);
        setMeter("ramMeter", 0);
        setText("taskTitle", "Status unavailable");
        setText("taskDescription", "Cannot verify active tasks");
        setText("taskDuration", "—");
        setText("taskCount", "Unavailable");
        setText("footerTaskStatus", "Status unavailable");
        setText("footerTaskPercent", "—");

        const taskIndicator = document.getElementById("taskIndicator");
        if (taskIndicator) taskIndicator.dataset.active = "false";

        const progressTrack = document.querySelector(".progress-track");
        if (progressTrack) progressTrack.dataset.active = "false";

        const taskProgressBar = document.getElementById("taskProgressBar");
        if (taskProgressBar) taskProgressBar.style.width = "0%";

        if (voiceCard) voiceCard.dataset.active = "false";
        if (stopSpeakingButton) {
            stopSpeakingButton.disabled = true;
            stopSpeakingButton.textContent = "STOP SPEECH";
        }

        setOrbState(
            speechStopPending
                ? "interrupting"
                : requestInProgress
                    ? "thinking"
                    : "idle"
        );
        setConversationState(requestInProgress ? "PROCESSING" : "OFFLINE");

        if (systemStatusItem) {
            systemStatusItem.dataset.status = "offline";
            const statusText = systemStatusItem.querySelector("strong");
            if (statusText) statusText.textContent = "OFFLINE";
        }

        document.body.classList.add("lewis-offline");
    }
}

if (aiModelSelect) {
    aiModelSelect.addEventListener("change", () => {
        const selectedOption = aiModelSelect.selectedOptions[0];

        aiModelSelectionDirty = Boolean(
            selectedOption &&
            (
                selectedOption.value !== aiModelSelect.dataset.activeProvider ||
                selectedOption.dataset.model !== aiModelSelect.dataset.activeModel
            )
        );

        if (aiModelSelectionDirty && aiModelSelectionStatus) {
            aiModelSelectionStatus.textContent = "Selection not applied.";
        }

        syncAIModelControls({
            ai_models: Array.from(aiModelSelect.options).map((option) => ({
                provider: option.value,
                model: option.dataset.model,
                name: option.textContent.split(" — ", 1)[0]
            })),
            ai_selection: {
                provider: aiModelSelect.dataset.activeProvider,
                model: aiModelSelect.dataset.activeModel
            }
        });
    });
}

if (applyAIModelButton) {
    applyAIModelButton.addEventListener("click", async () => {
        const option = aiModelSelect?.selectedOptions[0];

        if (!option || !option.dataset.model || aiModelSelectionSaving) return;

        aiModelSelectionSaving = true;
        applyAIModelButton.disabled = true;

        if (aiModelSelectionStatus) {
            aiModelSelectionStatus.textContent = "Applying selection...";
        }

        try {
            await apiRequest("/api/ai/model", {
                method: "POST",
                body: JSON.stringify({
                    provider: option.value,
                    model: option.dataset.model
                })
            });

            aiModelSelectionDirty = false;

            if (aiModelSelectionStatus) {
                aiModelSelectionStatus.textContent = "Selection applied.";
            }

            await updateHUDStatus();
        } catch (error) {
            console.error("LEWIS AI MODEL SELECTION ERROR:", error);

            if (aiModelSelectionStatus) {
                aiModelSelectionStatus.textContent =
                    `Could not apply selection: ${error.message}`;
            }
        } finally {
            aiModelSelectionSaving = false;
            syncAIModelControlsFromCurrent();
        }
    });
}

function syncAIModelControlsFromCurrent() {
    if (!aiModelSelect || !applyAIModelButton) return;

    const activeOption = Array.from(aiModelSelect.options).find(
        (option) =>
            option.value === aiModelSelect.dataset.activeProvider &&
            option.dataset.model === aiModelSelect.dataset.activeModel
    );

    const selectedOption = aiModelSelect.selectedOptions[0];

    const isDirty = selectedOption && (
        selectedOption.value !== activeOption?.value ||
        selectedOption.dataset.model !== activeOption?.dataset.model
    );

    applyAIModelButton.disabled = !isDirty || aiModelSelectionSaving;
}

// ==================================================
// PANEL CONTROLS
// ==================================================

function syncPanelButtons() {
    if (!hud) return;

    const leftVisible = !hud.classList.contains("left-panel-collapsed");
    const rightVisible = !hud.classList.contains("right-panel-collapsed");

    if (toggleLeftPanelButton) {
        toggleLeftPanelButton.setAttribute("aria-expanded", String(leftVisible));
    }

    if (toggleRightPanelButton) {
        toggleRightPanelButton.setAttribute("aria-expanded", String(rightVisible));
    }

    if (toggleSidePanelsButton) {
        toggleSidePanelsButton.setAttribute(
            "aria-expanded",
            String(leftVisible || rightVisible)
        );
    }

    updateAdaptiveHudContext();
}

function setFocusMode(enabled) {
    if (!hud) return;

    closeWorkspaceView();
    closeConversationDrawer();

    if (enabled && !hud.classList.contains("focus-mode")) {
        focusModePanelState = {
            leftCollapsed: hud.classList.contains("left-panel-collapsed"),
            rightCollapsed: hud.classList.contains("right-panel-collapsed")
        };
        hud.classList.add("focus-mode");
        document.body.classList.add("focus-mode-active");
    } else if (!enabled && hud.classList.contains("focus-mode")) {
        hud.classList.remove("focus-mode");
        hud.classList.toggle(
            "left-panel-collapsed",
            focusModePanelState?.leftCollapsed ?? true
        );
        hud.classList.toggle(
            "right-panel-collapsed",
            focusModePanelState?.rightCollapsed ?? true
        );
        focusModePanelState = null;
        document.body.classList.remove("focus-mode-active");
    }

    syncFocusTranscriptSizing();
    toggleFocusModeButton?.setAttribute("aria-pressed", String(enabled));
    if (toggleFocusModeButton) {
        toggleFocusModeButton.textContent = enabled ? "FULL" : "FOCUS";
    }
    syncPanelButtons();
}

function applyTheme(theme) {
    const selectedTheme = theme === "dark" ? "dark" : "light";
    const nextTheme = selectedTheme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = selectedTheme;
    document.documentElement.style.colorScheme = selectedTheme;

    const themeColor = document.querySelector('meta[name="theme-color"]');
    if (themeColor) {
        themeColor.content = selectedTheme === "dark" ? "#17191C" : "#F5F6F7";
    }

    if (toggleThemeButton) {
        toggleThemeButton.textContent = nextTheme.toUpperCase();
        toggleThemeButton.setAttribute(
            "aria-label",
            `Switch to ${nextTheme} theme`
        );
        toggleThemeButton.setAttribute(
            "aria-pressed",
            String(selectedTheme === "dark")
        );
        toggleThemeButton.title = `Switch to ${nextTheme} theme`;
    }
}

function initializeHudPreferences() {
    try {
        const saved = window.localStorage.getItem(HUD_PREFERENCES_KEY);
        if (saved) {
            const parsed = JSON.parse(saved);
            if (parsed && typeof parsed === "object") {
                if (typeof parsed.orbMotion === "boolean") {
                    hudPreferences.orbMotion = parsed.orbMotion;
                }
                if (typeof parsed.soundPreviewEnabled === "boolean") {
                    hudPreferences.soundPreviewEnabled =
                        parsed.soundPreviewEnabled;
                }
                if (typeof parsed.soundMuted === "boolean") {
                    hudPreferences.soundMuted = parsed.soundMuted;
                }
                if (
                    typeof parsed.soundVolume === "number" &&
                    Number.isFinite(parsed.soundVolume)
                ) {
                    hudPreferences.soundVolume =
                        Math.min(100, Math.max(0, parsed.soundVolume));
                }
                if (["soft", "clear"].includes(parsed.soundProfile)) {
                    hudPreferences.soundProfile = parsed.soundProfile;
                }
            }
        }
    } catch (error) {
        console.warn("LEWIS HUD PREFERENCE LOAD ERROR:", error);
    }
    applyHudPreferences();
}

function saveHudPreferences() {
    try {
        window.localStorage.setItem(
            HUD_PREFERENCES_KEY,
            JSON.stringify(hudPreferences)
        );
    } catch (error) {
        console.warn("LEWIS HUD PREFERENCE SAVE ERROR:", error);
    }
}

function applyHudPreferences() {
    hud?.classList.toggle(
        "orb-motion-disabled",
        !hudPreferences.orbMotion
    );
}

async function playInterfaceSoundPreview() {
    if (
        !hudPreferences.soundPreviewEnabled ||
        hudPreferences.soundMuted ||
        voiceSpeaking ||
        voiceOutputPending
    ) {
        return false;
    }

    const AudioContextConstructor =
        window.AudioContext || window.webkitAudioContext;
    if (!AudioContextConstructor) {
        throw new Error("This browser does not support Web Audio.");
    }
    if (!interfaceAudioContext) {
        interfaceAudioContext = new AudioContextConstructor();
    }
    if (interfaceAudioContext.state === "suspended") {
        await interfaceAudioContext.resume();
    }

    const oscillator = interfaceAudioContext.createOscillator();
    const volume = interfaceAudioContext.createGain();
    const now = interfaceAudioContext.currentTime;
    const peak = Math.max(0.0001, hudPreferences.soundVolume / 100 * 0.12);
    oscillator.type = "sine";
    oscillator.frequency.value =
        hudPreferences.soundProfile === "clear" ? 740 : 440;
    volume.gain.setValueAtTime(0.0001, now);
    volume.gain.exponentialRampToValueAtTime(peak, now + 0.015);
    volume.gain.exponentialRampToValueAtTime(0.0001, now + 0.16);
    oscillator.connect(volume);
    volume.connect(interfaceAudioContext.destination);
    oscillator.start(now);
    oscillator.stop(now + 0.17);
    return true;
}

function initializeTheme() {
    let theme = "light";

    try {
        const savedTheme = window.localStorage.getItem("lewis-hud-theme");
        if (savedTheme === "light" || savedTheme === "dark") {
            theme = savedTheme;
        }
    } catch (error) {
        console.warn("LEWIS THEME PREFERENCE LOAD ERROR:", error);
    }

    applyTheme(theme);
}

if (toggleThemeButton) {
    toggleThemeButton.addEventListener("click", () => {
        const nextTheme =
            document.documentElement.dataset.theme === "dark" ? "light" : "dark";
        applyTheme(nextTheme);

        try {
            window.localStorage.setItem("lewis-hud-theme", nextTheme);
        } catch (error) {
            console.warn("LEWIS THEME PREFERENCE SAVE ERROR:", error);
        }
    });
}

initializeTheme();
initializeHudPreferences();

if (hud && toggleLeftPanelButton) {
    toggleLeftPanelButton.addEventListener("click", () => {
        hud.classList.toggle("left-panel-collapsed");
        syncPanelButtons();
    });
}

if (hud && toggleRightPanelButton) {
    toggleRightPanelButton.addEventListener("click", () => {
        hud.classList.toggle("right-panel-collapsed");
        syncPanelButtons();
    });
}

if (hud && toggleSidePanelsButton) {
    toggleSidePanelsButton.addEventListener("click", () => {
        const bothHidden =
            hud.classList.contains("left-panel-collapsed") &&
            hud.classList.contains("right-panel-collapsed");

        if (bothHidden) {
            hud.classList.remove("left-panel-collapsed", "right-panel-collapsed");
        } else {
            hud.classList.add("left-panel-collapsed", "right-panel-collapsed");
        }

        syncPanelButtons();
    });
}

if (hud && toggleFocusModeButton) {
    toggleFocusModeButton.addEventListener("click", () => {
        setFocusMode(!hud.classList.contains("focus-mode"));
    });
}

syncPanelButtons();

// ==================================================
// LIVE SYSTEM LOG
// ==================================================

async function updateSystemLog() {
    const logContainer =
        document.querySelector(".recent-activity-list") ||
        document.querySelector(".system-log");
    if (!logContainer) return;

    try {
        const data = await apiRequest("/api/logs");

        if (!Array.isArray(data.logs)) {
            console.warn("LEWIS SYSTEM LOG: invalid log format.");
            return;
        }

        logContainer.replaceChildren();

        const recentLogs = data.logs.slice(-4);
        setText("notificationCount", recentLogs.length);
        setText(
            "recentActivityCount",
            `${recentLogs.length} ${recentLogs.length === 1 ? "EVENT" : "EVENTS"}`
        );

        if (!recentLogs.length) {
            const empty = document.createElement("span");
            empty.className = "empty-log";
            empty.textContent = "No recent system events";
            logContainer.appendChild(empty);
            return;
        }

        recentLogs.forEach((entry) => {
            const line = document.createElement("div");
            line.className = "system-log-entry";

            const message = document.createElement("span");
            message.textContent = String(entry.message || "System event");

            const time = document.createElement("time");
            time.textContent = String(entry.time || "");

            line.append(message, time);
            logContainer.appendChild(line);
        });
    } catch (error) {
        console.error("LEWIS LOG ERROR:", error);
    }
}

// ==================================================
// START LIVE SYSTEMS
// ==================================================

syncVoiceSessionControls();
syncConversationControls();

refreshConversationList().catch((error) => {
    console.error("LEWIS CONVERSATION LOAD ERROR:", error);
    addMessage(
        "SYSTEM",
        `Conversation history could not be loaded: ${error.message}`
    );
});

updateHUDStatus();
updateSystemLog();
updateClock();

setInterval(updateHUDStatus, 1000);
setInterval(updateSystemLog, 1000);
setInterval(updateClock, 30_000);

// ==================================================
// INITIAL MESSAGE
// ==================================================

addMessage("SYSTEM", "LEWIS HUD interface initialized.");