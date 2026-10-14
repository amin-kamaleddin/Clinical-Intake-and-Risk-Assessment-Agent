/* CIRA intake interface.
 *
 * The server owns the conversation and the record; this file only draws them
 * and sends one turn at a time. Every call goes through send(), which holds a
 * lock for the duration - two overlapping turns would let the agent answer the
 * same question twice and would double messages in the transcript. */

const RING_CIRCUMFERENCE = 2 * Math.PI * 31;

/** The one piece of interface text a patient has to read in their own
 *  language. Everything else they see is written by CIRA, which already
 *  replies in the language they chose. */
const COMPOSER_PLACEHOLDER = {
  English: "Type your answer…",
  French: "Saisissez votre réponse…",
  "Mandarin Chinese": "请输入您的回答…",
  Arabic: "اكتب إجابتك…",
  Hindi: "अपना उत्तर लिखें…",
  Farsi: "پاسخ خود را بنویسید…",
};

const state = {
  session: null,
  language: "English",
  speakReplies: false,
  busy: false,
  /** section key -> true when the clinician has expanded it */
  expanded: {},
  /** "section.label" -> last value shown, so new values can be highlighted */
  seen: {},
  /** keys that changed on the most recent turn */
  fresh: new Set(),
};

const el = (id) => document.getElementById(id);
const dom = {
  language: el("language"),
  voiceOut: el("voice-out"),
  newSession: el("new-session"),
  safety: el("safety"),
  sectionList: el("section-list"),
  transcript: el("transcript"),
  composer: el("composer"),
  input: el("input"),
  send: el("send"),
  mic: el("mic"),
  hint: el("hint"),
  ringValue: el("ring-value"),
  ringLabel: el("ring-label"),
  meterFill: el("meter-fill"),
  meterText: el("meter-text"),
  recordBody: el("record-body"),
  download: el("download"),
};

let sections = [];
let audio = null;

/* ------------------------------------------------------------------ server */

async function api(path, body) {
  const options = { method: "POST", headers: { "Content-Type": "application/json" } };
  if (body !== undefined) options.body = JSON.stringify(body);
  const response = await fetch(path, body === undefined ? { method: "GET" } : options);
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || "Something went wrong. Please try again.");
  }
  return response.json();
}

/** Runs one turn under a lock, with a typing indicator and errors surfaced. */
async function send(task, { showTyping = true } = {}) {
  if (state.busy) return null;
  state.busy = true;
  setBusy(true);
  const typing = showTyping ? addTyping() : null;
  try {
    return await task();
  } catch (error) {
    setHint(error.message, true);
    return null;
  } finally {
    if (typing) typing.remove();
    state.busy = false;
    setBusy(false);
  }
}

function setBusy(busy) {
  dom.send.disabled = busy;
  dom.mic.disabled = busy;
  dom.input.disabled = busy;
  if (!busy) dom.input.focus();
}

/* -------------------------------------------------------------- transcript */

/** The empty state. CIRA introduces itself on the first turn, so the opening
 *  screen explains what to do rather than greeting the patient twice. */
function showPlaceholder() {
  dom.transcript.innerHTML = `
    <div class="placeholder" id="placeholder">
      <h3>Ready when you are</h3>
      <p>Pick a section and CIRA will ask the first question.
         Type your answer, or use the microphone to speak it.</p>
    </div>`;
}

function addBubble(role, text, spokenNote) {
  document.getElementById("placeholder")?.remove();
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role === "cira" ? "cira" : "patient"}`;
  // Each message is laid out by its own script, so an English sentence stays
  // readable in an Arabic session and the reverse.
  bubble.dir = "auto";

  const who = document.createElement("span");
  who.className = "who";
  who.textContent = role === "cira" ? "CIRA" : "You";
  bubble.append(who);
  bubble.append(document.createTextNode(text));

  if (spokenNote) {
    const note = document.createElement("span");
    note.className = "spoken";
    note.textContent = "  (spoken)";
    bubble.append(note);
  }

  dom.transcript.append(bubble);
  dom.transcript.scrollTop = dom.transcript.scrollHeight;
  return bubble;
}

function addTyping() {
  document.getElementById("placeholder")?.remove();
  const typing = document.createElement("div");
  typing.className = "typing";
  typing.innerHTML = "<span></span><span></span><span></span>";
  dom.transcript.append(typing);
  dom.transcript.scrollTop = dom.transcript.scrollHeight;
  return typing;
}

function setHint(text, isError = false) {
  dom.hint.textContent = text || "";
  dom.hint.dir = "auto";
  dom.hint.style.color = isError ? "var(--rose)" : "var(--muted)";
}

/* ------------------------------------------------------------------ speech */

async function speak(text) {
  if (!state.speakReplies || !text) return;
  try {
    const response = await fetch("/api/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: state.session, text }),
    });
    if (!response.ok) throw new Error();
    if (audio) audio.pause();
    audio = new Audio(URL.createObjectURL(await response.blob()));
    await audio.play();
  } catch {
    setHint("CIRA's voice is unavailable right now.", true);
  }
}

let recorder = null;
let chunks = [];

async function startRecording() {
  if (state.busy) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recorder = new MediaRecorder(stream);
    chunks = [];
    recorder.ondataavailable = (event) => chunks.push(event.data);
    recorder.onstop = () => {
      stream.getTracks().forEach((track) => track.stop());
      submitRecording(new Blob(chunks, { type: "audio/webm" }));
    };
    recorder.start();
    dom.mic.classList.add("recording");
    setHint("Listening — press the microphone again to send.");
  } catch {
    setHint("No microphone access. You can type your answer instead.", true);
  }
}

function stopRecording() {
  if (recorder && recorder.state !== "inactive") recorder.stop();
  recorder = null;
  dom.mic.classList.remove("recording");
  setHint("");
}

async function submitRecording(blob) {
  if (blob.size < 1200) {
    setHint("That clip was too short to transcribe.", true);
    return;
  }
  await send(async () => {
    const form = new FormData();
    form.append("session", state.session);
    form.append("audio", blob, "clip.webm");
    const response = await fetch("/api/transcribe", { method: "POST", body: form });
    if (!response.ok) throw new Error("Could not transcribe that clip.");
    const data = await response.json();
    if (!data.text) {
      setHint(data.notice || "Nothing was picked up. Try again, or type your answer.", true);
      return null;
    }
    addBubble("patient", data.text, true);
    return applyTurn(data);
  });
}

/* ------------------------------------------------------------------ render */

function renderSections(snapshot) {
  dom.sectionList.innerHTML = "";
  snapshot.sections.forEach((section) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = [
      section.active ? "active" : "",
      section.complete ? "done" : section.filled > 0 ? "started" : "",
    ].join(" ").trim();

    const pip = document.createElement("span");
    pip.className = "pip";
    const name = document.createElement("span");
    name.textContent = section.title;
    const count = document.createElement("span");
    count.className = "count";
    count.textContent = `${section.filled}/${section.total}`;

    button.append(pip, name, count);
    button.onclick = () => openSection(section.key);
    item.append(button);
    dom.sectionList.append(item);
  });
}

function renderRecord(snapshot) {
  const { filled, total, sections_done, sections_total } = snapshot.progress;

  const ratio = total ? filled / total : 0;
  dom.ringValue.style.strokeDasharray = `${RING_CIRCUMFERENCE}`;
  dom.ringValue.style.strokeDashoffset = `${RING_CIRCUMFERENCE * (1 - ratio)}`;
  dom.ringLabel.innerHTML = `${filled}<small>/${total}</small>`;

  dom.meterFill.style.width = `${Math.round((sections_done / sections_total) * 100)}%`;
  dom.meterText.textContent = sections_done
    ? `${sections_done} of ${sections_total} sections complete`
    : "No sections completed";

  dom.recordBody.innerHTML = "";
  snapshot.sections.forEach((section) => {
    // The section being asked about is opened automatically; anything the
    // clinician opened by hand stays open across turns.
    const open = state.expanded[section.key] ?? (section.active || section.filled > 0);

    const wrapper = document.createElement("div");
    wrapper.className = `rsection${open ? " open" : ""}${section.active ? " current" : ""}`;

    const head = document.createElement("button");
    head.type = "button";
    head.className = "rsection-head";

    const chev = document.createElement("span");
    chev.className = "chev";
    chev.textContent = "▶";
    const title = document.createElement("span");
    title.textContent = section.title;
    const badge = document.createElement("span");
    badge.className = `badge ${section.filled === 0 ? "" : section.filled === section.total ? "full" : "part"}`;
    badge.textContent = `${section.filled}/${section.total}`;

    head.append(chev, title, badge);
    head.setAttribute("aria-expanded", String(open));
    head.onclick = () => {
      // Read what is on screen rather than the value captured when this row
      // was drawn. Capturing it meant the second click wrote back the first
      // click's answer: the row changed colour but never actually closed.
      const nowOpen = !wrapper.classList.contains("open");
      state.expanded[section.key] = nowOpen;
      wrapper.classList.toggle("open", nowOpen);
      head.setAttribute("aria-expanded", String(nowOpen));
      list.hidden = !nowOpen;
    };

    const list = document.createElement("ul");
    list.className = "fields";
    list.hidden = !open;

    section.fields.forEach((field) => {
      const key = `${section.key}.${field.label}`;
      const row = document.createElement("li");
      if (state.fresh.has(key)) row.classList.add("fresh");

      const label = document.createElement("span");
      label.className = "label";
      label.textContent = field.label;

      const value = document.createElement("span");
      value.className = `value${field.value ? "" : " blank"}`;
      value.textContent = field.value || "—";

      row.append(label, value);
      list.append(row);
    });

    wrapper.append(head, list);
    dom.recordBody.append(wrapper);
  });
}

/** Note which values are new, so renderRecord can highlight them once. */
function trackChanges(snapshot) {
  state.fresh = new Set();
  snapshot.sections.forEach((section) => {
    section.fields.forEach((field) => {
      const key = `${section.key}.${field.label}`;
      if (field.value && state.seen[key] !== field.value) state.fresh.add(key);
      state.seen[key] = field.value || null;
    });
  });
}

function render(snapshot) {
  document.body.dir = snapshot.rtl ? "rtl" : "ltr";
  dom.safety.hidden = !snapshot.safety.flagged;
  dom.safety.textContent = snapshot.safety.flagged ? snapshot.safety.message : "";

  trackChanges(snapshot);
  renderSections(snapshot);
  renderRecord(snapshot);
}

/** Draw one completed turn: the record first, then CIRA's reply. */
function applyTurn(data) {
  if (data.snapshot) render(data.snapshot);
  if (data.notice) setHint(data.notice);
  if (data.reply) {
    addBubble("cira", data.reply);
    speak(data.reply);
  }
  return data;
}

/* ------------------------------------------------------------------ actions */

async function startSession() {
  stopRecording();
  if (audio) audio.pause();
  showPlaceholder();
  state.seen = {};
  state.expanded = {};
  setHint("");

  const data = await send(
    () => api("/api/session", { language: state.language }),
    { showTyping: false },
  );
  if (!data) return;
  state.session = data.snapshot.session;
  render(data.snapshot);
}

async function openSection(key) {
  const data = await send(() => api("/api/section", { session: state.session, section: key }));
  if (data) applyTurn(data);
}

async function submitMessage(event) {
  event.preventDefault();
  const text = dom.input.value.trim();
  if (!text || state.busy) return;
  dom.input.value = "";
  addBubble("patient", text);
  const data = await send(() => api("/api/message", { session: state.session, text }));
  if (data) applyTurn(data);
}

async function changeLanguage() {
  state.language = dom.language.value;
  dom.input.placeholder = COMPOSER_PLACEHOLDER[state.language] || COMPOSER_PLACEHOLDER.English;
  if (!state.session) return;
  const data = await send(
    () => api("/api/language", { session: state.session, language: state.language }),
    { showTyping: false },
  );
  // Only the conversation language changes. The record stays in English, which
  // is what keeps one record from being split across two languages.
  if (data) {
    render(data.snapshot);
    setHint(`CIRA will continue in ${state.language}. The record stays in English.`);
  }
}

/* --------------------------------------------------------------------- init */

dom.composer.addEventListener("submit", submitMessage);
dom.language.addEventListener("change", changeLanguage);
dom.newSession.addEventListener("click", startSession);

dom.voiceOut.addEventListener("click", () => {
  state.speakReplies = !state.speakReplies;
  dom.voiceOut.setAttribute("aria-pressed", String(state.speakReplies));
  if (!state.speakReplies && audio) audio.pause();
});

dom.mic.addEventListener("click", () => {
  if (recorder) stopRecording();
  else startRecording();
});

dom.download.addEventListener("click", () => {
  if (state.session) window.location.href = `/api/record/${state.session}`;
});

(async function init() {
  const languages = await api("/api/languages");
  languages.forEach((language) => {
    const option = document.createElement("option");
    option.value = language.value;
    // Native name alongside the English one, so a patient can find their own
    // language in a list they can read.
    option.textContent = language.native === language.label
      ? language.label
      : `${language.label} — ${language.native}`;
    dom.language.append(option);
  });
  dom.language.value = state.language;
  await startSession();
})();
