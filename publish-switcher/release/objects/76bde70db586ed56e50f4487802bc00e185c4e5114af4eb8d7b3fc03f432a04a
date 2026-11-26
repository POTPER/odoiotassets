"""版本显示设置编辑器。

工程师编辑前缀隐藏规则、显示名、排序与可选元数据，写入 versions.json。
"""
import tkinter as tk
from tkinter import messagebox, ttk

from publish_switcher.configuration.visibility import read_policy, resolve_version, save_policy, validate_policy, METADATA_FIELDS
from publish_switcher.gui.widgets.style import style_dialog


def show_visibility_editor(parent, engine, saved):
    policy, snapshot = read_policy(engine)
    versions = [item["version"] for item in engine.list_config_versions()]
    window = tk.Toplevel(parent)
    style_dialog(window)
    window.title("配置版本显示设置")
    window.geometry("860x{}".format(min(720, max(620, parent.winfo_screenheight()-100))))
    window.minsize(680, 620)
    window.transient(parent)
    window.grab_set()
    buttons = ttk.Frame(window, padding=10)
    buttons.pack(side="bottom", fill="x")
    pages = ttk.Notebook(window)
    pages.pack(fill="both", expand=True, padx=10, pady=10)
    rules_page, versions_page = ttk.Frame(pages, padding=8), ttk.Frame(pages, padding=8)
    pages.add(rules_page, text="前缀规则")
    pages.add(versions_page, text="目录单独设置")
    default = tk.BooleanVar(value=policy["default_user_visible"])
    ttk.Checkbutton(rules_page, text="未命中任何规则时，对用户可见", variable=default).pack(anchor="w")
    ttk.Label(rules_page, text="优先级：目录单独设置 → 以下首条匹配规则 → 内置 . / F 隐藏 → 默认可见性。\n前缀区分大小写；可添加“用户可见”规则或单独开放目录，覆盖内置隐藏规则。",
              wraplength=650).pack(anchor="w", pady=8)
    rule_tree = ttk.Treeview(rules_page, columns=("prefix", "visible"), show="headings", height=7)
    rule_tree.heading("prefix", text="目录名前缀")
    rule_tree.heading("visible", text="用户可见性")
    rule_tree.pack(fill="both", expand=True)
    rule_inputs = ttk.Frame(rules_page)
    rule_inputs.pack(fill="x", pady=8)
    prefix = tk.StringVar(value="F")
    rule_visibility = tk.StringVar(value="仅工程师")
    ttk.Entry(rule_inputs, textvariable=prefix, width=16).pack(side="left")
    ttk.Combobox(rule_inputs, textvariable=rule_visibility, values=("仅工程师", "用户可见"),
                 state="readonly", width=12).pack(side="left", padx=6)
    rule_list = list(policy["rules"])

    table = ttk.Treeview(versions_page, columns=("folder", "name", "visible", "order"), show="headings", height=7)
    for key, text, width in (("folder", "实际目录", 230), ("name", "用户显示名称", 200),
                             ("visible", "用户可见性", 110), ("order", "顺序", 60)):
        table.heading(key, text=text)
        table.column(key, width=width, minwidth=55, stretch=key in ("folder", "name"))
    table.pack(fill="both", expand=True)
    form = ttk.Frame(versions_page)
    form.pack(fill="x", pady=10)
    form.columnconfigure(1, weight=1)
    visibility = tk.StringVar(value="跟随规则")
    alias, order = tk.StringVar(), tk.StringVar(value="0")
    metadata = {field: tk.StringVar() for field in METADATA_FIELDS}
    for row, text in enumerate(("用户可见性", "显示名称", "顺序")):
        ttk.Label(form, text=text).grid(row=row, column=0, sticky="w", pady=4)
    ttk.Combobox(form, textvariable=visibility, values=("跟随规则", "用户可见", "仅工程师"),
                 state="readonly", width=16).grid(row=0, column=1, sticky="w")
    ttk.Entry(form, textvariable=alias).grid(row=1, column=1, sticky="ew")
    ttk.Spinbox(form, from_=-10000, to=10000, textvariable=order, width=12).grid(row=2, column=1, sticky="w")
    for row, (field, label) in enumerate((("release_version", "版本号"), ("updated_at", "更新时间"), ("description", "说明")), 3):
        ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=metadata[field]).grid(row=row, column=1, sticky="ew")
    ttk.Label(versions_page, text="选择目录后编辑，点“应用到此目录”。显示名称留空时使用目录名。顺序数字越小越靠前。",
              wraplength=650).pack(anchor="w", pady=(0, 6))
    status = tk.StringVar(value="保存到 " + str(engine.target / "config/versions.json"))
    ttk.Label(buttons, textvariable=status, wraplength=460).pack(side="left")

    def candidate():
        return validate_policy(dict(policy, default_user_visible=default.get(), rules=rule_list))

    def refresh():
        selected = table.selection()
        table.delete(*table.get_children())
        value = candidate()
        for name in versions:
            options = resolve_version(value, name)
            table.insert("", "end", iid=name, values=(name, options["display_name"],
                         "用户可见" if options["user_visible"] else "仅工程师", options["order"]))
        if selected and table.exists(selected[0]):
            table.selection_set(selected[0])
        rule_tree.delete(*rule_tree.get_children())
        for index, item in enumerate(rule_list):
            rule_tree.insert("", "end", iid=str(index),
                             values=(item["prefix"], "用户可见" if item["user_visible"] else "仅工程师"))

    def add_rule():
        item = {"prefix": prefix.get(), "user_visible": rule_visibility.get() == "用户可见"}
        try:
            validate_policy(dict(candidate(), rules=rule_list + [item]))
        except Exception as exc:
            messagebox.showerror("规则无效", str(exc), parent=window)
            return
        rule_list.append(item)
        refresh()

    def remove_rule():
        selected = rule_tree.selection()
        if selected:
            rule_list.pop(int(selected[0]))
            refresh()

    def move_rule(direction):
        selected = rule_tree.selection()
        if selected:
            index = int(selected[0])
            destination = index + direction
            if 0 <= destination < len(rule_list):
                rule_list[index], rule_list[destination] = rule_list[destination], rule_list[index]
                refresh()
                rule_tree.selection_set(str(destination))

    def select_version(event=None):
        selected = table.selection()
        if selected:
            name = selected[0]
            options = policy["versions"].get(name, {})
            value = options.get("user_visible")
            visibility.set("跟随规则" if value is None else "用户可见" if value else "仅工程师")
            alias.set(options.get("display_name", ""))
            order.set(str(options.get("order", 0)))
            for field, variable in metadata.items():
                variable.set(options.get(field, ""))

    def apply_version():
        selected = table.selection()
        if not selected:
            return
        try:
            options = {"order": int(order.get())}
            if visibility.get() != "跟随规则":
                options["user_visible"] = visibility.get() == "用户可见"
            if alias.get().strip():
                options["display_name"] = alias.get().strip()
            options.update({field: variable.get().strip() for field, variable in metadata.items() if variable.get().strip()})
            validate_policy(dict(candidate(), versions=dict(policy["versions"], **{selected[0]: options})))
            policy["versions"][selected[0]] = options
            refresh()
            status.set("已应用到此目录，请点“保存全部设置”写入文件。")
        except Exception as exc:
            messagebox.showerror("设置无效", str(exc), parent=window)

    def save():
        try:
            save_policy(engine, candidate(), snapshot)
        except Exception as exc:
            messagebox.showerror("显示设置未保存", str(exc), parent=window)
            return
        window.destroy()
        saved()

    ttk.Button(rule_inputs, text="添加", command=add_rule).pack(side="left")
    ttk.Button(rule_inputs, text="删除", command=remove_rule).pack(side="left", padx=6)
    ttk.Button(rule_inputs, text="上移", command=lambda: move_rule(-1)).pack(side="left")
    ttk.Button(rule_inputs, text="下移", command=lambda: move_rule(1)).pack(side="left", padx=6)
    ttk.Button(form, text="应用到此目录", command=apply_version).grid(row=0, column=2, rowspan=3, padx=10)
    ttk.Button(buttons, text="保存全部设置", command=save).pack(side="right")
    ttk.Button(buttons, text="取消", command=window.destroy).pack(side="right", padx=8)
    default.trace_add("write", lambda *args: refresh())
    window.metadata_fields = metadata
    window.version_table = table
    table.bind("<<TreeviewSelect>>", select_version)
    refresh()
    return window
