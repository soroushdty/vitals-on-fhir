/* SPDX-License-Identifier: AGPL-3.0-or-later */

/*
 * Colour theme: light or dark.
 *
 * Loaded in <head> so a saved choice applies before the page is drawn (no
 * flash of the other theme). Without a saved choice the page follows the
 * system setting through the prefers-color-scheme rule in style.css, and the
 * switch shows whichever theme that gives. Choosing a theme stores only its
 * name ("light" or "dark") in localStorage; nothing else is stored.
 */

(function () {
  "use strict";

  var STORAGE_KEY = "vof-theme";
  var root = document.documentElement;
  var systemDark = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  var buttons = [];

  function savedTheme() {
    try {
      var value = window.localStorage.getItem(STORAGE_KEY);
      return value === "light" || value === "dark" ? value : null;
    } catch (err) {
      return null; // storage blocked: follow the system
    }
  }

  function currentTheme() {
    return savedTheme() || (systemDark && systemDark.matches ? "dark" : "light");
  }

  function showCurrent() {
    var theme = currentTheme();
    buttons.forEach(function (button) {
      var on = button.getAttribute("data-theme-choice") === theme;
      button.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function choose(theme) {
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch (err) {
      /* storage blocked: the choice lasts until the page is reloaded */
    }
    root.setAttribute("data-theme", theme);
    showCurrent();
  }

  // Apply a saved choice now, before the body is drawn.
  var saved = savedTheme();
  if (saved) {
    root.setAttribute("data-theme", saved);
  }

  function init() {
    buttons = Array.prototype.slice.call(document.querySelectorAll("[data-theme-choice]"));
    buttons.forEach(function (button) {
      button.addEventListener("click", function () {
        choose(button.getAttribute("data-theme-choice"));
      });
    });
    showCurrent();
    // With no saved choice, keep the switch in step with the system setting.
    if (systemDark && systemDark.addEventListener) {
      systemDark.addEventListener("change", showCurrent);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
