// settings.js (remplacer le fichier existant)
document.addEventListener("DOMContentLoaded", () => {
  if (window.__settingsInit) return;
  window.__settingsInit = true;

  const STORAGE_KEY = "site_interface_mode";

  const log = (...args) => { try { console.debug("[settings]", ...args); } catch(e){} };

  function setMode(mode, persist = false) {
    if (mode === "mobile") {
      document.body.classList.add("mobile-mode");
      document.body.classList.remove("pc-mode");
    } else {
      document.body.classList.add("pc-mode");
      document.body.classList.remove("mobile-mode");
    }
    if (persist) localStorage.setItem(STORAGE_KEY, mode);
    log("mode set to", mode);
  }

  // restore mode immediately
  const saved = localStorage.getItem(STORAGE_KEY);
  setMode(saved === "mobile" ? "mobile" : "pc", false);

  function attachIfReady() {
    const gear = document.getElementById("settings-gear");
    const popup = document.getElementById("settings-popup");
    const toggle = document.getElementById("interface-toggle");

    if (gear && popup && !gear.__settingsAttached) {
      gear.addEventListener("click", (e) => {
        e.stopPropagation();
        const isOpen = popup.classList.toggle("open");
        popup.setAttribute("aria-hidden", String(!isOpen));
        gear.setAttribute("aria-expanded", String(isOpen));
        log("gear clicked, popup open:", isOpen);
      });
      gear.__settingsAttached = true;
      log("gear/popup handlers attached");
    }

    if (toggle && !toggle.__settingsAttached) {
      toggle.checked = (localStorage.getItem(STORAGE_KEY) || "pc") === "pc";
      toggle.addEventListener("change", () => {
        const mode = toggle.checked ? "pc" : "mobile";
        setMode(mode, true);
      });
      toggle.__settingsAttached = true;
      log("toggle handler attached, checked:", toggle.checked);
    }

    return !!document.getElementById("settings-gear");
  }

  if (!attachIfReady()) {
    const mo = new MutationObserver((mutations, obs) => {
      if (attachIfReady()) {
        obs.disconnect();
        log("MutationObserver: attached and disconnected");
      }
    });
    mo.observe(document.documentElement || document.body, { childList: true, subtree: true });
    setTimeout(() => { try { mo.disconnect(); log("MutationObserver timeout disconnected"); } catch(e){} }, 10000);
  }
});
