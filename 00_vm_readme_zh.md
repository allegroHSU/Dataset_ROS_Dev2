# zone_level / VM

`VM (Ubuntu + ROS2)` 端負責：

- 讀取 `rosbag2` bag
- 解析 ROS2 topics
- 輸出 raw tables 與 `run_video.mp4`

目前使用腳本：

- `parse_bag_to_raw_tables.py`

狀態說明：

- 本頁只描述 VM 端目前已放入的正式入口與使用方法。
- 全管線後續的 labels / merge / split 步驟不在 VM 端完成，且其實作狀態請回看 `../../05_bag_to_training_tables_script_spec_zh.md`。
- `parse_bag_to_raw_tables_report.json` 會依實際執行情況標示 `decoded_raw_tables_exported` 或 metadata-only 類型狀態，方便回查當次解析是否真的完成 topic 解碼。
- 目前影片抽取已明確支援 `bgr8`、`rgb8`、`bgra8`、`rgba8`、`mono8`、`8UC1`、`mono16`、`16UC1`；若遇到其他 encoding，表格仍可輸出，但 `run_video.mp4` 可能會被跳過。

**SNR 欄位對應（TI mmWave 專屬）：**

- TI mmWave ROS2 driver 的 `/ti_mmwave/radar_scan_pcl` PointCloud2 訊息**沒有獨立 `snr` 欄位**，SNR 值是存在 `intensity` 欄位中（見 `ti_mmwave_rospkg/src/DataHandlerClass.cpp`）。
- `parse_bag_to_raw_tables.py` 在 `decode_point_cloud_rows()` 的 SNR fallback 順序為 `["snr", "SNR", "intensity"]`，可正確抓到 TI driver 填入 intensity 的 SNR 值。
- **舊版解析結果 `snr` 全為 NULL 的修補**：若你手邊有舊的 `points_table.parquet` 是用修正前的腳本解的，可用 `DataSet/patch_snr_from_intensity.py` 在 PC 端就地補回 `snr`，不需回到 VM 重跑一次。

這支 `parse_bag_to_raw_tables.py` 現在是可獨立執行的正式版本，可以直接複製到 VM / ROS2 node 工作目錄使用，不再依賴 repo 內的相對路徑。

執行時請使用正式參數名稱 `--bag-path`，不要使用 `--bag-dir`。

如果 bag 內實際 topic 名稱與預設值不同，請額外指定：

- `--radar-topic`
- `--image-topic`

**重要參數提醒**：

- `--camera-fps`：預設為 30.0，用來表示攝影機實際 FPS，並據此計算 `missing_image_threshold_frames` 對應的時間容忍範圍。
- `--video-fps`：預設為 30.0，只影響輸出的 `run_video.mp4` 播放 FPS，不影響 `sync_quality` 判定。
- 如果現場攝影機實際是 10 FPS，建議至少傳入 `--camera-fps 10`。若也希望輸出的影片維持 10 FPS，再額外加上 `--video-fps 10`。

**關於 `sync_ok_threshold_ms` 與 `missing_image_threshold_frames`**：

一頁式 checklist Section A 要求確認這兩個參數，但 `parse_bag_to_raw_tables.py` 目前沒有對應的 CLI 參數；
它們以硬碼預設值存在 `ParseConfig`：

- `sync_ok_threshold_ms = 50.0`（radar 與影像時間差在 50 ms 以內 → `ok`）
- `missing_image_threshold_frames = 3`（超過 3 個 camera 間隔視為 `missing_image`；實際容忍毫秒數 = `3 × (1000 / camera_fps)`）

如果現場 camera FPS 或同步容忍範圍與預設值不同，目前必須直接修改腳本內的 `ParseConfig` 類別。
`--camera-fps` 是唯一能影響 `missing_image` 門檻的 CLI 參數（透過改變 camera 間隔毫秒數）。

建議先安裝：

```bash
python3 -m pip install --user pandas pyarrow pyyaml opencv-python numpy
```

範例指令（以 10 FPS 攝影機為例）：

```bash
python3 /home/chris/Dataset_ROS_Dev2/parse_bag_to_raw_tables.py \
  --bag-path /home/chris/Dataset_ROS_Dev2/dataset_20260414_083138 \
  --output-dir /home/chris/Dataset_ROS_Dev2/dataset_20260414_083138 \
  --session-id 20260414 \
  --run-id 083138 \
  --radar-topic /ti_mmwave/radar_scan_pcl \
  --image-topic /image_raw \
  --camera-fps 10 \
  --video-fps 10
```

建議在 Ubuntu VM 執行前先檢查腳本是否為正常文字檔：

```bash
file /home/chris/Dataset_ROS_Dev2/parse_bag_to_raw_tables.py
head -20 /home/chris/Dataset_ROS_Dev2/parse_bag_to_raw_tables.py
grep -n -- "--bag-path" /home/chris/Dataset_ROS_Dev2/parse_bag_to_raw_tables.py
```


