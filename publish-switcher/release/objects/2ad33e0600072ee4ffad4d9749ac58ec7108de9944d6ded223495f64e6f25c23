"""用户「程序更新」页。

显示版本与通道，一键更新工具与 publish；详情与离线导入留给工程师。
"""
import json
import threading
import time
from tkinter import filedialog, messagebox, ttk
from publish_switcher.common.errors import SyncError
from publish_switcher.common.settings import save_settings
from publish_switcher.gui.widgets.reference import VersionBanner
from publish_switcher.version import VERSION
from publish_switcher.updates.channels import channel_name, selected_channel
from publish_switcher.updates import release as tool_update
from publish_switcher.updates import unified as unified_update


class ProgramPage:
    def __init__(self, application):
        self.application = application
        self.channel_picker = None

    def build_program_page(self):
        page = self.application.program_page
        page.columnconfigure(0, weight=1)
        self.version_banner = VersionBanner(page, VERSION, self.application.font_family)
        self.version_banner.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        channel_row = ttk.Frame(page)
        channel_row.grid(row=1, column=0, sticky="w")
        ttk.Label(channel_row, text="通道", style="Section.TLabel").pack(side="left", padx=(4, 10))
        self.channel_frame = ttk.Frame(channel_row)
        self.channel_frame.pack(side="left")
        self.program_check_button = ttk.Button(channel_row, text="更新", style="Primary.TButton",
                                               command=self.start_quick_update)
        self.program_check_button.pack(side="left", padx=(12, 0))
        self.refresh_update_channels()
        self.program_status_label = ttk.Label(page, textvariable=self.program_status, wraplength=650)
        self.program_status_label.grid(row=2, column=0, sticky="w", pady=8)
        actions = ttk.Frame(page)
        actions.grid(row=3, column=0, sticky="w")
        self.program_details_button = ttk.Button(actions, text="详情", command=self.toggle_program_notes)
        self.program_details_button.pack(side="left")
        self.program_apply_button = ttk.Button(actions, text="更新并重启", style="Primary.TButton",
                                                command=self.apply_program_update, state="disabled")
        self.program_apply_button.pack(side="left", padx=8)
        self.program_offline_button = ttk.Button(actions, text="导入离线更新", command=self.import_program_update)
        self.program_offline_button.pack(side="left")
        self.application.engineer_widgets.extend([self.program_status_label, self.program_details_button,
                                     self.program_apply_button, self.program_offline_button])
        self.program_notes_label = ttk.Label(page, textvariable=self.program_notes, wraplength=650, style="Muted.TLabel", justify="left")
        self.program_notes_label.grid(row=4, column=0, sticky="nw", pady=12)
        self.program_notes_label.grid_remove()


    def toggle_program_notes(self):
        if not self.application.engineer_mode:
            return
        self.program_notes_open = not self.program_notes_open
        self.program_notes_label.grid() if self.program_notes_open else self.program_notes_label.grid_remove()
        self.program_details_button.configure(text="收起详情" if self.program_notes_open else "详情")


    def refresh_update_channels(self):
        if not self.application.updates_enabled or not hasattr(self, "channel_frame"):
            return
        rows = self.application.settings_view.repository_list()
        if self.channel_snapshot == rows:
            return
        self.channel_snapshot = rows
        self.application.update_channel.set(0)
        if hasattr(self, "version_banner"):
            self.version_banner.set_state("idle", "—")
        self.application.program_checked = False
        self.program_release = None
        for button in self.channel_buttons:
            button.destroy()
        self.channel_buttons = []
        if self.channel_picker is not None:
            self.channel_picker.destroy()
            self.channel_picker = None
        if len(rows) > 4:
            self.channel_picker = ttk.Combobox(self.channel_frame, values=[channel_name(i) for i in range(len(rows))],
                                               state="readonly", width=10)
            self.channel_picker.current(0)
            self.channel_picker.pack()
            self.channel_picker.bind("<<ComboboxSelected>>", self.pick_channel)
        else:
            for index in range(len(rows)):
                button = ttk.Radiobutton(self.channel_frame, text=channel_name(index), style="Channel.TRadiobutton",
                                         variable=self.application.update_channel, value=index, command=self.change_update_channel)
                button.grid(row=0, column=index, padx=(4 if index else 0, 0))
                self.channel_buttons.append(button)
        self.update_channel_controls()

    def pick_channel(self, event):
        if not self.application.busy:
            self.application.update_channel.set(event.widget.current())
            self.change_update_channel()

    def update_channel_controls(self):
        for button in self.channel_buttons:
            button.configure(state="disabled" if self.application.busy else "normal")
        if self.channel_picker is not None:
            self.channel_picker.configure(state="disabled" if self.application.busy else "readonly")


    def program_channel(self):
        return selected_channel(self.application.settings_view.repository_list(), self.application.update_channel.get(), self.application.program_source.get().strip())


    def change_update_channel(self):
        if self.application.busy:
            return
        self.program_auto_enter = False
        self.application.program_checked = False
        self.program_release = None
        self.program_version_text.set("v" + VERSION)
        self.program_notes.set("")
        self.program_status.set("检查中…")
        self.version_banner.set_state("checking", self.channel_check_times.get(self.program_channel()[1], "—"))
        self.application.configure_access()
        self.application.update_ready()
        self.check_program_update()


    def save_program_source(self):
        if self.application.busy:
            return
        try:
            address = tool_update.https_url(self.application.program_source.get())
            save_settings(self.application.settings_file, {"program_update_url": address})
        except (ValueError, OSError, tool_update.UpdateError) as exc:
            messagebox.showerror("更新源未保存", str(exc))
            return
        self.application.program_source.set(address)
        self.application.program_checked = False
        self.program_release = None
        self.program_status.set("更新源已保存，请检查程序版本。")
        self.version_banner.set_state("idle", "—")
        self.application.configure_access()
        self.application.update_ready()


    def check_program_update(self):
        if getattr(self, "program_check_id", None):
            self.application.root.after_cancel(self.program_check_id)
            self.program_check_id = None
        if self.application.program_checking or self.application.busy:
            return
        try:
            repositories, address = self.program_channel()
        except SyncError as exc:
            self.application.program_checked = False
            self.program_release = None
            self.program_status.set("仓库列表无效，请在工程师设置中修改。")
            self.program_notes.set(str(exc))
            self.version_banner.set_state("error")
            self.application.update_ready()
            return
        self.application.program_checking = True
        self.program_status.set("检查中…")
        self.version_banner.set_state("checking", self.channel_check_times.get(address, "—"))
        def worker():
            try:
                value = tool_update.check_release(address, self.application.install_directory, VERSION, repositories=repositories)
                self.application.events.put(("program_check", (address, value, None, repositories)))
            except Exception as exc:
                self.application.logger.exception("swicher 程序版本检查失败")
                self.application.events.put(("program_check", (address, None, str(exc), repositories)))
        threading.Thread(target=worker, daemon=True).start()
        self.application.update_ready()


    def start_quick_update(self):
        if self.application.busy or self.application.program_checking:
            return
        from publish_switcher.gui.widgets.update_dialog import UpdateDialog
        if not self.application.quick_dialog or not self.application.quick_dialog.exists():
            self.application.quick_dialog = UpdateDialog(self.application)
        self.application.quick_dialog.begin()
        self.application.quick_committing.clear()
        try:
            repositories, address = self.program_channel()
            values = dict(install=self.application.install_directory, current=VERSION, target=self.application.target.get().strip(),
                          repositories=repositories, presets=json.loads(json.dumps(self.application.presets)),
                          extensions=list(self.application.file_extensions), release_url=address,
                          profile_id=self.application.quick_profile.get().strip(), sync_permissions=self.application.sync_permissions.get(),
                          cancel=self.application.cancel, settings_path=self.application.settings_file,
                          allow_missing_target=True)
        except Exception as exc:
            result = dict(success=False, publish="未更新", program="未更新", error=str(exc))
            self.application.quick_dialog.update(dict(message=str(exc), cancellable=False))
            self.application.quick_dialog.finish(result)
            return

        def event(value):
            if not value.get("cancellable", True):
                self.application.quick_committing.set()
            self.application.events.put(("quick_progress", value))

        self.application.run(lambda: unified_update.run_update(event=event, **values), self.quick_update_finished,
                 cancellable=False, system_update=True)


    def quick_update_finished(self, result):
        self.application.last_error = not result["success"]
        self.application.quick_dialog.finish(result)
        self.application.status.set("更新完成。" if result["success"] else "更新未完成：" + result.get("error", "请查看日志"))
        if result.get("target"):
            self.application.target.set(result["target"])
        self.application.checked = None
        self.application.config_view.config_preview = None
        self.application.assets_view.invalidate_assets()
        if "program_update_required" in result:
            self.application.program_checked = not result["program_update_required"]
            self.application.configure_access()
            checked_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(result.get("program_checked_at", time.time())))
            self.channel_check_times[self.program_channel()[1]] = checked_at
            self.version_banner.set_state("update" if result["program_update_required"] else "current", checked_at)
        if result.get("restart"):
            try:
                unified_update.start_restart(self.application.install_directory, result, self.application.engineer_mode)
            except Exception as exc:
                self.application.logger.exception("一键更新助手启动失败")
                self.application.quick_dialog.update(dict(message=str(exc), cancellable=False))
                self.application.quick_dialog.finish(result)
            else:
                self.application.root.after_idle(self.application.root.destroy)
                return
        if result["success"]:
            self.application.program_checked = True
            self.program_release = None
            self.program_status.set("已更新")
            self.application.configure_access()
            # Save/read cache and refresh config/Demo through the existing connection path.
            if not result.get("publish_skipped"):
                self.application.root.after_idle(lambda: self.application.connect(updated=True))


    def program_check_finished(self, data):
        address, value, error = data[:3]
        self.application.program_checking = False
        try:
            repositories, current_address = self.program_channel()
        except SyncError as exc:
            self.application.program_checked = False
            self.program_release = None
            self.program_status.set("通道无效，请检查设置。")
            self.program_notes.set(str(exc))
            self.version_banner.set_state("error")
            self.application.configure_access()
            self.application.update_ready()
            return
        if (len(data) > 3 and data[3] != repositories) or address != current_address:
            self.application.program_checked = False
            self.program_release = None
            self.check_program_update()
            return
        if error:
            self.program_status.set("检查失败，可换通道重试。")
            self.program_notes.set(error)
            self.application.program_checked = False
            self.version_banner.set_state("error")
        else:
            release, newer = value
            self.application.program_checked = not newer
            self.program_release = release if newer else None
            self.program_notes.set(release["notes"])
            checked_at = time.strftime("%Y-%m-%d %H:%M:%S")
            self.channel_check_times[address] = checked_at
            self.version_banner.set_state("update" if newer else "current", checked_at)
            if newer:
                self.program_version_text.set("v{} → v{}".format(VERSION, release["version"]))
                self.program_status.set("有新版本")
            else:
                self.program_status.set("已是最新版本")
        previous_error = unified_update.last_helper_error(self.application.install_directory)
        if previous_error:
            self.program_notes.set(previous_error + "\n\n" + self.program_notes.get())
        self.application.configure_access()
        self.application.update_ready()
        if self.application.program_checked:
            self.program_ready(enter=self.program_auto_enter)


    def program_ready(self, enter=True):
        self.application.configure_access()
        if self.application.target.get():
            if not self.application.engine:
                self.application.connect()
            if not self.application.engineer_mode and enter:
                self.application.pages.select(self.application.config_page)
        elif not self.application.engineer_mode:
            self.program_status.set("请联系工程师设置设备。")


    def apply_program_update(self):
        if not self.program_release or self.application.busy:
            return
        release = dict(self.program_release)
        self.program_status.set("正在下载、校验并准备新版程序…")
        count = [0]
        total = [release["size"]]

        def plan(size):
            total[0] = size

        def reset():
            count[0] = 0

        def progress(size):
            count[0] += size
            self.application.events.put(("log", "程序下载 {:.1f} / {:.1f} MiB".format(count[0] / 2**20, total[0] / 2**20)))
        self.application.run(lambda: tool_update.prepare_online(self.application.install_directory, release, VERSION, self.application.cancel, progress,
                                                              on_attempt=reset, on_plan=plan),
                 self.program_prepared, system_update=True)


    def import_program_update(self):
        if self.application.busy:
            return
        selected = filedialog.askopenfilename(parent=self.application.root, title="选择与安装包放在一起的 switcher-update.json",
                                              filetypes=[("程序发布信息", "*.json")])
        if not selected:
            return
        def work():
            release = tool_update.validate_release(tool_update.read_json(selected))
            record = tool_update.prepare_offline(self.application.install_directory, selected, VERSION)
            return release, record
        def done(result):
            release, record = result
            if tool_update.version_number(release["version"]) == tool_update.version_number(VERSION):
                tool_update.recover_update(self.application.install_directory)
                self.program_release = None
                self.application.program_checked = True
                self.program_status.set("已通过离线安装包验证当前版本，可以使用。")
                self.program_ready()
            else:
                self.program_prepared(record)
        self.application.run(work, done, system_update=True)


    def program_prepared(self, record):
        try:
            tool_update.launch_update_helper(self.application.install_directory, self.application.engineer_mode)
        except Exception as exc:
            tool_update.recover_update(self.application.install_directory)
            messagebox.showerror("更新助手未启动", str(exc))
            return
        self.application.root.destroy()
