const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;
const { open } = window.__TAURI__.opener;

const $ = (id) => document.getElementById(id);

let state = {
    configured: false,
    core_running: false,
    activeView: 'status', // status, settings
    logsOpen: false,
    install_dir: '', // Need to fetch this
    install_token: ''
};

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
    state.activeView = viewId;
    hide('view-status');
    hide('view-settings');
    show(`view-${viewId}`);
    
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
        
        // Update View Content
        if (state.activeView === 'status') renderStatus(s);
        if (state.activeView === 'settings') populateSettings(s); // Only populate if empty?
        
        if (!state.configured && state.activeView !== 'settings') {
            setView('settings');
        }
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
    // $('val-install-dir') -> Not sent by backend yet. Ignore for now or fetch if command added.
    
    $('token').value = s.install_token || '';
}

async function populateSettings(s) {
    // Check if dirty? For now just overwrite
    if (s.faceforge_home) $('setting-home').value = s.faceforge_home;
    if (s.core_port) $('setting-core-port').value = s.core_port;
    if (s.seaweed_s3_port) $('setting-seaweed-port').value = s.seaweed_s3_port;
    $('setting-seaweed-enabled').checked = !!s.seaweed_enabled;
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
window.addEventListener('DOMContentLoaded', () => {
    refreshState();
    
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
        const corePort = parseInt($('setting-core-port').value);
        const seaweedEnabled = $('setting-seaweed-enabled').checked;
        const seaweedPort = parseInt($('setting-seaweed-port').value);
        
        // Show confirmation if running
        if (state.status && state.status.core_running) {
             show('modal-confirm');
             return; // Wait for modal
        }
        
        await doSave(home, corePort, seaweedEnabled, seaweedPort);
    };
    
    $('btn-modal-cancel').onclick = () => hide('modal-confirm');
    $('btn-modal-confirm').onclick = async () => {
        hide('modal-confirm');
        // Save
        const home = $('setting-home').value;
        const corePort = parseInt($('setting-core-port').value);
        const seaweedEnabled = $('setting-seaweed-enabled').checked;
        const seaweedPort = parseInt($('setting-seaweed-port').value);
        
        await doSave(home, corePort, seaweedEnabled, seaweedPort);
        await invoke('restart_services');
    };
    
    async function doSave(home, corePort, seaweedEnabled, seaweedPort) {
        try {
            await invoke('save_wizard_settings', {
                home, corePort, seaweedEnabled, seaweedPort,
                seaweedWeedPath: null // not exposed in UI yet
            });
            await refreshState();
            setView('status');
        } catch(e) {
            alert("Error saving: " + e);
        }
    }
    
    // Controls
    $('btn-start').onclick = () => invoke('start_services').then(refreshState);
    $('btn-stop').onclick = () => invoke('stop_services').then(refreshState);
    $('btn-restart').onclick = () => invoke('restart_services').then(refreshState);
    
    $('btn-exit').onclick = () => invoke('request_exit');
    
    // Copy/Open helpers
    $('btn-copy-token').onclick = () => copyText($('token').value);
    
    // Periodically refresh state
    setInterval(refreshState, 3000);
});

// Tray listeners
listen('tray-open-ui', () => $('menu-webui').click());
listen('tray-show', () => { /* bring window to front handled by rust? here just refresh */ refreshState(); });
listen('tray-exit', () => invoke('request_exit')); // Fallback
