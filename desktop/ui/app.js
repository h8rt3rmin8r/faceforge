function setError(title, detail) {
  const banner = document.getElementById("error-banner");
  if (!banner) return;
  document.getElementById("error-title").textContent = title || "";
  document.getElementById("error-detail").textContent = detail || "";
  banner.classList.remove("hidden");
}

function clearError() {
  const banner = document.getElementById("error-banner");
  if (!banner) return;
  banner.classList.add("hidden");
  document.getElementById("error-title").textContent = "";
  document.getElementById("error-detail").textContent = "";
}

function toMessage(err) {
  if (!err) return "Unknown error";
  if (typeof err === "string") return err;
  if (err instanceof Error) return err.message || String(err);
  return String(err);
}

const invoke = async (cmd, args) => {
  const core = window.__TAURI__?.core;
  if (!core?.invoke) {
    throw new Error(
      "Desktop integration is unavailable. This usually means the app is not running inside the Tauri shell or was packaged incorrectly."
    );
  }
  return await core.invoke(cmd, args);
};

const listen = async (event, handler) => {
  const eventApi = window.__TAURI__?.event;
  if (!eventApi?.listen) {
    throw new Error(
      "Desktop events are unavailable. Please reinstall or run the packaged Desktop app (not a browser tab)."
    );
  }
  return await eventApi.listen(event, handler);
};

const $ = (id) => document.getElementById(id);

function show(sectionId) {
  for (const id of ["wizard", "status", "logs"]) {
    $(id).classList.toggle("hidden", id !== sectionId);
  }
}

function showExitModal(visible) {
  $("exit-modal").classList.toggle("hidden", !visible);
}

function renderStatus(state) {
  const s = state.status;
  const rows = [];
  if (!s) {
    rows.push(["Core", "Not started"]);
  } else {
    rows.push(["FACEFORGE_HOME", state.faceforge_home || "-"]);
    rows.push(["Core URL", s.core_url]);
    rows.push(["Core running", s.core_running ? "Yes" : "No"]);
    rows.push(["Core healthy", s.core_healthy ? "Yes" : "No"]);
    rows.push(["Seaweed enabled", s.seaweed_enabled ? "Yes" : "No"]);
    rows.push(["Seaweed running", s.seaweed_running ? "Yes" : "No"]);
    rows.push(["Seaweed S3 port", s.seaweed_s3_port || "-"]);
  }
  $("status-body").innerHTML = rows
    .map(([k, v]) => `<div class="k">${k}</div><div>${v}</div>`)
    .join("");
  $("token").value = state.install_token || "";
}

async function refresh() {
  const state = await invoke("get_state");
  if (!state.configured) {
    show("wizard");
  } else {
    show("status");
  }

  if (state.core_port) $("core_port").value = state.core_port;
  if (state.seaweed_s3_port) $("seaweed_port").value = state.seaweed_s3_port;
  $("seaweed_enabled").checked = !!state.seaweed_enabled;
  if (state.faceforge_home) $("home").value = state.faceforge_home;

  renderStatus(state);
}

async function suggestPorts() {
  const p = await invoke("suggest_ports");
  $("core_port").value = p.core_port;
  $("seaweed_port").value = p.seaweed_s3_port;
}

async function browseHome() {
  const picked = await invoke("pick_faceforge_home");
  if (picked) $("home").value = picked;
}

async function saveWizard() {
  const home = $("home").value.trim();
  if (!home) {
    setError("Setup needed", "Please choose FACEFORGE_HOME to continue.");
    return;
  }
  const corePort = parseInt($("core_port").value, 10);
  const seaweedEnabled = $("seaweed_enabled").checked;
  const seaweedPort = parseInt($("seaweed_port").value, 10);

  const payload = {
    faceforge_home: home,
    core_port: corePort,
    seaweed_enabled: seaweedEnabled,
    seaweed_s3_port: seaweedEnabled ? seaweedPort : null,
    seaweed_weed_path: null
  };

  await invoke("save_wizard_settings", { payload });
  await refresh();
}

async function start() {
  await invoke("start_services");
  await refresh();
}

async function stop() {
  await invoke("stop_services");
  await refresh();
}

async function restart() {
  await invoke("restart_services");
  await refresh();
}

async function openUi() {
  await invoke("open_ui");
}

async function copyToken() {
  const state = await invoke("get_state");
  const token = state.install_token || "";
  if (!token) return;
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(token);
  } else {
    // Fallback: select and copy.
    const input = $("token");
    input.focus();
    input.select();
    document.execCommand("copy");
  }
}

function wireUi() {
  const wrap = (fn) => async (...args) => {
    try {
      clearError();
      await fn(...args);
    } catch (e) {
      console.error(e);
      setError("Something went wrong", toMessage(e));
    }
  };

  $("btn-error-dismiss")?.addEventListener("click", () => clearError());

  $("btn-suggest").addEventListener("click", wrap(suggestPorts));
  $("btn-browse").addEventListener("click", wrap(browseHome));
  $("btn-save").addEventListener("click", wrap(saveWizard));

  $("btn-start").addEventListener("click", wrap(start));
  $("btn-stop").addEventListener("click", wrap(stop));
  $("btn-restart").addEventListener("click", wrap(restart));
  $("btn-open-ui").addEventListener("click", wrap(openUi));
  $("btn-copy").addEventListener("click", wrap(copyToken));

  $("btn-exit-stop").addEventListener(
    "click",
    wrap(async () => {
      await stop();
      showExitModal(false);
      await invoke("request_exit");
    })
  );
  $("btn-exit-leave").addEventListener(
    "click",
    wrap(async () => {
      showExitModal(false);
      await invoke("request_exit");
    })
  );
  $("btn-exit-cancel").addEventListener("click", () => showExitModal(false));
}

async function wireTrayEvents() {
  await listen("tray-open-ui", async () => {
    try { await openUi(); } catch (_) {}
  });
  await listen("tray-show", async (e) => {
    const which = e.payload;
    if (which === "logs") show("logs");
    else show("status");
    await refresh();
    try {
      const win = window.__TAURI__?.window?.getCurrentWindow;
      if (win) await win().show();
    } catch (_) {}
  });
  await listen("tray-stop", async () => {
    try { await stop(); } catch (_) {}
  });
  await listen("tray-restart", async () => {
    try { await restart(); } catch (_) {}
  });
  await listen("tray-exit", async () => {
    showExitModal(true);
    try {
      const win = window.__TAURI__?.window?.getCurrentWindow;
      if (win) await win().show();
    } catch (_) {}
  });
}

async function main() {
  wireUi();
  await wireTrayEvents();
  await suggestPorts();
  await refresh();
  setInterval(refresh, 2000);
}

main().catch((e) => {
  console.error(e);
  setError(
    "FaceForge Desktop couldn't start",
    `${toMessage(e)}\n\nIf you just installed FaceForge and are seeing this, please reinstall using the latest installer.`
  );
});
