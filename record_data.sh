#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROS_SETUP="/opt/ros/humble/setup.bash"
WS_SETUP="${SCRIPT_DIR}/install/setup.bash"

# 設定儲存資料夾名稱，加上時間戳記避免重複
BAG_NAME="dataset_$(date +%Y%m%d_%H%M%S)"
PID_RADAR=""
PID_CAMERA=""
RADAR_LOG="$(mktemp /tmp/dataset_radar_launch.XXXXXX.log)"
CAMERA_LOG="$(mktemp /tmp/dataset_camera_launch.XXXXXX.log)"
RADAR_MSG_CHECK_LOG="$(mktemp /tmp/dataset_radar_msg_check.XXXXXX.log)"
IMAGE_MSG_CHECK_LOG="$(mktemp /tmp/dataset_image_msg_check.XXXXXX.log)"
TI_COMMAND_PORT="${TI_COMMAND_PORT:-}"
TI_DATA_PORT="${TI_DATA_PORT:-}"
CAMERA_DEVICE="${CAMERA_DEVICE:-/dev/video0}"
TI_RVIZ="${TI_RVIZ:-false}"

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

require_path() {
  local path="$1"
  local hint="$2"
  if [ ! -e "${path}" ]; then
    echo "-> [錯誤] 找不到必要裝置: ${path}"
    echo "-> [提示] ${hint}"
    exit 1
  fi
}

probe_serial_device() {
  local path="$1"
  local label="$2"

  if [ ! -c "${path}" ]; then
    echo "-> [錯誤] ${label} 不是可用的字元裝置: ${path}"
    exit 1
  fi

  if ! bash -lc "exec 3<> '${path}'" 2>/dev/null; then
    echo "-> [錯誤] 無法開啟 ${label}: ${path}"
    echo "-> [提示] 請先拔插 TI 6843 USB，確認 alias 重新出現後再重跑"
    exit 1
  fi
}

source_with_relaxed_nounset() {
  set +u
  # shellcheck disable=SC1090
  source "$1"
  set -u
}

source_env() {
  if [ ! -f "${ROS_SETUP}" ]; then
    echo "-> [錯誤] 找不到 ROS 2 環境: ${ROS_SETUP}"
    exit 1
  fi

  source_with_relaxed_nounset "${ROS_SETUP}"

  if [ ! -f "${WS_SETUP}" ]; then
    echo "-> [錯誤] 找不到 workspace install/setup.bash: ${WS_SETUP}"
    echo "-> [提示] 請先在 ${SCRIPT_DIR} 執行: source /opt/ros/humble/setup.bash && colcon build --symlink-install"
    exit 1
  fi

  source_with_relaxed_nounset "${WS_SETUP}"
}

cleanup() {
  local exit_code=$?
  echo "-> 正在關閉感測器..."
  if [ -n "${PID_CAMERA}" ] && kill -0 "${PID_CAMERA}" 2>/dev/null; then
    kill -SIGINT "${PID_CAMERA}" 2>/dev/null || true
  fi
  sleep 1
  if [ -n "${PID_RADAR}" ] && kill -0 "${PID_RADAR}" 2>/dev/null; then
    kill -SIGINT "${PID_RADAR}" 2>/dev/null || true
  fi

  if [ "${exit_code}" -eq 0 ]; then
    rm -f "${RADAR_LOG}" "${CAMERA_LOG}" "${RADAR_MSG_CHECK_LOG}" "${IMAGE_MSG_CHECK_LOG}"
  else
    echo "-> [診斷] 保留失敗 log 供排查："
    echo "-> [診斷] RADAR_LOG=${RADAR_LOG}"
    echo "-> [診斷] CAMERA_LOG=${CAMERA_LOG}"
    echo "-> [診斷] RADAR_MSG_CHECK_LOG=${RADAR_MSG_CHECK_LOG}"
    echo "-> [診斷] IMAGE_MSG_CHECK_LOG=${IMAGE_MSG_CHECK_LOG}"
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

wait_for_topic_message() {
  local topic_name="$1"
  local timeout_secs="$2"
  local output_log="$3"

  : > "${output_log}"
  timeout "${timeout_secs}" ros2 topic echo --once "${topic_name}" >"${output_log}" 2>&1
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

abort_with_log_excerpt() {
  local title="$1"
  local log_file="$2"

  echo "-> [錯誤] ${title}"
  if [ -f "${log_file}" ]; then
    echo "-> [診斷] 最近的 launch log："
    tail -n 20 "${log_file}" || true
  fi
  exit 1
}

check_radar_launch_health() {
  if grep -E -q "Failed to open User serial port|Power cycle the mmWave Sensor|std::system_error|Invalid argument" "${RADAR_LOG}"; then
    abort_with_log_excerpt "TI 雷達啟動失敗，已自動中止錄製流程" "${RADAR_LOG}"
  fi

  if ! kill -0 "${PID_RADAR}" 2>/dev/null; then
    abort_with_log_excerpt "TI 雷達 launch 已提前結束，已自動中止錄製流程" "${RADAR_LOG}"
  fi
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
echo "-> TI RViz:         ${TI_RVIZ}"

require_path "${TI_COMMAND_PORT}" "請先確認 TI 雷達已被系統辨識，必要時執行 sudo bash /home/robot/setup_ti_radar_udev.sh"
require_path "${TI_DATA_PORT}" "請先確認 TI 雷達已被系統辨識，必要時執行 sudo bash /home/robot/setup_ti_radar_udev.sh"
probe_serial_device "${TI_COMMAND_PORT}" "TI command port"
probe_serial_device "${TI_DATA_PORT}" "TI data port"

echo "-> [OK] TI command/data port 檢查通過"
echo "-> 雷達 log: ${RADAR_LOG}"
echo "-> 相機 log: ${CAMERA_LOG}"

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
  rviz:="${TI_RVIZ}" >"${RADAR_LOG}" 2>&1 &
PID_RADAR=$!

echo "-> 等待雷達穩定 (10 秒)..."
sleep 10
check_radar_launch_health

# 2. 啟動攝影機
echo "-> 正在啟動攝影機..."
ros2 launch sensor_fusion_pkg camera.launch.py video_device:="${CAMERA_DEVICE}" >"${CAMERA_LOG}" 2>&1 &
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
  abort_with_log_excerpt "未偵測到雷達 topic ${RADAR_TOPIC}，已自動中止錄製流程" "${RADAR_LOG}"
fi

echo "-> 正在檢查雷達 topic 是否真的有資料..."
if wait_for_topic_message "${RADAR_TOPIC}" 8s "${RADAR_MSG_CHECK_LOG}"; then
  echo "-> [OK] 已收到雷達訊息: ${RADAR_TOPIC}"
else
  echo "-> [錯誤] 雷達 topic 已存在，但 8 秒內沒有收到任何資料: ${RADAR_TOPIC}"
  echo "-> [診斷] 這種情況會造成 bag 裡 topic count = 0"
  abort_with_log_excerpt "雷達資料流未建立，已自動中止錄製流程" "${RADAR_MSG_CHECK_LOG}"
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

echo "-> 正在檢查影像 topic 是否真的有資料..."
if wait_for_topic_message "${IMAGE_TOPIC}" 8s "${IMAGE_MSG_CHECK_LOG}"; then
  echo "-> [OK] 已收到影像訊息: ${IMAGE_TOPIC}"
else
  echo "-> [錯誤] 影像 topic 已存在，但 8 秒內沒有收到任何資料: ${IMAGE_TOPIC}"
  abort_with_log_excerpt "影像資料流未建立，已自動中止錄製流程" "${IMAGE_MSG_CHECK_LOG}"
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
