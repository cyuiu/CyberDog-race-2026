# macOS CyberDog 工具

macOS 版本，功能与 `tools/`（PowerShell）等价。

## 使用方式

```bash
# 首次配置
cp tools_mac/config.example.sh tools_mac/config.sh
# 编辑 config.sh 填入真实 IP
./tools_mac/setup_ssh_key.sh

# 日常使用
./tools_mac/push_to_dog.sh -a
./tools_mac/run_on_dog.sh -s manual_tests/check_status.py -p
./tools_mac/start_camera_view.sh -p
```

## 与 PowerShell 版的区别

- macOS 原生支持 ssh/scp，无需额外安装
- SSH 配置写入 host `cyberdog-mac`（Windows 版为 `cyberdog-win`）
- 浏览器用 `open` 命令打开
