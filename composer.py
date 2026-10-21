"""Composer entry point: `python composer.py [--config composer.config.json] [--port 8790] [--no-browser]`."""
from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from composer_lib.config import load_config  # noqa: E402
from composer_lib.server import make_server, start_inbox_thread  # noqa: E402


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="composer")
    ap.add_argument("--config", type=Path, default=Path(__file__).resolve().parent / "composer.config.json")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if args.port:
        cfg.port = args.port
    cfg.inbox_dir.mkdir(parents=True, exist_ok=True)
    cfg.workspace_dir.mkdir(parents=True, exist_ok=True)

    httpd = make_server("127.0.0.1", cfg.port, cfg)
    start_inbox_thread(httpd.app)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"composer: {url}", flush=True)
    print(f"  받은편지함: {cfg.inbox_dir}  (메일에서 받은 zip을 여기에 넣으세요)", flush=True)
    print(f"  작업 폴더:  {cfg.workspace_dir}", flush=True)
    print(f"  Confluence: {'설정됨' if cfg.confluence.configured else '미설정 (composer.config.json)'}", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
