(function () {
  const PREFIX = "EASYMENTOR_QUEUE::";
  const POLL_MS = 1200;
  const TYPE_DELAY_MS = 350;
  const STEP_DELAY_MS = 900;
  const SEARCH_PICK_DELAY_MS = 3000;
  let running = false;
  let lastQueueId = null;

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function decodeQueueFromWindowName() {
    if (!window.name || !window.name.startsWith(PREFIX)) return null;
    try {
      const raw = window.name.slice(PREFIX.length);
      const json = decodeURIComponent(escape(atob(raw)));
      const payload = JSON.parse(json);
      if (!payload || !Array.isArray(payload.recipients) || !payload.text) return null;
      return payload;
    } catch (e) {
      return null;
    }
  }

  function decodeQueueFromHash() {
    try {
      const hash = String(window.location.hash || "");
      if (!hash.startsWith("#easymentor=")) return null;
      const raw = decodeURIComponent(hash.replace("#easymentor=", ""));
      const json = decodeURIComponent(escape(atob(raw)));
      const payload = JSON.parse(json);
      if (!payload || !Array.isArray(payload.recipients) || !payload.text) return null;
      return payload;
    } catch (e) {
      return null;
    }
  }

  function bySelectors(selectors) {
    for (const s of selectors) {
      const node = document.querySelector(s);
      if (node) return node;
    }
    return null;
  }

  async function waitFor(selectors, timeoutMs) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const node = bySelectors(selectors);
      if (node) return node;
      await sleep(200);
    }
    return null;
  }

  function clearEditable(el) {
    el.focus();
    document.execCommand("selectAll", false, null);
    document.execCommand("delete", false, null);
    el.innerHTML = "";
  }

  async function setEditableText(el, text) {
    clearEditable(el);
    const lines = String(text || "").split("\n");
    for (let i = 0; i < lines.length; i++) {
      document.execCommand("insertText", false, lines[i]);
      if (i < lines.length - 1) {
        const br = document.createElement("br");
        el.appendChild(br);
      }
    }
    el.dispatchEvent(new InputEvent("input", { bubbles: true }));
    await sleep(TYPE_DELAY_MS);
  }

  function pressEnter(el) {
    const down = new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true });
    const up = new KeyboardEvent("keyup", { key: "Enter", code: "Enter", bubbles: true });
    el.dispatchEvent(down);
    el.dispatchEvent(up);
  }

  function ensureBanner() {
    let banner = document.getElementById("easymentor-auto-banner");
    if (banner) return banner;
    banner = document.createElement("div");
    banner.id = "easymentor-auto-banner";
    banner.style.position = "fixed";
    banner.style.right = "12px";
    banner.style.bottom = "12px";
    banner.style.zIndex = "99999";
    banner.style.background = "#0f172a";
    banner.style.color = "#fff";
    banner.style.padding = "8px 12px";
    banner.style.borderRadius = "10px";
    banner.style.fontSize = "12px";
    banner.style.fontFamily = "Segoe UI, Arial, sans-serif";
    banner.style.boxShadow = "0 6px 20px rgba(0,0,0,.35)";
    document.body.appendChild(banner);
    return banner;
  }

  function setStatus(text) {
    ensureBanner().textContent = text;
  }

  async function openNewChatAndSearch(phone) {
    const newChat = await waitFor(
      [
        "button[title='New chat']",
        "button[aria-label='New chat']",
        "span[data-icon='new-chat-outline']"
      ],
      12000
    );
    if (!newChat) return false;
    const clickable = newChat.closest("button") || newChat;
    clickable.click();
    await sleep(STEP_DELAY_MS);

    const search = await waitFor(
      [
        "div[role='textbox'][aria-label*='Search name or number']",
        "div[contenteditable='true'][data-tab='3']",
        "div[contenteditable='true'][data-tab='2']"
      ],
      12000
    );
    if (!search) return false;
    await setEditableText(search, phone);
    await sleep(SEARCH_PICK_DELAY_MS);
    pressEnter(search);
    await sleep(STEP_DELAY_MS);
    return true;
  }

  async function sendCurrentMessage(message) {
    const composer = await waitFor(
      [
        "footer div[role='textbox'][aria-label*='Type a message']",
        "footer div[contenteditable='true'][data-tab='10']",
        "footer div[contenteditable='true'][data-tab='6']"
      ],
      12000
    );
    if (!composer) return false;
    await setEditableText(composer, message);
    await sleep(250);
    pressEnter(composer);
    await sleep(STEP_DELAY_MS);
    return true;
  }

  async function runQueue(payload) {
    running = true;
    setStatus(`EasyMentor auto: starting (${payload.recipients.length})`);
    for (let i = 0; i < payload.recipients.length; i++) {
      const rec = payload.recipients[i];
      setStatus(`EasyMentor auto: ${i + 1}/${payload.recipients.length} ${rec.phone}`);
      const chatOk = await openNewChatAndSearch(rec.phone);
      if (!chatOk) {
        setStatus(`EasyMentor auto: failed chat ${rec.phone}`);
        continue;
      }
      const sentOk = await sendCurrentMessage(payload.text);
      if (!sentOk) {
        setStatus(`EasyMentor auto: failed send ${rec.phone}`);
      }
      await sleep(600);
    }
    setStatus("EasyMentor auto: completed");
    if (window.location.hash && window.location.hash.startsWith("#easymentor=")) {
      history.replaceState(null, "", "/");
    }
    window.name = "";
    running = false;
  }

  async function poll() {
    if (running) return;
    const payload = decodeQueueFromHash() || decodeQueueFromWindowName();
    if (!payload) return;
    const queueId = String(payload.createdAt || "");
    if (queueId && queueId === lastQueueId) return;
    lastQueueId = queueId;
    if (window.location.hash && window.location.hash.startsWith("#easymentor=")) {
      history.replaceState(null, "", "/");
    }
    await runQueue(payload);
  }

  setStatus("EasyMentor auto: waiting for queue");
  setInterval(poll, POLL_MS);
})();
