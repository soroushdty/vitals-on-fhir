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
  }

  function markLive() {
    if (els.reading) {
      els.reading.classList.remove("stale");
    }
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
  }

  function init() {
    cacheElements();
    els.form.addEventListener("submit", onSubmit);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
