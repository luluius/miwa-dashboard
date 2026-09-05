import webview
import sys
import os

APP_TITLE = "Miwa Dashboard"
APP_URL   = "https://miwa230.duckdns.org"

def main():
    # Icône optionnelle (si fournie à côté du .exe)
    icon_path = None
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(base, "icon.ico")
    if os.path.isfile(candidate):
        icon_path = candidate

    window = webview.create_window(
        APP_TITLE,
        APP_URL,
        width=1400,
        height=860,
        min_size=(900, 600),
        resizable=True,
        text_select=True,
    )

    webview.start(
        debug=False,
        icon=icon_path if icon_path else None,
    )

if __name__ == "__main__":
    main()
