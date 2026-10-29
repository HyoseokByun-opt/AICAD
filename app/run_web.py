"""Start the AICAD user interface: python run_web.py [--host 127.0.0.1] [--port 8100]"""
import argparse
import multiprocessing as mp
import os
import sys
import threading
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def main():
    ap = argparse.ArgumentParser(description="AICAD web user interface")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--open", action="store_true", help="open the browser")
    ap.add_argument("--start-ai", action="store_true", help="load the AI model at start")
    a = ap.parse_args()
    from web.server import create_app
    from aicad import __version__
    from aicad import llm
    app = create_app()
    url = f"http://{'127.0.0.1' if a.host in ('0.0.0.0', '') else a.host}:{a.port}"
    print(f"AICAD {__version__}  ->  {url}   (close this window to stop)", flush=True)
    if a.start_ai:
        llm.engine().start(wait=False)
    if a.open:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        from waitress import serve  # optional
        serve(app, host=a.host, port=a.port, threads=12)
    except ImportError:
        app.run(host=a.host, port=a.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    mp.freeze_support()
    main()
