// Dumb DOM scraper/applier. No matching, no navigation decisions, no network
// calls -- all of that lives in the Python server, relayed via background.js.
// This script only reports what's on the page and applies exactly what it's told.

(function () {
  let currentFields = new Map(); // fieldId -> element (or {radio: [{el, label}]})
  let currentButtons = new Map(); // buttonId -> element
  let scanCounter = 0;

  function isVisible(el) {
    if (!el) return false;
    if (el.disabled) return false;
    if (el.getAttribute && el.getAttribute("aria-hidden") === "true") return false;
    return !!(el.offsetParent || el.getClientRects().length);
  }

  function labelFor(el) {
    if (el.labels && el.labels.length > 0) {
      const text = el.labels[0].innerText && el.labels[0].innerText.trim();
      if (text) return text;
    }
    const ariaLabel = el.getAttribute("aria-label");
    if (ariaLabel && ariaLabel.trim()) return ariaLabel.trim();

    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      const ref = document.getElementById(labelledBy);
      if (ref && ref.innerText && ref.innerText.trim()) return ref.innerText.trim();
    }

    if (el.placeholder && el.placeholder.trim()) return el.placeholder.trim();

    const wrappingLabel = el.closest && el.closest("label");
    if (wrappingLabel && wrappingLabel.innerText && wrappingLabel.innerText.trim()) {
      return wrappingLabel.innerText.trim();
    }

    const fieldset = el.closest && el.closest("fieldset");
    if (fieldset) {
      const legend = fieldset.querySelector("legend");
      if (legend && legend.innerText && legend.innerText.trim()) return legend.innerText.trim();
    }

    return (el.name || el.id || "").replace(/[_-]/g, " ").trim();
  }

  function buttonText(el) {
    const text = (el.innerText || el.value || el.getAttribute("aria-label") || "").trim();
    return text;
  }

  // Best-effort: walks up from a checkbox with no `name` to find the smallest
  // ancestor that contains 2+ checkboxes, treating them as one grouped question
  // (e.g. "Are you open for relocation? [ ] No [ ] Yes, Mumbai [ ] Yes, Pune ...").
  // Not exhaustive of every possible layout -- a documented limitation, same
  // spirit as the closed-shadow-root caveat elsewhere in this project.
  function findCheckboxGroupContainer(el) {
    let node = el.parentElement;
    let depth = 0;
    while (node && depth < 5) {
      if (node.querySelectorAll('input[type="checkbox"]').length >= 2) return node;
      node = node.parentElement;
      depth += 1;
    }
    return null;
  }

  function findGroupLabel(container, checkboxEls) {
    const ariaLabel = container.getAttribute && container.getAttribute("aria-label");
    if (ariaLabel && ariaLabel.trim()) return ariaLabel.trim();

    const children = Array.from(container.children || []);
    for (const child of children) {
      if (checkboxEls.includes(child)) continue;
      if (child.querySelector && child.querySelector('input[type="checkbox"]')) continue;
      const text = (child.innerText || "").trim();
      if (text) return text;
    }

    let sib = container.previousElementSibling;
    let hops = 0;
    while (sib && hops < 3) {
      const text = (sib.innerText || "").trim();
      if (text) return text;
      sib = sib.previousElementSibling;
      hops += 1;
    }

    return "";
  }

  function collectAll(root, out) {
    // a[href^="javascript:"] / a[href="#"] are scoped to non-navigating, JS-action
    // anchors specifically (e.g. "Add Company Experience" links) -- not every <a> on
    // the page, which would risk matching real navigation links.
    const matches = root.querySelectorAll(
      'input, select, textarea, button, [role="button"], a[href^="javascript:"], a[href="#"]'
    );
    matches.forEach((el) => out.push(el));
    const hosts = root.querySelectorAll("*");
    hosts.forEach((el) => {
      if (el.shadowRoot) collectAll(el.shadowRoot, out);
    });
  }

  function scanPage() {
    scanCounter += 1;
    currentFields = new Map();
    currentButtons = new Map();

    const all = [];
    collectAll(document, all);

    const fields = [];
    const buttons = [];
    const radioGroups = new Map(); // name -> {options: [{value,label}], elements: []}
    const checkboxCandidates = []; // {el, label} -- grouped into fields after the main pass

    let passwordCount = 0;

    all.forEach((el, idx) => {
      const tag = el.tagName.toLowerCase();

      if (tag === "button" || tag === "a" || el.getAttribute("role") === "button") {
        if (!isVisible(el)) return;
        const id = `btn_${scanCounter}_${idx}`;
        currentButtons.set(id, el);
        buttons.push({
          buttonId: id,
          text: buttonText(el),
          tag,
          typeAttr: el.getAttribute("type") || undefined,
          ariaLabel: el.getAttribute("aria-label") || undefined,
        });
        return;
      }

      if (tag === "input") {
        const type = (el.getAttribute("type") || "text").toLowerCase();
        if (type === "submit" || type === "button") {
          if (!isVisible(el)) return;
          const id = `btn_${scanCounter}_${idx}`;
          currentButtons.set(id, el);
          buttons.push({
            buttonId: id,
            text: buttonText(el),
            tag,
            typeAttr: type,
            ariaLabel: el.getAttribute("aria-label") || undefined,
          });
          return;
        }
        if (type === "hidden" || type === "reset") return;
        if (!isVisible(el)) return;

        if (type === "password") passwordCount += 1;

        if (type === "radio") {
          const name = el.name || `radio_${idx}`;
          if (!radioGroups.has(name)) {
            radioGroups.set(name, { elements: [] });
          }
          radioGroups.get(name).elements.push({ el, label: labelFor(el) });
          return;
        }

        if (type === "checkbox") {
          checkboxCandidates.push({ el, label: labelFor(el) });
          return;
        }

        const id = `f_${scanCounter}_${idx}`;
        currentFields.set(id, el);
        fields.push({
          fieldId: id,
          tag,
          inputType: type,
          label: labelFor(el),
          placeholder: el.placeholder || undefined,
          name: el.name || undefined,
          idAttr: el.id || undefined,
          ariaLabel: el.getAttribute("aria-label") || undefined,
          options: [],
          currentValue: el.value || undefined,
          isRequired: !!el.required,
        });
        return;
      }

      if (tag === "select") {
        if (!isVisible(el)) return;
        const id = `f_${scanCounter}_${idx}`;
        currentFields.set(id, el);
        const options = Array.from(el.options || []).map((o) => o.text.trim());
        fields.push({
          fieldId: id,
          tag,
          inputType: "select",
          label: labelFor(el),
          name: el.name || undefined,
          idAttr: el.id || undefined,
          ariaLabel: el.getAttribute("aria-label") || undefined,
          options,
          currentValue: el.value || undefined,
          isRequired: !!el.required,
        });
        return;
      }

      if (tag === "textarea") {
        if (!isVisible(el)) return;
        const id = `f_${scanCounter}_${idx}`;
        currentFields.set(id, el);
        fields.push({
          fieldId: id,
          tag,
          inputType: "textarea",
          label: labelFor(el),
          placeholder: el.placeholder || undefined,
          name: el.name || undefined,
          idAttr: el.id || undefined,
          ariaLabel: el.getAttribute("aria-label") || undefined,
          options: [],
          currentValue: el.value || undefined,
          isRequired: !!el.required,
        });
        return;
      }
    });

    // Emit one DetectedField per radio group, options = each radio's label text.
    let radioIdx = 0;
    radioGroups.forEach((group, name) => {
      radioIdx += 1;
      const id = `radio_${scanCounter}_${radioIdx}`;
      currentFields.set(id, { radio: group.elements });
      const checked = group.elements.find((r) => r.el.checked);
      fields.push({
        fieldId: id,
        tag: "input",
        inputType: "radio",
        label: labelFor(group.elements[0].el) || name,
        name,
        options: group.elements.map((r) => r.label),
        currentValue: checked ? checked.label : undefined,
        isRequired: false,
      });
    });

    // Group checkboxes like radios: shared `name` first, else DOM-proximity.
    // A lone checkbox (no group found) keeps the simple boolean Yes/No shape.
    const byName = new Map();
    const unnamed = [];
    checkboxCandidates.forEach((c) => {
      if (c.el.name) {
        if (!byName.has(c.el.name)) byName.set(c.el.name, []);
        byName.get(c.el.name).push(c);
      } else {
        unnamed.push(c);
      }
    });

    const proximityGroups = [];
    const assigned = new Set();
    unnamed.forEach((c) => {
      if (assigned.has(c)) return;
      const container = findCheckboxGroupContainer(c.el);
      if (!container) return;
      const group = unnamed.filter(
        (other) => !assigned.has(other) && findCheckboxGroupContainer(other.el) === container
      );
      if (group.length >= 2) {
        group.forEach((g) => assigned.add(g));
        proximityGroups.push({ container, items: group });
      }
    });

    const standaloneCheckboxes = [];
    unnamed.forEach((c) => {
      if (!assigned.has(c)) standaloneCheckboxes.push(c);
    });

    let checkboxGroupIdx = 0;
    byName.forEach((items, name) => {
      if (items.length < 2) {
        standaloneCheckboxes.push(...items);
        return;
      }
      checkboxGroupIdx += 1;
      const id = `cbgroup_${scanCounter}_${checkboxGroupIdx}`;
      currentFields.set(id, { checkboxGroup: items });
      fields.push({
        fieldId: id,
        tag: "input",
        inputType: "checkbox-group",
        label: name,
        name,
        options: items.map((i) => i.label),
        currentValue: (items.find((i) => i.el.checked) || {}).label,
        isRequired: false,
      });
    });

    proximityGroups.forEach((grp) => {
      checkboxGroupIdx += 1;
      const id = `cbgroup_${scanCounter}_${checkboxGroupIdx}`;
      currentFields.set(id, { checkboxGroup: grp.items });
      const groupLabel =
        findGroupLabel(grp.container, grp.items.map((i) => i.el)) || "Multiple choice question";
      fields.push({
        fieldId: id,
        tag: "input",
        inputType: "checkbox-group",
        label: groupLabel,
        options: grp.items.map((i) => i.label),
        currentValue: (grp.items.find((i) => i.el.checked) || {}).label,
        isRequired: false,
      });
    });

    standaloneCheckboxes.forEach((c, idx) => {
      const id = `f_${scanCounter}_cb_${idx}`;
      currentFields.set(id, c.el);
      fields.push({
        fieldId: id,
        tag: "input",
        inputType: "checkbox",
        label: c.label,
        placeholder: c.el.placeholder || undefined,
        name: c.el.name || undefined,
        idAttr: c.el.id || undefined,
        ariaLabel: c.el.getAttribute("aria-label") || undefined,
        options: ["Yes", "No"],
        currentValue: c.el.checked ? "Yes" : "No",
        isRequired: !!c.el.required,
      });
    });

    const iframeSrcList = Array.from(document.querySelectorAll("iframe"))
      .map((f) => f.src)
      .filter(Boolean);

    return {
      page: {
        url: location.href,
        title: document.title,
        visibleTextSnippet: (document.body && document.body.innerText
          ? document.body.innerText.slice(0, 500)
          : ""),
        passwordFieldCount: passwordCount,
        iframeSrcList,
      },
      fields,
      buttons,
    };
  }

  function setNativeValue(el, value) {
    const proto = Object.getPrototypeOf(el);
    const descriptor = Object.getOwnPropertyDescriptor(proto, "value");
    if (descriptor && descriptor.set) {
      descriptor.set.call(el, value);
    } else {
      el.value = value;
    }
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function applyFill(fieldId, value) {
    const target = currentFields.get(fieldId);
    if (!target) return false;

    if (target.checkboxGroup) {
      const normalized = (value || "").trim().toLowerCase();
      const match =
        target.checkboxGroup.find((c) => c.label.trim().toLowerCase() === normalized) ||
        target.checkboxGroup.find((c) => normalized.includes(c.label.trim().toLowerCase()));
      if (!match) return false;
      // Treated as single-select, matching the ATS screening-question pattern this
      // was built for -- a true "check all that apply" case isn't reliably
      // distinguishable from this without more signal.
      target.checkboxGroup.forEach((c) => {
        const shouldCheck = c === match;
        if (c.el.checked !== shouldCheck) {
          c.el.checked = shouldCheck;
          c.el.dispatchEvent(new Event("change", { bubbles: true }));
        }
      });
      return true;
    }

    if (target.radio) {
      const normalized = (value || "").trim().toLowerCase();
      const match = target.radio.find(
        (r) => r.label.trim().toLowerCase() === normalized
      ) || target.radio.find((r) => r.label.trim().toLowerCase().includes(normalized));
      if (match) {
        match.el.checked = true;
        match.el.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      }
      return false;
    }

    const el = target;
    const tag = el.tagName.toLowerCase();

    if (tag === "input" && (el.getAttribute("type") || "").toLowerCase() === "checkbox") {
      const shouldCheck = (value || "").trim().toLowerCase() === "yes";
      el.checked = shouldCheck;
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }

    if (tag === "select") {
      const normalized = (value || "").trim().toLowerCase();
      const option = Array.from(el.options || []).find(
        (o) => o.text.trim().toLowerCase() === normalized
      );
      if (option) {
        el.value = option.value;
        el.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      }
      return false;
    }

    setNativeValue(el, value);
    return true;
  }

  function applyFileField(fieldId, filename, mimetype, byteArray) {
    const el = currentFields.get(fieldId);
    if (!el || el.radio) return false;
    try {
      const bytes = new Uint8Array(byteArray);
      const file = new File([bytes], filename, { type: mimetype });
      const dt = new DataTransfer();
      dt.items.add(file);
      el.files = dt.files;
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    } catch (err) {
      return false;
    }
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message || !message.type) return undefined;

    if (message.type === "SCAN_PAGE") {
      sendResponse(scanPage());
      return true;
    }

    if (message.type === "APPLY_FILLS") {
      const results = (message.fills || []).map((f) => ({
        fieldId: f.fieldId,
        applied: applyFill(f.fieldId, f.value),
      }));
      let clicked = false;
      if (message.clickButtonId) {
        const btn = currentButtons.get(message.clickButtonId);
        if (btn) {
          btn.click();
          clicked = true;
        }
      }
      sendResponse({ results, clicked });
      return true;
    }

    if (message.type === "APPLY_FILE_FIELD") {
      const applied = applyFileField(
        message.fieldId,
        message.filename,
        message.mimetype,
        message.bytes
      );
      sendResponse({ applied });
      return true;
    }

    return undefined;
  });
})();
