const API_BASE = "http://127.0.0.1:8765";

let activeTabId = null;

function sessionKey(tabId) {
  return `fillStatus:${tabId}`;
}

function el(id) {
  return document.getElementById(id);
}

function renderStatus(status) {
  const fillButton = el("fill-button");
  const blockedBanner = el("blocked-banner");
  const filledList = el("filled-list");
  const unfilledList = el("unfilled-list");
  const attachedList = el("attached-list");

  if (!status) {
    fillButton.disabled = false;
    fillButton.textContent = "Fill this page";
    blockedBanner.classList.add("hidden");
    filledList.innerHTML = "";
    unfilledList.innerHTML = "";
    attachedList.innerHTML = "";
    return;
  }

  fillButton.disabled = status.status === "running";
  fillButton.textContent = status.status === "running" ? "Filling..." : "Fill this page";

  if (status.blocked) {
    blockedBanner.textContent = `Blocked (${status.blocked.reason}): ${status.blocked.message}`;
    blockedBanner.classList.remove("hidden");
  } else if (status.status === "error") {
    blockedBanner.textContent = `Error: ${status.error}`;
    blockedBanner.classList.remove("hidden");
  } else {
    blockedBanner.classList.add("hidden");
  }

  filledList.innerHTML = "";
  (status.filledFields || []).forEach((f) => {
    const li = document.createElement("li");
    const badge = document.createElement("span");
    badge.className = `badge badge-${f.confidence}`;
    badge.textContent = f.confidence;
    li.appendChild(badge);
    li.appendChild(document.createTextNode(` ${f.label}: ${f.value}`));
    filledList.appendChild(li);
  });

  attachedList.innerHTML = "";
  (status.attachedFiles || []).forEach((a) => {
    const li = document.createElement("li");
    li.textContent = `${a.label}: ${a.filename}`;
    attachedList.appendChild(li);
  });

  unfilledList.innerHTML = "";
  (status.unfilledFields || []).forEach((u) => {
    const li = document.createElement("li");
    li.textContent = `${u.label}: ${u.reason}`;
    unfilledList.appendChild(li);
  });
}

async function loadInitialStatus() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tab = tabs[0];
  if (!tab || !tab.id) return;
  activeTabId = tab.id;

  const key = sessionKey(activeTabId);
  const stored = await chrome.storage.session.get(key);
  renderStatus(stored[key] || null);
}

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== "session" || activeTabId === null) return;
  const key = sessionKey(activeTabId);
  if (changes[key]) {
    renderStatus(changes[key].newValue);
  }
});

el("fill-button").addEventListener("click", () => {
  renderStatus({ status: "running", filledFields: [], unfilledFields: [], attachedFiles: [] });
  chrome.runtime.sendMessage({ type: "START_FILL" });
});

el("open-dashboard").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.tabs.create({ url: `${API_BASE}/` });
});

async function loadSettings() {
  try {
    const response = await fetch(`${API_BASE}/api/settings`);
    if (!response.ok) throw new Error("bad response");
    const settings = await response.json();
    el("auto-advance-toggle").checked = !!settings.autoAdvanceSteps;
    el("server-warning").classList.add("hidden");
  } catch (err) {
    el("server-warning").classList.remove("hidden");
  }
}

el("auto-advance-toggle").addEventListener("change", async (e) => {
  try {
    await fetch(`${API_BASE}/api/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ autoAdvanceSteps: e.target.checked, model: undefined }),
    });
  } catch (err) {
    // Server unreachable -- toggle still reflects intent locally.
  }
});

loadInitialStatus();
loadSettings();
