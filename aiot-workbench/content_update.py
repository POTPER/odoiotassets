"""Isolated strict-update worker. JSON lines are the entire GUI/worker protocol."""
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from bootstrap import configure
configure()


def emit(kind, **data):
    print(json.dumps(dict(kind=kind, **data), ensure_ascii=False), flush=True)


def execute(settings, offline=False, approve=None, send=emit, cancel=None, source_descriptor=None):
    from core import Engine, read_json, check_cancel, SyncError
    from switcher import profiles, selected
    from file_formats import describe
    from workbench_paths import default_publish
    config = read_json(settings)
    target = config.get("publish_dir") or config.get("target") or default_publish()
    engine = Engine(target, extensions=config.get("file_extensions"))
    engine.startup_recover()
    args = SimpleNamespace(offline=offline, local_catalog=config.get("local_catalog"),
        repo=None, branch=None, profile=config.get("home_update_profile", "rk"), version=None)
    if source_descriptor is not None and not offline:
        from core import Source
        from repository import remote_profiles, validate_presets, DEFAULT_PROFILES
        source = Source(**source_descriptor)
        items = remote_profiles(source, validate_presets(config.get("directory_profiles", DEFAULT_PROFILES)))
    else:
        items = profiles(args, config, engine)
    if offline:
        # A user-facing offline update uses the latest completely cached manifest.
        matches = [item for item in items if item["manifest"]["id"] == args.profile]
        if matches:
            def cached_at(item):
                key = hashlib.sha256(json.dumps(item["manifest"], sort_keys=True).encode()).hexdigest()
                return (engine.state / "profiles" / (key + ".json")).stat().st_mtime_ns
            items = [max(matches, key=cached_at)]
    item = selected(args, items)
    manifest = item["manifest"]
    permissions = config.get("sync_permissions") is True
    with engine.lock():
        engine.save_profile(manifest, item["source"])
        preview = engine.preview(manifest, mode="strict", sync_permissions=permissions, cancel=cancel)
    if preview["blocker"]:
        raise SyncError(preview["blocker"])
    send("preview", profile=manifest.get("name", manifest["id"]), version=manifest["version"],
         target=str(engine.target), formats=describe(engine.extensions), changes=preview["changes"],
         download_bytes=preview["download_bytes"], notices=preview.get("notices", []))
    if not preview["changes"]:
        send("done", unchanged=True)
        return
    if approve is None or not approve():
        send("cancelled")
        return
    check_cancel(cancel)
    # CachedOnlySource prevents an offline update from ever contacting the network.
    source = item["source"]
    if offline:
        from assets_sync import CachedOnlySource
        source = CachedOnlySource(source)
    result = engine.apply(manifest, source, mode="strict", expected_actual=preview["actual"],
        sync_permissions=permissions, cancel=cancel, log=lambda message: send("log", message=str(message)))
    send("done", unchanged=result.get("unchanged", False), backup=result.get("backup"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", required=True)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--auto-apply", action="store_true", help="由工作台统一更新流程自动确认严格更新")
    parser.add_argument("--source-json", help="统一更新流程固定的仓库提交")
    options = parser.parse_args()
    sys.path.append(str(ROOT / "launcher"))
    from launcher_process import set_process_role
    set_process_role("engineer")
    cancel = threading.Event()
    input_fd = sys.stdin.fileno()
    def command():
        raw = b""
        while len(raw) < 4096:
            part = os.read(input_fd, 1)
            if not part:
                return None
            if part == b"\n":
                return json.loads(raw)
            raw += part
        raise ValueError("更新指令过长。")
    def approve():
        if not options.auto_apply:
            request = command()
            if not request or request.get("command") != "apply":
                return False
        def watch():
            try:
                while True:
                    request = command()
                    if not request or request.get("command") == "cancel":
                        break
            finally:
                cancel.set()  # Parent exit cancels any uncommitted preparation.
        threading.Thread(target=watch, daemon=True).start()
        return True
    try:
        execute(options.settings, options.offline, approve, cancel=cancel,
                source_descriptor=json.loads(options.source_json) if options.source_json else None)
        return 0
    except Exception as exc:
        logging.exception("严格更新未完成")
        emit("error", message=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
