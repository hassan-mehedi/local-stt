//! The Python engine (`stt engine`) as a child process. It prints
//! {"port", "token"} on its first stdout line and quits when its stdin closes,
//! so dropping the child's stdin is how the app stops it.

use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager};

#[derive(Clone, Serialize, Default)]
pub struct EngineInfo {
    pub port: Option<u16>,
    pub token: Option<String>,
    pub error: Option<String>,
}

#[derive(Default)]
pub struct Engine {
    info: Mutex<EngineInfo>,
    child: Mutex<Option<(Child, ChildStdin)>>,
}

fn log_file(app: &AppHandle) -> Option<File> {
    let dir = app.path().app_log_dir().ok()?;
    fs::create_dir_all(&dir).ok()?;
    OpenOptions::new().create(true).append(true).open(dir.join("engine.log")).ok()
}

/// The bundled Python inside the app, or `uv run` against the source tree
/// when the app runs from `tauri dev`.
fn command(app: &AppHandle) -> Command {
    let bundled = app
        .path()
        .resource_dir()
        .map(|dir| dir.join("engine"))
        .ok()
        .filter(|dir| dir.join("python/bin/python3.12").exists());
    match bundled {
        Some(engine) => {
            let mut cmd = Command::new(engine.join("python/bin/python3.12"));
            // -B: writing __pycache__ into the signed bundle breaks its signature
            cmd.args(["-B", "-I", "-m", "local_stt", "engine"]);
            cmd
        }
        None => {
            let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
            let mut cmd = Command::new("uv");
            cmd.args(["run", "--frozen", "stt", "engine"]).current_dir(repo);
            cmd
        }
    }
}

impl Engine {
    pub fn info(&self) -> EngineInfo {
        self.info.lock().unwrap().clone()
    }

    fn set_info(&self, app: &AppHandle, info: EngineInfo) {
        *self.info.lock().unwrap() = info.clone();
        let _ = app.emit("engine", info);
    }

    pub fn start(&self, app: &AppHandle) {
        self.set_info(app, EngineInfo::default());
        let log = log_file(app);
        let stderr = match log.as_ref().and_then(|f| f.try_clone().ok()) {
            Some(f) => Stdio::from(f),
            None => Stdio::null(),
        };
        let spawned = command(app)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(stderr)
            .spawn();
        let mut child = match spawned {
            Ok(child) => child,
            Err(e) => {
                let error = format!("could not start the engine: {e}");
                self.set_info(app, EngineInfo { error: Some(error), ..Default::default() });
                return;
            }
        };
        let stdin = child.stdin.take().expect("piped stdin");
        let stdout = child.stdout.take().expect("piped stdout");
        *self.child.lock().unwrap() = Some((child, stdin));

        let app = app.clone();
        thread::spawn(move || {
            let mut lines = BufReader::new(stdout).lines();
            let info = match lines.next() {
                Some(Ok(line)) => parse_first_line(&line),
                _ => EngineInfo {
                    error: Some("the engine stopped while starting; see engine.log".into()),
                    ..Default::default()
                },
            };
            let engine = app.state::<Engine>();
            engine.set_info(&app, info);
            // anything printed later goes to the log
            let mut log = log;
            for line in lines.map_while(Result::ok) {
                if let Some(f) = log.as_mut() {
                    let _ = writeln!(f, "{line}");
                }
            }
            // stdout closed: the engine exited
            let stopped_on_purpose = engine.child.lock().unwrap().is_none();
            if !stopped_on_purpose {
                engine.set_info(
                    &app,
                    EngineInfo { error: Some("the engine stopped; see engine.log".into()), ..Default::default() },
                );
            }
        });
    }

    /// Closes the engine's stdin, waits up to two seconds, then kills it.
    pub fn stop(&self) {
        let Some((mut child, stdin)) = self.child.lock().unwrap().take() else {
            return;
        };
        drop(stdin);
        let deadline = Instant::now() + Duration::from_secs(2);
        while Instant::now() < deadline {
            if let Ok(Some(_)) = child.try_wait() {
                return;
            }
            thread::sleep(Duration::from_millis(50));
        }
        let _ = child.kill();
        let _ = child.wait();
    }
}

fn parse_first_line(line: &str) -> EngineInfo {
    #[derive(serde::Deserialize)]
    struct First {
        port: Option<u16>,
        token: Option<String>,
        error: Option<String>,
    }
    match serde_json::from_str::<First>(line) {
        Ok(First { port: Some(port), token: Some(token), .. }) => {
            EngineInfo { port: Some(port), token: Some(token), error: None }
        }
        Ok(First { error: Some(error), .. }) => EngineInfo { error: Some(error), ..Default::default() },
        _ => EngineInfo { error: Some(format!("unexpected engine output: {line}")), ..Default::default() },
    }
}

#[tauri::command]
pub fn engine_info(engine: tauri::State<Engine>) -> EngineInfo {
    engine.info()
}

#[tauri::command]
pub fn restart_engine(app: AppHandle, engine: tauri::State<Engine>) {
    engine.stop();
    engine.start(&app);
}
