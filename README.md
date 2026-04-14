# Dataset_ROS_Dev2 (Data Collection ROS2 node)

這是專為穿透實驗資料收集同步資料所建立的ROS2 node。
適用於 x86 PC 主機、NVIDIA Jetson Orin NX / NANO 平台 或 VM 環境。

## 📦 部署指南 (Deployment)

1. **取得程式碼**

```bash
git clone https://github.com/allegroHSU/Dataset_ROS_Dev2.git
cd Dataset_ROS_Dev2
```

1. **安裝系統相依套件**

```bash
rosdep update
rosdep install --from-paths src --ignore-src -r -y
```

1. **編譯工作區**
每次在新的實體機器 (如 Orin) 或 Container 內拉下程式碼後，必須重新編譯：

```bash
colcon build --symlink-install
```

## 🚀 執行資料採集

1. 確認硬體（TI 毫米波雷達 `/dev/ttyUSB*`、攝影機 `/dev/video*`）已接妥。
2. 載入環境並執行錄製：

```bash
source install/setup.bash
./record_data.sh
```

執行 `record_data.sh` 時，rosbag2 會使用 `mcap` storage 錄製資料，而不是預設的 `sqlite3/.db3`。

## ✅ 錄完 bag 後只檢查這 3 件事

1. 確認 bag 目錄已成功產生，且格式為 `mcap`：

```bash
ros2 bag info <bag_directory>
```

2. 確認影像與雷達五維點雲 topic 都有錄到：

```bash
ros2 bag info <bag_directory>
```

至少應看到：
- `/image_raw`
- `/ti_mmwave/radar_scan_pcl`

3. 抽查回放資料，確認影像可看到人出現，且雷達點雲有隨時間正常輸出：

```bash
ros2 bag play <bag_directory>
```

錄製完成後，請同步填寫 `run_log.csv`，紀錄本次採集條件、時間與備註，避免後續對資料來源混淆。

## 🧩 Bag 解析用法

若要將錄製完成的 `mcap` bag 解析成原始表格，可執行：

```bash
python3 /home/chris/Dataset_ROS_Dev2/parse_bag_to_raw_tables.py \
  --bag-path /home/chris/Dataset_ROS_Dev2/dataset_20260414_101911 \
  --output-dir /home/chris/Dataset_ROS_Dev2/dataset_20260414_101911 \
  --session-id 20260414 \
  --run-id 101911 \
  --radar-topic /ti_mmwave/radar_scan_pcl \
  --image-topic /image_raw
```

其中 `--radar-topic` 應使用 RViz 顯示的點雲 topic：
- `/ti_mmwave/radar_scan_pcl`
