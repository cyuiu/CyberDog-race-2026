# CyberDog2 校园机器人跑酷赛 — 2026

基于 [小米 CyberDog 2](https://github.com/XiaoMiRobots/cyberdog_bringup) 的校园跑酷赛项目。Windows 负责写代码和远程推送，ROS2 / Python 程序在机器狗 NX 端运行。

---

## 开发流程

```
Windows (PowerShell)          CyberDog2 (Ubuntu / ROS2)
─────────────────────         ──────────────────────────
tools/config.ps1              SSH 免密连接
tools/push_to_dog.ps1   ──>   /home/mi/cyberdog_course/program/
tools/run_on_dog.ps1    ──>   source ROS2 环境 -> python3 <脚本>
tools/start_camera_view.ps1   SSH 隧道 + 浏览器预览
```

不要在 Windows 本机直接运行 `program/` 下依赖 ROS2 的脚本。

---

## 目录说明

### `program/` — 机器狗端程序

所有 Python/Shell 代码，推送到狗端后运行。

| 子目录 | 说明 |
|--------|------|
| `core/` | 基础控制模块：运动状态读写（`cyberdog_base.py`）、步态参数（`cyberdog_gaits.py`）、动作指令（`cyberdog_actions.py`）、交互控制台（`cyberdog_console.py`） |
| `perception/` | 视觉感知：RGB 相机（`cyberdog_camera.py`）、鱼眼相机（`cyberdog_fisheye.py`）、相机预览（`camera_view.py`）、球体检测（`ball_detect2.py`） |
| `stages/` | 赛段逻辑：六关状态机，从石板路低速通过到隧道、独木桥等 |
| `manual_tests/` | 手动测试脚本：站立（`stand1.py`）、趴下（`down1.py`）、状态检查（`check_status.py`） |
| `set_demo/` | 亚稳态步态演示：crouch gait 参数 TOML + stand/crouch 切换脚本 |

### `tools/` — Windows 端工具

PowerShell 脚本，负责连接、同步、远程启动。详见 [`tools/README.md`](tools/README.md)。

| 脚本 | 用途 |
|------|------|
| `config.ps1` | 机器狗 IP 和目录配置（从 `config.example.ps1` 复制，不入 Git） |
| `connect_dog.ps1` | 检查 SSH 连接 / 打开交互式 SSH |
| `setup_ssh_key.ps1` | 配置 Windows → 机器狗免密 SSH |
| `push_to_dog.ps1` | 同步 `.py` / `.sh` 到狗端，支持单文件或全量推送 |
| `run_on_dog.ps1` | 远程运行狗端 Python 脚本，自动加载 ROS2 环境 |
| `start_camera_view.ps1` | 建立 SSH 隧道，启动狗端相机服务，浏览器查看画面 |

### `robot_runtime/` — 狗端运行时文件

推送到机器狗的扁平化文件副本，包含核心模块和启动脚本。

### `docs/` — 项目文档

| 文件 | 说明 |
|------|------|
| [`CYBERDOG_HARDWARE_PROBE.md`](docs/CYBERDOG_HARDWARE_PROBE.md) | CyberDog 2 硬件探测报告（处理器、IMU、相机、UWB 等） |
| [`AI_CYBERDOG_DEVELOPMENT_GUIDE.md`](docs/AI_CYBERDOG_DEVELOPMENT_GUIDE.md) | AI 开发指南：感知、运动、交互、安全开发流程 |
| [`RACE_RULES_CORRECTED.md`](docs/RACE_RULES_CORRECTED.md) | 校园跑酷赛比赛规则（赛段划分、评分标准） |
| [`development_notes.md`](docs/development_notes.md) | 开发记录：工作区迁移、已验证链路、技术债、后续优先级 |

### `blogs-rolling/` — CyberDog 官方文档

官方中文开发文档，覆盖各子系统（感知、运动、通信、AI 等）。详见 [`blogs-rolling/docs/cn/`](blogs-rolling/docs/cn/)。

### `legacy/` — 归档

已废弃的 Ubuntu 端工具脚本（`connect_dog.sh`、`push_to_dog.sh`、`start_camera_view.sh`）。

---

## 比赛赛段

详见 [`RACE_RULES_CORRECTED.md`](docs/RACE_RULES_CORRECTED.md)。

开发优先级：**先能安全停，再能低速动，再能感知，再能完成单关，最后串联全赛道。**

---

## 快速上手

```powershell
# 1. 配置机器狗地址
Copy-Item .\tools\config.example.ps1 .\tools\config.ps1
# 编辑 config.ps1 填入真实 IP

# 2. 首次配置免密 SSH
.\tools\setup_ssh_key.ps1

# 3. 推送代码到狗端
.\tools\push_to_dog.ps1 -All

# 4. 远程运行脚本
.\tools\run_on_dog.ps1 -Script manual_tests/check_status.py -PushFirst

# 5. 查看相机画面
.\tools\start_camera_view.ps1 -PushFirst
```

### 不用工具，手动操作

如果不使用 `tools/` 脚本，可以直接用 SSH / SCP 手动完成：

```bash
# 将机器狗 IP 替换为实际地址，下同
DOG_IP=<机器狗IP>

# 1. 首次连接，配置免密 SSH（后续可跳过）
ssh-copy-id mi@$DOG_IP

# 2. 推送代码到狗端
scp -r program/core program/perception program/manual_tests \
    mi@$DOG_IP:~/cyberdog_course/program/

# 3. SSH 登录狗端
ssh mi@$DOG_IP

# 4. 在狗端加载 ROS2 环境并运行脚本
source /opt/ros2/galactic/setup.bash
source /opt/ros2/cyberdog/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///etc/mi/cyclonedds.xml
export ROS_DOMAIN_ID=42

cd ~/cyberdog_course/program
python3 manual_tests/check_status.py

# 5. 查看相机画面（另开一个终端）
# 建立 SSH 隧道，将狗端 8080 端口映射到本地
ssh -L 8080:localhost:8080 mi@$DOG_IP

# 在狗端启动相机服务（SSH 登录后执行）
cd ~/cyberdog_course/program
./run_camera_view.sh
# 浏览器打开 http://localhost:8080
```

> **提示**：`tools/` 脚本本质上就是封装了上述 SSH/SCP 命令 + ROS2 环境变量设置，省去每次手动输入。

---

## 致谢

- [小米 CyberDog 开源社区](https://github.com/XiaoMiRobots)
- 2026 年校园机器人跑酷赛组委会
