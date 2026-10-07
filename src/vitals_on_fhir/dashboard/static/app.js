/* SPDX-License-Identifier: AGPL-3.0-or-later */

/*
 * vitals-on-fhir dashboard client.
 *
 * Opens a WebSocket to the server (passing the access token as a query
 * parameter, since browsers cannot set custom WebSocket headers) and updates
 * the DOM purely from server-pushed envelopes. There is no polling and no page
 * reload (FR-7, FR-10).
 *
 * Two envelope types are handled (see design section 10 / broadcaster.py):
 *   { "type": "observation", "resource": { ...FHIR Observation... } }
 *   { "type": "connection_state", "state": "<connected|disconnected|...>" }
 *
 * While the device is disconnected the last reading is dimmed and no new
 * values are shown; presentation resumes automatically on reconnect (FR-6).
 *
 * When the server runs the mock adapter it also exposes /mock/scenarios; the
 * page then shows a dropdown and a Simulate button that starts the chosen
 * scenario from the beginning. A third envelope, { "type": "reset" }, then
 * tells every open page to clear its chart and readings.
 *
 * Readings are also drawn as a live two-minute line chart (plain SVG, no
 * libraries) with the lowest / average / highest value in view.
 *
 * On load the page first shows the safety and scope notes, which must be
 * acknowledged (once per browser session). It then asks GET /status whether a
 * token is needed. In demo mode (no token set on the server) it hides the
 * token form and connects at once.
 *
 * Every Observation is also shown as JSON in the FHIR resources card, and the
 * Device it references is read from GET /fhir/Device/{id} and summarised under
 * the reading.
 */

(function () {
  "use strict";

  // Human-readable labels for the adapter ConnectionState wire values.
  var DEVICE_STATE_LABELS = {
    connected: "Connected — receiving heart rate",
    connecting: "Connecting to the device…",
    reconnecting: "Connection lost — trying to reconnect…",
    disconnected: "Device disconnected",
  };

  // States in which live values are considered current. Any other state means
  // we stop showing new values until the device reconnects (FR-6).
  var LIVE_STATES = { connected: true };

  // Live chart: how much history is shown, and the SVG geometry (viewBox units).
  var CHART_WINDOW_MS = 2 * 60 * 1000;
  var CHART_REFRESH_MS = 1000;
  var CHART_W = 600;
  var CHART_H = 220;
  var CHART_PAD = { left: 38, right: 12, top: 12, bottom: 24 };
  var SVG_NS = "http://www.w3.org/2000/svg";

  // Connected but no valid reading for this long: tell the user (e.g. sensor off).
  var SILENCE_MS = 8000;

  var history = []; // [{ t: epoch ms, v: bpm }], oldest first
  var scenarioOptions = []; // [{ id, label, description, group }] from /mock/scenarios
  var deviceLive = false; // true while the device is reported connected
  var lastReadingAt = null; // epoch ms of the latest valid reading, or null
  var socket = null;
  var reconnectTimer = null;
  var manualClose = false;
  var currentToken = "";
  var authRequired = true; // false in demo mode (see GET /status)

  var els = {};

  function cacheElements() {
    els.form = document.getElementById("connect-form");
    els.demoNote = document.getElementById("demo-note");
    els.tokenInput = document.getElementById("token-input");
    els.connectButton = document.getElementById("connect-button");
    els.hrValue = document.getElementById("hr-value");
    els.hrTimestamp = document.getElementById("hr-timestamp");
    els.reading = document.querySelector(".reading");
    els.connectionStatus = document.getElementById("connection-status");
    els.chart = document.getElementById("hr-chart");
    els.statMin = document.getElementById("stat-min");
    els.statAvg = document.getElementById("stat-avg");
    els.statMax = document.getElementById("stat-max");
    els.simCard = document.getElementById("sim-card");
    els.simSelect = document.getElementById("sim-select");
    els.simStart = document.getElementById("sim-start");
    els.simDescription = document.getElementById("sim-description");
    els.simStatus = document.getElementById("sim-status");
    els.readingNote = document.getElementById("reading-note");
    els.deviceProps = document.getElementById("device-props");
    els.welcome = document.getElementById("welcome-dialog");
    els.welcomeAck = document.getElementById("welcome-ack");
    els.welcomeReopen = document.getElementById("welcome-reopen");
    els.fhirPause = document.getElementById("fhir-pause");
    els.fhirTrail = document.getElementById("fhir-trail");
    els.fhirJson = document.getElementById("fhir-json");
    els.fhirRecent = document.getElementById("fhir-recent");
  }

  function setStatus(text, kind) {
    els.connectionStatus.textContent = text;
    els.connectionStatus.classList.remove("is-connected", "is-down");
    if (kind === "connected") {
      els.connectionStatus.classList.add("is-connected");
    } else if (kind === "down") {
      els.connectionStatus.classList.add("is-down");
    }
  }

  // Stop presenting live values: dim the last reading (FR-6).
  function markStale() {
    if (els.reading) {
      els.reading.classList.add("stale");
    }
    if (els.chart) {
      els.chart.classList.add("stale");
    }
  }

  function markLive() {
    if (els.reading) {
      els.reading.classList.remove("stale");
    }
    if (els.chart) {
      els.chart.classList.remove("stale");
    }
  }

  function svgEl(name, attrs) {
    var node = document.createElementNS(SVG_NS, name);
    for (var key in attrs) {
      node.setAttribute(key, attrs[key]);
    }
    return node;
  }

  // Round the plotted range outward to multiples of 10 bpm, at least 40 bpm
  // tall, so the axis does not jump on every reading.
  function chartRange(points) {
    var lo = Infinity;
    var hi = -Infinity;
    points.forEach(function (p) {
      lo = Math.min(lo, p.v);
      hi = Math.max(hi, p.v);
    });
    if (!isFinite(lo)) {
      return { lo: 40, hi: 120 };
    }
    lo = Math.floor(lo / 10) * 10;
    hi = Math.ceil(hi / 10) * 10;
    if (hi - lo < 40) {
      var mid = (hi + lo) / 2;
      lo = Math.floor((mid - 20) / 10) * 10;
      hi = lo + 40;
    }
    return { lo: lo, hi: hi };
  }

  function drawChart() {
    if (!els.chart) {
      return;
    }
    var now = Date.now();
    var start = now - CHART_WINDOW_MS;
    history = history.filter(function (p) {
      return p.t >= start;
    });

    var plotW = CHART_W - CHART_PAD.left - CHART_PAD.right;
    var plotH = CHART_H - CHART_PAD.top - CHART_PAD.bottom;
    var range = chartRange(history);
    function x(t) {
      return CHART_PAD.left + ((t - start) / CHART_WINDOW_MS) * plotW;
    }
    function y(v) {
      return CHART_PAD.top + (1 - (v - range.lo) / (range.hi - range.lo)) * plotH;
    }

    var svg = svgEl("svg", {
      viewBox: "0 0 " + CHART_W + " " + CHART_H,
      "aria-hidden": "true",
    });

    // Horizontal gridlines with a bpm label each.
    var step = (range.hi - range.lo) / 4;
    for (var i = 0; i <= 4; i++) {
      var v = range.lo + step * i;
      svg.appendChild(
        svgEl("line", { class: "grid", x1: CHART_PAD.left, x2: CHART_W - CHART_PAD.right, y1: y(v), y2: y(v) })
      );
      var label = svgEl("text", {
        class: "axis-label",
        x: CHART_PAD.left - 6,
        y: y(v) + 4,
        "text-anchor": "end",
      });
      label.textContent = String(Math.round(v));
      svg.appendChild(label);
    }

    // Time axis: the window start and "now".
    var startLabel = svgEl("text", { class: "axis-label", x: CHART_PAD.left, y: CHART_H - 6 });
    startLabel.textContent = "2 min ago";
    svg.appendChild(startLabel);
    var nowLabel = svgEl("text", {
      class: "axis-label",
      x: CHART_W - CHART_PAD.right,
      y: CHART_H - 6,
      "text-anchor": "end",
    });
    nowLabel.textContent = "now";
    svg.appendChild(nowLabel);

    if (history.length === 0) {
      var empty = svgEl("text", { class: "empty-label", x: CHART_W / 2, y: CHART_H / 2 });
      empty.textContent = "Waiting for readings…";
      svg.appendChild(empty);
    } else {
      var d = history
        .map(function (p, idx) {
          return (idx === 0 ? "M" : "L") + x(p.t).toFixed(1) + " " + y(p.v).toFixed(1);
        })
        .join(" ");
      svg.appendChild(svgEl("path", { class: "line", d: d }));
      var last = history[history.length - 1];
      svg.appendChild(svgEl("circle", { class: "dot", cx: x(last.t), cy: y(last.v), r: 4 }));
    }

    els.chart.replaceChildren(svg);
    updateStats();
  }

  function updateStats() {
    if (history.length === 0) {
      els.statMin.textContent = els.statAvg.textContent = els.statMax.textContent = "—";
      return;
    }
    var values = history.map(function (p) {
      return p.v;
    });
    var sum = values.reduce(function (a, b) {
      return a + b;
    }, 0);
    els.statMin.textContent = String(Math.round(Math.min.apply(null, values)));
    els.statAvg.textContent = String(Math.round(sum / values.length));
    els.statMax.textContent = String(Math.round(Math.max.apply(null, values)));
  }

  // Format an ISO 8601 instant into a friendly local time for non-technical
  // users (NFR-3). Falls back to the raw string if parsing fails.
  function formatTimestamp(iso) {
    if (!iso) {
      return "Unknown time";
    }
    var d = new Date(iso);
    if (isNaN(d.getTime())) {
      return iso;
    }
    return d.toLocaleString();
  }

  // While the device is connected but silent, say so instead of leaving an old
  // number on screen as if it were current.
  function updateSilenceNote() {
    var silentFor = lastReadingAt === null ? 0 : Date.now() - lastReadingAt;
    if (deviceLive && lastReadingAt !== null && silentFor > SILENCE_MS) {
      els.readingNote.textContent =
        "No new valid reading for " +
        Math.round(silentFor / 1000) +
        " seconds. The sensor may be off the skin, or readings are being rejected.";
      els.readingNote.hidden = false;
      markStale();
    } else {
      els.readingNote.hidden = true;
    }
  }

  function handleObservation(resource) {
    if (!resource || typeof resource !== "object") {
      return;
    }
    viewObservation(resource);
    noteDeviceReference(resource);
    var quantity = resource.valueQuantity || {};
    var value = quantity.value;
    if (value !== undefined && value !== null) {
      els.hrValue.textContent = String(value);
    }
    els.hrTimestamp.textContent = formatTimestamp(resource.effectiveDateTime);
    markLive();

    // A reading arriving means the device is delivering data, whatever status
    // message we last saw (e.g. one sent before this page connected).
    deviceLive = true;
    lastReadingAt = Date.now();
    setStatus(DEVICE_STATE_LABELS.connected, "connected");
    updateSilenceNote();

    if (typeof value === "number" && isFinite(value)) {
      var t = Date.parse(resource.effectiveDateTime);
      history.push({ t: isNaN(t) ? Date.now() : t, v: value });
      drawChart();
    }
  }

  function handleConnectionState(state) {
    var label = DEVICE_STATE_LABELS[state] || ("Device state: " + state);
    deviceLive = !!LIVE_STATES[state];
    if (deviceLive) {
      // Start the silence countdown afresh after a (re)connect.
      lastReadingAt = Date.now();
      setStatus(label, "connected");
      markLive();
      // The device may have been found only now, with its address.
      refreshDevice();
    } else {
      // Disconnected / reconnecting / connecting: stop showing new values.
      setStatus(label, "down");
      markStale();
    }
  }

  // A new simulated session started: forget everything shown so far.
  function resetDisplay() {
    history = [];
    lastReadingAt = null;
    els.hrValue.textContent = "—";
    els.hrTimestamp.textContent = "No reading yet";
    els.readingNote.hidden = true;
    markLive();
    drawChart();
    resetViewer();
  }

  // ---------------------------------------------------------------------
  // Welcome notice: the safety and scope notes must be acknowledged before
  // the page connects. The acknowledgement lasts for this browser session.
  // ---------------------------------------------------------------------

  var WELCOME_KEY = "vof-welcome-acknowledged";

  function welcomeAcknowledged() {
    try {
      return window.sessionStorage.getItem(WELCOME_KEY) === "yes";
    } catch (err) {
      return false;
    }
  }

  function openWelcome() {
    if (els.welcome.open) {
      return;
    }
    if (typeof els.welcome.showModal === "function") {
      els.welcome.showModal();
    } else {
      els.welcome.setAttribute("open", "");
    }
  }

  // Show the notes unless already acknowledged, then call *proceed* once.
  function requireWelcome(proceed) {
    var acknowledged = welcomeAcknowledged();
    els.welcome.addEventListener("cancel", function (event) {
      // Escape must not stand in for "I understand" the first time.
      if (!acknowledged) {
        event.preventDefault();
      }
    });
    els.welcome.addEventListener("close", function () {
      // Some browsers close a modal on a repeated Escape despite the above.
      if (!acknowledged) {
        openWelcome();
      }
    });
    els.welcomeAck.addEventListener("click", function () {
      var first = !acknowledged;
      acknowledged = true;
      try {
        window.sessionStorage.setItem(WELCOME_KEY, "yes");
      } catch (err) {
        /* storage blocked: ask again next time */
      }
      els.welcome.close();
      if (first) {
        proceed();
      }
    });
    els.welcomeReopen.addEventListener("click", openWelcome);
    if (acknowledged) {
      proceed();
    } else {
      openWelcome();
    }
  }

  // ---------------------------------------------------------------------
  // FHIR resource access: the page reads related resources through the same
  // read-only API any other FHIR client would use.
  // ---------------------------------------------------------------------

  // A relative literal reference this server can resolve, e.g. "Device/mock-hr".
  var LOCAL_REFERENCE = /^(Patient|Device|Observation)\/([A-Za-z0-9\-.]{1,64})$/;

  function fetchResource(reference) {
    var match = LOCAL_REFERENCE.exec(reference);
    if (!match) {
      return Promise.reject(new Error("unsupported reference"));
    }
    var url = "/fhir/" + match[1] + "/" + encodeURIComponent(match[2]);
    return fetch(url, { headers: authHeaders({ Accept: "application/fhir+json" }) }).then(
      function (response) {
        if (!response.ok) {
          throw new Error("HTTP " + response.status);
        }
        return response.json();
      }
    );
  }

  // ---------------------------------------------------------------------
  // Device details under the reading, from the FHIR Device the readings
  // reference. Fetched again on (re)connect: a Bluetooth device's address is
  // known only once it has been found.
  // ---------------------------------------------------------------------

  var deviceReference = null;

  var IDENTIFIER_LABELS = {
    bluetooth_address: "Bluetooth address",
    profile: "Bluetooth profile",
    mock: "Simulator ID",
  };

  function identifierLabel(system) {
    if (IDENTIFIER_LABELS[system]) {
      return IDENTIFIER_LABELS[system];
    }
    var words = String(system).replace(/_/g, " ");
    return words.charAt(0).toUpperCase() + words.slice(1);
  }

  function isSimulated(resource) {
    var security = (resource.meta && resource.meta.security) || [];
    return security.some(function (label) {
      return label && label.code === "HTEST";
    });
  }

  function addDeviceRow(term, detail) {
    var row = document.createElement("div");
    var dt = document.createElement("dt");
    var dd = document.createElement("dd");
    dt.textContent = term;
    dd.textContent = detail;
    row.appendChild(dt);
    row.appendChild(dd);
    els.deviceProps.appendChild(row);
  }

  function renderDevice(device) {
    els.deviceProps.replaceChildren();
    var names = (device.deviceName || []).map(function (entry) {
      return entry.name;
    });
    var model = [device.manufacturer, names[0]].filter(Boolean).join(" ");
    addDeviceRow("Device", model || "Unnamed device");
    (device.identifier || []).forEach(function (identifier) {
      if (identifier && identifier.value) {
        addDeviceRow(identifierLabel(identifier.system), identifier.value);
      }
    });
    if (isSimulated(device)) {
      addDeviceRow("Data", "Simulated (test data)");
    }
    els.deviceProps.hidden = false;
  }

  function refreshDevice() {
    if (!deviceReference) {
      return;
    }
    fetchResource(deviceReference)
      .then(renderDevice)
      .catch(function () {
        /* keep whatever is shown */
      });
  }

  function noteDeviceReference(resource) {
    var reference = resource.device && resource.device.reference;
    if (typeof reference === "string" && reference !== deviceReference) {
      deviceReference = reference;
      refreshDevice();
    }
  }

  // ---------------------------------------------------------------------
  // FHIR resource viewer: the latest Observation as highlighted JSON, values
  // that changed since the previous one flashed, a pause switch, the recent
  // readings, and references that open the resource they point to.
  // ---------------------------------------------------------------------

  var RECENT_LIMIT = 20;
  var viewer = {
    recent: [], // received Observations, newest first
    trail: [], // [{ label, resource }]: the Observation, then opened references
    previous: null, // the Observation shown live before the current one
    paused: false,
    missed: 0, // Observations received while paused
  };

  function span(className, text) {
    var node = document.createElement("span");
    node.className = className;
    node.textContent = text;
    return node;
  }

  function isLeaf(value) {
    return value === null || typeof value !== "object";
  }

  // Paths ("valueQuantity.value", "code.coding[0].code") of leaves in *next*
  // whose value differs from *prev*, or that *prev* lacks.
  function changedPaths(prev, next) {
    var changed = {};
    function walk(a, b, path) {
      if (isLeaf(b)) {
        if (!isLeaf(a) || a !== b) {
          changed[path] = true;
        }
        return;
      }
      var keys = Array.isArray(b) ? b.map(function (_, i) { return i; }) : Object.keys(b);
      keys.forEach(function (key) {
        var childPath = Array.isArray(b) ? path + "[" + key + "]" : (path ? path + "." : "") + key;
        walk(a && typeof a === "object" ? a[key] : undefined, b[key], childPath);
      });
    }
    if (prev) {
      walk(prev, next, "");
    }
    return changed;
  }

  function referenceButton(value) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "json-ref";
    button.textContent = JSON.stringify(value);
    button.title = "Open " + value;
    button.addEventListener("click", function () {
      openReference(value);
    });
    return button;
  }

  // Append *value* to *out* as pretty-printed JSON (two-space indent, the
  // same layout as JSON.stringify(value, null, 2)) built from text nodes.
  function appendJson(out, value, path, indent, changed, key) {
    if (isLeaf(value)) {
      var kind = value === null ? "null" : typeof value;
      var node =
        key === "reference" && typeof value === "string" && LOCAL_REFERENCE.test(value)
          ? referenceButton(value)
          : span("json-" + kind, JSON.stringify(value));
      if (changed[path]) {
        node.classList.add("json-changed");
      }
      out.appendChild(node);
      return;
    }
    var isArray = Array.isArray(value);
    var keys = isArray ? value.map(function (_, i) { return i; }) : Object.keys(value);
    var open = isArray ? "[" : "{";
    var close = isArray ? "]" : "}";
    if (keys.length === 0) {
      out.appendChild(document.createTextNode(open + close));
      return;
    }
    var inner = indent + "  ";
    out.appendChild(document.createTextNode(open + "\n"));
    keys.forEach(function (k, index) {
      out.appendChild(document.createTextNode(inner));
      var childPath = isArray ? path + "[" + k + "]" : (path ? path + "." : "") + k;
      if (!isArray) {
        out.appendChild(span("json-key", JSON.stringify(k)));
        out.appendChild(document.createTextNode(": "));
      }
      appendJson(out, value[k], childPath, inner, changed, isArray ? key : k);
      out.appendChild(document.createTextNode(index < keys.length - 1 ? ",\n" : "\n"));
    });
    out.appendChild(document.createTextNode(indent + close));
  }

  function renderTrail() {
    els.fhirTrail.replaceChildren();
    viewer.trail.forEach(function (step, index) {
      if (index > 0) {
        els.fhirTrail.appendChild(span("trail-sep", "›"));
      }
      var last = index === viewer.trail.length - 1;
      var item = document.createElement(last ? "span" : "button");
      item.textContent = step.label;
      if (last) {
        item.className = "trail-current";
        item.setAttribute("aria-current", "true");
      } else {
        item.type = "button";
        item.className = "trail-link";
        item.addEventListener("click", function () {
          viewer.trail = viewer.trail.slice(0, index + 1);
          showTrail({}, true);
        });
      }
      els.fhirTrail.appendChild(item);
    });
  }

  // Draw the last resource on the trail, highlighting the *changed* paths.
  // Navigating to another resource starts at its top; live updates keep the
  // reader's scroll position.
  function showTrail(changed, navigated) {
    renderTrail();
    var step = viewer.trail[viewer.trail.length - 1];
    els.fhirJson.replaceChildren();
    if (!step) {
      els.fhirJson.textContent = "Waiting for the first resource…";
      return;
    }
    appendJson(els.fhirJson, step.resource, "", "", changed, null);
    if (navigated) {
      els.fhirJson.scrollTop = 0;
    }
  }

  function resourceLabel(resource) {
    return resource.resourceType + (resource.id ? "/" + resource.id : "");
  }

  function openReference(reference) {
    fetchResource(reference)
      .then(function (resource) {
        viewer.trail.push({ label: reference, resource: resource });
        setPaused(true); // keep the opened resource on screen
        showTrail({}, true);
      })
      .catch(function (err) {
        var error = { error: "Could not open " + reference + ": " + err.message };
        viewer.trail.push({ label: reference, resource: error });
        showTrail({}, true);
      });
  }

  function showObservation(resource, changed, navigated) {
    viewer.trail = [{ label: resourceLabel(resource), resource: resource }];
    showTrail(changed, navigated);
  }

  function updatePauseButton() {
    els.fhirPause.setAttribute("aria-pressed", viewer.paused ? "true" : "false");
    if (!viewer.paused) {
      els.fhirPause.textContent = "Pause";
    } else if (viewer.missed > 0) {
      els.fhirPause.textContent = "Resume (" + viewer.missed + " new)";
    } else {
      els.fhirPause.textContent = "Resume";
    }
  }

  function setPaused(paused) {
    viewer.paused = paused;
    if (!paused) {
      viewer.missed = 0;
      var latest = viewer.recent[0];
      if (latest) {
        showObservation(latest, {}, true);
        viewer.previous = latest;
      }
    }
    updatePauseButton();
    renderRecent();
  }

  // Short names for the LOINC codes this project emits (vitals/builtin/).
  var VITAL_NAMES = {
    "8867-4": "Heart rate",
    "85354-9": "Blood pressure",
    "59408-5": "Oxygen saturation",
    "8310-5": "Body temperature",
    "29463-7": "Body weight",
  };

  function formatQuantity(quantity) {
    return quantity && quantity.value !== undefined ? String(quantity.value) : "?";
  }

  // One line per reading: time, what was measured, and its value(s).
  function summarize(resource) {
    var coding = (resource.code && resource.code.coding) || [];
    var first = coding[0] || {};
    var name = VITAL_NAMES[first.code] || (first.code ? "LOINC " + first.code : "Observation");
    var time = resource.effectiveDateTime ? formatTimestamp(resource.effectiveDateTime) : "";
    var value = "";
    if (resource.valueQuantity) {
      value = formatQuantity(resource.valueQuantity) + " " + (resource.valueQuantity.unit || "");
    } else if (resource.component && resource.component.length) {
      var parts = resource.component.map(function (component) {
        return formatQuantity(component.valueQuantity);
      });
      var unit = (resource.component[0].valueQuantity || {}).unit || "";
      value = parts.join("/") + " " + unit;
    }
    return [time, name, value.trim()].filter(Boolean).join(" · ");
  }

  function renderRecent() {
    els.fhirRecent.replaceChildren();
    var shown = viewer.trail[0] && viewer.trail[0].resource;
    viewer.recent.forEach(function (resource) {
      var item = document.createElement("li");
      var button = document.createElement("button");
      button.type = "button";
      button.className = "recent-item";
      button.textContent = summarize(resource);
      if (resource === shown) {
        button.setAttribute("aria-current", "true");
      }
      button.addEventListener("click", function () {
        setPaused(true);
        showObservation(resource, {}, true);
        renderRecent();
      });
      item.appendChild(button);
      els.fhirRecent.appendChild(item);
    });
  }

  function viewObservation(resource) {
    viewer.recent.unshift(resource);
    if (viewer.recent.length > RECENT_LIMIT) {
      viewer.recent.length = RECENT_LIMIT;
    }
    if (viewer.paused) {
      viewer.missed += 1;
      updatePauseButton();
    } else {
      showObservation(resource, changedPaths(viewer.previous, resource));
      viewer.previous = resource;
    }
    renderRecent();
  }

  function resetViewer() {
    viewer.recent = [];
    viewer.trail = [];
    viewer.previous = null;
    viewer.missed = 0;
    viewer.paused = false;
    updatePauseButton();
    showTrail({});
    renderRecent();
  }

  function handleMessage(event) {
    var envelope;
    try {
      envelope = JSON.parse(event.data);
    } catch (err) {
      return;
    }
    if (!envelope || typeof envelope !== "object") {
      return;
    }
    if (envelope.type === "observation") {
      handleObservation(envelope.resource);
    } else if (envelope.type === "connection_state") {
      handleConnectionState(envelope.state);
    } else if (envelope.type === "reset") {
      resetDisplay();
    }
  }

  function authHeaders(extra) {
    var headers = currentToken ? { Authorization: "Bearer " + currentToken } : {};
    for (var key in extra) {
      headers[key] = extra[key];
    }
    return headers;
  }

  function findScenario(id) {
    var found = null;
    scenarioOptions.forEach(function (candidate) {
      if (candidate.id === id) {
        found = candidate;
      }
    });
    return found;
  }

  // The description follows the dropdown; the status line says what is running.
  function showSelectedDescription() {
    var option = findScenario(els.simSelect.value);
    els.simDescription.textContent = option ? option.description : "";
  }

  function markRunning(id) {
    var option = findScenario(id);
    els.simStatus.textContent = option ? "Simulating: " + option.label : "";
  }

  // Start the dropdown's scenario from the beginning. The server clears the
  // previous run and tells every page to reset (see the "reset" envelope).
  function startScenario() {
    var id = els.simSelect.value;
    els.simStart.disabled = true;
    fetch("/mock/scenario", {
      method: "PUT",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ scenario: id }),
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("HTTP " + response.status);
        }
        return response.json();
      })
      .then(function (data) {
        markRunning(data.current);
      })
      .catch(function () {
        els.simStatus.textContent = "Could not start the simulation.";
      })
      .then(function () {
        els.simStart.disabled = false;
      });
  }

  // Build the dropdown, one group (optgroup) per scenario category.
  function renderScenarios(data) {
    scenarioOptions = data.scenarios || [];
    els.simSelect.replaceChildren();
    var group = null;
    var optgroup = null;
    scenarioOptions.forEach(function (option) {
      if (option.group !== group) {
        group = option.group;
        optgroup = document.createElement("optgroup");
        optgroup.label = group;
        els.simSelect.appendChild(optgroup);
      }
      var item = document.createElement("option");
      item.value = option.id;
      item.textContent = option.label;
      optgroup.appendChild(item);
    });
    els.simSelect.value = data.current;
    showSelectedDescription();
    markRunning(data.current);
    els.simCard.hidden = false;
  }

  // Only the mock adapter exposes /mock/scenarios; any other answer (404 for a
  // real device, 401 for a wrong token) leaves the simulator panel hidden.
  function loadScenarios() {
    els.simCard.hidden = true;
    fetch("/mock/scenarios", { headers: authHeaders() })
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (data) {
        if (data) {
          renderScenarios(data);
        }
      })
      .catch(function () {
        /* leave the panel hidden */
      });
  }

  function buildWebSocketUrl(token) {
    var scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    var query = token ? "?token=" + encodeURIComponent(token) : "";
    return scheme + "//" + window.location.host + "/ws" + query;
  }

  function scheduleReconnect() {
    if (manualClose || reconnectTimer) {
      return;
    }
    // Automatic reconnect without user action or page reload (FR-6, FR-7).
    reconnectTimer = window.setTimeout(function () {
      reconnectTimer = null;
      openSocket(currentToken);
    }, 3000);
  }

  function openSocket(token) {
    if (!token && authRequired) {
      return;
    }
    manualClose = false;

    try {
      socket = new WebSocket(buildWebSocketUrl(token));
    } catch (err) {
      setStatus("Unable to open connection", "down");
      scheduleReconnect();
      return;
    }

    setStatus("Connecting to the server…", null);

    socket.addEventListener("open", function () {
      setStatus("Waiting for device…", null);
    });

    socket.addEventListener("message", handleMessage);

    socket.addEventListener("close", function () {
      // The link to the server dropped: stop showing live values and retry
      // unless the user disconnected on purpose.
      markStale();
      if (!manualClose) {
        setStatus("Server connection lost — reconnecting…", "down");
        scheduleReconnect();
      }
    });

    socket.addEventListener("error", function () {
      // "close" follows and handles reconnect; just reflect the failure.
      setStatus("Connection error", "down");
    });
  }

  function onSubmit(event) {
    event.preventDefault();
    var token = els.tokenInput.value.trim();
    if (!token) {
      return;
    }
    currentToken = token;

    // Reset any existing connection before opening a new one.
    manualClose = true;
    if (reconnectTimer) {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (socket) {
      try {
        socket.close();
      } catch (err) {
        /* ignore */
      }
      socket = null;
    }

    openSocket(currentToken);
    loadScenarios();
  }

  // Demo mode: the server needs no token, so skip the prompt and connect now.
  function startDemo() {
    authRequired = false;
    els.form.hidden = true;
    els.demoNote.hidden = false;
    openSocket("");
    loadScenarios();
  }

  // Ask the server whether a token is needed. If it cannot say, keep the
  // token prompt, which works either way.
  function checkAuthRequired() {
    fetch("/status")
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (data) {
        if (data && data.auth_required === false) {
          startDemo();
        }
      })
      .catch(function () {
        /* keep the token prompt */
      });
  }

  function init() {
    cacheElements();
    els.form.addEventListener("submit", onSubmit);
    els.simSelect.addEventListener("change", showSelectedDescription);
    els.simStart.addEventListener("click", startScenario);
    els.fhirPause.addEventListener("click", function () {
      setPaused(!viewer.paused);
    });
    drawChart();
    // Connect only once the safety and scope notes are acknowledged.
    requireWelcome(checkAuthRequired);
    // Slide the window forward between readings (and across disconnects).
    window.setInterval(function () {
      drawChart();
      updateSilenceNote();
    }, CHART_REFRESH_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
