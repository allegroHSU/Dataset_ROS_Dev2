#!/bin/bash

# 設定儲存資料夾名稱，加上時間戳記避免重複
BAG_NAME="dataset_$(date +%Y%m%d_%H%M%S)"

echo "=========================================="
echo "   資料採集系統"
echo "=========================================="

# 0. 自動賦予權限 (省去手動打指令)
echo "-> [自動] 賦予 USB 與攝影機權限..."
sudo chmod 666 /dev/ttyACM* /dev/ttyUSB* /dev/video0

# 1. 啟動雷達
echo "-> 正在啟動雷達 (無 Rviz 模式)..."
ros2 launch ti_mmwave_rospkg 6843AOP_StaticTracking.py &
PID_RADAR=$!

echo "-> 等待雷達穩定 (10 秒)..."
sleep 10
# 2. 啟動攝影機
echo "-> 正在啟動攝影機..."
ros2 launch sensor_fusion_pkg camera.launch.py &
PID_CAMERA=$!

echo "-> 等待攝影機穩定 (5 秒)..."
sleep 5

# 3. 開始錄製
echo "------------------------------------------"
echo "-> 系統就緒！開始錄製資料夾: $BAG_NAME"
echo "-> 錄製中，請勿拔除 USB 線..."
echo "-> 按 [Ctrl+C] 結束錄製"
echo "------------------------------------------"

# 執行錄影
ros2 bag record -o $BAG_NAME \
    /image_raw \
    /ti_mmwave/radar_scan \
    /ti_mmwave/radar_scan_pcl \
    /ti_mmwave/radar_track_array \
    /ti_mmwave/radar_micro_doppler_data_array

# --- 結束處理 (優雅關閉) ---
echo "-> 正在關閉感測器..."
kill -SIGINT $PID_CAMERA
sleep 1
kill -SIGINT $PID_RADAR
echo "-> 錄製完成！資料已儲存於 $BAG_NAME"