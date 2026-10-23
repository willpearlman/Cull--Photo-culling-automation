"""Desktop app: the local server in a native window. No terminal, no browser.

    python -m cull.desktop

Starts the FastAPI server on a free port on 127.0.0.1 in a background thread, waits until it
answers, then opens a pywebview window (Edge WebView2 on Windows, WebKit on macOS) on it.
The page gets one native helper, window.pywebview.api.pick_folder(). Closing the window ends
the app.
"""
from __future__ import annotations

import logging
import socket
import sys
import threading
import time
import urllib.request

import uvicorn

from cull import config

log = logging.getLogger("cull.desktop")


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Api:
    """Methods the page can call through window.pywebview.api.

    pywebview exposes every public attribute to the page and walks into objects to do it, so
    the window is kept in a private attribute: as a public one, pywebview recursed through the
    native window's internals until Python ran out of stack.
    """

    def __init__(self):
        self._window = None

    def pick_folder(self):
        import webview
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return result[0] if result else None


def _serve(port):
    log.info("serving on 127.0.0.1:%d", port)
    from cull.server import app
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                           log_config=None))
    threading.Thread(target=server.run, daemon=True, name="cull-server").start()
    url = f"http://127.0.0.1:{port}/"
    for _ in range(200):  # up to 20 s for the first import of the heavy modules
        try:
            urllib.request.urlopen(url + "api/shoot", timeout=1)
            return url
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("Cull's local server did not start")


def main():
    config.APP_DATA.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s",
                        filename=str(config.APP_DATA / "cull.log") if config.FROZEN else None)
    if config.FROZEN:
        # No console in the packaged app: send crashes and hang dumps to a file too.
        import faulthandler
        _crash = open(config.APP_DATA / "crash.log", "a", encoding="utf-8")  # noqa: SIM115
        faulthandler.enable(_crash)
    import webview
    url = _serve(_free_port())
    api = Api()
    api._window = webview.create_window("Cull", url, js_api=api, width=1400, height=900,
                                       min_size=(900, 600), background_color="#1b1d21")
    webview.start(private_mode=False)  # keep localStorage (tile size) between launches
    return 0


if __name__ == "__main__":
    sys.exit(main())
