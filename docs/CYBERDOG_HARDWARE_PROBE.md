# CyberDog 2026 实体机探测报告与接口参考

更新日期：2026-07-20

本文档记录了对参赛实体机的完整探测结果，包含所有已确认可用的传感器、运动接口、话题、服务和调用方式。队友或 AI 对话可直接参考本文档进行开发，无需重复探测。

---

## 1. 机器狗连接

```text
SSH IP:       10.68.130.221
SSH 用户名:   mi
机器狗名称:   mi-desktop
```

连接命令：

```bash
ssh mi@10.68.130.221
```

传输文件：

```bash
scp your_script.py mi@10.68.130.221:/home/mi/cyberdog_course/program/
```

---

## 2. ROS 2 环境配置

每次 SSH 登录后、运行任何 ROS 2 命令前，必须先加载环境：

```bash
set +u
source /opt/ros2/galactic/setup.bash
source /opt/ros2/cyberdog/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///etc/mi/cyclonedds.xml
export ROS_DOMAIN_ID=42
export ROS_LOCALHOST_ONLY=0
```

注意：`source` 时可能报 `libg2o` 的 warning，不影响使用。

```text
操作系统:    Ubuntu 18.04.5 LTS
架构:        aarch64 / NVIDIA Jetson
ROS 2 版本:  Galactic
DDS:         Cyclone DDS
ROS_DOMAIN_ID: 42
```

---

## 3. 已确认可用的话题和服务总览

### 3.1 运动控制

| 话题/服务 | 类型 | 用途 |
|-----------|------|------|
| `/custom_namespace/motion_status` | `protocol/msg/MotionStatus` | 订阅：运动状态（安全检查） |
| `/custom_namespace/motion_result_cmd` | `protocol/srv/MotionResultCmd` | 调用：一次性动作（站立、趴下、跳跃） |
| `/custom_namespace/motion_servo_cmd` | `protocol/msg/MotionServoCmd` | 发布：连续步态（前进、后退、转向） |

### 3.2 视觉/相机

| 话题/服务 | 类型 | 用途 |
|-----------|------|------|
| `/mi_desktop_48_b0_2d_7b_05_1d/camera_service` | `protocol/srv/CameraService` | 调用：启动/停止 RGB 相机 |
| `/custom_namespace/camera_service` | `protocol/srv/CameraService` | 同上（别名，均可使用） |
| `/custom_namespace/image` | `sensor_msgs/msg/Image` | 订阅：RGB 图像 640x480 bgr8 |

### 3.3 激光雷达

| 话题 | 类型 | 用途 |
|------|------|------|
| `/custom_namespace/scan` | `sensor_msgs/msg/LaserScan` | 订阅：2D 激光扫描 |

### 3.4 鱼眼/立体相机（通过 V4L2 直接采集，不走 ROS）

| 组件 | 方式 | 状态 |
|------|------|------|
| `/dev/video2` (左 OV9782) | V4L2 直接采集 | **可用** |
| `/dev/video3` (右 OV9782) | V4L2 直接采集 | **可用** |
| `CyberDogFisheyeCamera` 类 | Python V4L2 双摄并发 | **可用** |
| `stereo_camera` ROS 节点 | lifecycle 激活 | 不使用（无帧/卡死） |

### 3.5 3D 点云（当前不可用）

| 话题 | 状态 |
|------|------|
| `/mi_desktop_48_b0_2d_7b_05_1d/ground_point_cloud` | 无数据 |
| `/mi_desktop_48_b0_2d_7b_05_1d/non_ground_point_cloud` | 无数据 |
| `/mi_desktop_48_b0_2d_7b_05_1d/camera/depth/color/points` | 无数据 |

---

## 4. 运动控制详解

### 4.1 一次性动作（MotionResultCmd 服务）

通过调用 `/custom_namespace/motion_result_cmd` 服务执行单次动作，完成后机器狗回到默认姿态。

服务定义 `protocol/srv/MotionResultCmd`：

```text
请求字段:
  motion_id    int32    动作编号
  cmd_source   uint8    来源 (MotionResultCmd.Request.APP)

响应字段:
  motion_id    int32
  result       bool     是否成功
  code         int32    返回码
```

已确认的动作列表（来自 `cyberdog_actions.py`）：

| 名称 | motion_id | 风险 | 英文描述 |
|------|-----------|------|----------|
| 站立 | 111 | low | RECOVERYSTAND |
| 趴下 | 101 | low | GETDOWN |
| 坐下 | 143 | medium | sit |
| 作揖 | 123 | medium | bow |
| 握左手 | 141 | medium | shake left hand |
| 握右手 | 142 | medium | shake right hand |
| 扭屁股 | 144 | medium | hip circle |
| 伸懒腰 | 146 | medium | stretch |
| 头画圈 | 145 | medium | head circle |
| 坐下左摆头 | 148 | medium | sit head left |
| 坐下右摆头 | 149 | medium | sit head right |
| 坐下左右摆头 | 150 | medium | sit head left-right |
| 跳上台阶 | 126 | high | jump up step |
| 跳下台阶 | 137 | high | jump down step |
| 跳下高台 | 147 | very_high | jump down platform |
| 抱手跳跃 | 500 | very_high | jump with raised hands |
| 后空翻 | 121 | very_high | back flip |
| 前空翻 | 122 | very_high | front flip |
| 右侧空翻 | 127 | very_high | right flip |
| 左侧空翻 | 128 | very_high | left flip |

赛道相关动作：
- 站立: `111`（第一赛段开始需要）
- 趴下: `101`（第六赛段结束需要）
- 跳上台阶: `126`（第五赛段独木桥跳跃可能需要）
- 跳下高台: `147`（第五赛段离开独木桥）

### 4.2 连续步态（MotionServoCmd 话题）

通过向 `/custom_namespace/motion_servo_cmd` 话题发布消息实现持续运动。必须以固定频率（约 20Hz）持续发布，退出时必须发送 `SERVO_END`。

消息定义 `protocol/msg/MotionServoCmd`：

```text
字段:
  motion_id    int32       步态编号
  cmd_source   uint8       来源 (MotionServoCmd.APP = 0)
  cmd_type     uint8       命令类型 (SERVO_DATA = 1, SERVO_END = 2)
  vel_des      float[3]    速度 [前进/后退, 左右平移, 偏航旋转]
  step_height  float[2]    步高 [前腿, 后腿]
```

速度限制（项目安全限幅）：

```text
MAX_X     = 0.12   m/s   前后方向
MAX_Y     = 0.05   m/s   左右方向
MAX_YAW   = 0.35   rad/s 旋转
MAX_DURATION = 2.0  s     单次最长时间
```

已确认的步态列表（来自 `cyberdog_gaits.py`）：

| 名称 | motion_id | vel [x, y, yaw] | duration | 风险 |
|------|-----------|------------------|----------|------|
| 自适应慢走前进 1s | 345 | [0.05, 0.0, 0.0] | 1.0 | medium |
| 自适应后退 1s | 345 | [-0.04, 0.0, 0.0] | 1.0 | medium |
| 自适应左移 1s | 345 | [0.0, 0.03, 0.0] | 1.0 | medium |
| 自适应右移 1s | 345 | [0.0, -0.03, 0.0] | 1.0 | medium |
| 原地左转 0.8s | 345 | [0.0, 0.0, 0.25] | 0.8 | medium |
| 原地右转 0.8s | 345 | [0.0, 0.0, -0.25] | 0.8 | medium |
| 慢走步态前进 1s | 303 | [0.05, 0.0, 0.0] | 1.0 | medium |
| 中速步态前进 1s | 308 | [0.08, 0.0, 0.0] | 1.0 | high |
| 快走步态前进 1s | 305 | [0.10, 0.0, 0.0] | 1.0 | high |
| 变频步态前进 1s | 304 | [0.05, 0.0, 0.0] | 1.0 | high |
| 四足跳跑 1s | 301 | [0.03, 0.0, 0.0] | 1.0 | very_high |
| 四足蹦跳 1s | 302 | [0.02, 0.0, 0.0] | 1.0 | very_high |
| 停止步态 | 345 | type: "stop" | — | low |

步态 ID 说明：
- **345**: 自适应步态，最常用，支持前后左右和旋转
- **303**: 慢走步态
- **308**: 中速步态
- **305**: 快走步态
- **304**: 变频步态
- **301**: 四足跳跑
- **302**: 四足蹦跳

### 4.3 运动状态（MotionStatus 订阅）

消息定义 `protocol/msg/MotionStatus` 中的关键字段 `switch_status`：

| 值 | 名称 | 含义 |
|----|------|------|
| 0 | NORMAL | 正常，可以运动 |
| 1 | TRANSITIONING | 姿态切换中 |
| 2 | ESTOP | 急停 |
| 3 | EDAMP | 电子阻尼 |
| 4 | LIFTED | 被抬起 |
| 5 | BAN_TRANS | 禁止切换 |
| 6 | OVER_HEAT | 过热 |
| 7 | LOW_BAT | 低电量 |
| 8 | ORI_ERR | 姿态错误 |
| 9 | FOOTPOS_ERR | 足端位置错误 |
| 10 | STAND_STUCK | 站立卡住 |
| 11 | MOTOR_OVER_HEAT | 电机过热 |
| 12 | MOTOR_OVER_CURR | 电机过流 |
| 13 | MOTOR_ERR | 电机错误 |
| 14 | CHARGING | 充电中 |

只有 `switch_status == 0 (NORMAL)` 时才允许执行运动。

---

## 5. RGB 相机详解

### 5.1 相机参数

```text
话题:          /custom_namespace/image
类型:          sensor_msgs/msg/Image
分辨率:        640 x 480
编码:          bgr8（OpenCV 标准格式）
帧率:          15 fps
QoS:           RELIABLE, VOLATILE
```

### 5.2 相机服务 CameraService

服务定义 `protocol/srv/CameraService`：

```text
请求字段:
  command   uint8    命令编号
  args      string   参数（通常为空）
  width     uint16   图像宽度
  height    uint16   图像高度
  fps       uint16   帧率

命令编号:
  0  SET_PARAMETERS
  1  TAKE_PICTURE
  2  START_RECORDING
  3  STOP_RECORDING
  4  GET_STATE
  5  DELETE_FILE
  6  GET_ALL_FILES
  7  START_LIVE_STREAM
  8  STOP_LIVE_STREAM
  9  START_IMAGE_PUBLISH    <-- 启动图像发布
  10 STOP_IMAGE_PUBLISH     <-- 停止图像发布

响应字段:
  result    uint8    结果码 (0=成功)
  msg       string   消息
  code      int32    返回码

结果码:
  0  RESULT_SUCCESS
  1  RESULT_INVALID_ARGS
  2  RESULT_UNSUPPORTED
  3  RESULT_TIMEOUT
  4  RESULT_BUSY
  5  RESULT_INVALID_STATE（常见：上次未正常停止）
  6  RESULT_INNER_ERROR
  255 RESULT_UNDEFINED_ERROR
```

相机服务话题名：`/mi_desktop_48_b0_2d_7b_05_1d/camera_service` 或 `/custom_namespace/camera_service`（两个均可使用）

### 5.3 CyberDogCamera 类（项目封装）

文件位置：`/home/mi/cyberdog_course/program/cyberdog_camera.py`

这个类封装了相机启动、图像订阅、OpenCV 转换和网页预览。所有视觉识别脚本都应该复用这个类，不要重复写相机启动逻辑。

```python
# 导入方式（在机器狗端运行）
from cyberdog_camera import CyberDogCamera

# 创建相机节点
cam = CyberDogCamera(
    namespace="/mi_desktop_48_b0_2d_7b_05_1d",  # 机器狗命名空间
    width=640,
    height=480,
    fps=15,
    enable_preview=True,     # 是否开启网页预览
    web_host="0.0.0.0",
    web_port=8080,
    output_dir="/home/mi/cyberdog_course/program/captures",
)

# 启动相机（内部有重试逻辑：第一次失败会 STOP 再 START）
cam.start_camera()

# 等待图像到达（spin 处理回调）
cam.spin_for(2.0)

# 获取当前帧（标准 OpenCV BGR numpy 数组，640x480x3）
frame = cam.latest_frame

# 保存截图
cam.save_latest("my_screenshot.jpg")

# 停止相机
cam.stop_camera()
```

关键属性：
- `cam.latest_frame`: 最新一帧 OpenCV BGR 图像（`numpy.ndarray`, shape=(480, 640, 3)），无图像时为 `None`
- `cam.frame_count`: 已收到的帧数

网页预览：
- 启动后浏览器访问 `http://<机器狗IP>:8080` 可看到实时画面
- 提供 MJPEG 流：`http://<机器狗IP>:8080/stream.mjpg`

---

## 6. 鱼眼相机详解

### 6.1 鱼眼相机参数

```text
硬件:          2x OV9782 (OmniVision)
设备:          /dev/video2 (左), /dev/video3 (右)
传感器格式:    RG10 (10-bit Bayer), 通过 V4L2 直接采集
输出格式:      mono8 灰度图 (RG10 右移 2 位)
单目分辨率:    640 x 400 (默认)
合成画面:      左右拼接, 1280 x 400 BGR
接口方式:      V4L2 MMAP 直接采集 (绕过 ROS 和 stereo_camera 节点)
采集框架:      Python V4L2 + select.poll 双摄并发
```

注意：鱼眼相机**不通过 ROS 话题发布**，而是直接通过 V4L2 读取设备文件。因此不需要激活 `stereo_camera` 生命周期节点。

### 6.2 CyberDogFisheyeCamera 类

文件位置：`/home/mi/cyberdog_course/program/perception/cyberdog_fisheye.py`

这个类直接读取两颗 OV9782 鱼眼摄像头，将左右灰度画面合成为网页预览。

```python
from cyberdog_fisheye import CyberDogFisheyeCamera

# 创建鱼眼相机节点
cam = CyberDogFisheyeCamera(
    left_device="/dev/video2",     # 左鱼眼设备
    right_device="/dev/video3",    # 右鱼眼设备
    width=640,                     # 单目宽度
    height=400,                    # 单目高度
    preview_fps=15,                # 预览帧率
    enable_preview=True,           # 是否开启网页预览
    web_host="0.0.0.0",
    web_port=8080,
    output_dir="/home/mi/cyberdog_course/program/captures",
)

# 启动相机（内部启动 V4L2 采集线程，等待双目都出帧）
success = cam.start_camera(ready_timeout=8.0)

# 获取合成帧（左右拼接的 BGR 图像, 1280x400x3）
frame = cam.latest_frame

# 获取单目帧数统计
print(cam.frame_counts)  # {"left": 150, "right": 148}

# 保存截图
cam.save_latest("fisheye_view_latest.jpg")

# 停止相机
cam.stop_camera()
```

### 6.3 关键属性和方法

```text
属性:
  cam.latest_frame      最新合成帧 (numpy.ndarray, shape=(400, 1280, 3), BGR)
                        左半部分为左鱼眼, 右半部分为右鱼眼
                        上方标注 "LEFT /dev/video2" 和 "RIGHT /dev/video3"
  cam.frame_counts      字典 {"left": N, "right": N}, 各目已采集帧数

方法:
  start_camera(timeout) 启动双摄采集, 返回 True/False
  stop_camera()         停止采集并释放设备
  save_latest(filename) 保存最新合成帧到 captures/ 目录
  spin_for(seconds)     阻塞等待指定时间
```

### 6.4 Windows 一键启动

```powershell
# 启动鱼眼相机预览（自动推送代码、建立 SSH 隧道、打开浏览器）
.\tools\start_camera_view.ps1 -Source fisheye

# 启动 RGB 相机预览
.\tools\start_camera_view.ps1 -Source rgb

# 先推送代码再启动
.\tools\start_camera_view.ps1 -Source fisheye -PushFirst
```

浏览器自动打开 `http://127.0.0.1:18080`，可看到左右鱼眼实时画面。

### 6.5 注意事项

- 鱼眼相机直接操作 `/dev/video2` 和 `/dev/video3`，如果 `stereo_camera` 节点处于 active 状态会占用设备，导致鱼眼模块无法打开。使用前确保 `stereo_camera` 为 `unconfigured`。
- 输出是灰度图（mono8），不是彩色图。
- `start_camera()` 会阻塞直到左右都出帧（默认 8 秒超时），返回 `False` 表示启动失败。
- `stop_camera()` 必须调用以释放 V4L2 设备，否则下次启动可能失败。

---

## 7. 2D 激光雷达详解

### 7.1 雷达参数

```text
话题:           /custom_namespace/scan
类型:           sensor_msgs/msg/LaserScan
频率:           ~10 Hz
扫描角度范围:    -90° ~ +90°（前方 180°）
角度分辨率:     ~0.37°（0.00641 rad）
采样点数:       491
最小距离:       0.01 m
最大距离:       30.0 m
QoS:            RELIABLE, VOLATILE
frame_id:       laser_frame
```

### 7.2 数据结构

```text
LaserScan 消息字段:
  header          时间戳和 frame_id
  angle_min       -1.5708 rad (-90°)
  angle_max        1.5708 rad (+90°)
  angle_increment  0.00641 rad
  range_min        0.01 m
  range_max        30.0 m
  ranges           float[491]  各角度的距离值（米）
  intensities      float[491]  各角度的反射强度
```

角度与数组索引的对应关系：

```text
ranges[0]    -> angle_min (-90°, 正左方)
ranges[245]  -> 0° (正前方)
ranges[490]  -> angle_max (+90°, 正右方)
```

某个索引 i 对应的角度 = angle_min + i * angle_increment

### 7.3 Python 订阅示例

```python
from sensor_msgs.msg import LaserScan

# 在 Node 类中创建订阅
self.scan_sub = self.create_subscription(
    LaserScan,
    '/custom_namespace/scan',
    self.scan_callback,
    10,
)

def scan_callback(self, msg):
    """回调函数，msg.ranges 是 491 个距离值"""
    # 正前方距离（中间点）
    front_dist = msg.ranges[245]

    # 左前方 45°
    left_45 = msg.ranges[122]

    # 右前方 45°
    right_45 = msg.ranges[367]

    # 查找前方最近障碍物
    front_ranges = msg.ranges[196:294]  # 前方约 ±30°
    min_dist = min(front_ranges)
```

---

## 8. 语音播报（扬声器）

### 8.1 服务信息

```text
话题:   /custom_namespace/speech_text_play
类型:   protocol/srv/AudioTextPlay
用途:   文字转语音播报（赛道规则要求识别目标物后语音播报）
```

### 8.2 服务定义 protocol/srv/AudioTextPlay

```text
请求字段:
  module_name    string     模块名（任意字符串，如 "race"）
  is_online      bool       是否在线（填 true）
  speech         AudioPlay  预置语音（播报自定义文字时可忽略）
    module_name  string
    play_id      uint16
  text           string     要播报的文字内容

响应字段:
  status    uint8    0=播放完毕, 1=播放失败
  code      int32    返回码
```

### 8.3 命令行测试

```bash
ros2 service call /custom_namespace/speech_text_play protocol/srv/AudioTextPlay "{module_name: 'race', is_online: true, speech: {module_name: 'race', play_id: 0}, text: '识别到可乐瓶'}"
```

### 8.4 Python 调用示例

```python
import rclpy
from rclpy.node import Node
from protocol.srv import AudioTextPlay


class SpeechNode(Node):
    def __init__(self):
        super().__init__('speech_node')
        self.speech_client = self.create_client(AudioTextPlay, '/custom_namespace/speech_text_play')

    def speak(self, text):
        """播报指定文字"""
        if not self.speech_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error('语音服务不可用')
            return False

        request = AudioTextPlay.Request()
        request.module_name = 'race'
        request.is_online = True
        request.speech.module_name = 'race'
        request.speech.play_id = 0
        request.text = text

        future = self.speech_client.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)

        if future.result() is not None:
            response = future.result()
            if response.status == 0:
                self.get_logger().info(f'播报成功: {text}')
                return True
            else:
                self.get_logger().warn(f'播报失败: status={response.status}, code={response.code}')
                return False
        else:
            self.get_logger().error('语音服务调用超时')
            return False
```

### 8.5 赛道播报内容参考

根据赛道规则，第四赛段需要识别后播报：

| 目标物/障碍 | 播报内容 |
|-------------|----------|
| 可乐 | "识别到可乐瓶" |
| 橙球 | "识别到橙色小球" |
| 足球 | "识别到足球" |
| 限高杆 | "识别到限高杆" |
| 方块 | "识别到无法跨越障碍" |

---

## 9. CyberDogBaseNode（运动控制基础类）

文件位置：`/home/mi/cyberdog_course/program/cyberdog_base.py`

所有运动控制脚本都应该继承这个类，它封装了：
- 状态订阅和安全检查
- 一次性动作调用
- 连续步态发布和自动停止
- 速度限幅

```python
from cyberdog_base import CyberDogBaseNode

# 创建节点
node = CyberDogBaseNode("my_node_name")

# ========== 一次性动作 ==========

# 执行站立
node.run_motion_action({"name": "站立", "motion_id": 111})

# 执行趴下
node.run_motion_action({"name": "趴下", "motion_id": 101})

# 执行跳上台阶
node.run_motion_action({"name": "跳上台阶", "motion_id": 126})

# ========== 连续步态 ==========

# 前进 1 秒
node.run_servo_gait({
    "name": "自适应慢走前进 1s",
    "motion_id": 345,
    "vel": [0.05, 0.0, 0.0],
    "duration": 1.0,
})

# 原地左转 0.8 秒
node.run_servo_gait({
    "name": "原地左转 0.8s",
    "motion_id": 345,
    "vel": [0.0, 0.0, 0.25],
    "duration": 0.8,
})

# 停止步态
node.run_servo_gait({"name": "停止步态", "type": "stop", "motion_id": 345})

# ========== 安全检查 ==========

# 等待并检查状态是否安全
if node.ensure_safe_status():
    print("可以运动")
else:
    print("状态不安全，不能运动")

# 手动获取当前状态
if node.latest_status is not None:
    status_name = node.switch_status_name(node.latest_status.switch_status)
    print(f"当前状态: {status_name}")
```

### 9.1 run_servo_gait 的内部流程

```text
1. ensure_safe_status()  检查状态
2. clamp 速度到安全范围
3. 循环: 按 20Hz 发布 MotionServoCmd (cmd_type=SERVO_DATA)
4. 到时间后 finally: 发送 SERVO_END（发送 3 次确保送达）
```

### 9.2 完整程序模板

```python
#!/usr/bin/env python3
"""赛道脚本模板"""
import rclpy
from cyberdog_base import CyberDogBaseNode
from cyberdog_actions import ACTIONS
from cyberdog_gaits import GAITS


def main():
    rclpy.init()
    node = CyberDogBaseNode("race_script")

    try:
        # 1. 站立
        node.run_motion_action({"name": "站立", "motion_id": 111})
        import time; time.sleep(1.0)

        # 2. 前进
        node.run_servo_gait({
            "name": "前进",
            "motion_id": 345,
            "vel": [0.05, 0.0, 0.0],
            "duration": 2.0,
        })

        # 3. 左转
        node.run_servo_gait({
            "name": "左转",
            "motion_id": 345,
            "vel": [0.0, 0.0, 0.25],
            "duration": 0.8,
        })

        # ... 更多步态组合 ...

    except KeyboardInterrupt:
        node.get_logger().info("用户中断")
    finally:
        # 确保停止步态并趴下
        try:
            node.stop_servo()
        except Exception:
            pass
        try:
            node.run_motion_action({"name": "趴下", "motion_id": 101})
        except Exception:
            pass
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
```

### 9.3 完整示例：stand1.py（独立站立程序）

以下是一个不依赖 `cyberdog_base.py` 的独立站立程序，可直接复制到机器狗运行，用于验证运动服务是否正常。

```python
#!/usr/bin/env python3
"""
stand1.py — CyberDog 恢复站立（独立完整版）

在机器狗 NX 端运行：
  cd /home/mi/cyberdog_course/program
  python3 stand1.py

依赖：rclpy, protocol（已装在机器狗上）
"""

import sys
import time

import rclpy
from rclpy.node import Node
from protocol.srv import MotionResultCmd

# ========== 配置 ==========
MOTION_SERVICE = "/custom_namespace/motion_result_cmd"  # 运动服务话题
MOTION_ID_STAND = 111   # 站立动作 ID（来自 cyberdog_actions.py）
SERVICE_TIMEOUT = 10.0  # 等待服务的超时（秒）
ACTION_TIMEOUT = 30.0   # 等待动作完成的超时（秒）


class StandNode(Node):
    def __init__(self):
        super().__init__('stand_node')
        self.get_logger().info('初始化站立节点...')
        self.client = self.create_client(MotionResultCmd, MOTION_SERVICE)

    def do_stand(self):
        # 1. 等待运动服务可用
        self.get_logger().info(f'等待运动服务 {MOTION_SERVICE} ...')
        if not self.client.wait_for_service(timeout_sec=SERVICE_TIMEOUT):
            self.get_logger().error('运动服务不可用，请检查机器狗是否正常运行')
            return False
        self.get_logger().info('运动服务已就绪')

        # 2. 构造请求
        request = MotionResultCmd.Request()
        request.motion_id = MOTION_ID_STAND
        request.cmd_source = MotionResultCmd.Request.APP

        # 3. 发送请求
        self.get_logger().info(f'发送站立请求: motion_id={MOTION_ID_STAND}')
        future = self.client.call_async(request)

        # 4. 等待响应（带超时）
        end_time = time.monotonic() + ACTION_TIMEOUT
        while time.monotonic() < end_time and rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.1)
            if future.done():
                try:
                    response = future.result()
                except Exception as exc:
                    self.get_logger().error(f'服务调用异常: {exc}')
                    return False

                self.get_logger().info(
                    f'收到响应: result={response.result}, code={response.code}'
                )
                if response.result:
                    self.get_logger().info('站立成功!')
                    return True
                else:
                    self.get_logger().warn(f'站立失败, code={response.code}')
                    return False

        self.get_logger().error('等待动作响应超时')
        return False


def main():
    rclpy.init()
    node = StandNode()
    success = False
    try:
        success = node.do_stand()
    except KeyboardInterrupt:
        node.get_logger().info('用户中断')
    finally:
        node.destroy_node()
        rclpy.shutdown()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
```

运行方式：

```bash
cd /home/mi/cyberdog_course/program
python3 stand1.py
```

成功输出：

```text
[INFO] [stand_node]: 初始化站立节点...
[INFO] [stand_node]: 等待运动服务 /custom_namespace/motion_result_cmd ...
[INFO] [stand_node]: 运动服务已就绪
[INFO] [stand_node]: 发送站立请求: motion_id=111
[INFO] [stand_node]: 收到响应: result=True, code=0
[INFO] [stand_node]: 站立成功!
```

---

## 10. 视觉识别参考

### 10.1 已有的视觉脚本

```text
/home/mi/cyberdog_course/program/cyberdog_camera.py   相机基础模块（复用）
/home/mi/cyberdog_course/program/camera_view.py       相机预览（测试用）
/home/mi/cyberdog_course/program/ball_detect1.py      球检测 v1
/home/mi/cyberdog_course/program/ball_detect2.py      球检测 v2
```

### 10.2 图像处理基本流程

```python
import cv2
from cyberdog_camera import CyberDogCamera

cam = CyberDogCamera(namespace="/mi_desktop_48_b0_2d_7b_05_1d")
cam.start_camera()

# 等待图像
cam.spin_for(2.0)

frame = cam.latest_frame  # numpy BGR 640x480x3

# ---- 橙球检测示例 ----
hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
# 橙色 HSV 范围（需根据实际场地调整）
lower_orange = (10, 100, 100)
upper_orange = (25, 255, 255)
mask = cv2.inRange(hsv, lower_orange, upper_orange)
contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

for cnt in contours:
    area = cv2.contourArea(cnt)
    if area > 500:
        x, y, w, h = cv2.boundingRect(cnt)
        cx, cy = x + w // 2, y + h // 2
        print(f"橙球位置: ({cx}, {cy}), 面积: {area}")

cam.stop_camera()
```

### 10.3 雷达 + 视觉融合示例

```python
import cv2
import numpy as np
from sensor_msgs.msg import LaserScan
from cyberdog_camera import CyberDogCamera
from cyberdog_base import CyberDogBaseNode


class RaceNode(CyberDogBaseNode):
    def __init__(self):
        super().__init__("race_node")

        # 相机
        self.cam = CyberDogCamera(namespace="/mi_desktop_48_b0_2d_7b_05_1d")
        self.cam.start_camera()

        # 雷达
        self.latest_scan = None
        self.scan_sub = self.create_subscription(
            LaserScan,
            '/custom_namespace/scan',
            self.scan_callback,
            10,
        )

    def scan_callback(self, msg):
        self.latest_scan = msg

    def get_front_distance(self):
        """获取正前方距离（米）"""
        if self.latest_scan is None:
            return None
        return self.latest_scan.ranges[245]

    def get_obstacle_in_front(self, angle_range=30):
        """获取前方指定角度范围内的最近障碍物距离"""
        if self.latest_scan is None:
            return None
        center = 245
        half = int(angle_range / 0.37)  # 角度转索引
        front = self.latest_scan.ranges[center - half : center + half]
        valid = [r for r in front if 0.01 < r < 30.0]
        return min(valid) if valid else None
```

---

## 11. 机器狗上已有的全部文件

```text
/home/mi/cyberdog_course/program/
├── cyberdog_base.py        运动控制基础类（状态、安全、步态、动作）
├── cyberdog_actions.py     动作列表（20 个一次性动作）
├── cyberdog_gaits.py       步态列表（12 种连续步态 + 停止）
├── cyberdog_camera.py      相机基础模块（启动、订阅、转换、预览）
├── cyberdog_console.py     交互控制台（菜单选择动作/步态）
├── check_status.py         状态检查脚本（只读，验证连接用）
├── stand1.py               站立脚本
├── down1.py                趴下脚本
├── camera_view.py          相机预览脚本
├── ball_detect1.py         球检测 v1
├── ball_detect2.py         球检测 v2
└── captures/               截图保存目录
```

---

## 12. 开发注意事项

### 12.1 安全规则

- 所有运动前必须检查 `switch_status == 0 (NORMAL)`
- 连续步态的 `SERVO_END` 必须放在 `finally` 中确保发送
- 默认低速、短时长，高风险动作需要显式解锁
- 急停、摔倒、低电量、感知丢失时停止运动
- 触线、碰撞等扣分事件记录后继续，不必停机

### 12.2 代码规范

- CyberDog 项目代码使用中文注释
- 优先复用 `cyberdog_base.py`、`cyberdog_camera.py`
- 使用 `MotionID.<NAME>` 或已确认的数值
- 所有等待都有超时，所有循环都能退出
- 不猜测接口、字段、动作 ID，证据不足先探测

### 12.3 开发顺序

```text
1. 先能安全停（趴下、急停）
2. 再能低速动（前进、转向）
3. 再能感知（相机、雷达）
4. 再完成单关
5. 最后串联全赛道
```

### 12.4 测试时

- 空旷平地、有人看护、APP 急停可用
- 先运行只读脚本（`check_status.py`），再低风险动作（`stand1.py`），最后运动+感知
- 保存日志、参数和测试结论
