#!/usr/bin/env python3
"""Minimal Ubuntu launcher: competition background, Start, and Exit AIoT."""
import argparse
from pathlib import Path
import queue
import signal
import sys
import threading
import os
import traceback
import time
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootstrap import configure
configure()

from launcher_runtime import LauncherController, config_directory, load_settings
from launcher_preferences import preferences, save_preferences, open_results_directory
from core import SyncError
from desktop_identity import configure_launcher_window
from launcher_diagnostics import LAUNCHER_VERSION, doctor, show_diagnostic_error
from launcher_process import set_process_role
from running_aiot import find_running_aiot


ASSETS = Path(__file__).resolve().parent / "assets"


class LauncherWindow:
    def __init__(self, root, controller, background=None, settings=None, settings_path=None, instance=None, status_monitor=None):
        import tkinter as tk
        from tkinter import ttk
        from tkinter import font
        from launcher_style import APP_NAME, BG, WINDOW_WIDTH, WINDOW_HEIGHT, LauncherButton, LauncherChrome
        from launcher_style import load_image_pixels, image_photo

        self.root, self.controller = root, controller
        self.instance = instance
        self.busy, self.closing, self.destroyed = True, False, False
        self.external_running = False
        self.external_stopping = False
        self.external_pids = []
        self.status_error = None
        self.status_epoch = time.monotonic()
        self.status_monitor = status_monitor
        self.settings = dict(settings or {})
        self.settings_path = Path(settings_path) if settings_path is not None else config_directory() / "settings.json"
        self.config_controller = LauncherController(self.settings.get("publish_dir", getattr(controller, "publish", "")))
        self.external_stop_controller = LauncherController(self.settings.get("publish_dir", getattr(controller, "publish", "")))
        self.config_busy = False
        self.config_action = None
        self.results_dir, self.theme = preferences(self.settings)
        self.settings_dialog = None
        self.settings_auth_active = False
        self.results_panel = None
        self.results_panel_item = None
        self.file_events = queue.Queue()
        self.opening_results = False
        self.background_path = Path(background) if background is not None else ASSETS / "background.png"
        self.photo = None
        self.window_icon = None
        self.sidebar_icon = None
        root.title(APP_NAME)
        root.geometry("{}x{}".format(WINDOW_WIDTH, WINDOW_HEIGHT))
        root.minsize(WINDOW_WIDTH, WINDOW_HEIGHT)
        root.maxsize(WINDOW_WIDTH, WINDOW_HEIGHT)
        root.resizable(False, False)
        configure_launcher_window(root)
        self.audit("window-created", "Tk {} / {}".format(root.tk.call("info", "patchlevel"), root.tk.call("tk", "windowingsystem")))
        for name in ("<Map>", "<Unmap>", "<FocusIn>", "<FocusOut>"):
            root.bind(name, self.window_event, add="+")
        available_fonts = set(font.families(root))
        family = next((name for name in ("Noto Sans CJK SC", "Noto Sans SC", "Microsoft YaHei UI",
                                        "Microsoft YaHei", "微软雅黑", "WenQuanYi Micro Hei")
                       if name in available_fonts),
                      font.Font(root=root, name="TkDefaultFont", exists=True).actual("family"))
        self.family = family
        background_pixels = load_image_pixels(self.background_path)
        if background_pixels is not None:
            self.photo = image_photo(background_pixels, root)
            import PIL
            print("图像渲染：Pillow {} / LANCZOS；原图 {}×{}；{}".format(
                PIL.__version__, *background_pixels.size, self.background_path), file=sys.stderr)
        window_pixels = load_image_pixels(ASSETS / "icon.png")
        if window_pixels is not None:
            self.window_icon = image_photo(window_pixels, root)
            root.iconphoto(True, self.window_icon)
        sidebar_pixels = load_image_pixels(ASSETS / "sidebar-icon.png")
        if sidebar_pixels is not None:
            self.sidebar_icon = image_photo(sidebar_pixels, root)
        self.canvas = LauncherChrome(root, family, photo=self.photo, icon=self.sidebar_icon or self.window_icon,
                                     theme=self.theme, source_pixels=background_pixels,
                                     icon_pixels=sidebar_pixels if sidebar_pixels is not None else window_pixels)
        self.canvas.pack(fill="both", expand=True)
        self.start_button = LauncherButton(self.canvas, text="启动", command=self.start,
                                          family=family, primary=True, width=154, theme=self.theme)
        self.exit_button = LauncherButton(self.canvas, text="停止", command=self.stop, family=family, width=100, theme=self.theme)
        self.results_button = LauncherButton(self.canvas, text="查看成果", command=self.view_results,
                                            family=family, width=138, theme=self.theme)
        self.results_button.configure(state="normal")
        self.settings_button = LauncherButton(self.canvas, text="设置", command=self.open_settings,
                                             family=family, width=160, theme=self.theme, sidebar=True)
        self.settings_button.configure(state="normal")
        self.status = tk.StringVar(value="正在加载…")
        self.status_trace = self.status.trace_add("write", lambda *_: self.canvas.set_message(self.status.get()))
        self.progress_frame = tk.Frame(self.canvas, background=BG, height=3)
        self.progress_frame.pack_propagate(False)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Launcher.Horizontal.TProgressbar", troughcolor=BG, background="#8bb5ec",
                        bordercolor=BG, lightcolor="#8bb5ec", darkcolor="#8bb5ec", borderwidth=0)
        self.progress = ttk.Progressbar(self.progress_frame, mode="indeterminate", style="Launcher.Horizontal.TProgressbar")
        self.progress.pack(fill="both", expand=True)
        self.progress.start(15)
        self.start_item = self.canvas.create_window(0, 0, window=self.start_button, anchor="ne")
        self.exit_item = self.canvas.create_window(0, 0, window=self.exit_button, anchor="ne")
        self.results_item = self.canvas.create_window(0, 0, window=self.results_button, anchor="ne")
        self.settings_item = self.canvas.create_window(16, 546, window=self.settings_button, anchor="nw")
        self.progress_item = self.canvas.create_window(0, 0, window=self.progress_frame, anchor="nw", height=3)
        self.canvas.layout_callback = self.layout_controls
        self.apply_theme(self.theme)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = root.after(50, self.poll)
        controller.initialize()
        if self.status_monitor is not None:
            self.status_monitor.start()

    def audit(self, event, detail=""):
        try:
            print("[{}] GUI pid={} {} {}".format(datetime.now().isoformat(timespec="seconds"),
                                                os.getpid(), event, detail), file=sys.stderr, flush=True)
        except (OSError, ValueError):
            pass

    def window_event(self, event):
        if event.widget is self.root and not self.destroyed:
            self.audit("window-event", "type={} state={} busy={}".format(event.type, self.root.state(), self.busy))

    def activate(self):
        if self.destroyed:
            return
        self.show_home()
        self.root.deiconify()
        self.root.lift()
        # Keep an open password/settings dialog in front, without bypassing it.
        grabbed = self.root.grab_current()
        window = grabbed.winfo_toplevel() if grabbed is not None else self.root
        window.deiconify()
        window.lift()
        window.focus_force()
        self.audit("existing-window-activated")

    def layout_controls(self, right, top, left, progress_y, width):
        self.canvas.coords(self.start_item, right - 262, top)
        self.canvas.coords(self.exit_item, right - 150, top)
        self.canvas.coords(self.results_item, right, top)
        self.canvas.coords(self.settings_item, 16, top)
        self.canvas.coords(self.progress_item, left, progress_y)
        self.canvas.itemconfigure(self.progress_item, width=width)

    def apply_theme(self, theme):
        from tkinter import ttk
        from launcher_style import palette
        self.theme = theme
        colors = palette(theme)
        self.root.configure(background=colors["bg"])
        self.canvas.set_theme(theme)
        for button in (self.start_button, self.exit_button, self.results_button, self.settings_button):
            button.set_theme(theme)
        self.progress_frame.configure(background=colors["bg"])
        ttk.Style(self.root).configure("Launcher.Horizontal.TProgressbar", troughcolor=colors["bg"],
                                       background=colors["accent"], bordercolor=colors["bg"])
        if self.results_panel is not None:
            self.results_panel.apply_theme(theme)

    def open_settings(self):
        from launcher_settings import SettingsDialog, request_settings_access
        if self.results_panel is not None and self.results_panel.submitting:
            from tkinter import messagebox
            messagebox.showinfo("正在提交成果", "请等待成果提交完成后再修改设置。", parent=self.root)
            return
        if self.settings_dialog is not None and self.settings_dialog.window.winfo_exists():
            self.settings_dialog.window.lift()
            return
        if self.settings_auth_active or self.closing or self.destroyed:
            return
        self.settings_auth_active = True
        try:
            allowed = request_settings_access(self.root, self.theme, self.family)
        finally:
            self.settings_auth_active = False
        if not allowed or self.closing or self.destroyed:
            return
        self.settings_dialog = SettingsDialog(self.root, self.results_dir, self.theme, self.family,
                                              self.save_settings, self.apply_theme, settings=self.settings,
                                              on_config_refresh=self.load_configs, on_config_replace=self.replace_config,
                                              running=self.busy, on_config_clear=self.clear_task_data)

    def load_configs(self):
        return self.begin_config("list")

    def replace_config(self, version):
        return self.begin_config("replace", version)

    def clear_task_data(self):
        return self.begin_config("clear")

    def begin_config(self, action, version=None):
        if self.busy or self.config_busy or self.closing or self.destroyed:
            return False
        if self.results_panel is not None and self.results_panel.submitting:
            return False
        if action == "list":
            accepted = self.config_controller.list_configs()
        elif action == "clear":
            accepted = self.config_controller.clear_task_data()
        else:
            accepted = self.config_controller.replace_config(version)
        if not accepted:
            return False
        self.status_epoch = time.monotonic()
        self.config_busy, self.config_action = True, action
        self.start_button.configure(state="disabled")
        self.results_button.configure(state="disabled")
        self.settings_dialog.set_config_busy(True, action)
        return True

    def handle_config_event(self, event, data):
        if event != "finished":
            return
        self.status_epoch = time.monotonic()
        self.config_busy = False
        dialog = self.settings_dialog
        if dialog is not None and dialog.window.winfo_exists():
            dialog.set_config_busy(False)
            dialog.config_panel.receive(self.config_action, data)
        self.start_button.configure(state="normal" if not self.busy else "disabled")
        self.results_button.configure(state="disabled" if self.opening_results else "normal")
        if self.closing:
            self.closing = False
            self.close(force=True, reason='configuration-finished')

    def save_settings(self, results_dir, theme, submission_enabled=False, submission_dir=""):
        self.settings = save_preferences(self.settings_path,
                                         self.settings.get("publish_dir", getattr(self.controller, "publish", "")),
                                         results_dir, theme, submission_enabled, submission_dir)
        self.results_dir, _ = preferences(self.settings)
        self.apply_theme(theme)
        if self.results_panel is not None:
            if self.settings.get("submission_enabled", False) is not True:
                self.show_home()
            self.results_panel.reconfigure(self.results_dir, self.settings)

    def view_results(self):
        if self.closing or self.config_busy:
            return
        if self.settings.get("submission_enabled", False) is not True:
            self.show_home()
            if self.opening_results:
                return
            self.opening_results = True
            self.results_button.configure(state="disabled")
            events, folder = self.file_events, self.results_dir
            def open_folder():
                error = None
                try:
                    open_results_directory(folder)
                except Exception as exc:
                    error = str(exc)
                events.put(error)
            threading.Thread(target=open_folder, daemon=True).start()
            return
        from results_panel import ResultsPanel
        if self.results_panel is None:
            self.results_panel = ResultsPanel(self.canvas, self.results_dir, self.settings, self.theme,
                                              self.family, self.show_home)
            self.results_panel_item = self.canvas.create_window(192, 0, window=self.results_panel,
                                                                anchor="nw", width=908, height=526)
        else:
            self.results_panel.visible = True
            self.canvas.itemconfigure(self.results_panel_item, state="normal")
            self.results_panel.refresh()

    def show_home(self):
        if self.results_panel is not None:
            self.results_panel.visible = False
            self.canvas.itemconfigure(self.results_panel_item, state="hidden")

    def start(self):
        if self.busy or self.config_busy or self.closing:
            return
        if self.controller.start():
            self.status_epoch = time.monotonic()
            self.audit("start-request")
            self.busy = True
            self.start_button.configure(text="启动中…", state="disabled")
            self.exit_button.configure(state="disabled")
            self.status.set("正在检查…")
            self.canvas.set_phase("starting")
            self.progress.pack(fill="both", expand=True)
            self.progress.start(15)

    def stop(self, reason="stop-button"):
        if self.external_running:
            if self.external_stopping:
                return True
            if not self.external_stop_controller.stop_existing():
                return False
            self.external_stopping = True
            self.status_epoch = time.monotonic()
            self.exit_button.configure(state='disabled')
            self.start_button.configure(text='停止中…', state='disabled')
            self.status.set('正在停止 AIoT…')
            self.canvas.set_phase('stopping')
            self.progress.pack(fill='both', expand=True)
            self.progress.start(15)
            self.audit('stop-external-request', '{} pids={}'.format(reason, self.external_pids))
            return True
        if self.busy and not self.external_running:
            self.audit("stop-request", reason)
            self.controller.request_stop()
            self.exit_button.configure(state="disabled")
            self.start_button.configure(text="停止中…")
            self.status.set("")
            self.canvas.set_phase("stopping")
            self.progress.pack(fill="both", expand=True)
            self.progress.start(15)
            return True
        return False

    def display_external(self, pids):
        changed = not self.external_running or self.external_pids != pids
        self.external_running, self.busy = True, True
        self.external_pids = list(pids)
        self.status_error = None
        self.start_button.configure(text='运行中', state='disabled')
        self.exit_button.configure(state='normal')
        self.progress.stop()
        self.progress.pack_forget()
        self.canvas.set_phase('running')
        self.status.set('AIoT 已由其他入口启动')
        if changed:
            self.audit('external-aiot-running', str(pids))

    def display_idle(self):
        self.external_running, self.busy = False, False
        self.external_pids = []
        self.status_error = None
        self.start_button.configure(text='启动', state='normal')
        self.exit_button.configure(state='disabled')
        self.progress.stop()
        self.progress.pack_forget()
        self.canvas.set_phase('idle')
        self.status.set('')

    def report_error(self, title, data):
        show_diagnostic_error(self.root, title, data, self.config_controller.publish, self.settings_path.parent / 'logs')

    def handle_process_status(self, data):
        if (self.closing or self.destroyed or self.external_stopping or self.config_busy or
                getattr(self.controller, 'busy', False) or (self.busy and not self.external_running) or
                data['sample_started'] < self.status_epoch):
            return
        if data.get('error'):
            if self.status_error != data['error']:
                self.audit('process-status-error', data['error'])
            self.status_error = data['error']
            self.status.set('无法检测 AIoT 状态，请查看日志')
            self.start_button.configure(state='disabled')
        elif data['pids']:
            self.display_external(data['pids'])
        elif self.external_running or self.status_error:
            self.display_idle()

    def handle_external_stop(self, event, data):
        if event != 'finished':
            return
        self.external_stopping = False
        self.status_epoch = time.monotonic()
        self.progress.stop()
        self.progress.pack_forget()
        was_closing = self.closing
        if was_closing and not data.get('error') and not data.get('remaining_pids'):
            # End an initial read-only observer only after the stop helper succeeds.
            # Its terminal event must arrive before the GUI exits.
            self.controller.request_stop()
            if not getattr(self.controller, 'busy', False):
                self.destroy()
            else:
                self.status.set('正在等待退出清理…')
            return
        if was_closing:
            self.closing = False
        remaining = data.get('remaining_pids') or (self.external_pids if data.get('error') else [])
        if remaining:
            self.display_external(remaining)
        elif not getattr(self.controller, 'busy', False):
            self.display_idle()
        else:
            self.status.set('正在确认停止…')
        if data.get('error'):
            self.report_error('AIoT 停止失败', data)
        elif was_closing and remaining:
            from tkinter import messagebox
            messagebox.showwarning('暂未退出', '检测到新的 AIoT 实例，请停止后再退出。', parent=self.root)

    def handle_event(self, event, data):
        if event == "status":
            if not self.controller.stop_event.is_set():
                self.status.set(data)
        elif event == 'external_running':
            if not self.external_stopping:
                self.display_external(data['pids'])
                if self.closing and not self.stop(reason='close-external-detected'):
                    self.closing = False
        elif event == "started":
            self.external_running = False
            self.external_pids = []
            self.status_error = None
            self.audit("aiot-started", str(data))
            if self.closing or self.controller.stop_event.is_set():
                self.stop()
            else:
                self.start_button.configure(text="运行中", state="disabled")
                self.exit_button.configure(state="normal")
                self.status.set("")
        elif event == "stable":
            if not self.closing and not self.controller.stop_event.is_set():
                self.progress.stop()
                self.progress.pack_forget()
                self.status.set("")
                self.canvas.set_phase("running")
        elif event == 'stop_failed':
            self.audit(event, str(data))
            self.closing = False
            self.busy = True
            self.progress.stop()
            self.progress.pack_forget()
            self.start_button.configure(text='停止失败', state='disabled')
            self.exit_button.configure(state='normal')
            self.canvas.set_phase('error')
            self.status.set('停止失败，可重试。')
            self.report_error('AIoT 停止失败', data)
        elif event in ("ready", "finished"):
            self.audit(event, str(data))
            self.status_epoch = time.monotonic()
            if self.external_stopping:
                return
            was_stopping = self.closing or self.controller.stop_event.is_set() or data.get('stopped')
            self.display_idle()
            if self.closing and not data.get('error'):
                self.destroy()
                return
            self.closing = False
            if event == "finished":
                self.root.deiconify()
                self.root.lift()
            if data.get('error'):
                self.canvas.set_phase("error")
                if was_stopping:
                    self.status.set('停止失败，请检查运行状态。')
                    self.report_error('AIoT 停止失败', data)
                else:
                    self.status.set('启动检查失败。' if event == 'ready' else '启动失败，请重试。')
                    self.report_error('启动器检查失败' if event == 'ready' else 'AIoT 启动失败', data)

    def poll(self):
        if self.destroyed:
            return
        try:
            self.poll_events()
        except Exception:
            self.audit('poll-error', traceback.format_exc())
        finally:
            if not self.destroyed:
                self.poll_id = self.root.after(50, self.poll)

    def poll_events(self):
        if self.instance is not None and self.instance.activation_requested():
            try:
                self.activate()
            except Exception:
                # Focus/WM errors must not block processing AIoT exit notifications.
                self.audit('window-activation-error', traceback.format_exc())
        try:
            while not self.destroyed:
                error = self.file_events.get_nowait()
                self.opening_results = False
                self.results_button.configure(state="normal")
                if error and not self.closing:
                    from tkinter import messagebox
                    messagebox.showerror("无法查看成果", error, parent=self.root)
        except queue.Empty:
            pass
        try:
            while not self.destroyed:
                event, data = self.controller.events.get_nowait()
                self.handle_event(event, data)
        except queue.Empty:
            pass
        try:
            while not self.destroyed:
                event, data = self.config_controller.events.get_nowait()
                self.handle_config_event(event, data)
        except queue.Empty:
            pass
        try:
            while not self.destroyed:
                event, data = self.external_stop_controller.events.get_nowait()
                self.handle_external_stop(event, data)
        except queue.Empty:
            pass
        if self.status_monitor is not None:
            try:
                while not self.destroyed:
                    self.handle_process_status(self.status_monitor.events.get_nowait())
            except queue.Empty:
                pass
        if not self.destroyed:
            if self.settings_dialog is not None and self.settings_dialog.window.winfo_exists():
                self.settings_dialog.config_panel.set_running(self.busy)

    def close(self, force=False, reason="window-close"):
        if self.closing or self.destroyed:
            return
        self.audit("close-request", "reason={} force={}".format(reason, force))
        if self.config_busy:
            self.closing = True
            self.status.set("正在等待配置操作完成…")
            return
        if self.external_stopping:
            self.closing = True
            self.status.set('正在等待 AIoT 停止…')
            return
        if not self.busy:
            # Recheck at close instead of trusting a sample up to one second old.
            try:
                existing = find_running_aiot(self.settings.get('publish_dir', getattr(self.controller, 'publish', '')))
            except Exception as exc:
                self.audit('close-check-error', str(exc))
                self.report_error('暂未退出', {'error': '无法检查 AIoT 是否运行：' + str(exc)})
                return
            if existing:
                self.display_external(existing)
        if self.busy:
            from tkinter import messagebox
            if not force and not messagebox.askyesno("关闭启动器", "AIoT 正在启动或运行，停止 AIoT 并退出启动器？", parent=self.root):
                self.audit("close-cancelled")
                return
            if self.destroyed or self.closing:
                return
            self.closing = True
            if self.busy:
                if not self.stop(reason=reason):
                    self.closing = False
                    self.report_error('暂未退出', {'error': '停止操作尚未就绪，请稍后重试。'})
            else:
                self.destroy()  # AIoT can exit while the confirmation dialog is open.
        else:
            self.destroy()

    def destroy(self):
        if self.destroyed:
            return
        if self.config_busy:
            self.closing = True
            return
        self.destroyed = True
        self.audit("window-destroyed")
        if self.status_monitor is not None:
            self.status_monitor.close()
        if self.results_panel is not None:
            self.results_panel.shutdown()
        self.progress.stop()
        self.status.trace_remove("write", self.status_trace)
        self.root.after_cancel(self.poll_id)
        self.root.destroy()


def main(argv=None):
    set_process_role("gui")
    parser = argparse.ArgumentParser(description="2026金砖赛事-物联传感技术应用")
    parser.add_argument("--publish-dir", help="临时指定部署目录；窗口不显示目录")
    parser.add_argument("--settings-file", help="安装器指定的部署设置文件")
    parser.add_argument('--version', action='version', version=LAUNCHER_VERSION)
    parser.add_argument('--doctor', action='store_true', help='检查安装与图形会话')
    args = parser.parse_args(argv)
    if args.doctor:
        return doctor(args.publish_dir, args.settings_file)
    from single_instance import SingleInstance
    instance = SingleInstance(config_directory() / "instance")
    try:
        if not instance.start_or_activate():
            message = ("启动器已在运行，已请求唤起现有窗口。DISPLAY={}".format(instance.existing_display)
                       if instance.activation_succeeded else "启动器已在运行，暂时无法发送唤起请求，请稍后再次打开。")
            print(message, flush=True)
            return 0
        return run_window(args, instance)
    except (OSError, SyncError) as exc:
        print("无法启动启动器：" + str(exc), file=sys.stderr)
        return 1
    finally:
        instance.close()


def run_window(args, instance):
    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError:
        print("缺少 Tkinter，请先运行 bash install-launcher.sh。", file=sys.stderr)
        return 1
    try:
        root = tk.Tk(className="Aiotlauncher")
    except tk.TclError as exc:
        print("需要可用的图形桌面：" + str(exc), file=sys.stderr)
        return 1
    try:
        settings = load_settings(args.settings_file)
        if args.publish_dir:
            settings["publish_dir"] = args.publish_dir
        controller = LauncherController(settings["publish_dir"])
    except (ValueError, OSError, SyncError) as exc:
        root.withdraw()
        messagebox.showerror("部署配置错误", str(exc), parent=root)
        root.destroy()
        return 1
    try:
        from status_monitor import ProcessStatusMonitor
        monitor = ProcessStatusMonitor(settings['publish_dir'])
        ui = LauncherWindow(root, controller, settings=settings, settings_path=args.settings_file, instance=instance,
                            status_monitor=monitor)
    except SyncError as exc:
        print(str(exc), file=sys.stderr)
        root.withdraw()
        messagebox.showerror("图片组件错误", str(exc), parent=root)
        root.destroy()
        return 1
    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGHUP", signal.SIGTERM)):
        if sig not in previous:
            previous[sig] = signal.signal(sig, lambda number, frame: ui.close(force=True, reason="signal:{}".format(number)))
    try:
        root.mainloop()
    finally:
        controller.request_stop()
        if controller.thread is not None:
            controller.thread.join()
        if ui.config_controller.thread is not None:
            ui.config_controller.thread.join()
        if ui.external_stop_controller.thread is not None:
            ui.external_stop_controller.thread.join()
        monitor.close()
        monitor.wait()
        if ui.results_panel is not None:
            ui.results_panel.wait()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
