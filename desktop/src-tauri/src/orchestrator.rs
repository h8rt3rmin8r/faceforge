use crate::ports::{write_ports, RuntimePorts};
use crate::settings::WizardSettings;
use anyhow::Context;
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
}

pub struct Orchestrator {
    repo_root: PathBuf,
    core_child: Option<Child>,
    seaweed_child: Option<Child>,
    last_core_start: Option<Instant>,
    core_restart_attempts: u32,
}

impl Orchestrator {
    pub fn new(repo_root: PathBuf) -> Self {
        Self {
            repo_root,
            core_child: None,
            seaweed_child: None,
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

    fn resolve_weed_path(&self, settings: &WizardSettings) -> Option<PathBuf> {
        if let Some(p) = &settings.seaweed_weed_path {
            if p.exists() {
                return Some(p.clone());
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
                if c.exists() {
                    return Some(c);
                }
            }
        }
        
        None
    }

    pub fn start_seaweed_if_enabled(&mut self, settings: &WizardSettings) -> anyhow::Result<()> {
        if !settings.seaweed_enabled {
            return Ok(());
        }
        if self.is_seaweed_running() {
            return Ok(());
        }

        let weed = self
            .resolve_weed_path(settings)
            .context("SeaweedFS enabled but 'weed' binary not found under FACEFORGE_HOME/tools")?;

        let s3_port = settings
            .seaweed_s3_port
            .context("SeaweedFS enabled but seaweed_s3_port not set")?;

        let data_dir = settings.faceforge_home.join("s3").join("seaweedfs");
        std::fs::create_dir_all(&data_dir)?;

        let mut cmd = Command::new(weed);
        cmd.arg("server")
            .arg("-ip=127.0.0.1")
            .arg(format!("-dir={}", data_dir.to_string_lossy()))
            .arg("-master.port=9333")
            .arg("-volume.port=8080")
            .arg("-filer.port=8888")
            .arg("-s3")
            .arg(format!("-s3.port={}", s3_port))
            .current_dir(&settings.faceforge_home)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            // CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
            cmd.creation_flags(0x00000200 | 0x08000000);
        }

        self.seaweed_child = Some(cmd.spawn().context("Failed to start SeaweedFS")?);
        Ok(())
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

        // Strategy: prefer venv python (dev mode), fallback to bundled executable sidecar (prod mode).
        let (bin_path, args, work_dir) = if let Some(python) = self.find_venv_python() {
            // Dev mode
            (
                python,
                vec!["-m".to_string(), "faceforge_core".to_string()],
                Some(self.repo_root.clone()),
            )
        } else {
            // Prod mode: expect `faceforge-core.exe` sidecar adjacent to this executable.
            let exe = std::env::current_exe()?;
            let dir = exe.parent().context("Cannot resolve parent of current executable")?;
            let sidecar = dir.join("faceforge-core.exe");
            if !sidecar.exists() {
                anyhow::bail!("Core executable not found at {:?} (and .venv missing)", sidecar);
            }
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
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());

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
        }
    }
}
