//! The recording pill: a borderless panel at the bottom of the screen that
//! never takes focus, so typing goes on landing in the app in front.

use tauri::{AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, WebviewUrl};

const BOTTOM_MARGIN: f64 = 14.0;

#[cfg(target_os = "macos")]
mod panel {
    use tauri_nspanel::tauri_panel;

    tauri_panel! {
        panel!(PillPanel {
            config: {
                can_become_key_window: false,
                is_floating_panel: true
            }
        })
    }
}

#[cfg(target_os = "macos")]
mod hover {
    use tauri::{AppHandle, Emitter};
    use tauri_nspanel::objc2::rc::Retained;
    use tauri_nspanel::objc2::{
        define_class, msg_send, AllocAnyThread, DefinedClass, MainThreadMarker, MainThreadOnly,
    };
    use tauri_nspanel::objc2_app_kit::{NSEvent, NSTrackingArea, NSTrackingAreaOptions, NSView};
    use tauri_nspanel::objc2_foundation::{NSObject, NSObjectProtocol};

    pub struct HoverIvars {
        app: AppHandle,
    }

    define_class!(
        #[unsafe(super(NSObject))]
        #[thread_kind = MainThreadOnly]
        #[name = "LocalSttPillHover"]
        #[ivars = HoverIvars]
        pub struct PillHover;

        unsafe impl NSObjectProtocol for PillHover {}

        impl PillHover {
            #[unsafe(method(mouseEntered:))]
            fn mouse_entered(&self, _event: &NSEvent) {
                let _ = self.ivars().app.emit_to("pill", "pill-hover", true);
            }

            #[unsafe(method(mouseExited:))]
            fn mouse_exited(&self, _event: &NSEvent) {
                let _ = self.ivars().app.emit_to("pill", "pill-hover", false);
            }
        }
    );

    /// WKWebView tracks the mouse only in the key window and the pill never
    /// becomes key, so this tracking area reports hover to the page instead.
    pub fn track(app: &AppHandle, view: &NSView) {
        let Some(mtm) = MainThreadMarker::new() else {
            return;
        };
        let owner = PillHover::alloc(mtm).set_ivars(HoverIvars { app: app.clone() });
        let owner: Retained<PillHover> = unsafe { msg_send![super(owner), init] };
        let options = NSTrackingAreaOptions::ActiveAlways
            | NSTrackingAreaOptions::MouseEnteredAndExited
            | NSTrackingAreaOptions::InVisibleRect;
        let area = unsafe {
            NSTrackingArea::initWithRect_options_owner_userInfo(
                NSTrackingArea::alloc(),
                view.bounds(),
                options,
                Some(&owner),
                None,
            )
        };
        view.addTrackingArea(&area);
        // the tracking area does not retain its owner; the pill lives as long as the app
        std::mem::forget(owner);
    }
}

#[cfg(target_os = "macos")]
pub fn create(app: &AppHandle) -> tauri::Result<()> {
    use tauri_nspanel::{CollectionBehavior, PanelBuilder, PanelLevel, StyleMask};

    let panel = PanelBuilder::<_, panel::PillPanel>::new(app, "pill")
        .url(WebviewUrl::App("index.html#/pill".into()))
        .size(tauri::Size::Logical(LogicalSize { width: 80.0, height: 26.0 }))
        .level(PanelLevel::Status)
        .has_shadow(false)
        .transparent(true)
        .no_activate(true)
        .accepts_mouse_moved_events(true)
        .style_mask(StyleMask::empty().borderless().nonactivating_panel())
        .with_window(|w| w.decorations(false).transparent(true).focusable(false).visible(false))
        .collection_behavior(CollectionBehavior::new().can_join_all_spaces().full_screen_auxiliary())
        .build()?;
    panel.hide();
    hover::track(app, &panel.content_view());
    Ok(())
}

#[cfg(not(target_os = "macos"))]
pub fn create(app: &AppHandle) -> tauri::Result<()> {
    tauri::WebviewWindowBuilder::new(app, "pill", WebviewUrl::App("index.html#/pill".into()))
        .decorations(false)
        .transparent(true)
        .always_on_top(true)
        .skip_taskbar(true)
        .focused(false)
        .visible(false)
        .inner_size(80.0, 26.0)
        .build()?;
    Ok(())
}

/// Bottom center of the screen the mouse is on, above the Dock.
fn place(app: &AppHandle, width: f64, height: f64) -> tauri::Result<()> {
    let Some(window) = app.get_webview_window("pill") else {
        return Ok(());
    };
    let cursor = app.cursor_position()?;
    let monitor = match app.monitor_from_point(cursor.x, cursor.y)? {
        Some(m) => Some(m),
        None => app.primary_monitor()?,
    };
    let Some(monitor) = monitor else {
        return Ok(());
    };
    let scale = monitor.scale_factor();
    let area = monitor.work_area();
    let (x, y) = (area.position.x as f64 / scale, area.position.y as f64 / scale);
    let (w, h) = (area.size.width as f64 / scale, area.size.height as f64 / scale);
    window.set_size(LogicalSize { width, height })?;
    window.set_position(LogicalPosition {
        x: x + (w - width) / 2.0,
        y: y + h - height - BOTTOM_MARGIN,
    })?;
    Ok(())
}

fn show(app: &AppHandle) {
    #[cfg(target_os = "macos")]
    {
        use tauri_nspanel::ManagerExt;
        if let Ok(panel) = app.get_webview_panel("pill") {
            panel.show();
        }
    }
    #[cfg(not(target_os = "macos"))]
    if let Some(window) = app.get_webview_window("pill") {
        let _ = window.show();
    }
}

fn hide(app: &AppHandle) {
    #[cfg(target_os = "macos")]
    {
        use tauri_nspanel::ManagerExt;
        if let Ok(panel) = app.get_webview_panel("pill") {
            panel.hide();
        }
    }
    #[cfg(not(target_os = "macos"))]
    if let Some(window) = app.get_webview_window("pill") {
        let _ = window.hide();
    }
}

/// Sizes and shows the pill. Panels belong to the main thread.
#[tauri::command]
pub fn pill_show(app: AppHandle, width: f64, height: f64) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        let _ = place(&handle, width, height);
        show(&handle);
    });
}

#[tauri::command]
pub fn pill_hide(app: AppHandle) {
    // a hidden panel gets no mouseExited
    let _ = app.emit_to("pill", "pill-hover", false);
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || hide(&handle));
}
