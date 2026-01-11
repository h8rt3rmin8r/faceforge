# FaceForge User Guide

## Quick Start (Windows)

1.  **Download and Install**: Run the `FaceForge_Setup_x64.exe` installer.
2.  **First Run**:
    *   Launch FaceForge from the Start Menu or Desktop shortcut.
    *   You will see the **System Settings** screen.
    *   **Data Directory**: Choose a folder where FaceForge will store your database and files (defaults to `C:\FaceForge`).
    *   **S3 Storage**: Confirm storage settings (enabled by default).
    *   **Save**: Click "Save Configuration". The services will start automatically.
3.  **Open UI**:
    *   Click the **Open UI** button in the FaceForge Desktop window.
    *   Alternatively, right-click the system tray icon (FaceForge logo) and select **Open UI**.
    *   The main interface will open in your default browser.

## The Desktop Application

The FaceForge Desktop window acts as the command center:

*   **Status**: View connection details and service health.
*   **Logs**: Check internal logs if issues arise.
*   **Start / Stop / Restart**: Manually control the background services.
*   **Open UI**: Launch the web interface.

*Note: Closing the Desktop window minimizes it to the system tray. To fully quit, right-click the tray icon and select **Exit**.*

## Features

*   **Entities**: Create person entries, add tags and custom fields.
*   **Assets**: Drag and drop images/videos. Metadata is automatically extracted.
*   **Search**: Find assets by tag, date, or EXIF data.

## Troubleshooting

*   **Logs**: Click the **Logs** button in the Desktop app, or check the `logs` folder inside your Data Directory.
*   **Restart Services**: Use the **Restart** button in the Desktop app if the services become unresponsive.
