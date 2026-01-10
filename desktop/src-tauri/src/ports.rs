use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct RuntimePorts {
    pub core: Option<u16>,
    pub seaweed_s3: Option<u16>,
}

pub fn ports_path(faceforge_home: &Path) -> PathBuf {
    faceforge_home.join("run").join("ports.json")
}

pub fn write_ports(faceforge_home: &Path, ports: &RuntimePorts) -> anyhow::Result<()> {
    let run_dir = faceforge_home.join("run");
    fs::create_dir_all(&run_dir)?;
    let payload = serde_json::json!({
        "core": ports.core,
        "seaweed_s3": ports.seaweed_s3
    });
    fs::write(ports_path(faceforge_home), serde_json::to_vec_pretty(&payload)?)?;
    Ok(())
}
