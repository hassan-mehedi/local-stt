// no console window on Windows release builds
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod engine;
mod pill;
mod tray;

use tauri::{ActivationPolicy, AppHandle, Emitter, Manager, RunEvent, WindowEvent};

use engine::Engine;

/// Shows the main window, optionally on a route such as "/settings". While
/// it is open the app has a Dock icon, so the window can't get lost.
pub fn show_main(app: &AppHandle, route: Option<&str>) {
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    #[cfg(target_os = "macos")]
    let _ = app.set_activation_policy(ActivationPolicy::Regular);
    let _ = window.show();
    let _ = window.unminimize();
    let _ = window.set_focus();
    if let Some(route) = route {
        let _ = window.emit("navigate", route);
    }
}

fn hide_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.hide();
    }
    #[cfg(target_os = "macos")]
    let _ = app.set_activation_policy(ActivationPolicy::Accessory);
}

#[tauri::command]
fn open_main(app: AppHandle, route: Option<String>) {
    show_main(&app, route.as_deref());
}

/// Hides local-stt so the app that was in front before gets the keyboard
/// back, e.g. before typing a history entry into it again.
#[tauri::command]
fn hide_app(app: AppHandle) {
    hide_main(&app);
    #[cfg(target_os = "macos")]
    let _ = app.hide();
}

/// macOS applies privacy permissions to a process only from its next start.
#[tauri::command]
fn restart_app(app: AppHandle) {
    app.state::<Engine>().stop();
    app.restart();
}

fn main() {
    let mut builder = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| show_main(app, None)))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ));
    #[cfg(target_os = "macos")]
    {
        builder = builder.plugin(tauri_nspanel::init());
    }
    let app = builder
        .manage(Engine::default())
        .invoke_handler(tauri::generate_handler![
            engine::engine_info,
            engine::restart_engine,
            pill::pill_show,
            pill::pill_hide,
            tray::set_tray_state,
            open_main,
            hide_app,
            restart_app,
        ])
        .setup(|app| {
            #[cfg(target_os = "macos")]
            app.set_activation_policy(ActivationPolicy::Accessory);
            tray::create(app.handle())?;
            pill::create(app.handle())?;
            app.state::<Engine>().start(app.handle());
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    api.prevent_close();
                    hide_main(window.app_handle());
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building local-stt");

    app.run(|app, event| match event {
        RunEvent::Exit => app.state::<Engine>().stop(),
        #[cfg(target_os = "macos")]
        RunEvent::Reopen { .. } => show_main(app, None),
        _ => {}
    });
}
