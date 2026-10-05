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
 * page then shows buttons to switch the simulated heart rhythm.
 *
 * Readings are also drawn as a live two-minute line chart (plain SVG, no
 * libraries) with the lowest / average / highest value in view.
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

  var history = []; // [{ t: epoch ms, v: bpm }], oldest first
  var scenarioOptions = []; // [{ id, label, description }] from /mock/scenarios
  var socket = null;
  var reconnectTimer = null;
  var manualClose = false;
  var currentToken = "";

  var els = {};

  function cacheElements() {
    els.form = document.getElementById("connect-form");
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
    els.simButtons = document.getElementById("sim-buttons");
    els.simStatus = document.getElementById("sim-status");
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

  function handleObservation(resource) {
    if (!resource || typeof resource !== "object") {
      return;
    }
    var quantity = resource.valueQuantity || {};
    var value = quantity.value;
    if (value !== undefined && value !== null) {
      els.hrValue.textContent = String(value);
    }
    els.hrTimestamp.textContent = formatTimestamp(resource.effectiveDateTime);
    markLive();

    // A reading arriving means the device is delivering data, whatever status
    // message we last saw (e.g. one sent before this page connected).
    setStatus(DEVICE_STATE_LABELS.connected, "connected");

    if (typeof value === "number" && isFinite(value)) {
      var t = Date.parse(resource.effectiveDateTime);
      history.push({ t: isNaN(t) ? Date.now() : t, v: value });
      drawChart();
    }
  }

  function handleConnectionState(state) {
    var label = DEVICE_STATE_LABELS[state] || ("Device state: " + state);
    if (LIVE_STATES[state]) {
      setStatus(label, "connected");
      markLive();
    } else {
      // Disconnected / reconnecting / connecting: stop showing new values.
      setStatus(label, "down");
      markStale();
    }
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
    }
  }

  function authHeaders(extra) {
    var headers = { Authorization: "Bearer " + currentToken };
    for (var key in extra) {
      headers[key] = extra[key];
    }
    return headers;
  }

  // Highlight the active scenario button and say which one is running.
  function markScenario(id) {
    var label = "";
    Array.prototype.forEach.call(els.simButtons.children, function (button) {
      var active = button.getAttribute("data-id") === id;
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    scenarioOptions.forEach(function (option) {
      if (option.id === id) {
        label = option.label;
      }
    });
    els.simStatus.textContent = label ? "Simulating: " + label : "";
  }

  function selectScenario(id) {
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
        markScenario(data.current);
      })
      .catch(function () {
        els.simStatus.textContent = "Could not change the simulated rhythm.";
      });
  }

  function renderScenarios(data) {
    scenarioOptions = data.scenarios || [];
    els.simButtons.replaceChildren();
    scenarioOptions.forEach(function (option) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "sim-button";
      button.setAttribute("data-id", option.id);
      button.setAttribute("aria-pressed", "false");
      var title = document.createElement("strong");
      title.textContent = option.label;
      var detail = document.createElement("span");
      detail.textContent = option.description;
      button.appendChild(title);
      button.appendChild(detail);
      button.addEventListener("click", function () {
        selectScenario(option.id);
      });
      els.simButtons.appendChild(button);
    });
    markScenario(data.current);
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
    return (
      scheme +
      "//" +
      window.location.host +
      "/ws?token=" +
      encodeURIComponent(token)
    );
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
    if (!token) {
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

  function init() {
    cacheElements();
    els.form.addEventListener("submit", onSubmit);
    drawChart();
    // Slide the window forward between readings (and across disconnects).
    window.setInterval(drawChart, CHART_REFRESH_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
