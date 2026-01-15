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
    install_token: '',
    settingsDirty: false,
    settingsDraft: null,
    errorKind: null, // null | 'backend' | 'action'
    errorTitle: null,
    errorSummary: null,
    errorDetail: null,
    errorExpanded: false
};

const DEFAULT_CORE_PORT = 43210;
const DEFAULT_SEAWEED_S3_PORT = 43211;

const SETTINGS_DRAFT_KEY = 'faceforge_desktop_settings_draft_v1';

function loadSettingsDraft() {
    try {
        const raw = localStorage.getItem(SETTINGS_DRAFT_KEY);
        if (!raw) return null;
        const v = JSON.parse(raw);
        return (v && typeof v === 'object') ? v : null;
    } catch {
        return null;
    }
}

function saveSettingsDraft(draft) {
    try {
        localStorage.setItem(SETTINGS_DRAFT_KEY, JSON.stringify(draft || {}));
    } catch {
        // ignore
    }
}

function clearSettingsDraft() {
    try {
        localStorage.removeItem(SETTINGS_DRAFT_KEY);
    } catch {
        // ignore
    }
}

function normalizeErrorText(value) {
    if (value == null) return '';
    if (typeof value === 'string') return value;
    try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

function setErrorExpanded(expanded) {
    state.errorExpanded = !!expanded;
    const detailEl = $('error-detail');
    const btn = $('btn-error-toggle');
    if (detailEl) detailEl.classList.toggle('hidden', !state.errorExpanded);
    if (btn) btn.textContent = state.errorExpanded ? 'Hide' : 'Details';
}

function showError(title, detail, opts) {
    const kind = (opts && opts.kind) ? opts.kind : 'action';
    const force = !!(opts && opts.force);

    // Do not let background health/polling errors override a user-visible action error.
    if (!force && state.errorKind === 'action' && kind === 'backend') {
        return;
    }

    const banner = $('error-banner');
    if (!banner) return;

    const detailText = normalizeErrorText(detail);
    const summaryText = (opts && opts.summary != null) ? normalizeErrorText(opts.summary) : detailText;

    state.errorTitle = title || 'Error';
    state.errorSummary = summaryText;
    state.errorDetail = detailText;

    $('error-title').textContent = state.errorTitle;
    $('error-summary').textContent = state.errorSummary;
    const detailEl = $('error-detail');
    if (detailEl) detailEl.textContent = state.errorDetail;

    state.errorKind = kind;
    banner.classList.remove('banner-hidden');
    banner.setAttribute('aria-hidden', 'false');

    // Default: collapsed details (more readable).
    if (opts && typeof opts.expanded === 'boolean') {
        setErrorExpanded(opts.expanded);
    } else {
        setErrorExpanded(false);
    }
}

function hideError() {
    const banner = $('error-banner');
    if (!banner) return;
    state.errorKind = null;
    state.errorTitle = null;
    state.errorSummary = null;
    state.errorDetail = null;
    state.errorExpanded = false;
    banner.classList.add('banner-hidden');
    banner.setAttribute('aria-hidden', 'true');
}

let toastTimer = null;
function showToast(message) {
    const el = $('toast');
    if (!el) return;
    el.textContent = message || '';
    el.classList.remove('toast-hidden');
    el.setAttribute('aria-hidden', 'false');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
        el.classList.add('toast-hidden');
        el.setAttribute('aria-hidden', 'true');
    }, 1200);
}

async function copyErrorToClipboard() {
    const text = [state.errorTitle, state.errorSummary, state.errorDetail]
        .filter(Boolean)
        .join('\n\n');
    if (!text) return;
    try {
        await navigator.clipboard.writeText(text);
        showToast('Copied');
    } catch (e) {
        console.error(e);
        showToast('Copy failed');
    }
}

function looksLikeSeaweedFailure(title, detail) {
    const t = (title || '').toLowerCase();
    const d = (detail || '').toLowerCase();
    return t.includes('seaweed') || d.includes('seaweedfs') || d.includes('weed=');
}

async function showActionError(title, err) {
    const detail = normalizeErrorText(err);
    if (looksLikeSeaweedFailure(title, detail)) {
        // Attach tail of seaweed.log to make diagnosis immediate.
        let tail = [];
        try {
            tail = await invoke('read_seaweed_log', { lines: 60 });
        } catch (e) {
            tail = [`(Could not read seaweed.log: ${normalizeErrorText(e)})`];
        }
        const enriched = `${detail}\n\n--- seaweed.log (tail) ---\n${tail.join('\n')}`;
        showError(title, enriched, { kind: 'action', expanded: true, summary: detail });
        return;
    }

    showError(title, detail, { kind: 'action', expanded: false });
}

let loadingCount = 0;
let loadingShowTimer = null;
let loadingShownAt = null;
let loadingMinShowMs = 300;
let loadingDelayMs = 200;
let loadingPendingSubtitle = 'Working…';
let loadingPendingDetail = 'Please wait';

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
        loadingShownAt = performance.now();
        return;
    }

    overlay.classList.add('loading-hidden');
    overlay.setAttribute('aria-busy', 'false');
    setTimeout(() => {
        overlay.classList.add('hidden');
        overlay.classList.remove('loading-hidden');
    }, 180);
}

function beginLoading(subtitle, detail, opts) {
    loadingCount += 1;

    if (subtitle) loadingPendingSubtitle = subtitle;
    if (detail) loadingPendingDetail = detail;

    // Defer showing the overlay to avoid flash for fast operations.
    // If already visible, just update text.
    const overlay = $('loading-overlay');
    const isVisible = overlay && !overlay.classList.contains('hidden') && !overlay.classList.contains('loading-hidden');
    if (isVisible) {
        setLoading(true, loadingPendingSubtitle, loadingPendingDetail);
        return;
    }

    // For restart/apply operations, show immediately (no "nothing happened" feeling).
    if (opts && opts.immediate) {
        if (loadingShowTimer != null) {
            clearTimeout(loadingShowTimer);
            loadingShowTimer = null;
        }
        setLoading(true, loadingPendingSubtitle, loadingPendingDetail);
        return;
    }

    if (loadingShowTimer == null) {
        loadingShowTimer = window.setTimeout(() => {
            loadingShowTimer = null;
            if (loadingCount > 0) setLoading(true, loadingPendingSubtitle, loadingPendingDetail);
        }, loadingDelayMs);
    }
}

function endLoading() {
    loadingCount = Math.max(0, loadingCount - 1);

    if (loadingCount !== 0) return;

    if (loadingShowTimer != null) {
        clearTimeout(loadingShowTimer);
        loadingShowTimer = null;
        return;
    }

    const elapsed = (loadingShownAt == null) ? Infinity : (performance.now() - loadingShownAt);
    const remaining = Math.max(0, loadingMinShowMs - elapsed);
    if (remaining > 0) {
        setTimeout(() => setLoading(false), remaining);
    } else {
        setLoading(false);
    }
}

async function withLoading(promiseFactory, subtitle, detail, opts) {
    beginLoading(subtitle, detail, opts);
    try {
        return await promiseFactory();
    } finally {
        endLoading();
    }
}

function currentSettingsFormSnapshot() {
    const home = $('setting-home')?.value || '';
    const corePortRaw = $('setting-core-port')?.value;
    const corePort = parseInt(corePortRaw, 10);
    const seaweedEnabled = !!$('setting-seaweed-enabled')?.checked;
    const seaweedPortRaw = $('setting-seaweed-port')?.value;
    const seaweedPort = parseInt(seaweedPortRaw, 10);
    const autoRestart = !!$('setting-auto-restart')?.checked;
    const minimizeOnExit = !!$('setting-minimize-on-exit')?.checked;
    const logSizeRaw = $('setting-log-size')?.value;
    const maxLogSizeMb = parseInt(logSizeRaw, 10);
    const s3Provider = $('setting-s3-provider')?.value || 'seaweedfs';

    return {
        faceforge_home: home,
        core_port: Number.isFinite(corePort) ? corePort : null,
        seaweed_enabled: seaweedEnabled,
        seaweed_s3_port: Number.isFinite(seaweedPort) ? seaweedPort : null,
        auto_restart: autoRestart,
        minimize_on_exit: minimizeOnExit,
        max_log_size_mb: Number.isFinite(maxLogSizeMb) ? maxLogSizeMb : null,
        s3_provider: s3Provider,
    };
}

function applyDraftToSettingsForm(draft) {
    if (!draft || typeof draft !== 'object') return;
    if (typeof draft.faceforge_home === 'string') $('setting-home').value = draft.faceforge_home;
    if (draft.core_port != null) $('setting-core-port').value = draft.core_port;
    if (typeof draft.seaweed_enabled === 'boolean') $('setting-seaweed-enabled').checked = draft.seaweed_enabled;
    if (draft.seaweed_s3_port != null) $('setting-seaweed-port').value = draft.seaweed_s3_port;
    if (typeof draft.auto_restart === 'boolean') $('setting-auto-restart').checked = draft.auto_restart;
    if (typeof draft.minimize_on_exit === 'boolean') $('setting-minimize-on-exit').checked = draft.minimize_on_exit;
    if (draft.max_log_size_mb != null) $('setting-log-size').value = draft.max_log_size_mb;
    if (typeof draft.s3_provider === 'string') $('setting-s3-provider').value = draft.s3_provider;
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
        showToast('Copied');
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

async function openLocalPath(path) {
    if (!path || path === '-') return;
    try {
        await invoke('open_local_path', { path });
        showToast('Opened');
    } catch (e) {
        console.error(e);
        showToast('Open failed');
        await showActionError('Open Failed', e);
    }
}

// Commands
async function refreshState() {
    try {
        const s = await invoke("get_state");
        if (s && s.error) {
            showError('Desktop Backend Error', s.error, { kind: 'backend' });
        } else {
            // Only auto-clear backend errors; action errors stay until dismissed.
            if (state.errorKind === 'backend') hideError();
        }

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
        showError('Connection Lost', 'Could not talk to desktop backend.', { kind: 'backend', force: true });
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

    function pathJoin(home, rel) {
        if (!home) return rel;
        const usesBackslash = home.includes('\\');
        const sep = usesBackslash ? '\\' : '/';
        const trimmedHome = home.endsWith('\\') || home.endsWith('/') ? home.slice(0, -1) : home;
        const trimmedRel = rel.startsWith('\\') || rel.startsWith('/') ? rel.slice(1) : rel;
        return `${trimmedHome}${sep}${trimmedRel}`;
    }

    // Status log buttons call window.openLogsSource.
    
    const seaweedEnabled = !!(s.status && s.status.seaweed_enabled);
    const seaweedRunning = !!(s.status && s.status.seaweed_running);
    const seaweedLastError = (s.status && s.status.seaweed_last_error) ? String(s.status.seaweed_last_error) : '';
    const seaweedState = seaweedEnabled
        ? (seaweedRunning ? 'Running' : (seaweedLastError ? `Stopped — ${seaweedLastError}` : 'Stopped'))
        : 'Disabled';

    const seaweedLogPath = pathJoin(s.faceforge_home || '', 'logs/seaweed.log');

    const rows = [
        {
            k: 'Core Service',
            v: running ? 'Running' : 'Stopped',
            actions: ''
        },
        {
            k: 'Core Health',
            v: s.status && s.status.core_healthy ? 'Healthy' : 'Unknown',
            actions: ''
        },
        {
                        k: 'S3 Storage',
            v: seaweedState,
            actions: seaweedEnabled
                ? `
                                        <button class="icon-btn" onclick="openLocalPath('${seaweedLogPath.replace(/\\/g, '\\\\')}')">Open log</button>
                  `
                : ''
        }
    ];

    const html = rows
        .map((r) => `
        <div class="kv-key">${r.k}</div>
        <div class="kv-val">${r.v}</div>
        <div class="kv-actions">${r.actions || ''}</div>
    `)
        .join('');
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
    // Prevent background refresh from clobbering in-progress edits.
    if (state.settingsDirty) return;

    // Start from persisted state.
    if (s.faceforge_home) $('setting-home').value = s.faceforge_home;
    $('setting-core-port').value = s.core_port || DEFAULT_CORE_PORT;
    $('setting-seaweed-port').value = s.seaweed_s3_port || DEFAULT_SEAWEED_S3_PORT;
    $('setting-seaweed-enabled').checked = !!s.seaweed_enabled;
    $('setting-auto-restart').checked = !!s.auto_restart;
    $('setting-minimize-on-exit').checked = (s.minimize_on_exit !== false);
    if (s.max_log_size_mb) $('setting-log-size').value = s.max_log_size_mb;

    // If a draft exists (from navigation), prefer showing it.
    const draft = state.settingsDraft || loadSettingsDraft();
    if (draft) {
        applyDraftToSettingsForm(draft);
        state.settingsDraft = draft;
    }
}

// Log Polling
let logInterval;
async function fetchLogs() {
    if (!state.logsOpen) return;
    try {
        const source = $('logs-source') ? $('logs-source').value : 'core';
        const cmd = (source === 'seaweed') ? 'read_seaweed_log' : 'read_core_log';
        const lines = await invoke(cmd, { lines: 50 });
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
    state.settingsDraft = loadSettingsDraft();

    beginLoading('Starting…', 'Initializing desktop UI');
    try {
        await refreshState();
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

    $('btn-refresh-logs').onclick = fetchLogs;
    if ($('logs-source')) {
        $('logs-source').onchange = fetchLogs;
    }
    
    $('btn-close-logs').onclick = $('menu-logs').onclick;
    
    $('menu-webui').onclick = async () => {
        if (!state.configured) return;
        try {
            await invoke('open_ui'); 
        } catch(e) { alert(e); }
    };
    
    // Error banner
    $('btn-error-dismiss').onclick = hideError;
    if ($('btn-error-toggle')) $('btn-error-toggle').onclick = () => setErrorExpanded(!state.errorExpanded);
    if ($('btn-error-copy')) $('btn-error-copy').onclick = copyErrorToClipboard;

    // Exposed for inline Status buttons.
    window.openLogsSource = (source) => {
        if (!state.logsOpen) {
            state.logsOpen = true;
            const drawer = $('logs-drawer');
            if (drawer) drawer.classList.remove('collapsed');
            if (!logInterval) logInterval = setInterval(fetchLogs, 2000);
        }
        if ($('logs-source')) $('logs-source').value = source || 'core';
        fetchLogs();
    };

    // Settings draft persistence (keeps values when navigating away/back)
    const onSettingsChanged = () => {
        state.settingsDirty = true;
        const draft = currentSettingsFormSnapshot();
        state.settingsDraft = draft;
        saveSettingsDraft(draft);
    };
    [
        'setting-home',
        'setting-core-port',
        'setting-seaweed-enabled',
        'setting-seaweed-port',
        'setting-auto-restart',
        'setting-minimize-on-exit',
        'setting-log-size',
        'setting-s3-provider',
    ].forEach(id => {
        const el = $(id);
        if (!el) return;
        el.addEventListener('input', onSettingsChanged);
        el.addEventListener('change', onSettingsChanged);
    });

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
        let maxLogSizeMb = parseInt($('setting-log-size').value);
        if (!Number.isFinite(maxLogSizeMb) || maxLogSizeMb <= 0) maxLogSizeMb = 10;
        
        // Show confirmation if running
        if (state.status && state.status.core_running) {
             show('modal-confirm');
             return; // Wait for modal
        }
        
        await withLoading(
            () => doSave(home, corePort, seaweedEnabled, seaweedPort, autoRestart, minimizeOnExit, maxLogSizeMb),
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
        let maxLogSizeMb = parseInt($('setting-log-size').value);
        if (!Number.isFinite(maxLogSizeMb) || maxLogSizeMb <= 0) maxLogSizeMb = 10;
        
        try {
            await withLoading(
                async () => {
                    await doSave(
                        home,
                        corePort,
                        seaweedEnabled,
                        seaweedPort,
                        autoRestart,
                        minimizeOnExit,
                        maxLogSizeMb,
                        { suppressViewChange: true }
                    );
                    await invoke('restart_services');
                },
                'Applying settings…',
                'Restarting local services',
                { immediate: true }
            );
            await refreshState();
            const running = state.status && state.status.core_running;
            setView(running ? 'status' : 'settings');
        } catch (e) {
            await showActionError('Restart Failed', e);
        }
    };
    
    async function doSave(home, corePort, seaweedEnabled, seaweedPort, autoRestart, minimizeOnExit, maxLogSizeMb, opts) {
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
                    minimize_on_exit: minimizeOnExit,
                    max_log_size_mb: maxLogSizeMb
                }
            });
            state.settingsDirty = false;
            state.settingsDraft = null;
            clearSettingsDraft();

            const suppressViewChange = !!(opts && opts.suppressViewChange);
            if (!suppressViewChange) {
                await refreshState();
                const running = state.status && state.status.core_running;
                setView(running ? 'status' : 'settings');
            }
        } catch(e) {
            showError('Save Failed', String(e));
            throw e;
        }
    }
    
    // Controls
    $('btn-start').onclick = async () => {
        try {
            await withLoading(async () => {
                await invoke('start_services');
            }, 'Starting…', 'Launching local services', { immediate: true });
            await refreshState();
        } catch (e) {
            await showActionError('Start Failed', e);
        }
    };
    $('btn-stop').onclick = async () => {
        try {
            await withLoading(async () => {
                await invoke('stop_services');
            }, 'Stopping…', 'Shutting down services', { immediate: true });
            await refreshState();
        } catch (e) {
            await showActionError('Stop Failed', e);
        }
    };
    $('btn-restart').onclick = async () => {
        try {
            await withLoading(async () => {
                await invoke('restart_services');
            }, 'Restarting…', 'Re-launching services', { immediate: true });
            await refreshState();
        } catch (e) {
            await showActionError('Restart Failed', e);
        }
    };

    $('btn-exit').onclick = async () => {
        try {
            await withLoading(async () => {
                await invoke('request_ui_exit');
            }, 'Exiting…', 'Finalizing shutdown');
        } catch (e) {
            await showActionError('Exit Failed', e);
        }
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
