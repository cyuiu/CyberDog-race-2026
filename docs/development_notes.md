# Development Notes

## 初始状态

本仓库初版来自 Ubuntu VM 中的：

```text
/home/kiki/cyberdog_develop/program
```

通过 VMware 共享目录同步到 Windows 后整理入仓库。

同步时排除了：

- Python 缓存
- 日志文件
- 图像截图
- 临时文件
- 压缩归档
- 密钥类文件

## 当前主线工作区

当前主开发工作区已经迁移到：

```text
G:\Cyberdog_win
```

Windows 只作为写代码、同步文件和远程启动脚本的入口。ROS2 / CyberDog Python 程序仍在机器狗 NX 端运行。

机器狗端运行目录约定为：

```text
/home/mi/cyberdog_course/program
```

推荐远程运行方式是由 Windows 工具负责：

```text
Windows PowerShell
-> SSH/scp
-> 机器狗端 source ROS2 环境
-> 机器狗端 python3 <脚本>
```

不要在 Windows 本机直接运行 `program/` 下依赖 ROS2 / CyberDog 的 Python 脚本。

## 已确认链路

- 可以通过无线 SSH 连接 CyberDog。
- ROS2 Galactic 可用。
- 已验证 `motion_status` 状态读取。
- 已验证低风险站立动作。
- 已验证相机服务、图像话题和本地/网页预览链路。
- 已有蓝球/橙球 HSV 视觉检测探索脚本。

## 2026-07-08 远端脚本拉回审查

已从机器狗目录只读拉回 `.py` / `.sh` 脚本到 Windows 审查目录：

```text
G:\Cyberdog_win\dog_review\robot_pull_20260708_093658
```

审查结论：

- 机器狗端和 Windows 主线工作区中同名 `.py` / `.sh` 文件内容一致。
- 机器狗端额外存在 `run_py.sh`，这是早期交互式运行器，安全判断依赖文件名匹配，不建议作为当前主入口。
- Windows 主线工作区额外存在 `start_camera_view.sh`，更像本机 Linux/Ubuntu 辅助入口，不属于当前机器狗端 runtime 主线。
- 暂不删除远端文件；后续应先归档，再确认新版入口可用后清理。

## 当前技术债

这些问题应优先处理，因为后续六关状态机都会依赖基础安全能力：

1. `cyberdog_base.py` 的步态循环只在启动前检查 `motion_status`，运行中还需要持续检查状态，异常立即 `SERVO_END`。
2. `cyberdog_console.py` 默认菜单包含高风险和极高风险动作，应默认隐藏或锁定。
3. 远程运行工具不应只靠文件名猜测是否会运动，应改成明确白名单：纯状态检查、纯相机预览、纯视觉检测可以免确认，其余默认需要安全确认。
4. `ball_detect1.py` / `ball_detect2.py` 仍有重复相机启动逻辑，应逐步复用 `cyberdog_camera.py` 中带 STOP/重试保护的相机基础模块。
5. 公开仓库文档和本地 Windows 工作区仍需继续同步，但真实 IP、密码、日志、截图、审查拉回目录不能入仓。

## 后续优先级

1. 固化基础控制台和安全检查。
2. 只测试站立、趴下、状态读取等低风险动作。
3. 整理相机感知模块，保留可复用接口。
4. 第一赛段从石板低速通过策略开始。
5. 再进入球阵、黄线、隧道、独木桥等高复杂度赛段。

总原则：先能安全停，再能低速动，再能感知，再能完成单关，最后再串联全赛道。
