//! The menu bar icon and its menu. The pill window owns the engine calls,
//! so Start/Stop rows are passed to it as a "menu" event.

use std::sync::Mutex;

use tauri::image::Image;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{TrayIcon, TrayIconBuilder};
use tauri::{AppHandle, Emitter, Manager, Wry};

pub struct Tray {
    icon: TrayIcon,
    dictation: MenuItem<Wry>,
    meeting: MenuItem<Wry>,
    last: Mutex<(String, bool)>,
}

fn icon(state: &str) -> (Image<'static>, bool) {
    // (image, template): template icons follow the menu bar's light or dark color
    match state {
        "recording" => (Image::from_bytes(include_bytes!("../icons/tray/recording.png")).unwrap(), false),
        "transcribing" => (Image::from_bytes(include_bytes!("../icons/tray/transcribing.png")).unwrap(), false),
        "idle" => (Image::from_bytes(include_bytes!("../icons/tray/idle.png")).unwrap(), true),
        _ => (Image::from_bytes(include_bytes!("../icons/tray/off.png")).unwrap(), true),
    }
}

pub fn create(app: &AppHandle) -> tauri::Result<()> {
    let dictation = MenuItem::with_id(app, "dictation", "Start dictation", true, None::<&str>)?;
    let meeting = MenuItem::with_id(app, "meeting", "Record meeting", true, None::<&str>)?;
    let open = MenuItem::with_id(app, "open", "Open local-stt", true, None::<&str>)?;
    let settings = MenuItem::with_id(app, "settings", "Settings…", true, Some("CmdOrCtrl+,"))?;
    let quit = MenuItem::with_id(app, "quit", "Quit local-stt", true, Some("CmdOrCtrl+Q"))?;
    let menu = Menu::with_items(
        app,
        &[
            &dictation,
            &meeting,
            &PredefinedMenuItem::separator(app)?,
            &open,
            &settings,
            &PredefinedMenuItem::separator(app)?,
            &quit,
        ],
    )?;
    let (image, template) = icon("off");
    let tray = TrayIconBuilder::with_id("main")
        .icon(image)
        .icon_as_template(template)
        .tooltip("local-stt")
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "open" => crate::show_main(app, None),
            "settings" => crate::show_main(app, Some("/settings")),
            "quit" => app.exit(0),
            id => {
                let _ = app.emit_to("pill", "menu", id.to_string());
            }
        })
        .build(app)?;
    app.manage(Tray { icon: tray, dictation, meeting, last: Mutex::new((String::new(), false)) });
    Ok(())
}

/// dictation: off | loading | idle | recording | transcribing
#[tauri::command]
pub fn set_tray_state(app: AppHandle, dictation: String, meeting: bool) {
    let tray = app.state::<Tray>();
    {
        let mut last = tray.last.lock().unwrap();
        if *last == (dictation.clone(), meeting) {
            return;
        }
        *last = (dictation.clone(), meeting);
    }
    let shown = if meeting && dictation != "transcribing" { "recording" } else { dictation.as_str() };
    let (image, template) = icon(shown);
    let _ = tray.icon.set_icon(Some(image));
    let _ = tray.icon.set_icon_as_template(template);
    let label = match dictation.as_str() {
        "off" => "Start dictation",
        "loading" => "Loading the model…",
        _ => "Stop dictation",
    };
    let _ = tray.dictation.set_text(label);
    let _ = tray.dictation.set_enabled(dictation != "loading");
    let _ = tray.meeting.set_text(if meeting { "Stop and transcribe meeting" } else { "Record meeting" });
}
