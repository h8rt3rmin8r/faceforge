#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod orchestrator;
mod ports;
mod settings;

use orchestrator::{Orchestrator, ServiceStatus};
use settings::{DesktopBootstrap, WizardSettings};

use serde::Serialize;
use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;
use tauri::Emitter;
use tauri::Manager;

#[derive(Default)]
struct AppState {
    bootstrap: Option<DesktopBootstrap>,
    settings: Option<WizardSettings>,
    install_token: Option<String>,
    orchestrator: Option<Orchestrator>,
    desired_running: bool,
}

#[derive(Serialize)]
struct UiState {
    configured: bool,
    faceforge_home: Option<String>,
    core_port: Option<u16>,
    seaweed_enabled: bool,
    seaweed_s3_port: Option<u16>,
    auto_restart: bool,
    minimize_on_exit: bool,
    install_token: Option<String>,
    status: Option<ServiceStatus>,
    error: Option<String>,
    install_dir: Option<PathBuf>,
}

fn repo_root_from_exe() -> PathBuf {
    // Dev-oriented: executable lives under desktop/src-tauri/target/... so walk up to repo root.
    // In packaged builds this should be replaced with embedded Core.
    let exe = std::env::current_exe().unwrap_or_else(|_| PathBuf::from("."));
    let mut p = exe.parent().unwrap_or_else(|| std::path::Path::new(".")).to_path_buf();
    for _ in 0..8 {
        if p.join("core").join("src").join("faceforge_core").exists() {
            return p;
        }
        if let Some(parent) = p.parent() {
            p = parent.to_path_buf();
        }
    }
    PathBuf::from(".")
}

fn bootstrap_path(app: &tauri::AppHandle) -> PathBuf {
    app.path()
        .app_config_dir()
        .unwrap_or_else(|_| PathBuf::from("."))
        .join("faceforge-desktop.json")
}

fn load_bootstrap(app: &tauri::AppHandle) -> Option<DesktopBootstrap> {
    let path = bootstrap_path(app);
    let raw = fs::read_to_string(path).ok()?;
    serde_json::from_str(&raw).ok()
}

fn save_bootstrap(app: &tauri::AppHandle, b: &DesktopBootstrap) -> anyhow::Result<()> {
    let path = bootstrap_path(app);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(path, serde_json::to_vec_pretty(b)?)?;
    Ok(())
}

fn ensure_bundled_tools(_app: &tauri::AppHandle, _faceforge_home: &std::path::Path) {
    // Legacy: we used to copy tools to FACEFORGE_HOME/tools. 
    // New (v0.2.10): Tools stay in the install dir. 
    // We do nothing here, avoiding duplication.
}

fn ui_state_from_guard(app: &tauri::AppHandle, guard: &mut AppState) -> UiState {
    if guard.bootstrap.is_none() {
        guard.bootstrap = load_bootstrap(app);
    }

    if guard.orchestrator.is_none() {
        let repo_root = repo_root_from_exe();
        guard.orchestrator = Some(Orchestrator::new(repo_root));
    }

    let configured = guard.bootstrap.is_some();
    let mut error: Option<String> = None;

    // Load settings/token lazily.
    if configured && guard.settings.is_none() {
        if let Some(b) = guard.bootstrap.clone() {
            // MVP: Ensure tools are in place before we rely on them.
            ensure_bundled_tools(app, b.faceforge_home.as_path());

            match settings::read_desktop_json(&b.faceforge_home) {
                Ok(s) => {
                    guard.install_token = settings::read_install_token(&b.faceforge_home).ok();
                    guard.settings = Some(s);
                }
                Err(e) => {
                    error = Some(format!("Failed to read desktop settings: {e}"));
                }
            }
        }
    }

    // Build a snapshot of status (best-effort health check).
    let status = if let (Some(s), Some(o)) = (guard.settings.clone(), guard.orchestrator.as_mut()) {
        let ok = o.core_healthy(&s);
        Some(o.status_snapshot(&s, ok))
    } else {
        None
    };

    UiState {
        configured,
        faceforge_home: guard
            .settings
            .as_ref()
            .map(|s| s.faceforge_home.to_string_lossy().to_string())
            .or_else(|| {
                guard.bootstrap
                    .as_ref()
                    .map(|b| b.faceforge_home.to_string_lossy().to_string())
            }),
        core_port: guard.settings.as_ref().map(|s| s.core_port),
        seaweed_enabled: guard.settings.as_ref().map(|s| s.seaweed_enabled).unwrap_or(false),
        seaweed_s3_port: guard.settings.as_ref().and_then(|s| s.seaweed_s3_port),
        auto_restart: guard.settings.as_ref().map(|s| s.auto_restart).unwrap_or(false),
        minimize_on_exit: guard
            .settings
            .as_ref()
            .map(|s| s.minimize_on_exit)
            .unwrap_or(true),
        install_token: guard.install_token.clone(),
        status,
        error,
        install_dir: Some(repo_root_from_exe()),
    }
}

#[tauri::command]
fn suggest_ports() -> serde_json::Value {
    fn pick(start: u16) -> u16 {
        for p in start..(start + 200) {
            if portpicker::is_free(p) {
                return p;
            }
        }
        start
    }

    serde_json::json!({
        "core_port": pick(43210),
        "seaweed_s3_port": pick(43211)
    })
}

#[tauri::command]
async fn pick_faceforge_home(_app: tauri::AppHandle) -> Result<Option<String>, String> {
    // Use rfd for a simple cross-platform folder picker.
    // Run it off the UI thread to avoid blocking.
    let picked = tauri::async_runtime::spawn_blocking(move || rfd::FileDialog::new().pick_folder())
        .await
        .map_err(|e| e.to_string())?;
    Ok(picked.map(|p| p.to_string_lossy().to_string()))
}

#[tauri::command]
fn get_state(app: tauri::AppHandle, state: tauri::State<Mutex<AppState>>) -> UiState {
    let mut guard = state.lock().unwrap();
    ui_state_from_guard(&app, &mut guard)
}

#[tauri::command]
async fn save_wizard_settings(
    app: tauri::AppHandle,
    state: tauri::State<'_, Mutex<AppState>>,
    payload: WizardSettings,
) -> Result<UiState, String> {
    let mut guard = state.lock().unwrap();

    // Ensure FACEFORGE_HOME layout exists; Core will also do this.
    fs::create_dir_all(payload.faceforge_home.join("config")).map_err(|e| e.to_string())?;
    fs::create_dir_all(payload.faceforge_home.join("tmp")).map_err(|e| e.to_string())?;

    let token = settings::write_core_json(&payload.faceforge_home, &payload)
        .map_err(|e| e.to_string())?;
    settings::write_desktop_json(&payload.faceforge_home, &payload).map_err(|e| e.to_string())?;

    let bootstrap = DesktopBootstrap {
        faceforge_home: payload.faceforge_home.clone(),
    };
    save_bootstrap(&app, &bootstrap).map_err(|e| e.to_string())?;

    guard.bootstrap = Some(bootstrap);
    guard.install_token = Some(token);
    guard.settings = Some(payload);

    Ok(ui_state_from_guard(&app, &mut guard))
}

#[tauri::command]
async fn start_services(
    app: tauri::AppHandle,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<UiState, String> {
    let mut guard = state.lock().unwrap();
    let settings = guard
        .settings
        .clone()
        .ok_or_else(|| "Not configured".to_string())?;
    let orch = guard.orchestrator.as_mut().ok_or_else(|| "Orchestrator missing".to_string())?;

    orch.start_seaweed_if_enabled(&settings).map_err(|e| e.to_string())?;
    orch.start_core(&settings).map_err(|e| e.to_string())?;
    guard.desired_running = true;

    Ok(ui_state_from_guard(&app, &mut guard))
}

#[tauri::command]
async fn stop_services(
    app: tauri::AppHandle,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<UiState, String> {
    let mut guard = state.lock().unwrap();
    if let Some(orch) = guard.orchestrator.as_mut() {
        orch.stop_core();
        orch.stop_seaweed();
    }
    guard.desired_running = false;
    Ok(ui_state_from_guard(&app, &mut guard))
}

#[tauri::command]
async fn restart_services(
    app: tauri::AppHandle,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<UiState, String> {
    stop_services(app.clone(), state.clone()).await?;
    start_services(app, state).await
}

#[tauri::command]
async fn open_ui(state: tauri::State<'_, Mutex<AppState>>) -> Result<(), String> {
    let guard = state.lock().unwrap();
    let settings = guard
        .settings
        .as_ref()
        .ok_or_else(|| "Not configured".to_string())?;
    let url = format!("http://127.0.0.1:{}/ui/login", settings.core_port);
    tauri_plugin_opener::open_url(url, None::<String>).map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
async fn request_exit(app: tauri::AppHandle) {
    app.exit(0);
}

#[tauri::command]
async fn request_ui_exit(
    app: tauri::AppHandle,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<(), String> {
    let minimize = {
        let guard = state.lock().unwrap();
        guard
            .settings
            .as_ref()
            .map(|s| s.minimize_on_exit)
            .unwrap_or(true)
    };

    if minimize {
        if let Some(w) = app.get_webview_window("main") {
            let _ = w.hide();
        }
        return Ok(());
    }

    {
        let mut guard = state.lock().unwrap();
        if let Some(orch) = guard.orchestrator.as_mut() {
            orch.stop_core();
            orch.stop_seaweed();
        }
    }
    app.exit(0);
    Ok(())
}

#[tauri::command]
fn read_core_log(app: tauri::AppHandle, lines: usize) -> Result<Vec<String>, String> {
    let state = app.state::<Mutex<AppState>>();
    let guard = state.lock().unwrap();
    if let Some(s) = &guard.settings {
        let log_path = s.faceforge_home.join("logs").join("core.log");
        if !log_path.exists() {
             return Ok(vec![format!("Log file not found at {:?}", log_path)]);
        }
        
        // Simple tail implementation
        // For large logs, this is inefficient (reading whole file), but sufficient for MVP rolling logs (10MB).
        match std::fs::read_to_string(&log_path) {
            Ok(content) => {
                let all_lines: Vec<&str> = content.lines().collect();
                let start = all_lines.len().saturating_sub(lines);
                Ok(all_lines[start..].iter().map(|s| s.to_string()).collect())
            }
            Err(e) => Ok(vec![format!("Error reading log: {}", e)])
        }
    } else {
        Ok(vec!["Settings not loaded - cannot resolve log path.".into()])
    }
}

fn build_tray(app: &tauri::AppHandle) -> anyhow::Result<()> {
    use tauri::menu::{Menu, MenuItem};
    use tauri::tray::TrayIconBuilder;

    // Load the icon for the tray
    // Note: in a bundle "resources" works differently, but for tray icon standard path resolution
    // via `app.default_window_icon()` usually works if window icon is set.
    // Or we can load explicitly if we want a dedicated tray icon.
    // Let's try to get the app icon first.
    let icon = app.default_window_icon().cloned().or_else(|| {
        // Fallback: try loading from resources or built-in
        // Ideally the bundle icon is used.
        None
    });
    
    // For now, let's assume default_window_icon is available if configured in tauri.conf.json.
    // If not, we might need to load from bytes.

    let open_ui = MenuItem::with_id(app, "open_ui", "Web UI", true, None::<&str>)?;
    let status = MenuItem::with_id(app, "show_status", "Open Desktop App", true, None::<&str>)?;
    let exit = MenuItem::with_id(app, "exit", "Exit", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open_ui, &status, &exit])?;

    let builder = TrayIconBuilder::new()
        .menu(&menu)
        .on_menu_event(move |app, event| {
            let id = event.id().as_ref();
            match id {
                "open_ui" => {
                    let _ = app.emit("tray-open-ui", ());
                }
                "show_status" => {
                    let _ = app.emit("tray-show", "status");
                }
                "exit" => {
                    {
                        let state = app.state::<Mutex<AppState>>();
                        if let Ok(mut guard) = state.lock() {
                            if let Some(orch) = guard.orchestrator.as_mut() {
                                orch.stop_core();
                                orch.stop_seaweed();
                            }
                        };
                    }
                    app.exit(0);
                }
                _ => {}
            }
        });
    
    // Set icon if available
    if let Some(i) = icon {
        builder.icon(i).build(app)?;
    } else {
        // Fallback or just build (warning: unchecked)
        builder.build(app)?; 
    }

    Ok(())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(Mutex::new(AppState::default()))
        .setup(|app| {
            let app_handle = app.handle();
            build_tray(&app_handle)?;

            // Background monitor: keep Core alive and restart if needed.
            let app_handle = app_handle.clone();
            std::thread::spawn(move || loop {
                {
                    let state = app_handle.state::<Mutex<AppState>>();
                    let mut guard = state.lock().unwrap();
                    let desired_running = guard.desired_running;
                    if let (Some(settings), Some(orch)) =
                        (guard.settings.clone(), guard.orchestrator.as_mut())
                    {
                        // Only auto-restart when the user wants services running.
                        // Default behavior: do not start Core automatically after configuring.
                        if desired_running && settings.auto_restart {
                            orch.tick_health_and_maybe_restart(&settings);
                        }
                    }
                }
                std::thread::sleep(std::time::Duration::from_secs(2));
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let minimize = {
                    let state = window.app_handle().state::<Mutex<AppState>>();
                    let guard = state.lock().unwrap();
                    guard
                        .settings
                        .as_ref()
                        .map(|s| s.minimize_on_exit)
                        .unwrap_or(true)
                };

                if minimize {
                    api.prevent_close();
                    let _ = window.hide();
                } else {
                    api.prevent_close();
                    let state = window.app_handle().state::<Mutex<AppState>>();
                    if let Ok(mut guard) = state.lock() {
                        if let Some(orch) = guard.orchestrator.as_mut() {
                            orch.stop_core();
                            orch.stop_seaweed();
                        }
                    }
                    window.app_handle().exit(0);
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            suggest_ports,
            pick_faceforge_home,
            get_state,
            save_wizard_settings,
            start_services,
            stop_services,
            restart_services,
            open_ui,
            request_exit,
            request_ui_exit,
            read_core_log,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
