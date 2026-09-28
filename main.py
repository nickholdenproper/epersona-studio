"""ePersona Studio launcher — FastAPI backend + native pywebview window."""
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from studio.config import PORT


def free_port(preferred):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('127.0.0.1', preferred))
            return preferred
        except OSError:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]


def wait_ready(url, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def run_server(port):
    import uvicorn
    from server import app
    uvicorn.run(app, host='127.0.0.1', port=port, log_level='warning')


def main():
    port = free_port(PORT)
    url = f'http://127.0.0.1:{port}/'
    t = threading.Thread(target=run_server, args=(port,), daemon=True)
    t.start()

    print(f'[STUDIO] Backend starting on {url}')
    if not wait_ready(url):
        print('[STUDIO] Server failed to become ready — aborting.')
        sys.exit(1)
    print('[STUDIO] Backend ready.')

    try:
        import webview
        webview.create_window(
            'ePersona Studio', url,
            width=1500, height=940, min_size=(1150, 720),
            background_color='#0f1220',
        )
        print('[STUDIO] Opening native window (WebView2)...')
        webview.start()
        print('[STUDIO] Window closed.')
    except Exception as e:
        print(f'[STUDIO] pywebview unavailable ({e}) — opening default browser.')
        webbrowser.open(url)
        print('[STUDIO] Close this console window to quit the app.')
        try:
            while t.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
