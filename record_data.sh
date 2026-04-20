#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROS_SETUP="/opt/ros/humble/setup.bash"
WS_SETUP="${SCRIPT_DIR}/install/setup.bash"

# 設定儲存資料夾名稱，加上時間戳記避免重複
BAG_NAME="dataset_$(date +%Y%m%d_%H%M%S)"
PID_RADAR=""
PID_CAMERA=""
TI_COMMAND_PORT="${TI_COMMAND_PORT:-}"
TI_DATA_PORT="${TI_DATA_PORT:-}"
CAMERA_DEVICE="${CAMERA_DEVICE:-/dev/video0}"

pick_ti_ports() {
  if [ -z "${TI_COMMAND_PORT}" ]; then
    if [ -e /dev/ti_radar_command ]; then
      TI_COMMAND_PORT="/dev/ti_radar_command"
    else
      TI_COMMAND_PORT="/dev/ttyUSB0"
    fi
  fi

  if [ -z "${TI_DATA_PORT}" ]; then
    if [ -e /dev/ti_radar_data ]; then
      TI_DATA_PORT="/dev/ti_radar_data"
    else
      TI_DATA_PORT="/dev/ttyUSB1"
    fi
  fi
}

source_env() {
  if [ ! -f "${ROS_SETUP}" ]; then
    echo "-> [錯誤] 找不到 ROS 2 環境: ${ROS_SETUP}"
    exit 1
  fi

  source "${ROS_SETUP}"

  if [ ! -f "${WS_SETUP}" ]; then
    echo "-> [錯誤] 找不到 workspace install/setup.bash: ${WS_SETUP}"
    echo "-> [提示] 請先在 ${SCRIPT_DIR} 執行: source /opt/ros/humble/setup.bash && colcon build --symlink-install"
    exit 1
  fi

  source "${WS_SETUP}"
}

cleanup() {
  echo "-> 正在關閉感測器..."
  if [ -n "${PID_CAMERA}" ] && kill -0 "${PID_CAMERA}" 2>/dev/null; then
    kill -SIGINT "${PID_CAMERA}" 2>/dev/null || true
  fi
  sleep 1
  if [ -n "${PID_RADAR}" ] && kill -0 "${PID_RADAR}" 2>/dev/null; then
    kill -SIGINT "${PID_RADAR}" 2>/dev/null || true
  fi
}

grant_device_permissions() {
  local devices=()
  for pattern in /dev/ttyACM* /dev/ttyUSB* /dev/video*; do
    for dev in ${pattern}; do
      if [ -e "${dev}" ]; then
        devices+=("${dev}")
      fi
    done
  done

  if [ "${#devices[@]}" -eq 0 ]; then
    echo "-> [警告] 目前沒有偵測到可授權的 /dev/ttyACM* /dev/ttyUSB* /dev/video*"
    return 0
  fi

  echo "-> [自動] 賦予 USB 與攝影機權限..."
  sudo chmod 666 "${devices[@]}"
}

topic_exists() {
  local topic_name="$1"
  ros2 topic list 2>/dev/null | grep -Fxq "${topic_name}"
}

prompt_continue_or_abort() {
  local message="$1"
  local answer
  echo "-> [警告] ${message}"
  while true; do
    read -r -p "-> 要中止還是繼續? 輸入 a(中止) 或 c(繼續): " answer
    case "${answer}" in
      a|A)
        echo "-> 已中止錄製。請先排除問題後再重新執行。"
        exit 1
        ;;
      c|C)
        echo "-> 依使用者指示繼續錄製。"
        return 0
        ;;
      *)
        echo "-> 請輸入 a 或 c。"
        ;;
    esac
  done
}

trap cleanup EXIT

source_env
pick_ti_ports

echo "=========================================="
echo "   資料採集系統"
echo "=========================================="

grant_device_permissions

echo "-> 目前可見裝置:"
ls -l /dev/ttyACM* /dev/ttyUSB* /dev/video* 2>/dev/null || true
echo "-> TI command port: ${TI_COMMAND_PORT}"
echo "-> TI data port:    ${TI_DATA_PORT}"
echo "-> Camera device:   ${CAMERA_DEVICE}"

if ! ros2 pkg prefix usb_cam >/dev/null 2>&1; then
  echo "-> [錯誤] 缺少 ROS 套件 usb_cam"
  echo "-> [建議] sudo apt install ros-humble-usb-cam"
  exit 1
fi

if ! ros2 pkg prefix rosbag2_storage_mcap >/dev/null 2>&1; then
  echo "-> [錯誤] 缺少 rosbag2 mcap storage plugin"
  echo "-> [建議] sudo apt install ros-humble-rosbag2-storage-mcap"
  exit 1
fi

# 1. 啟動雷達
echo "-> 正在啟動雷達 (無 Rviz 模式)..."
ros2 launch ti_mmwave_rospkg 6843AOP_StaticTracking.py \
  command_port:="${TI_COMMAND_PORT}" \
  data_port:="${TI_DATA_PORT}" \
  rviz:=false &
PID_RADAR=$!

echo "-> 等待雷達穩定 (10 秒)..."
sleep 10

# 2. 啟動攝影機
echo "-> 正在啟動攝影機..."
ros2 launch sensor_fusion_pkg camera.launch.py video_device:="${CAMERA_DEVICE}" &
PID_CAMERA=$!

echo "-> 等待攝影機穩定 (5 秒)..."
sleep 5

# 3. 錄製前檢查
RADAR_TOPIC="/ti_mmwave/radar_scan_pcl"
IMAGE_TOPIC="/image_raw"

echo "-> 正在檢查關鍵 topic..."
if topic_exists "${RADAR_TOPIC}"; then
  echo "-> [OK] 已偵測到雷達 topic: ${RADAR_TOPIC}"
else
  prompt_continue_or_abort "未偵測到雷達 topic ${RADAR_TOPIC}"
fi

if topic_exists "${IMAGE_TOPIC}"; then
  echo "-> [OK] 已偵測到影像 topic: ${IMAGE_TOPIC}"
else
  echo "-> [診斷] 目前未偵測到 ${IMAGE_TOPIC}"
  if ! ls /dev/video* >/dev/null 2>&1; then
    echo "-> [可能原因] 容器內沒有 /dev/video*，相機裝置沒有掛進來。"
  else
    echo "-> [可能原因] usb_cam 節點已啟動，但 video_device 設定錯誤或相機無法開啟。"
    echo "-> [提示] 請檢查 camera.launch.py 內的 video_device，目前預設是 /dev/video0。"
  fi
  prompt_continue_or_abort "未偵測到影像 topic ${IMAGE_TOPIC}，若繼續將只會錄到雷達資料"
fi

# 4. 開始錄製
echo "------------------------------------------"
echo "-> 系統就緒！開始錄製資料夾: ${BAG_NAME}"
echo "-> 錄製中，請勿拔除 USB 線..."
echo "-> 按 [Ctrl+C] 結束錄製"
echo "------------------------------------------"

ros2 bag record -s mcap -o "${BAG_NAME}" \
  /image_raw \
  /ti_mmwave/radar_scan \
  /ti_mmwave/radar_scan_pcl \
  /ti_mmwave/radar_track_array \
  /ti_mmwave/radar_micro_doppler_data_array

echo "-> 錄製完成！資料已儲存於 ${BAG_NAME}"
