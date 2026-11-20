"""One repository snapshot updates the workbench directory and publish files."""
import json
import os
from pathlib import Path
import subprocess

import tool_update


def update_publish(install, settings, offline=False, report=lambda message: None, source_descriptor=None):
    # The worker shares the backend without blocking Tk or sharing process state.
    from launcher_process import interpreter_for
    command = [interpreter_for("engineer"), str(Path(install) / "content_update.py"),
               "--settings", str(settings), "--auto-apply"]
    if offline:
        command.append("--offline")
    elif source_descriptor is not None:
        command += ["--source-json", json.dumps(source_descriptor)]
    logfile = Path(settings).parent / "logs/content-update.log"
    logfile.parent.mkdir(parents=True, exist_ok=True)
    result = None
    error = None
    report("正在检查应用文件…")
    with logfile.open("a", encoding="utf-8", buffering=1) as log:
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
            text=True, encoding="utf-8", bufsize=1, cwd=str(install),
            env=dict(os.environ, PYTHONIOENCODING="utf-8", AIOT_WORKBENCH_HOST_PID=str(os.getpid())))
        try:
            for line in child.stdout:
                log.write(line)
                event = json.loads(line)
                if event["kind"] == "preview":
                    report("正在更新应用文件（{} 项）…".format(len(event["changes"])) if event["changes"] else "应用文件已是最新。")
                elif event["kind"] == "done":
                    result = event
                elif event["kind"] == "error":
                    error = event["message"]
            code = child.wait()
        except BaseException:
            child.stdin.close()  # EOF cancels preparation; the engine finishes rollback.
            child.wait()
            raise
        finally:
            child.stdin.close()
            child.stdout.close()
    if code or result is None:
        raise RuntimeError(error or "应用文件更新进程未正常完成，请查看日志：" + str(logfile))
    return result


def update_all(install, settings, current, release=None, offline_manifest=None,
               report=lambda message: None, cancel=None):
    """Prepare self-update first, finish publish, then let the GUI commit/restart."""
    record = None
    try:
        if offline_manifest:
            report("正在校验离线程序包…")
            record = tool_update.prepare_offline(install, offline_manifest, current)
        elif release:
            report("正在下载并校验启动器…")
            record = tool_update.prepare_online(install, release, current, cancel, lambda size: None)
        source = release.get("source") if release and release.get("kind") == "repository" else None
        published = update_publish(install, settings, offline=bool(offline_manifest), report=report, source_descriptor=source)
        return {"program_record": record, "publish": published}
    except BaseException:
        if record is not None:
            tool_update.recover_update(install)
        raise
