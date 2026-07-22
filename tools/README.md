# Windows CyberDog 工具

这些 PowerShell 脚本让 Windows 负责连接、同步和远程启动。Windows 不需要安装 ROS2；ROS2 程序在机器狗 NX 端运行。

## 工具说明

- `config.example.ps1`：不含真实地址的配置模板。
- `config.ps1`：本地机器狗地址和目录配置，不提交到 Git。
- `connect_dog.ps1`：检查连接或打开交互式 SSH。
- `setup_ssh_key.ps1`：配置 Windows 到机器狗的免密 SSH。
- `push_to_dog.ps1`：递归同步 `.py` / `.sh`，保留 `core`、`perception` 等子目录。
- `run_on_dog.ps1`：加载狗端 ROS2 环境并运行指定 Python 脚本。
- `start_camera_view.ps1`：建立 SSH 隧道、启动狗端相机服务并打开浏览器。

## 常用命令

```powershell
Copy-Item .\tools\config.example.ps1 .\tools\config.ps1
.\tools\connect_dog.ps1
.\tools\setup_ssh_key.ps1
.\tools\push_to_dog.ps1 -Files perception/camera_view.py
.\tools\push_to_dog.ps1 -All
.\tools\run_on_dog.ps1 -Script manual_tests/check_status.py -PushFirst
.\tools\run_on_dog.ps1 -Script perception/fisheye_probe.py -PushFirst -Args "--duration","12"
.\tools\start_camera_view.ps1 -PushFirst
.\tools\start_camera_view.ps1 -Source fisheye -PushFirst
```

鱼眼默认读取 `/dev/video2` 和 `/dev/video3`，可通过 `-LeftDevice`、`-RightDevice` 覆盖。

`start_camera_view.ps1` 必须使用免密 SSH，因为 SSH 隧道和狗端相机进程会在隐藏后台进程中启动，无法交互输入密码。

## 相机调用链

```text
Windows tools/start_camera_view.ps1
  -> SSH 隧道和远程命令
  -> 狗内 program/perception/run_camera_view.sh
  -> camera_view.py
  -> RGB: cyberdog_camera.py
  -> 鱼眼: cyberdog_fisheye.py -> /dev/video2 + /dev/video3
```

旧的 Ubuntu 主机端 `connect_dog.sh`、`push_to_dog.sh` 和 `start_camera_view.sh` 已归档到 `legacy/ubuntu_tools/`，不属于当前 Windows 主流程。
