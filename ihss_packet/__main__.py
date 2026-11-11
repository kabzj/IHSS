"""Start the tool: python -m ihss_packet"""

from __future__ import annotations

import argparse
import webbrowser

from .server import make_server


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="ihss-packet", description="IHSS Packet Tool (runs locally).")
    ap.add_argument("--port", type=int, default=8765, help="local port (default 8765; 0 = any free port)")
    ap.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    args = ap.parse_args(argv)
    try:
        httpd = make_server(args.port)
    except OSError:
        httpd = make_server(0)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"IHSS Packet Tool is running at {url}  (only reachable from this computer)")
    print("Press Ctrl+C to stop. Session answers are cleared when it stops.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
