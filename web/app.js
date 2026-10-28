const $ = (id) => document.getElementById(id);
const transcript = $("transcript");

let history = [];
let busy = false;
let allMemories = [];

const SUGGESTIONS = [
  "I'm building a robotics side project in Rust and I keep hitting lifetime errors. Remember that.",
  "What do you know about me so far?",
  "Research what changed in open-weight reasoning models this month, then file the conclusion.",
  "Give me my daily brief.",
];

const TOOL_LABELS = {
  remember: "wrote memory",
  recall: "searched memory",
  web_search: "searched the web",
  think_harder: "escalated",
  load_skill: "loaded skill",
};

/* ---------- rendering ---------- */

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

// Deliberately tiny: bold, inline code, and links. Not a full Markdown parser.
function lightMarkup(text) {
  return esc(text)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/(https?:\/\/[^\s<)]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
}

function renderDemoPill(turnsLeft) {
  const pill = $("demoPill");
  if (turnsLeft === null || turnsLeft === undefined) {
    pill.hidden = true;
    return;
  }
  pill.hidden = false;
  pill.textContent = `Demo \u00b7 ${turnsLeft} message${turnsLeft === 1 ? "" : "s"} left`;
  pill.classList.toggle("low", turnsLeft <= 5);
}

function clearEmpty() {
  const empty = $("empty");
  if (empty) empty.remove();
}

function addMessage(role, text) {
  clearEmpty();
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;
  wrap.innerHTML =
    `<div class="who">${role === "user" ? "You" : "Mnemo"}</div>` +
    `<div class="bubble">${role === "user" ? esc(text) : lightMarkup(text)}</div>`;
  transcript.appendChild(wrap);
  transcript.scrollTop = transcript.scrollHeight;
  return wrap;
}

function addThinking() {
  clearEmpty();
  const el = document.createElement("div");
  el.className = "msg assistant";
  el.id = "thinking";
  el.innerHTML =
    '<div class="who">Mnemo</div><div class="thinking"><span class="dot"></span>Working&hellip;</div>';
  transcript.appendChild(el);
  transcript.scrollTop = transcript.scrollHeight;
  return el;
}

function renderTrace(events, modelsUsed) {
  if (!events?.length && !modelsUsed?.length) return "";
  const items = (events || [])
    .map((e) => {
      const label =
        e.tool === "remember" && e.deduped
          ? "updated memory"
          : TOOL_LABELS[e.tool] || e.tool;
      const cls = e.tool === "think_harder" ? "trace-item escalate" : "trace-item";
      return `<div class="${cls}"><span class="t-name">${esc(label)}</span>` +
             `<span>${esc(e.detail || "")}</span></div>`;
    })
    .join("");
  const models = (modelsUsed || []).length
    ? `<div class="models">served by ${modelsUsed.map((m) => `<code>${esc(m)}</code>`).join(" + ")} on Nebius Token Factory</div>`
    : "";
  return `<div class="trace">${items}</div>${models}`;
}

/* ---------- chat ---------- */

async function send(text) {
  if (busy || !text.trim()) return;
  busy = true;
  $("send").disabled = true;
  addMessage("user", text);
  const thinking = addThinking();

  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history }),
    });
    const data = await resp.json();
    thinking.remove();

    if (!resp.ok) {
      clearEmpty();
      const el = document.createElement("div");
      el.className = "msg assistant";
      el.innerHTML = `<div class="who">Mnemo</div><div class="error">${esc(data.detail || "Request failed.")}</div>`;
      transcript.appendChild(el);
    } else {
      const wrap = document.createElement("div");
      wrap.className = "msg assistant";
      wrap.innerHTML =
        '<div class="who">Mnemo</div>' +
        renderTrace(data.events, data.models_used) +
        `<div class="bubble">${lightMarkup(data.reply)}</div>`;
      transcript.appendChild(wrap);

      history.push({ role: "user", content: text });
      history.push({ role: "assistant", content: data.reply });
      history = history.slice(-20);
      renderDemoPill(data.turns_left);

      const touched = (data.events || [])
        .filter((e) => e.tool === "remember" && e.memory_id)
        .map((e) => e.memory_id);
      await loadMemories(touched);
    }
  } catch (err) {
    thinking.remove();
    const el = document.createElement("div");
    el.className = "msg assistant";
    el.innerHTML = `<div class="who">Mnemo</div><div class="error">${esc(String(err))}</div>`;
    transcript.appendChild(el);
  } finally {
    busy = false;
    $("send").disabled = false;
    transcript.scrollTop = transcript.scrollHeight;
    $("input").focus();
  }
}

/* ---------- memory pane ---------- */

function renderMemories(flashIds = []) {
  const filter = $("memSearch").value.trim().toLowerCase();
  const rows = filter
    ? allMemories.filter(
        (m) =>
          m.text.toLowerCase().includes(filter) ||
          m.kind.includes(filter) ||
          (m.tags || []).some((t) => t.toLowerCase().includes(filter))
      )
    : allMemories;

  $("memCount").textContent = allMemories.length;
  const list = $("memories");

  if (!rows.length) {
    list.innerHTML = `<p class="hint">${
      allMemories.length ? "Nothing matches that filter." :
      "No memories yet. Tell it something about yourself, or add one directly above."
    }</p>`;
    return;
  }

  list.innerHTML = rows
    .map(
      (m) => `
    <li class="${m.pinned ? "pinned" : ""} ${flashIds.includes(m.id) ? "flash" : ""}" data-id="${m.id}">
      <div class="mem-top">
        <span class="mem-meta">#${m.id} &middot; ${esc(m.kind)} &middot; ${esc(m.source)}</span>
      </div>
      <p class="mem-text" data-id="${m.id}">${esc(m.text)}</p>
      ${(m.tags || []).length ? `<div class="mem-tags">${m.tags.map((t) => `<span>${esc(t)}</span>`).join("")}</div>` : ""}
      <div class="mem-actions">
        <button data-act="pin" data-id="${m.id}">${m.pinned ? "Unpin" : "Pin"}</button>
        <button data-act="edit" data-id="${m.id}">Edit</button>
        <button class="del" data-act="del" data-id="${m.id}">Delete</button>
      </div>
    </li>`
    )
    .join("");
}

async function loadMemories(flashIds = []) {
  const resp = await fetch("/api/memories");
  const data = await resp.json();
  allMemories = data.memories || [];
  renderMemories(flashIds);
}

async function loadSkills() {
  const resp = await fetch("/api/skills");
  const data = await resp.json();
  $("skills").innerHTML = (data.skills || []).length
    ? data.skills
        .map(
          (s) => `<li>
            <h3>${esc(s.name)}</h3>
            <p>${esc(s.description)}</p>
            <div class="file">${esc(s.file)}</div>
            <pre>${esc(s.body)}</pre>
          </li>`
        )
        .join("")
    : '<p class="hint">No skills found. Drop a Markdown file into <code>skills/</code>.</p>';
}

async function loadHealth() {
  const status = $("status");
  try {
    const resp = await fetch("/api/health");
    const h = await resp.json();

    if (!h.nebius_configured) {
      status.textContent = "NEBIUS_API_KEY missing";
      status.className = "status bad";
    } else if (!h.tavily_configured) {
      status.textContent = "Token Factory connected · web search off";
      status.className = "status warn";
    } else {
      status.textContent = "Token Factory + Tavily connected";
      status.className = "status ok";
    }

    renderDemoPill(h.turns_left);
    if (h.demo_mode) {
      const empty = $("empty");
      if (empty) {
        const note = document.createElement("p");
        note.className = "hint";
        note.style.marginTop = "18px";
        note.textContent =
          "Public demo: these memories are yours alone, kept against a cookie in " +
          "your browser, and nobody else can see them.";
        empty.appendChild(note);
      }
    }

    const row = (k, v, cls = "") =>
      `<li><span class="k">${esc(k)}</span><span class="v ${cls}">${esc(v)}</span></li>`;
    $("config").innerHTML = [
      row("Inference", "Nebius Token Factory"),
      row("Base URL", h.base_url),
      row("Fast model", h.model_fast, "on"),
      row("Reasoning model", h.model_deep, "on"),
      row("Nebius API key", h.nebius_configured ? "set" : "missing",
          h.nebius_configured ? "on" : "off"),
      row("Tavily API key", h.tavily_configured ? "set" : "missing",
          h.tavily_configured ? "on" : "off"),
      row("Memories stored", String(h.memory?.total ?? 0)),
      row("Skills loaded", String((h.skills || []).length)),
      row("Memory file", h.db_path),
    ].join("");
  } catch {
    status.textContent = "Server unreachable";
    status.className = "status bad";
  }
}

/* ---------- events ---------- */

$("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $("input");
  const text = input.value;
  input.value = "";
  input.style.height = "auto";
  send(text);
});

$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("composer").requestSubmit();
  }
});

$("input").addEventListener("input", (e) => {
  e.target.style.height = "auto";
  e.target.style.height = Math.min(e.target.scrollHeight, 160) + "px";
});

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => {
      t.classList.toggle("active", t === tab);
      t.setAttribute("aria-selected", String(t === tab));
    });
    document.querySelectorAll(".tab-panel").forEach((p) => {
      p.classList.toggle("active", p.id === `panel-${tab.dataset.tab}`);
    });
  });
});

$("memSearch").addEventListener("input", () => renderMemories());

$("addMemory").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("newMemText");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  await fetch("/api/memories", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, kind: "note", tags: [] }),
  });
  await loadMemories();
});

$("memories").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const id = Number(btn.dataset.id);
  const mem = allMemories.find((m) => m.id === id);

  if (btn.dataset.act === "del") {
    await fetch(`/api/memories/${id}`, { method: "DELETE" });
    await loadMemories();
    return;
  }

  if (btn.dataset.act === "pin") {
    await fetch(`/api/memories/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pinned: !mem.pinned }),
    });
    await loadMemories();
    return;
  }

  if (btn.dataset.act === "edit") {
    const p = document.querySelector(`.mem-text[data-id="${id}"]`);
    if (!p) return;
    const editing = p.getAttribute("contenteditable") === "true";
    if (editing) {
      const text = p.textContent.trim();
      p.setAttribute("contenteditable", "false");
      btn.textContent = "Edit";
      if (text && text !== mem.text) {
        await fetch(`/api/memories/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        await loadMemories();
      }
    } else {
      p.setAttribute("contenteditable", "true");
      p.focus();
      btn.textContent = "Save";
    }
  }
});

$("wipeBtn").addEventListener("click", async () => {
  if (!confirm("Delete every stored memory? This cannot be undone.")) return;
  await fetch("/api/memories/wipe", { method: "POST" });
  await loadMemories();
});

/* ---------- boot ---------- */

$("suggestions").innerHTML = SUGGESTIONS.map(
  (s) => `<button type="button">${esc(s)}</button>`
).join("");
$("suggestions").addEventListener("click", (e) => {
  const btn = e.target.closest("button");
  if (btn) send(btn.textContent);
});

loadHealth();
loadMemories();
loadSkills();
$("input").focus();
