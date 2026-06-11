const $ = (sel) => document.querySelector(sel);

const ui = {
    usernameInput: $("#username-input"),
    btnConnect: $("#btn-connect"),
    btnPause: $("#btn-pause"),
    btnStop: $("#btn-stop"),
    btnSave: $("#btn-save-settings"),
    aiModel: $("#ai-model"),
    openaiKey: $("#openai-key"),
    openaiKeyRow: $("#openai-key-row"),
    toggleOpenaiKey: $("#toggle-openai-key"),
    tavilyKey: $("#tavily-key"),
    toggleTavilyKey: $("#toggle-tavily-key"),
    ttsVoice: $("#tts-voice"),
    systemPrompt: $("#system-prompt"),
    thankFollowers: $("#thank-followers"),
    thankGifts: $("#thank-gifts"),
    memoryList: $("#memory-list"),
    memoryCount: $("#memory-count"),
    btnRefreshMemory: $("#btn-refresh-memory"),
    btnClearMemory: $("#btn-clear-memory"),
    statusBadge: $("#status-badge"),
    statusText: $("#status-text"),
    chatLog: $("#chat-log"),
    msgCounter: $("#msg-counter"),
};

let ws = null;
let currentState = "stopped";
let msgCount = 0;

// --- WebSocket ---

function connectWS() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/ws`);

    ws.onopen = () => console.log("WebSocket connected");

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleWSMessage(data);
    };

    ws.onclose = () => {
        console.log("WebSocket disconnected, reconnecting...");
        setTimeout(connectWS, 2000);
    };
}

function handleWSMessage(data) {
    switch (data.type) {
        case "status":
            updateStatus(data.state, data.error);
            break;
        case "connected":
            break;
        case "chat":
            addChatEntry(data.username, data.message, null);
            break;
        case "response":
            addChatEntry(data.username, data.message, data.response, data.web_search, data.recall, data.tool_log);
            break;
        case "follow":
            addFollowEntry(data.username, data.message);
            break;
        case "gift":
            addGiftEntry(data.username, data.message, data.gift, data.count, data.diamonds);
            break;
        case "error":
            addChatEntry(data.username, data.message, `⚠ ${data.error}`, false, false, data.tool_log);
            break;
    }
}

function addFollowEntry(username, message) {
    const empty = ui.chatLog.querySelector(".chat-empty");
    if (empty) empty.remove();

    const div = document.createElement("div");
    div.className = "chat-entry follow-entry";
    div.innerHTML = `<div class="chat-msg">
        <span class="follow-badge">nuovo follower</span>
        <span class="chat-user">${escapeHtml(username)}</span>
    </div>
    <div class="bot-response">${escapeHtml(message)}</div>`;

    ui.chatLog.appendChild(div);
    ui.chatLog.scrollTop = ui.chatLog.scrollHeight;

    msgCount++;
    ui.msgCounter.textContent = `${msgCount} messaggi`;
}

function updateStatus(state, error) {
    currentState = state;

    ui.statusBadge.className = `status-badge ${state}`;

    const labels = {
        stopped: "Disconnesso",
        running: "Connesso",
        paused: "In pausa",
    };
    ui.statusText.textContent = error
        ? `Errore: ${error}`
        : labels[state] || state;

    const isRunning = state === "running" || state === "paused";
    ui.btnConnect.disabled = isRunning;
    ui.btnPause.disabled = !isRunning;
    ui.btnStop.disabled = !isRunning;
    ui.btnPause.textContent = state === "paused" ? "Riprendi" : "Pausa";
}

function addChatEntry(username, message, response, webSearch, recall, toolLog) {
    // Remove empty state message
    const empty = ui.chatLog.querySelector(".chat-empty");
    if (empty) empty.remove();

    const div = document.createElement("div");
    const isCommand = message.trim().toLowerCase().startsWith("/bot");

    if (response) {
        div.className = "chat-entry has-response";
    } else if (isCommand) {
        div.className = "chat-entry";
    } else {
        div.className = "chat-entry chat-only";
    }

    const displayMsg = isCommand ? message.trim().substring(4).trim() : message;
    const commandTag = isCommand ? ' <span class="chat-command">/bot</span>' : "";

    let html = `<div class="chat-msg">
        <span class="chat-user">${escapeHtml(username)}</span>${commandTag}
        <span class="chat-text">${escapeHtml(displayMsg)}</span>
    </div>`;

    if (response) {
        const searchTag = webSearch ? '<span class="search-badge">web search</span>' : "";
        const recallTag = recall ? '<span class="memory-badge">memoria</span>' : "";
        html += `<div class="bot-response">${searchTag}${recallTag}${escapeHtml(response)}</div>`;
    }

    // Diagnostic line(s): what tools the bot called and their outcome. Only the
    // operator sees the dashboard, so this is for debugging, not the audience.
    if (toolLog && toolLog.length) {
        const lines = toolLog
            .map((t) => `<div class="tool-log-line">🔧 ${escapeHtml(t)}</div>`)
            .join("");
        html += `<div class="tool-log">${lines}</div>`;
    }

    div.innerHTML = html;
    ui.chatLog.appendChild(div);
    ui.chatLog.scrollTop = ui.chatLog.scrollHeight;

    msgCount++;
    ui.msgCounter.textContent = `${msgCount} messaggi`;
}

function addGiftEntry(username, message, gift, count, diamonds) {
    const empty = ui.chatLog.querySelector(".chat-empty");
    if (empty) empty.remove();

    const div = document.createElement("div");
    div.className = "chat-entry gift-entry";
    const giftLabel = count > 1 ? `${gift} ×${count}` : gift;
    const diamondTag = diamonds
        ? `<span class="gift-diamonds">💎 ${diamonds}</span>`
        : "";
    div.innerHTML = `<div class="chat-msg">
        <span class="gift-badge">regalo</span>
        <span class="chat-user">${escapeHtml(username)}</span>
        <span class="chat-text">${escapeHtml(giftLabel)}</span>
        ${diamondTag}
    </div>
    <div class="bot-response">${escapeHtml(message)}</div>`;

    ui.chatLog.appendChild(div);
    ui.chatLog.scrollTop = ui.chatLog.scrollHeight;

    msgCount++;
    ui.msgCounter.textContent = `${msgCount} messaggi`;
}

function escapeHtml(text) {
    const d = document.createElement("div");
    d.textContent = text;
    return d.innerHTML;
}

// --- API calls ---

async function api(method, path, body) {
    const opts = { method, headers: { "Content-Type": "application/json" } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(path, opts);
    return res.json();
}

// --- Event listeners ---

ui.btnConnect.addEventListener("click", async () => {
    const username = ui.usernameInput.value.trim().replace(/^@/, "");
    if (!username) return;
    ui.btnConnect.disabled = true;
    ui.btnConnect.textContent = "Connessione...";
    await api("POST", "/api/start", { username });
    ui.btnConnect.textContent = "Connetti";
});

ui.btnPause.addEventListener("click", () => api("POST", "/api/pause"));
ui.btnStop.addEventListener("click", () => api("POST", "/api/stop"));

// Eye toggle: reveal/hide an API key field. The inputs stay deliberately
// narrow, so even when revealed during a live stream only a slice is visible.
function bindEye(button, input) {
    button.addEventListener("click", () => {
        input.type = input.type === "password" ? "text" : "password";
    });
}
bindEye(ui.toggleOpenaiKey, ui.openaiKey);
bindEye(ui.toggleTavilyKey, ui.tavilyKey);

// Which models require the user's OpenAI key (the cloud ones). Filled when the
// catalog loads, so we can show/hide the key field for the selected model.
let modelNeedsKey = {};

// The OpenAI key only matters for models that use OpenAI; hide it otherwise.
function updateKeyVisibility() {
    ui.openaiKeyRow.style.display =
        modelNeedsKey[ui.aiModel.value] ? "" : "none";
}
ui.aiModel.addEventListener("change", updateKeyVisibility);

// --- Tabs ---

document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
});

function switchTab(name) {
    document.querySelectorAll(".tab").forEach((t) =>
        t.classList.toggle("active", t.dataset.tab === name)
    );
    document.querySelectorAll(".view").forEach((v) =>
        v.classList.toggle("active", v.id === `view-${name}`)
    );
    // Refresh memory whenever the settings tab is opened, so it reflects what
    // the bot just stored without a manual click.
    if (name === "settings") loadMemory();
}

// --- Memory viewer ---

async function loadMemory() {
    const data = await api("GET", "/api/memory");
    if (!data) return;
    ui.memoryCount.textContent = `${data.count} voci`;
    ui.memoryList.innerHTML = "";
    if (!data.entries.length) {
        ui.memoryList.innerHTML =
            '<div class="chat-empty">Nessun ricordo salvato.</div>';
        return;
    }
    for (const e of data.entries) {
        const div = document.createElement("div");
        div.className = "memory-entry";
        const when = e.ts
            ? new Date(e.ts * 1000).toLocaleString("it-IT")
            : (e.date || "");
        const kind = e.kind === "bot_qa" ? "Q&A bot" : "chat";
        let html = `<div class="memory-meta">
            <span class="memory-when">${escapeHtml(when)}</span>
            <span class="memory-user">${escapeHtml(e.username || "?")}</span>
            <span class="memory-kind">${kind}</span>
        </div>
        <div class="memory-msg">${escapeHtml(e.message || "")}</div>`;
        if (e.response) {
            html += `<div class="memory-resp">${escapeHtml(e.response)}</div>`;
        }
        div.innerHTML = html;
        ui.memoryList.appendChild(div);
    }
}

ui.btnRefreshMemory.addEventListener("click", loadMemory);

ui.btnClearMemory.addEventListener("click", async () => {
    if (!confirm("Svuotare tutta la memoria del bot? L'azione è irreversibile.")) {
        return;
    }
    await api("DELETE", "/api/memory");
    loadMemory();
});

// Build the single "Modello" dropdown from the backend catalog — the provider
// behind each option is resolved server-side, never shown to the user.
async function loadModels() {
    const models = await api("GET", "/api/models");
    if (!models) return;
    ui.aiModel.innerHTML = "";
    for (const m of models) {
        modelNeedsKey[m.id] = m.needs_key;
        const opt = document.createElement("option");
        opt.value = m.id;
        opt.textContent = m.label;
        ui.aiModel.appendChild(opt);
    }
}

ui.btnSave.addEventListener("click", async () => {
    await api("PUT", "/api/settings", {
        model_id: ui.aiModel.value,
        openai_api_key: ui.openaiKey.value,
        tavily_api_key: ui.tavilyKey.value,
        tts_voice: ui.ttsVoice.value,
        system_prompt: ui.systemPrompt.value,
        thank_followers: ui.thankFollowers.checked,
        thank_gifts: ui.thankGifts.checked,
    });
    ui.btnSave.textContent = "Salvato!";
    ui.btnSave.classList.add("saved");
    setTimeout(() => {
        ui.btnSave.textContent = "Salva";
        ui.btnSave.classList.remove("saved");
    }, 1500);
});

// --- Init ---

async function init() {
    connectWS();
    // Populate the model dropdown before applying status, so the saved model_id
    // can actually be selected.
    await loadModels();
    const status = await api("GET", "/api/status");
    if (status) {
        updateStatus(status.state);
        if (status.username) {
            ui.usernameInput.value = status.username;
        }
        if (status.model_id) ui.aiModel.value = status.model_id;
        if (status.tts_voice) ui.ttsVoice.value = status.tts_voice;
        if (status.system_prompt) ui.systemPrompt.value = status.system_prompt;
        ui.openaiKey.value = status.openai_api_key || "";
        ui.tavilyKey.value = status.tavily_api_key || "";
        ui.thankFollowers.checked = status.thank_followers !== false;
        ui.thankGifts.checked = status.thank_gifts !== false;
        updateKeyVisibility();
    }
}

init();
