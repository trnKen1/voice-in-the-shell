use tauri::{Manager, PhysicalPosition};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let window = app.get_webview_window("main").expect("main window");

            // Dock to bottom-center of the primary monitor. Uses a fixed
            // margin as a stand-in for the taskbar's actual height/autohide
            // state — revisit with real work-area detection if it's off.
            if let (Ok(Some(monitor)), Ok(window_size)) =
                (window.primary_monitor(), window.outer_size())
            {
                let monitor_size = monitor.size();
                let margin_bottom: i32 = 72;
                let x = (monitor_size.width as i32 - window_size.width as i32) / 2;
                let y = monitor_size.height as i32 - window_size.height as i32 - margin_bottom;
                let _ = window.set_position(PhysicalPosition::new(x, y));
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
