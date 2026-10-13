#!/usr/bin/env python3
import os
import subprocess
import stat

def create_aiot_shortcut():
    """
    为AIOT应用创建Ubuntu快捷方式，并确保可执行文件有正确权限
    """
    # 基础路径设置
    publish_dir = "/home/ubuntu/linux-arm64/publish"
    
    # 定义关键文件路径
    start_app = os.path.join(publish_dir, "StartApp.sh")
    icon_file = os.path.join(publish_dir, "logo_AIoT.png")
    
    # 目标目录（用户级应用目录）
    desktop_dir = os.path.expanduser("/home/ztl/桌面")
    desktop_file = os.path.join(desktop_dir, "AIOT.desktop")
    
    # 确保目录存在
    os.makedirs(desktop_dir, exist_ok=True)
    
    # 验证关键文件是否存在
    missing_files = []
    if not os.path.exists(start_app):
        missing_files.append(f"可执行文件: {start_app}")
    if not os.path.exists(icon_file):
        missing_files.append(f"图标文件: {icon_file}")
    
    if missing_files:
        print("错误: 以下文件不存在，请检查路径:")
        for f in missing_files:
            print(f"  - {f}")
        print("请确保软件已正确安装在指定位置")
        return False
    
    # 1. 确保StartApp.sh有执行权限
    try:
        current_permissions = os.stat(start_app).st_mode
        if not (current_permissions & stat.S_IXUSR):
            print(f"为可执行文件添加权限: {start_app}")
            os.chmod(start_app, current_permissions | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except Exception as e:
        print(f"警告: 无法设置执行权限: {str(e)}")
        print("请手动运行: chmod +x /home/ubuntu/linux_arm64/publish/StartApp.sh")
    
    # 2. 创建.desktop文件内容
    desktop_content = f"""[Desktop Entry]
Name=AIOT
Exec={start_app}
Icon={icon_file}
Type=Application
Terminal=true
Categories=Application;
StartupNotify=false
"""
    
    # 3. 写入并设置快捷方式文件
    try:
        with open(desktop_file, "w") as f:
            f.write(desktop_content)
        
        # 设置快捷方式权限
        os.chmod(desktop_file, 0o755)
        print(f"成功创建快捷方式: {desktop_file}")
        
        # 4. 尝试刷新桌面数据库
        try:
            subprocess.run(["update-desktop-database", desktop_dir], check=True)
            print("桌面数据库已刷新")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("提示: 需要手动刷新桌面数据库或重启系统")
        
        # 5. 验证快捷方式
        print("\n验证步骤:")
        print(f"1. 检查文件权限: ls -l {start_app}")
        print(f"2. 尝试运行应用: {start_app}")
        print("3. 在应用程序菜单中搜索 'AIOT'")
        print("4. 或通过命令行启动: gtk-launch AIOT")
        
        return True
    except Exception as e:
        print(f"创建快捷方式失败: {str(e)}")
        return False

if __name__ == "__main__":
    create_aiot_shortcut()
