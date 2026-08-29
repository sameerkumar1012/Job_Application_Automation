// All fetch() calls to the local Python server live here (not in content.js)
// because a content script's fetches are subject to the target page's CSP,
// while this MV3 background service worker is extension-origin and, combined
// with the host_permissions grant for 127.0.0.1, bypasses that restriction.

const API_BASE = "http://127.0.0.1:8765";
const MAX_STEPS = 20;
const STEP_SETTLE_MS = 1000;

function sessionKey(tabId) {
  return `fillStatus:${tabId}`;
}

async function setStatus(tabId, patch) {
  const key = sessionKey(tabId);
  const existing = (await chrome.storage.session.get(key))[key] || {};
  const updated = { ...existing, ...patch };
  await chrome.storage.session.set({ [key]: updated });
  return updated;
}

function sendToFrame(tabId, frameId, message) {
  return new Promise((resolve) => {
    chrome.tabs.sendMessage(tabId, message, { frameId }, (response) => {
      if (chrome.runtime.lastError) {
        resolve(null);
        return;
      }
      resolve(response);
    });
  });
}

async function scanAllFrames(tabId) {
  let frames;
  try {
    frames = await chrome.webNavigation.getAllFrames({ tabId });
  } catch (err) {
    frames = [{ frameId: 0 }];
  }
  if (!frames || frames.length === 0) frames = [{ frameId: 0 }];

  const perFrame = [];
  for (const frame of frames) {
    const result = await sendToFrame(tabId, frame.frameId, { type: "SCAN_PAGE" });
    if (result) {
      perFrame.push({ frameId: frame.frameId, ...result });
    }
  }
  return perFrame;
}

function buildFillRequest(perFrame) {
  const fields = [];
  const buttons = [];
  let page = { url: "", title: "", visibleTextSnippet: "", passwordFieldCount: 0, iframeSrcList: [] };

  perFrame.forEach((frame) => {
    if (frame.frameId === 0 && frame.page) {
      page = frame.page;
    } else if (!page.url && frame.page) {
      page = frame.page;
    }
    (frame.fields || []).forEach((f) => {
      fields.push({ ...f, fieldId: `${frame.frameId}:${f.fieldId}`, frameId: frame.frameId });
    });
    (frame.buttons || []).forEach((b) => {
      buttons.push({ ...b, buttonId: `${frame.frameId}:${b.buttonId}`, frameId: frame.frameId });
    });
  });

  return { page, fields, buttons };
}

async function callFillApi(fillRequest) {
  const response = await fetch(`${API_BASE}/api/fill`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fillRequest),
  });
  if (!response.ok) {
    throw new Error(`Server error ${response.status}`);
  }
  return response.json();
}

function splitByFrame(prefixedId) {
  const idx = prefixedId.indexOf(":");
  return {
    frameId: parseInt(prefixedId.slice(0, idx), 10),
    localId: prefixedId.slice(idx + 1),
  };
}

async function applyFillsAcrossFrames(tabId, filledFields, clickButtonId) {
  const byFrame = new Map();
  filledFields.forEach((f) => {
    const { frameId, localId } = splitByFrame(f.fieldId);
    if (!byFrame.has(frameId)) byFrame.set(frameId, []);
    byFrame.get(frameId).push({ fieldId: localId, value: f.value });
  });

  let clickFrame = null;
  let clickLocalId = null;
  if (clickButtonId) {
    const split = splitByFrame(clickButtonId);
    clickFrame = split.frameId;
    clickLocalId = split.localId;
    if (!byFrame.has(clickFrame)) byFrame.set(clickFrame, []);
  }

  // fieldId (prefixed) -> whether content.js actually managed to write it into the DOM.
  const appliedById = new Map();
  for (const [frameId, fills] of byFrame.entries()) {
    const response = await sendToFrame(tabId, frameId, {
      type: "APPLY_FILLS",
      fills,
      clickButtonId: frameId === clickFrame ? clickLocalId : undefined,
    });
    (response && response.results ? response.results : []).forEach((r) => {
      appliedById.set(`${frameId}:${r.fieldId}`, r.applied);
    });
  }
  return appliedById;
}

async function attachFilesIfMatched(tabId, perFrame) {
  const attached = [];
  for (const frame of perFrame) {
    for (const field of frame.fields || []) {
      if ((field.inputType || "").toLowerCase() !== "file") continue;
      const label = (field.label || "").toLowerCase();
      let endpoint = null;
      let kind = null;
      if (/resume|\bcv\b/.test(label)) {
        endpoint = "/api/resume-file";
        kind = "resume";
      } else if (/cover letter/.test(label)) {
        endpoint = "/api/cover-letter-file";
        kind = "cover letter";
      }
      if (!endpoint) continue;

      try {
        const response = await fetch(`${API_BASE}${endpoint}`);
        if (!response.ok) continue;
        const disposition = response.headers.get("Content-Disposition") || "";
        const match = disposition.match(/filename="([^"]+)"/);
        const filename = match ? match[1] : `${kind}.bin`;
        const mimetype = response.headers.get("Content-Type") || "application/octet-stream";
        const buffer = await response.arrayBuffer();
        const applyResult = await sendToFrame(tabId, frame.frameId, {
          type: "APPLY_FILE_FIELD",
          fieldId: field.fieldId,
          filename,
          mimetype,
          bytes: Array.from(new Uint8Array(buffer)),
        });
        if (applyResult && applyResult.applied) {
          attached.push({ label: field.label, filename });
        }
      } catch (err) {
        // No file uploaded server-side, or attach failed -- leave it to the
        // user to attach manually, already reflected via unfilledFields.
      }
    }
  }
  return attached;
}

async function runFill(tabId) {
  await setStatus(tabId, {
    status: "running",
    filledFields: [],
    unfilledFields: [],
    attachedFiles: [],
    blocked: null,
    error: null,
  });

  const allFilled = [];
  const allUnfilled = [];
  const allAttached = [];

  // Detects a "next" click that didn't actually change anything (e.g. the site's own
  // validation silently blocked navigation) so the loop stops instead of repeatedly
  // re-scanning/re-filling/re-clicking the same stuck step up to MAX_STEPS.
  let previousSignature = null;
  let clickedLastStep = false;

  function signatureOf(fillRequest) {
    return JSON.stringify({
      url: fillRequest.page.url,
      fields: fillRequest.fields.map((f) => `${f.fieldId}|${f.label}`).sort(),
    });
  }

  try {
    for (let step = 0; step < MAX_STEPS; step += 1) {
      const perFrame = await scanAllFrames(tabId);
      const fillRequest = buildFillRequest(perFrame);
      const signature = signatureOf(fillRequest);

      if (clickedLastStep && signature === previousSignature) {
        break;
      }

      const attached = await attachFilesIfMatched(tabId, perFrame);
      allAttached.push(...attached);

      const result = await callFillApi(fillRequest);

      if (result.blocked) {
        await setStatus(tabId, {
          status: "blocked",
          blocked: result.blocked,
          filledFields: allFilled,
          unfilledFields: allUnfilled,
          attachedFiles: allAttached,
        });
        return;
      }

      const appliedById = await applyFillsAcrossFrames(
        tabId,
        result.filledFields || [],
        result.clickButtonId
      );

      // A field the backend says it "filled" but content.js couldn't actually write
      // into the DOM (e.g. the value didn't match any option) must not be reported
      // as filled -- demote it so the user isn't told something happened that didn't.
      (result.filledFields || []).forEach((f) => {
        if (appliedById.get(f.fieldId) === false) {
          allUnfilled.push({
            fieldId: f.fieldId,
            label: f.label,
            reason: "AI/matcher produced a value, but it could not be applied to this field.",
          });
        } else {
          allFilled.push(f);
        }
      });
      allUnfilled.push(...(result.unfilledFields || []));

      await setStatus(tabId, {
        status: "running",
        filledFields: allFilled,
        unfilledFields: allUnfilled,
        attachedFiles: allAttached,
      });

      if (!result.clickButtonId || !result.advancedToNextStep) {
        break;
      }

      previousSignature = signature;
      clickedLastStep = true;
      await new Promise((resolve) => setTimeout(resolve, STEP_SETTLE_MS));
    }

    await setStatus(tabId, {
      status: "done",
      filledFields: allFilled,
      unfilledFields: allUnfilled,
      attachedFiles: allAttached,
    });
  } catch (err) {
    await setStatus(tabId, {
      status: "error",
      error: err && err.message ? err.message : String(err),
      filledFields: allFilled,
      unfilledFields: allUnfilled,
      attachedFiles: allAttached,
    });
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== "START_FILL") return undefined;

  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs[0];
    if (!tab || !tab.id) {
      sendResponse({ error: "No active tab found." });
      return;
    }
    runFill(tab.id);
    sendResponse({ started: true, tabId: tab.id });
  });
  return true;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.remove(sessionKey(tabId));
});
