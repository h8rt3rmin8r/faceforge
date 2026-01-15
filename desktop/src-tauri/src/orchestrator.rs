use crate::ports::{write_ports, RuntimePorts};
use crate::settings::WizardSettings;
use anyhow::Context;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::net::{SocketAddr, TcpStream};
use std::time::{Duration, Instant};

#[derive(Debug, Clone, serde::Serialize)]
pub struct ServiceStatus {
    pub core_running: bool,
    pub core_healthy: bool,
    pub core_url: String,
    pub seaweed_enabled: bool,
    pub seaweed_running: bool,
    pub seaweed_s3_port: Option<u16>,
    pub seaweed_last_error: Option<String>,
}

pub struct Orchestrator {
    repo_root: PathBuf,
    core_child: Option<Child>,
    seaweed_child: Option<Child>,
    last_seaweed_error: Option<String>,
    last_core_start: Option<Instant>,
    core_restart_attempts: u32,
}

impl Orchestrator {
    pub fn new(repo_root: PathBuf) -> Self {
        Self {
            repo_root,
            core_child: None,
            seaweed_child: None,
            last_seaweed_error: None,
            last_core_start: None,
            core_restart_attempts: 0,
        }
    }

    pub fn is_core_running(&mut self) -> bool {
        if let Some(child) = &mut self.core_child {
            match child.try_wait() {
                Ok(Some(_)) => {
                    self.core_child = None;
                    false
                }
                Ok(None) => true,
                Err(_) => false,
            }
        } else {
            false
        }
    }

    pub fn is_seaweed_running(&mut self) -> bool {
        if let Some(child) = &mut self.seaweed_child {
            match child.try_wait() {
                Ok(Some(_)) => {
                    self.seaweed_child = None;
                    false
                }
                Ok(None) => true,
                Err(_) => false,
            }
        } else {
            false
        }
    }

    fn find_venv_python(&self) -> Option<PathBuf> {
        let candidates = [
            self.repo_root.join(".venv").join("Scripts").join("python.exe"),
            self.repo_root.join(".venv").join("bin").join("python"),
        ];
        for c in candidates {
            if c.exists() {
                return Some(c);
            }
        }
        None
    }

    fn resolve_core_sidecar(&self) -> anyhow::Result<PathBuf> {
        // In dev builds we keep a copy at desktop/src-tauri/binaries.
        // In packaged builds Tauri may rename sidecars with a target triple.
        // We therefore try a small search strategy rather than assuming an exact filename.

        let mut candidates: Vec<PathBuf> = vec![
            self.repo_root
                .join("desktop")
                .join("src-tauri")
                .join("binaries")
                .join("faceforge-core.exe"),
            self.repo_root
                .join("desktop")
                .join("src-tauri")
                .join("binaries")
                .join("faceforge-core"),
        ];

        let exe = std::env::current_exe()?;
        if let Some(dir) = exe.parent() {
            candidates.push(dir.join("faceforge-core.exe"));
            candidates.push(dir.join("faceforge-core"));
            candidates.push(dir.join("binaries").join("faceforge-core.exe"));
            candidates.push(dir.join("binaries").join("faceforge-core"));

            // Tauri sidecars may be named like `faceforge-core-x86_64-pc-windows-msvc.exe`.
            if let Ok(entries) = std::fs::read_dir(dir) {
                for entry in entries.flatten() {
                    let p = entry.path();
                    if !p.is_file() {
                        continue;
                    }
                    let Some(name) = p.file_name().and_then(|s| s.to_str()) else {
                        continue;
                    };
                    if !name.starts_with("faceforge-core") {
                        continue;
                    }
                    #[cfg(windows)]
                    {
                        if !name.ends_with(".exe") {
                            continue;
                        }
                    }
                    candidates.push(p);
                }
            }
        }

        for c in candidates {
            if c.exists() {
                return Ok(c);
            }
        }

        anyhow::bail!(
            "Core executable sidecar not found (and .venv missing). Looked in repo binaries and beside the desktop executable."
        )
    }

    fn weed_candidates(&self, settings: &WizardSettings) -> Vec<PathBuf> {
        let mut out: Vec<PathBuf> = Vec::new();

        if let Some(p) = &settings.seaweed_weed_path {
            if p.exists() {
                out.push(p.clone());
            }
        }

        // Check install directory (bundled tools)
        // In dev, repo_root is the root. In prod, repo_root might be where the executable is.
        // We expect `tools/weed.exe` adjacent to or inside the install info.
        
        // 1. "tools" dir relative to repo_root (dev style or portable)
        let tools_dirs = [
            self.repo_root.join("tools"),
            // In dev environment structure:
            self.repo_root.join("desktop").join("src-tauri").join("resources").join("tools"),
            // In prod structure (often adjacent to executable):
            self.repo_root.join("..").join("resources").join("tools"),
        ];

        for t_dir in tools_dirs {
            let user_home_dupe = settings.faceforge_home.join("tools"); // Fallback if user actually put it there
            
            let candidates = [
                t_dir.join("weed.exe"),
                t_dir.join("weed"),
                user_home_dupe.join("weed.exe"), // Allow user override if they manually put it there
            ];

            for c in candidates {
                out.push(c);
            }
        }

        out
    }

    fn resolve_weed_path(&self, settings: &WizardSettings) -> Option<PathBuf> {
        // First honor explicit setting.
        if let Some(p) = &settings.seaweed_weed_path {
            if p.exists() {
                return Some(p.clone());
            }
        }

        for c in self.weed_candidates(settings) {
            if c.exists() {
                return Some(c);
            }
        }

        None
    }

    fn prepare_log_file(log_path: &std::path::Path, max_log_size_mb: u32) -> anyhow::Result<std::fs::File> {
        let max_bytes: u64 = (max_log_size_mb.max(1) as u64) * 1024 * 1024;
        if let Ok(meta) = std::fs::metadata(log_path) {
            if meta.len() > max_bytes {
                let rotated = log_path.with_extension("log.1");
                let _ = std::fs::remove_file(&rotated);
                let _ = std::fs::rename(log_path, &rotated);
            }
        }
        Ok(OpenOptions::new().create(true).append(true).open(log_path)?)
    }

    pub fn start_seaweed_if_enabled(&mut self, settings: &WizardSettings) -> anyhow::Result<()> {
        if !settings.seaweed_enabled {
            return Ok(());
        }
        if self.is_seaweed_running() {
            return Ok(());
        }

        let result: anyhow::Result<()> = (|| {

        let weed = match self.resolve_weed_path(settings) {
            Some(p) => p,
            None => {
                let candidates = self
                    .weed_candidates(settings)
                    .into_iter()
                    .map(|p| p.to_string_lossy().to_string())
                    .collect::<Vec<_>>();
                anyhow::bail!(
                    "SeaweedFS enabled but 'weed' binary was not found. Looked for: {}. If you're building from source, run scripts/ensure-seaweedfs.ps1 to download the official Windows x64 binary.",
                    candidates.join("; ")
                );
            }
        };

        #[cfg(windows)]
        {
            use std::io::Read;
            // Quick sanity check: avoid trying to spawn a placeholder text file.
            let mut f = std::fs::File::open(&weed).with_context(|| format!("Failed to open weed binary at {:?}", &weed))?;
            let mut buf = [0u8; 128];
            let n = f.read(&mut buf).unwrap_or(0);
            let slice = &buf[..n];
            let is_mz = slice.len() >= 2 && slice[0] == b'M' && slice[1] == b'Z';
            if !is_mz {
                let preview = String::from_utf8_lossy(slice);
                anyhow::bail!(
                    "SeaweedFS weed binary at {:?} is not a valid Windows executable (missing MZ header). \
If you're building from source, run scripts/ensure-seaweedfs.ps1 (it downloads the official Windows x64 weed.exe). \
Preview: {}",
                    &weed,
                    preview.replace('\r', " ").replace('\n', " ")
                );
            }
        }

        let s3_port = settings
            .seaweed_s3_port
            .context("SeaweedFS enabled but seaweed_s3_port not set")?;

        // These are currently hardcoded in the command args below.
        let master_port: u16 = 9333;
        let volume_port: u16 = 8080;
        let filer_port: u16 = 8888;

        let data_dir = settings.faceforge_home.join("s3").join("seaweedfs");
        std::fs::create_dir_all(&data_dir)?;

        // Preflight port checks: if anything is already listening, SeaweedFS may fail or exit immediately.
        let mut conflicts: Vec<String> = Vec::new();
        for (name, port) in [
            ("master", master_port),
            ("volume", volume_port),
            ("filer", filer_port),
            ("s3", s3_port),
        ] {
            if Self::tcp_port_open("127.0.0.1", port, Duration::from_millis(120)) {
                conflicts.push(format!("{name}:{port}"));
            }
        }
        if !conflicts.is_empty() {
            anyhow::bail!(
                "SeaweedFS cannot start because these ports already have listeners: {}",
                conflicts.join(", ")
            );
        }

        let mut cmd = Command::new(&weed);
        cmd.arg("server")
            .arg("-ip=127.0.0.1")
            .arg(format!("-dir={}", data_dir.to_string_lossy()))
            .arg(format!("-master.port={}", master_port))
            .arg(format!("-volume.port={}", volume_port))
            .arg(format!("-filer.port={}", filer_port))
            .arg("-s3")
            .arg(format!("-s3.port={}", s3_port))
            .current_dir(&settings.faceforge_home)
            .stdin(Stdio::null());

        // Log to FACEFORGE_HOME/logs/seaweed.log for debugging.
        let logs_dir = settings.faceforge_home.join("logs");
        std::fs::create_dir_all(&logs_dir)?;
        let log_path = logs_dir.join("seaweed.log");
        let out = Self::prepare_log_file(&log_path, settings.max_log_size_mb)?;
        let err = out.try_clone()?;
        cmd.stdout(Stdio::from(out)).stderr(Stdio::from(err));

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            // CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
            cmd.creation_flags(0x00000200 | 0x08000000);
        }

        fn format_spawn_error(e: &std::io::Error) -> String {
            let raw = e.raw_os_error();
            let mut s = format!("{}", e);
            s.push_str(&format!(" (kind={:?}", e.kind()));
            if let Some(code) = raw {
                s.push_str(&format!(", os_error={}", code));
                #[cfg(windows)]
                {
                    // Common Windows causes:
                    // 2 = file not found, 5 = access denied, 193 = bad exe, 126 = missing DLL/module.
                    if code == 2 {
                        s.push_str(", hint=path not found");
                    } else if code == 5 {
                        s.push_str(", hint=access denied (AV/quarantine/permissions)");
                    } else if code == 193 {
                        s.push_str(", hint=not a valid Windows executable (wrong arch?)");
                    } else if code == 126 {
                        s.push_str(", hint=missing dependency/DLL (VC runtime?)");
                    }
                }
            }
            s.push(')');
            s
        }

        let child = cmd.spawn().map_err(|e| {
            let msg = format!(
                "Failed to start SeaweedFS (weed={:?}, s3_port={}, log={:?}). Spawn error: {}",
                &weed,
                s3_port,
                log_path,
                format_spawn_error(&e)
            );
            anyhow::anyhow!(msg)
        })?;

        self.seaweed_child = Some(child);

        // Brief readiness probe: if the process exits immediately, return an actionable error.
        let start = Instant::now();
        let timeout = Duration::from_secs(2);
        while start.elapsed() < timeout {
            if Self::tcp_port_open("127.0.0.1", s3_port, Duration::from_millis(120)) {
                return Ok(());
            }
            if let Some(child) = &mut self.seaweed_child {
                if let Ok(Some(status)) = child.try_wait() {
                    self.seaweed_child = None;
                    anyhow::bail!(
                        "SeaweedFS exited immediately ({:?}). Check logs at {:?}",
                        status,
                        log_path
                    );
                }
            }
            std::thread::sleep(Duration::from_millis(100));
        }

        Ok(())
        })();

        match result {
            Ok(()) => {
                self.last_seaweed_error = None;
                Ok(())
            }
            Err(e) => {
                // Preserve for Status UI; string is fine for MVP.
                self.last_seaweed_error = Some(e.to_string());
                Err(e)
            }
        }
    }

    pub fn stop_seaweed(&mut self) {
        if let Some(mut c) = self.seaweed_child.take() {
            let _ = c.kill();
            let _ = c.wait();
        }
    }

    pub fn start_core(&mut self, settings: &WizardSettings) -> anyhow::Result<()> {
        if self.is_core_running() {
            return Ok(());
        }

        // Ensure ports.json exists for Core's `python -m faceforge_core`.
        write_ports(
            &settings.faceforge_home,
            &RuntimePorts {
                core: Some(settings.core_port),
                seaweed_s3: settings.seaweed_s3_port,
            },
        )?;

        // Strategy: prefer venv python (dev mode), fallback to bundled executable sidecar.
        let (bin_path, args, work_dir) = if let Some(python) = self.find_venv_python() {
            // Dev mode
            (
                python,
                vec!["-m".to_string(), "faceforge_core".to_string()],
                Some(self.repo_root.clone()),
            )
        } else {
            // Packaged mode: use a sidecar.
            let sidecar = self.resolve_core_sidecar()?;
            (sidecar, vec![], None)
        };

        let mut cmd = Command::new(&bin_path);
        
        if let Some(wd) = work_dir {
            cmd.current_dir(wd)
                // Avoid relying on editable install in dev: point PYTHONPATH at core/src.
                .env("PYTHONPATH", self.repo_root.join("core").join("src"));
        } else {
            // In prod, never inherit an arbitrary CWD (e.g. installer launched from Downloads).
            cmd.current_dir(&settings.faceforge_home);
        }

        cmd.args(args)
            .env("FACEFORGE_HOME", &settings.faceforge_home)
            .env("FACEFORGE_BIND", "127.0.0.1")
            .stdin(Stdio::null());

        // Capture output for diagnosis (Core can fail fast in dev if deps are missing).
        let logs_dir = settings.faceforge_home.join("logs");
        std::fs::create_dir_all(&logs_dir)?;
        let log_path = logs_dir.join("core.log");
        let out = Self::prepare_log_file(&log_path, settings.max_log_size_mb)?;
        let err = out.try_clone()?;
        cmd.stdout(Stdio::from(out)).stderr(Stdio::from(err));

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            // CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
            cmd.creation_flags(0x00000200 | 0x08000000);
        }

        self.core_child = Some(cmd.spawn().context(format!("Failed to start Core: {:?}", bin_path))?);
        self.last_core_start = Some(Instant::now());
        self.core_restart_attempts = 0;
        Ok(())
    }

    pub fn stop_core(&mut self) {
        if let Some(mut c) = self.core_child.take() {
            let _ = c.kill();
            let _ = c.wait();
        }
    }

    fn tcp_port_open(host: &str, port: u16, timeout: Duration) -> bool {
        let addr: SocketAddr = match format!("{}:{}", host, port).parse() {
            Ok(a) => a,
            Err(_) => return false,
        };
        TcpStream::connect_timeout(&addr, timeout).is_ok()
    }

    pub fn core_healthy(&self, settings: &WizardSettings) -> bool {
        // Basic health heuristic for Sprint 12: local port accept.
        Self::tcp_port_open("127.0.0.1", settings.core_port, Duration::from_millis(250))
    }

    pub fn tick_health_and_maybe_restart(&mut self, settings: &WizardSettings) {
        let running = self.is_core_running();
        if !running {
            // If the process exited unexpectedly, attempt a few restarts.
            if self.core_restart_attempts < 3 {
                let backoff_ms = 500u64 * (1u64 << self.core_restart_attempts);
                std::thread::sleep(Duration::from_millis(backoff_ms));
                if self.start_core(settings).is_ok() {
                    self.core_restart_attempts += 1;
                }
            }
            return;
        }

        // If we recently started, allow a short grace period.
        if let Some(t0) = self.last_core_start {
            if t0.elapsed() < Duration::from_secs(2) {
                return;
            }
        }

        let ok = self.core_healthy(settings);
        if ok {
            self.core_restart_attempts = 0;
            return;
        }

        // If unhealthy for too long after start, restart once.
        if let Some(t0) = self.last_core_start {
            if t0.elapsed() > Duration::from_secs(10) {
                self.stop_core();
                let _ = self.start_core(settings);
                self.last_core_start = Some(Instant::now());
                self.core_restart_attempts = 1;
            }
        }
    }

    pub fn status_snapshot(&mut self, settings: &WizardSettings, core_healthy: bool) -> ServiceStatus {
        let core_url = format!("http://127.0.0.1:{}", settings.core_port);
        ServiceStatus {
            core_running: self.is_core_running(),
            core_healthy,
            core_url,
            seaweed_enabled: settings.seaweed_enabled,
            seaweed_running: self.is_seaweed_running(),
            seaweed_s3_port: settings.seaweed_s3_port,
            seaweed_last_error: self.last_seaweed_error.clone(),
        }
    }
}
