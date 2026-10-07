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
 *   { "type": "connection_state", "state": "<connected|disconnected|...>",
 *     "reason": "<why not connected yet>" (only while the server retries) }
 *
 * While the device is disconnected the last reading is dimmed and no new
 * values are shown; presentation resumes automatically on reconnect (FR-6).
 *
 * When the server runs the mock adapter it also exposes /mock/scenarios; the
 * page then shows a dropdown and a Simulate button that starts the chosen
 * scenario from the beginning. A third envelope, { "type": "reset" }, then
 * tells every open page to clear its chart and readings.
 *
 * Readings are also drawn as a live strip chart (plain SVG, no libraries): a
 * fixed time scale with a gridline every 10 seconds, counted from the first
 * reading, that grows to the right and scrolls sideways. It follows the latest
 * reading unless the user has scrolled back. Below it are the lowest, average
 * and highest values kept (up to 30 minutes).
 *
 * The page opens on a start screen with the safety and scope notes and the
 * access token; nothing connects until "I understand". GET /status says
 * whether a token is needed (in demo mode the token field is hidden), and the
 * token is checked against GET /fhir/metadata before the app screen opens.
 * The Home button disconnects, forgets the token and returns to the start
 * screen. The token is never stored.
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

  // Live chart: a strip at a fixed time scale that grows to the right and
  // scrolls sideways, with the bpm axis fixed on the left (sizes in CSS px).
  var CHART_REFRESH_MS = 1000;
  var CHART_H = 220;
  var CHART_PAD = { top: 12, bottom: 24, left: 8, right: 16 };
  var CHART_AXIS_W = 40;
  var CHART_PX_PER_S = 6; // so the 10 s gridlines are 60 px apart
  var CHART_TICK_S = 10;
  var CHART_KEEP_MS = 30 * 60 * 1000; // older readings are dropped
  var CHART_GAP_MS = 5000; // a longer silence breaks the line
  var CHART_FOLLOW_SLACK = 8; // px from the right edge that still counts as "at latest"
  var SVG_NS = "http://www.w3.org/2000/svg";

  // Connected but no valid reading for this long: tell the user (e.g. sensor off).
  var SILENCE_MS = 8000;

  var history = []; // [{ t: epoch ms, v: bpm }], oldest first
  var sessionStart = null; // epoch ms of the session's first reading: "0 s" on the chart
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
    els.chartLatest = document.getElementById("chart-latest");
    els.statMin = document.getElementById("stat-min");
    els.statAvg = document.getElementById("stat-avg");
    els.statMax = document.getElementById("stat-max");
    els.simCard = document.getElementById("sim-card");
    els.simSelect = document.getElementById("sim-select");
    els.simStart = document.getElementById("sim-start");
    els.simDescription = document.getElementById("sim-description");
    els.simStatus = document.getElementById("sim-status");
    els.readingNote = document.getElementById("reading-note");
    els.connectionReason = document.getElementById("connection-reason");
    els.deviceProps = document.getElementById("device-props");
    els.homeView = document.getElementById("home-view");
    els.appView = document.getElementById("app-view");
    els.homeButton = document.getElementById("home-button");
    els.tokenField = document.getElementById("token-field");
    els.connectError = document.getElementById("connect-error");
    els.demoBadge = document.getElementById("demo-badge");
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

  // Build the chart's fixed bpm axis and its scrolling plot area once, so
  // redrawing every second keeps the reader's scroll position.
  function initChart() {
    els.chartAxis = document.createElement("div");
    els.chartAxis.className = "chart-axis";
    els.chartScroll = document.createElement("div");
    els.chartScroll.className = "chart-scroll";
    els.chart.replaceChildren(els.chartAxis, els.chartScroll);
    els.chartScroll.addEventListener("scroll", updateLatestButton);
    els.chartLatest.addEventListener("click", function () {
      scrollChartToLatest();
      updateLatestButton();
    });
  }

  // True when the plot is scrolled to its right edge (or does not scroll).
  function chartFollowsLatest() {
    var box = els.chartScroll;
    return box.scrollWidth - box.clientWidth - box.scrollLeft <= CHART_FOLLOW_SLACK;
  }

  function scrollChartToLatest() {
    els.chartScroll.scrollLeft = els.chartScroll.scrollWidth;
  }

  function updateLatestButton() {
    els.chartLatest.hidden = chartFollowsLatest();
  }

  function drawChart() {
    if (!els.chartScroll) {
      return;
    }
    var now = Date.now();
    history = history.filter(function (p) {
      return p.t >= now - CHART_KEEP_MS;
    });
    var following = chartFollowsLatest();
    var visibleW = els.chartScroll.clientWidth || 480;
    var plotH = CHART_H - CHART_PAD.top - CHART_PAD.bottom;
    var range = chartRange(history);
    function y(v) {
      return CHART_PAD.top + (1 - (v - range.lo) / (range.hi - range.lo)) * plotH;
    }

    // The strip starts at the 10 s tick at or before the oldest reading kept
    // and runs to now; it fills at least the visible width.
    var hasData = history.length > 0 && sessionStart !== null;
    var firstTick = 0;
    var start = now;
    var end = now;
    if (hasData) {
      firstTick = Math.floor((history[0].t - sessionStart) / 1000 / CHART_TICK_S) * CHART_TICK_S;
      start = sessionStart + firstTick * 1000;
      end = Math.max(now, history[history.length - 1].t);
    }
    function x(t) {
      return CHART_PAD.left + ((t - start) / 1000) * CHART_PX_PER_S;
    }
    var width = Math.max(visibleW, Math.ceil(x(end)) + CHART_PAD.right);

    var plot = svgEl("svg", { width: width, height: CHART_H, "aria-hidden": "true" });
    var axis = svgEl("svg", { width: CHART_AXIS_W, height: CHART_H, "aria-hidden": "true" });

    // Horizontal gridlines across the strip; their bpm labels on the fixed axis.
    var step = (range.hi - range.lo) / 4;
    for (var i = 0; i <= 4; i++) {
      var v = range.lo + step * i;
      plot.appendChild(svgEl("line", { class: "grid", x1: 0, x2: width, y1: y(v), y2: y(v) }));
      var label = svgEl("text", {
        class: "axis-label",
        x: CHART_AXIS_W - 6,
        y: y(v) + 4,
        "text-anchor": "end",
      });
      label.textContent = String(Math.round(v));
      axis.appendChild(label);
    }

    if (!hasData) {
      var empty = svgEl("text", { class: "empty-label", x: visibleW / 2, y: CHART_H / 2 });
      empty.textContent = "Waiting for readings…";
      plot.appendChild(empty);
    } else {
      // Vertical gridline and label every 10 s, counted from the first reading.
      var lastTick = Math.floor((end - sessionStart) / 1000 / CHART_TICK_S) * CHART_TICK_S;
      for (var sec = firstTick; sec <= lastTick; sec += CHART_TICK_S) {
        var tx = x(sessionStart + sec * 1000);
        plot.appendChild(svgEl("line", {
          class: "grid grid-time",
          x1: tx,
          x2: tx,
          y1: CHART_PAD.top,
          y2: CHART_H - CHART_PAD.bottom,
        }));
        var tick = svgEl("text", {
          class: "axis-label",
          x: tx,
          y: CHART_H - 6,
          "text-anchor": tx < 20 ? "start" : "middle",
        });
        tick.textContent = sec + " s";
        plot.appendChild(tick);
      }

      // The line, broken wherever readings stopped for a while.
      var d = history
        .map(function (p, idx) {
          var gap = idx === 0 || p.t - history[idx - 1].t > CHART_GAP_MS;
          return (gap ? "M" : "L") + x(p.t).toFixed(1) + " " + y(p.v).toFixed(1);
        })
        .join(" ");
      plot.appendChild(svgEl("path", { class: "line", d: d }));
      var last = history[history.length - 1];
      plot.appendChild(svgEl("circle", { class: "dot", cx: x(last.t), cy: y(last.v), r: 4 }));
    }

    els.chartAxis.replaceChildren(axis);
    els.chartScroll.replaceChildren(plot);
    if (following) {
      scrollChartToLatest();
    }
    updateLatestButton();
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
    showConnectionReason(null);
    updateSilenceNote();

    if (typeof value === "number" && isFinite(value)) {
      var t = Date.parse(resource.effectiveDateTime);
      var point = { t: isNaN(t) ? Date.now() : t, v: value };
      if (sessionStart === null) {
        sessionStart = point.t;
      }
      history.push(point);
      drawChart();
    }
  }

  // Why the device is not connected yet, as the server reported it (or hide).
  function showConnectionReason(reason) {
    if (reason) {
      els.connectionReason.textContent =
        "Not connected yet: " + reason + ". The service keeps trying.";
      els.connectionReason.hidden = false;
    } else {
      els.connectionReason.textContent = "";
      els.connectionReason.hidden = true;
    }
  }

  function handleConnectionState(state, reason) {
    var label = DEVICE_STATE_LABELS[state] || ("Device state: " + state);
    deviceLive = !!LIVE_STATES[state];
    showConnectionReason(deviceLive ? null : reason);
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
    sessionStart = null;
    if (els.chartScroll) {
      els.chartScroll.scrollLeft = 0;
    }
    lastReadingAt = null;
    els.hrValue.textContent = "—";
    els.hrTimestamp.textContent = "No reading yet";
    els.readingNote.hidden = true;
    markLive();
    drawChart();
    resetViewer();
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
      handleConnectionState(envelope.state, envelope.reason);
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
    // The token is checked first: the server rejects a WebSocket before
    // accepting it, which the browser reports only as a dropped connection.
    reconnectTimer = window.setTimeout(function () {
      reconnectTimer = null;
      checkToken(currentToken).then(function (result) {
        if (manualClose) {
          return;
        }
        if (result === "rejected") {
          goHome(TOKEN_REJECTED_LATER);
        } else {
          openSocket(currentToken);
        }
      });
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

  // ---------------------------------------------------------------------
  // Start screen and app screen. The start screen carries the safety and
  // scope notes and the token; "I understand" checks the token and opens the
  // app screen, and Home goes back, disconnecting and forgetting the token.
  // The token is never stored.
  // ---------------------------------------------------------------------

  var TOKEN_REJECTED = "That access token was not accepted. Check it and try again.";
  var TOKEN_REJECTED_LATER =
    "The server no longer accepts this access token. Enter the current one to reconnect.";

  // Ask the API whether *token* is accepted: "ok", "rejected" or "unreachable".
  // GET /fhir/metadata needs the token and returns a fixed document.
  function checkToken(token) {
    if (!authRequired) {
      return Promise.resolve("ok");
    }
    return fetch("/fhir/metadata", { headers: { Authorization: "Bearer " + token } })
      .then(function (response) {
        if (response.ok) {
          return "ok";
        }
        return response.status === 401 || response.status === 403 ? "rejected" : "unreachable";
      })
      .catch(function () {
        return "unreachable";
      });
  }

  function showConnectError(message) {
    els.connectError.textContent = message;
    els.connectError.hidden = !message;
  }

  function showView(view) {
    els.homeView.hidden = view !== "home";
    els.appView.hidden = view !== "app";
    window.scrollTo(0, 0);
  }

  function enterApp(token) {
    currentToken = token;
    els.tokenInput.value = "";
    showConnectError("");
    showView("app");
    drawChart(); // now that the chart has a width
    openSocket(currentToken);
    loadScenarios();
  }

  // Close the connection and clear everything the session showed.
  function disconnect() {
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
    currentToken = "";
    deviceLive = false;
    deviceReference = null;
    els.deviceProps.replaceChildren();
    els.deviceProps.hidden = true;
    els.simCard.hidden = true;
    resetDisplay();
    setStatus("Not connected", null);
    showConnectionReason(null);
  }

  function goHome(message) {
    disconnect();
    showView("home");
    showConnectError(message || "");
    (authRequired ? els.tokenInput : els.connectButton).focus();
  }

  function onSubmit(event) {
    event.preventDefault();
    showConnectError("");
    if (!authRequired) {
      enterApp("");
      return;
    }
    var token = els.tokenInput.value.trim();
    if (!token) {
      showConnectError("Enter the access token (VOF_API_TOKEN) set on the server.");
      els.tokenInput.focus();
      return;
    }
    els.connectButton.disabled = true;
    checkToken(token).then(function (result) {
      els.connectButton.disabled = false;
      if (result === "ok") {
        enterApp(token);
      } else if (result === "rejected") {
        showConnectError(TOKEN_REJECTED);
        els.tokenInput.select();
      } else {
        showConnectError("Could not reach the server. Is vitals-on-fhir running?");
      }
    });
  }

  // Demo mode: the server needs no token, so the start screen asks only for
  // the acknowledgement.
  function useDemoMode() {
    authRequired = false;
    els.tokenField.hidden = true;
    els.tokenInput.disabled = true;
    els.demoNote.hidden = false;
    els.demoBadge.hidden = false;
    els.connectButton.textContent = "I understand — start demo";
  }

  // Ask the server whether a token is needed. If it cannot say, keep the
  // token field, which works either way.
  function checkAuthRequired() {
    fetch("/status")
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (data) {
        if (data && data.auth_required === false) {
          useDemoMode();
        }
      })
      .catch(function () {
        /* keep the token field */
      });
  }

  function init() {
    cacheElements();
    els.form.addEventListener("submit", onSubmit);
    els.homeButton.addEventListener("click", function () {
      goHome("");
    });
    els.simSelect.addEventListener("change", showSelectedDescription);
    els.simStart.addEventListener("click", startScenario);
    els.fhirPause.addEventListener("click", function () {
      setPaused(!viewer.paused);
    });
    initChart();
    drawChart();
    // Nothing connects until the start screen's "I understand".
    checkAuthRequired();
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
