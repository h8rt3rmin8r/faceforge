const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;
const { open } = window.__TAURI__.opener;

const $ = (id) => document.getElementById(id);

let state = {
    configured: false,
    core_running: false,
    activeView: 'status', // status, settings
    initialViewChosen: false,
    logsOpen: false,
    install_dir: '', // Need to fetch this
    install_token: ''
};

const DEFAULT_CORE_PORT = 43210;
const DEFAULT_SEAWEED_S3_PORT = 43211;

let loadingCount = 0;
function setLoading(isLoading, subtitle, detail) {
    const overlay = $('loading-overlay');
    if (!overlay) return;
    if (subtitle) $('loading-subtitle').textContent = subtitle;
    if (detail) $('loading-detail').textContent = detail;

    // We want a nice fade rather than an instant display:none.
    if (isLoading) {
        overlay.classList.remove('hidden');
        overlay.classList.remove('loading-hidden');
        overlay.setAttribute('aria-busy', 'true');
        return;
    }

    overlay.classList.add('loading-hidden');
    overlay.setAttribute('aria-busy', 'false');
    setTimeout(() => {
        overlay.classList.add('hidden');
        overlay.classList.remove('loading-hidden');
    }, 180);
}

function beginLoading(subtitle, detail) {
    loadingCount += 1;
    setLoading(true, subtitle, detail);
}

function endLoading() {
    loadingCount = Math.max(0, loadingCount - 1);
    if (loadingCount === 0) setLoading(false);
}

async function withLoading(promiseFactory, subtitle, detail) {
    beginLoading(subtitle, detail);
    try {
        return await promiseFactory();
    } finally {
        endLoading();
    }
}

function resetLoadingSteps() {
    document.querySelectorAll('.loading-step').forEach(el => {
        el.classList.remove('is-active');
        el.classList.remove('is-done');
    });
}

function setLoadingStep(stepId) {
    const order = ['config', 'engine', 'ready'];
    const idx = order.indexOf(stepId);
    if (idx < 0) return;

    order.forEach((id, i) => {
        const el = document.querySelector(`.loading-step[data-step="${id}"]`);
        if (!el) return;
        el.classList.toggle('is-active', i === idx);
        el.classList.toggle('is-done', i < idx);
    });
}

async function loadingReadyBeat() {
    setLoadingStep('ready');
    $('loading-subtitle').textContent = 'Ready';
    $('loading-detail').textContent = 'All systems nominal';
    await new Promise(r => setTimeout(r, 240));
}

// Utils
function show(id) {
    $(id).classList.remove('hidden');
}
function hide(id) {
    $(id).classList.add('hidden');
}
function setView(viewId) {
    if (!state.configured && viewId !== 'settings') {
        // Gating
        return;
    }

    if (state.activeView === viewId) return;

    const prevView = state.activeView;
    state.activeView = viewId;

    const prevEl = prevView ? $(`view-${prevView}`) : null;
    const nextEl = $(`view-${viewId}`);
    if (!nextEl) return;

    // Crossfade: fade out previous (if any), fade in next.
    nextEl.classList.remove('hidden');
    nextEl.classList.add('view-enter');
    requestAnimationFrame(() => {
        nextEl.classList.remove('view-enter');
    });

    if (prevEl && !prevEl.classList.contains('hidden')) {
        prevEl.classList.add('view-exit');
        setTimeout(() => {
            prevEl.classList.add('hidden');
            prevEl.classList.remove('view-exit');
        }, 180);
    } else {
        // Ensure others are hidden
        ['status', 'settings'].forEach(k => {
            if (k !== viewId) {
                const el = $(`view-${k}`);
                if (el) el.classList.add('hidden');
            }
        });
    }
    
    // Breadcrumbs
    $('crumb-text').textContent = `Home > ${viewId.charAt(0).toUpperCase() + viewId.slice(1)}`;
    
    // Menu active state
    ['status', 'settings', 'webui'].forEach(k => {
        const el = $(`menu-${k}`);
        if(el) el.classList.toggle('active', k === viewId);
    });
}

async function copyText(text) {
    if (!text) return;
    try {
        await navigator.clipboard.writeText(text);
        // maybe show toast?
    } catch (e) { console.error(e); }
}

async function openPath(path) {
    if (!path || path === '-') return;
    try {
        // Use opener for URLs, need check if it's URL or Path.
        // For paths, we might need a specific command if opener doesn't handle paths seamlessly on all OS.
        // Assuming open() handles both.
        await open(path);
    } catch (e) { console.error(e); }
}

// Commands
async function refreshState() {
    try {
        const s = await invoke("get_state");
        state.configured = s.configured;
        state.status = s.status;
        state.faceforge_home = s.faceforge_home;
        state.install_token = s.install_token;
        state.core_port = s.core_port;
        state.auto_restart = !!s.auto_restart;
        state.minimize_on_exit = (s.minimize_on_exit !== false);
        state.install_dir = s.install_dir || '';
        
        // Update Gating
        ['menu-status', 'menu-logs', 'menu-webui'].forEach(id => {
            const el = $(id);
            if (!state.configured) {
                el.classList.add('disabled');
                el.title = "Configure settings first";
            } else {
                el.classList.remove('disabled');
                el.title = "";
            }
        });
        
        // Update Controls logic (Start/Stop/Restart)
        updateControls(s.status);
        
        // Choose initial view (prevents blank first-load UI)
        if (!state.initialViewChosen) {
            const running = s.status && s.status.core_running;
            const next = (!s.configured || !running) ? 'settings' : 'status';
            setView(next);
            state.initialViewChosen = true;
        }

        // Enforce gating: if not configured, always show Settings.
        if (!state.configured && state.activeView !== 'settings') {
            setView('settings');
        }

        // Update View Content
        if (state.activeView === 'status') renderStatus(s);
        if (state.activeView === 'settings') populateSettings(s);
    } catch (e) {
        console.error(e);
        // setError("Connection Lost", "Could not talk to desktop backend.");
    }
}

function updateControls(status) {
    const running = status && status.core_running;
    $('btn-start').disabled = running;
    $('btn-stop').disabled = !running;
    $('btn-restart').disabled = !running;
}

function renderStatus(s) {
    // Fill KV table
    const running = s.status && s.status.core_running;
    const coreUrl = s.status ? s.status.core_url : '-';
    
    const rows = [
        ['Core Service', running ? 'Running' : 'Stopped'],
        ['Core Health', s.status && s.status.core_healthy ? 'Healthy' : 'Unknown'],
        ['SeaweedFS', s.status && s.status.seaweed_running ? 'Running' : 'Stopped']
    ];
    
    const html = rows.map(([k, v]) => `
        <div class="kv-key">${k}</div>
        <div class="kv-val">${v}</div>
        <div class="kv-actions"></div>
    `).join('');
    $('status-body').innerHTML = html;
    
    // Links
    const links = [];
    if (running && coreUrl) {
        links.push(['Core API', coreUrl]);
        links.push(['API Docs', `${coreUrl}/docs`]);
        links.push(['Web UI', `${coreUrl}/ui`]); // Assuming /ui redirect
    }
    
    $('links-body').innerHTML = links.map(([label, url]) => `
        <div class="kv-key">${label}</div>
        <div class="kv-val"><a href="#" onclick="openPath('${url}')">${url}</a></div>
        <div class="kv-actions">
            <button class="icon-btn" onclick="copyText('${url}')">Copy</button>
            <button class="icon-btn" onclick="openPath('${url}')">Open</button>
        </div>
    `).join('');

    // Directories
    // We don't have install_dir in UiState yet, assuming we can get it or just leave placeholder.
    // MVP: The new layout in index.html relies on separate fields. 
    $('val-data-dir').innerText = s.faceforge_home || '-';
    $('val-install-dir').innerText = s.install_dir || '-';
    
    $('token').value = s.install_token || '';
}

async function populateSettings(s) {
    // Check if dirty? For now just overwrite
    if (s.faceforge_home) $('setting-home').value = s.faceforge_home;
    if (s.core_port) {
        $('setting-core-port').value = s.core_port;
    } else if (!$('setting-core-port').value) {
        $('setting-core-port').value = DEFAULT_CORE_PORT;
    }
    if (s.seaweed_s3_port) {
        $('setting-seaweed-port').value = s.seaweed_s3_port;
    } else if (!$('setting-seaweed-port').value) {
        $('setting-seaweed-port').value = DEFAULT_SEAWEED_S3_PORT;
    }
    $('setting-seaweed-enabled').checked = !!s.seaweed_enabled;
    $('setting-auto-restart').checked = !!s.auto_restart;
    $('setting-minimize-on-exit').checked = (s.minimize_on_exit !== false);
    // log size not yet persisted in settings struct, might default to 10
}

// Log Polling
let logInterval;
async function fetchLogs() {
    if (!state.logsOpen) return;
    try {
        const lines = await invoke('read_core_log', { lines: 50 });
        const viewer = $('logs-viewer');
        viewer.textContent = lines.join('\n');
        if ($('logs-auto-scroll').checked) {
            viewer.scrollTop = viewer.scrollHeight;
        }
    } catch(e) {
        $('logs-viewer').textContent = "Error reading logs: " + e;
    }
}

// Global Events
window.addEventListener('DOMContentLoaded', async () => {
    beginLoading('Initializing…', 'Loading configuration');
    resetLoadingSteps();
    setLoadingStep('config');
    try {
        await refreshState();
        setLoadingStep('engine');
        $('loading-subtitle').textContent = 'Initializing…';
        $('loading-detail').textContent = 'Checking engine status';
        await new Promise(r => setTimeout(r, 120));
        await loadingReadyBeat();
    } finally {
        endLoading();
    }
    
    // Menu Clicks
    $('menu-status').onclick = () => setView('status');
    $('menu-settings').onclick = () => setView('settings');
    $('menu-logs').onclick = () => {
        state.logsOpen = !state.logsOpen;
        const drawer = $('logs-drawer');
        drawer.classList.toggle('collapsed', !state.logsOpen);
        if (state.logsOpen) {
            fetchLogs();
            if(!logInterval) logInterval = setInterval(fetchLogs, 2000);
        } else {
            if(logInterval) clearInterval(logInterval);
            logInterval = null;
        }
    };
    
    $('btn-close-logs').onclick = $('menu-logs').onclick;
    
    $('menu-webui').onclick = async () => {
        if (!state.configured) return;
        try {
            await invoke('open_ui'); 
        } catch(e) { alert(e); }
    };
    
    // Settings Actions
    $('btn-browse').onclick = async () => {
        const path = await invoke("pick_faceforge_home");
        if (path) $('setting-home').value = path;
    };
    
    $('btn-suggest').onclick = async () => {
        const p = await invoke("suggest_ports");
        $('setting-core-port').value = p.core_port;
        $('setting-seaweed-port').value = p.seaweed_s3_port;
    };
    
    $('btn-save').onclick = async () => {
        // Collect data
        const home = $('setting-home').value;
        let corePort = parseInt($('setting-core-port').value);
        if (!Number.isFinite(corePort) || corePort <= 0) corePort = DEFAULT_CORE_PORT;
        const seaweedEnabled = $('setting-seaweed-enabled').checked;
        let seaweedPort = parseInt($('setting-seaweed-port').value);
        if (!Number.isFinite(seaweedPort) || seaweedPort <= 0) seaweedPort = DEFAULT_SEAWEED_S3_PORT;
        const autoRestart = $('setting-auto-restart').checked;
        const minimizeOnExit = $('setting-minimize-on-exit').checked;
        
        // Show confirmation if running
        if (state.status && state.status.core_running) {
             show('modal-confirm');
             return; // Wait for modal
        }
        
        await withLoading(
            () => doSave(home, corePort, seaweedEnabled, seaweedPort, autoRestart, minimizeOnExit),
            'Saving settings…',
            'Writing configuration files'
        );
    };
    
    $('btn-modal-cancel').onclick = () => hide('modal-confirm');
    $('btn-modal-confirm').onclick = async () => {
        hide('modal-confirm');
        // Save
        const home = $('setting-home').value;
        let corePort = parseInt($('setting-core-port').value);
        if (!Number.isFinite(corePort) || corePort <= 0) corePort = DEFAULT_CORE_PORT;
        const seaweedEnabled = $('setting-seaweed-enabled').checked;
        let seaweedPort = parseInt($('setting-seaweed-port').value);
        if (!Number.isFinite(seaweedPort) || seaweedPort <= 0) seaweedPort = DEFAULT_SEAWEED_S3_PORT;
        const autoRestart = $('setting-auto-restart').checked;
        const minimizeOnExit = $('setting-minimize-on-exit').checked;
        
        await withLoading(
            async () => {
                resetLoadingSteps();
                setLoadingStep('config');
                await doSave(home, corePort, seaweedEnabled, seaweedPort, autoRestart, minimizeOnExit);
                setLoadingStep('engine');
                await invoke('restart_services');
                await loadingReadyBeat();
            },
            'Applying settings…',
            'Restarting local services'
        );
    };
    
    async function doSave(home, corePort, seaweedEnabled, seaweedPort, autoRestart, minimizeOnExit) {
        try {
            const seaweed_s3_port = seaweedEnabled ? seaweedPort : null;
            await invoke('save_wizard_settings', {
                payload: {
                    faceforge_home: home,
                    core_port: corePort,
                    seaweed_enabled: seaweedEnabled,
                    seaweed_s3_port,
                    seaweed_weed_path: null,
                    auto_restart: autoRestart,
                    minimize_on_exit: minimizeOnExit
                }
            });
            await refreshState();
            const running = state.status && state.status.core_running;
            setView(running ? 'status' : 'settings');
        } catch(e) {
            alert("Error saving: " + e);
        }
    }
    
    // Controls
    $('btn-start').onclick = async () => {
        await withLoading(async () => {
            resetLoadingSteps();
            setLoadingStep('engine');
            await invoke('start_services');
            await loadingReadyBeat();
        }, 'Starting…', 'Launching Core service');
        await refreshState();
    };
    $('btn-stop').onclick = async () => {
        await withLoading(async () => {
            resetLoadingSteps();
            setLoadingStep('engine');
            await invoke('stop_services');
            await loadingReadyBeat();
        }, 'Stopping…', 'Shutting down services');
        await refreshState();
    };
    $('btn-restart').onclick = async () => {
        await withLoading(async () => {
            resetLoadingSteps();
            setLoadingStep('engine');
            await invoke('restart_services');
            await loadingReadyBeat();
        }, 'Restarting…', 'Re-launching services');
        await refreshState();
    };

    $('btn-exit').onclick = async () => {
        await withLoading(async () => {
            resetLoadingSteps();
            setLoadingStep('engine');
            await invoke('request_ui_exit');
        }, 'Exiting…', 'Finalizing shutdown');
    };
    
    // Copy/Open helpers
    $('btn-copy-token').onclick = () => copyText($('token').value);
    
    // Periodically refresh state
    setInterval(refreshState, 3000);
});

// Tray listeners
listen('tray-open-ui', () => $('menu-webui').click());
listen('tray-show', (event) => {
    if (event && event.payload === 'status') setView('status');
    refreshState();
});
listen('tray-exit', () => invoke('request_exit')); // Fallback
