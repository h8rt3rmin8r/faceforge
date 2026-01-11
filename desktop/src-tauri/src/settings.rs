use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use rand::RngCore;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DesktopBootstrap {
    pub faceforge_home: PathBuf,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WizardSettings {
    pub faceforge_home: PathBuf,
    pub core_port: u16,
    pub seaweed_enabled: bool,
    pub seaweed_s3_port: Option<u16>,
    pub seaweed_weed_path: Option<PathBuf>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CoreJsonConfig {
    pub version: String,
    pub auth: AuthConfig,
    pub network: NetworkConfig,
    pub paths: serde_json::Value,
    pub tools: serde_json::Value,
    pub storage: serde_json::Value,
    pub seaweed: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuthConfig {
    pub install_token: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NetworkConfig {
    pub bind_host: String,
    pub core_port: u16,
    pub seaweed_s3_port: Option<u16>,
}

pub fn generate_install_token() -> String {
    let mut bytes = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut bytes);
    URL_SAFE_NO_PAD.encode(bytes)
}

pub fn core_json_path(faceforge_home: &Path) -> PathBuf {
    faceforge_home.join("config").join("core.json")
}

pub fn desktop_json_path(faceforge_home: &Path) -> PathBuf {
    faceforge_home.join("config").join("desktop.json")
}

pub fn write_core_json(faceforge_home: &Path, settings: &WizardSettings) -> anyhow::Result<String> {
    fs::create_dir_all(faceforge_home.join("config"))?;

    let existing_token = read_install_token(faceforge_home).ok();
    let token = existing_token.unwrap_or_else(generate_install_token);

    let storage = if settings.seaweed_enabled {
        let mut access = [0u8; 16];
        let mut secret = [0u8; 32];
        rand::thread_rng().fill_bytes(&mut access);
        rand::thread_rng().fill_bytes(&mut secret);
        serde_json::json!({
            "routing": {
                "default_provider": "s3",
                "kind_map": {},
                "s3_min_size_bytes": null
            },
            "s3": {
                "enabled": true,
                "endpoint_url": null,
                "access_key": URL_SAFE_NO_PAD.encode(access),
                "secret_key": URL_SAFE_NO_PAD.encode(secret),
                "bucket": "faceforge",
                "region": "us-east-1",
                "use_ssl": false
            }
        })
    } else {
        serde_json::json!({
            "routing": {
                "default_provider": "fs",
                "kind_map": {},
                "s3_min_size_bytes": null
            },
            "s3": {
                "enabled": false,
                "endpoint_url": null,
                "access_key": null,
                "secret_key": null,
                "bucket": "faceforge",
                "region": "us-east-1",
                "use_ssl": false
            }
        })
    };

    // Desktop manages SeaweedFS for Sprint 12.
    // Keep Core-managed seaweed disabled to avoid double-spawn.
    let core_payload = serde_json::json!({
        "version": "1",
        "auth": { "install_token": token },
        "network": {
            "bind_host": "127.0.0.1",
            "core_port": settings.core_port,
            "seaweed_s3_port": settings.seaweed_s3_port
        },
        "paths": {
            "db_dir": null,
            "s3_dir": null,
            "logs_dir": null,
            "plugins_dir": null
        },
        "tools": {
            "exiftool_enabled": true,
            "exiftool_path": null
        },
        "storage": storage,
        "seaweed": {
            "enabled": false,
            "weed_path": null,
            "data_dir": null,
            "ip": "127.0.0.1",
            "master_port": 9333,
            "volume_port": 8080,
            "filer_port": 8888,
            "s3_port": settings.seaweed_s3_port
        }
    });

    fs::write(core_json_path(faceforge_home), serde_json::to_vec_pretty(&core_payload)?)?;
    Ok(token)
}

pub fn write_desktop_json(faceforge_home: &Path, settings: &WizardSettings) -> anyhow::Result<()> {
    fs::create_dir_all(faceforge_home.join("config"))?;
    let payload = serde_json::json!({
        "faceforge_home": settings.faceforge_home,
        "core_port": settings.core_port,
        "seaweed_enabled": settings.seaweed_enabled,
        "seaweed_s3_port": settings.seaweed_s3_port,
        "seaweed_weed_path": settings.seaweed_weed_path
    });
    fs::write(desktop_json_path(faceforge_home), serde_json::to_vec_pretty(&payload)?)?;
    Ok(())
}

pub fn read_desktop_json(faceforge_home: &Path) -> anyhow::Result<WizardSettings> {
    let raw = fs::read_to_string(desktop_json_path(faceforge_home))?;
    let v: serde_json::Value = serde_json::from_str(&raw)?;
    let home_str = v
        .get("faceforge_home")
        .and_then(|x| x.as_str())
        .map(|s| s.to_string())
        .unwrap_or_else(|| faceforge_home.to_string_lossy().to_string());
    Ok(WizardSettings {
        faceforge_home: PathBuf::from(home_str),
        core_port: v.get("core_port").and_then(|x| x.as_u64()).unwrap_or(43210) as u16,
        seaweed_enabled: v
            .get("seaweed_enabled")
            .and_then(|x| x.as_bool())
            .unwrap_or(false),
        seaweed_s3_port: v.get("seaweed_s3_port").and_then(|x| x.as_u64()).map(|n| n as u16),
        seaweed_weed_path: v.get("seaweed_weed_path").and_then(|x| x.as_str()).map(PathBuf::from),
    })
}

pub fn read_install_token(faceforge_home: &Path) -> anyhow::Result<String> {
    let raw = fs::read_to_string(core_json_path(faceforge_home))?;
    let cfg: CoreJsonConfig = serde_json::from_str(&raw)?;
    let token = cfg.auth.install_token.trim().to_string();
    if token.is_empty() {
        anyhow::bail!("install_token missing in core.json")
    }
    Ok(token)
}
