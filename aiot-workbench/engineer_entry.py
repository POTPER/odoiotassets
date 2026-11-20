#!/usr/bin/env python3
"""Isolated Switcher host. Shares the deployment settings and operation locks."""
import argparse
import logging
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from bootstrap import configure
configure()


def main():
    from core import atomic_json, read_json
    sys.path.append(str(ROOT / "launcher"))
    from launcher_process import set_process_role
    set_process_role("engineer")
    config_dir = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "aiot-workbench"
    settings = config_dir / "settings.json"
    config_dir.mkdir(parents=True, exist_ok=True)
    data = read_json(settings) if settings.exists() else {}
    from workbench_paths import default_publish
    target = data.get("publish_dir") or data.get("target") or default_publish()
    # Parent passes its exact settings path, including non-default installations.
    args = sys.argv[1:]
    hosted = bool(args and args[0] == "--hosted")
    if hosted:
        args.pop(0)
        settings = Path(args.pop(0))
        data = read_json(settings)
        target = data["publish_dir"]
    if args and args[0] == "gui":
        args = ["engineer"]
    data.update(target=target, publish_dir=target)
    import tool_update
    from contextlib import nullcontext
    # A hosted panel is protected by its parent's lifetime lock. Standalone SSH
    # operations acquire it themselves, so an update cannot rename loaded code.
    with (nullcontext() if hosted else tool_update.instance_lock(ROOT)):
        if not hosted:
            tool_update.recover_update(ROOT)
        atomic_json(settings, data)
        if args and args[0] == "engineer":
            import tkinter as tk
            import app
            app.CONFIG = settings
            logfile = settings.parent / "logs/engineer.log"
            logfile.parent.mkdir(parents=True, exist_ok=True)
            logging.basicConfig(filename=str(logfile), level=logging.INFO,
                                format="%(asctime)s %(levelname)s %(message)s")
            class EngineerPanel(app.Application):
                def build_settings_page(self):
                    super().build_settings_page()
                    from tkinter import ttk
                    import tkinter as tk
                    from tkinter import messagebox
                    import re
                    options = ttk.LabelFrame(self.settings_page, text="工作台主页更新设置", padding=12)
                    options.pack(fill="x", pady=8)
                    ttk.Label(options, text="文件更新方案 ID（RK 默认 rk）").grid(row=0, column=0, sticky="w")
                    self.home_profile = tk.StringVar(value=data.get("home_update_profile", "rk"))
                    profile = ttk.Combobox(options, textvariable=self.home_profile, values=[p["id"] for p in self.presets])
                    profile.grid(row=0, column=1, padx=10, sticky="ew")
                    ttk.Label(options, text="工作台仓库内目录").grid(row=1, column=0, sticky="w", pady=8)
                    self.program_directory = tk.StringVar(value=data.get("workbench_directory", "aiot-workbench"))
                    source = ttk.Entry(options, textvariable=self.program_directory, width=60)
                    source.grid(row=1, column=1, sticky="ew", padx=10)
                    options.columnconfigure(1, weight=1)
                    self.controls.extend([profile, source])
                    def save():
                        try:
                            identity = self.home_profile.get().strip()
                            if not re.fullmatch(r"[A-Za-z0-9_-]+", identity):
                                raise ValueError("方案 ID 只允许字母、数字、下划线和短横线。")
                            from core import relative_path
                            directory = relative_path(self.program_directory.get().strip())
                            saved = read_json(settings)
                            saved.pop("program_update_url", None)
                            saved.update(home_update_profile=identity, workbench_directory=directory)
                            atomic_json(settings, saved)
                            self.status.set("更新设置已保存：程序和资源共用连接设置中的仓库。")
                        except Exception as exc:
                            messagebox.showerror("设置未保存", str(exc), parent=self.root)
                    self.button(options, "保存主页更新设置", save).grid(row=2, column=1, sticky="w", padx=10, pady=8)
                def build_program_page(self):
                    from tkinter import ttk
                    ttk.Label(self.program_page, text="AIoT 工作台程序更新", style="Title.TLabel").pack(anchor="w", pady=12)
                    ttk.Label(self.program_page, text="更新会同时更新用户主页和工程师面板。\n请关闭维护窗口，返回主页点击“程序更新”。").pack(anchor="w")
                def check_program_update(self):
                    from tkinter import messagebox
                    messagebox.showinfo("程序更新", "请返回工作台主页检查程序更新。", parent=self.root)
            root = tk.Tk()
            panel = EngineerPanel(root, engineer=True, updates=False)
            root.title("AIoT 工作台 · 工程师面板")
            root.mainloop()
            if panel.worker is not None:
                panel.worker.join()
            return 0
        import switcher
        import diagnostics
        diagnostics.settings_path = lambda: settings
        switcher.settings_path = lambda: settings
        switcher.default_log_path = lambda: settings.parent / "logs/engineer.log"
        # Global options stay before the subcommand, exactly as in Switcher.
        return switcher.main(["--target", target] + (args or ["cli"]))


if __name__ == "__main__":
    raise SystemExit(main())
