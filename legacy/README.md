# Legacy

这里保存旧环境脚本和停用实验，仅用于追溯，不属于当前 Windows 主流程，也不会被 `tools/push_to_dog.ps1 -All` 同步。

- `ubuntu_tools/`：旧 Ubuntu 开发电脑上的 SSH、同步和相机启动脚本。
- `robot_tools/`：旧机器狗端交互启动脚本。
- `experiments/ball_detect1.py`：较早的球识别实验；当前待完善版本是 `program/perception/ball_detect2.py`。

旧 `push_to_dog.sh` 和 `run_py.sh` 原本位于 `SH/` 子目录，却只扫描脚本自身目录的顶层 `.py`，因此在原位置无法找到活动 Python 文件。它们被原样归档，当前请使用 `tools/` 下的 PowerShell 工具。
