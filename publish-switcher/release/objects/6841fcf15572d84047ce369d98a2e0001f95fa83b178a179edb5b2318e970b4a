"""多仓库顺序编辑器。

增删改仓库地址并逐项检测，只改设置，不触碰本地 publish 文件。
"""
import tkinter as tk
from tkinter import ttk, messagebox

from publish_switcher.common.settings import save_settings
from publish_switcher.repositories.discovery import normalize, discover
from publish_switcher.gui.widgets.style import style_dialog


def show_editor(app, settings_path):
    window = tk.Toplevel(app.root)
    style_dialog(window)
    window.title("同步仓库：按列表顺序查询")
    window.geometry("920x570")
    window.transient(app.root)
    rows = app.settings_view.repository_list()
    frame = ttk.Frame(window, padding=16)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="首个可用仓库提供方案；固定提交后不跨仓库拼接文件。", style="Title.TLabel").pack(anchor="w")
    ttk.Label(frame, text="支持 Gitee、GitHub、GitLab.com、jihulab.com 及自建 HTTPS GitLab。必须填写完整公开项目地址。", wraplength=860).pack(anchor="w", pady=8)
    table = ttk.Treeview(frame, columns=("url", "branch", "status"), show="headings", height=8, selectmode="browse")
    for key, title, width in (("url", "仓库项目地址（从上往下）", 580), ("branch", "分支", 100), ("status", "检测", 120)):
        table.heading(key, text=title)
        table.column(key, width=width)
    table.pack(fill="both", expand=True)
    controls = ttk.Frame(frame)
    controls.pack(fill="x", pady=10)
    address, branch = tk.StringVar(), tk.StringVar()
    ttk.Label(controls, text="项目地址").grid(row=0, column=0)
    ttk.Entry(controls, textvariable=address, width=72).grid(row=0, column=1, sticky="ew", padx=8)
    ttk.Label(controls, text="分支").grid(row=1, column=0, pady=8)
    ttk.Entry(controls, textvariable=branch, width=28).grid(row=1, column=1, sticky="w", padx=8)
    controls.columnconfigure(1, weight=1)
    hint = tk.StringVar(value="GitLab/极狐项目尚未提供，请在创建镜像后添加实际项目 URL；分支留空使用各仓库默认分支。")
    tk.Label(frame, textvariable=hint, wraplength=860, height=4, anchor="w", justify="left").pack(fill="x", pady=8)
    actions = ttk.Frame(frame)
    actions.pack(fill="x")

    def selected():
        value = table.selection()
        return int(value[0]) if value else None

    def render(select=None, results=None):
        table.delete(*table.get_children())
        for index, item in enumerate(rows):
            status = results[index]["status"] if results else "未检测"
            table.insert("", "end", iid=str(index), values=(item["url"], item["branch"] or "默认", status))
        if select is not None and 0 <= select < len(rows):
            table.selection_set(str(select))

    def pick(event=None):
        index = selected()
        if index is not None:
            address.set(rows[index]["url"])
            branch.set(rows[index]["branch"])
    table.bind("<<TreeviewSelect>>", pick)

    def edit(replace=False):
        if app.busy:
            return
        try:
            value = normalize([{"url": address.get(), "branch": branch.get()}])[0]
            updated = list(rows)
            index = selected() if replace else len(rows)
            if index is None:
                return
            if replace:
                updated[index] = value
            else:
                updated.append(value)
            rows[:] = normalize(updated)
            render(index)
        except Exception as exc:
            messagebox.showerror("仓库未添加", str(exc), parent=window)

    def remove():
        index = selected()
        if not app.busy and index is not None and len(rows) > 1:
            rows.pop(index)
            render(min(index, len(rows) - 1))

    def move(offset):
        index = selected()
        if not app.busy and index is not None and 0 <= index + offset < len(rows):
            rows[index], rows[index + offset] = rows[index + offset], rows[index]
            render(index + offset)

    def test():
        if app.busy:
            return
        snapshot = normalize(rows)
        hint.set("正在依次检测仓库与方案列表，只读检查，不修改 publish；可在主窗口取消。")
        def done(results):
            if rows != snapshot:
                hint.set("列表已修改，请重新检测。")
                return
            render(results=results)
            hint.set("\n".join(item["url"] + "：" + (item["error"] or "可用，提交 " + item["commit"][:12]) for item in results))
        app.run(lambda: discover(snapshot, app.presets, app.log, app.cancel, all_results=True), done)

    def save():
        if app.busy:
            return
        try:
            values = normalize(rows)
            save_settings(settings_path, {"repository_sources": values,
                                          "repo": values[0]["url"], "branch": values[0]["branch"]})
            app.repository_sources = values
            app.repo.set(values[0]["url"])
            app.branch.set(values[0]["branch"])
            app.program_view.refresh_update_channels()
            app.files_view.invalidate_check()
            if app.updates_enabled:
                app.program_checked = False
                app.program_view.program_release = None
                app.update_ready()
                if not app.program_checking:
                    app.program_view.check_program_update()
            app.status.set("仓库顺序已保存；下次刷新将依次查询。")
            window.destroy()
        except Exception as exc:
            messagebox.showerror("仓库设置未保存", str(exc), parent=window)

    for title, callback in (("添加", edit), ("更新选中", lambda: edit(True)), ("移除", remove),
                            ("上移", lambda: move(-1)), ("下移", lambda: move(1)), ("依次检测", test)):
        ttk.Button(actions, text=title, command=callback).pack(side="left", padx=(0, 6))
    ttk.Button(actions, text="保存顺序", command=save).pack(side="right")
    render(0)
