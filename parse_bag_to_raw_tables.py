from __future__ import annotations

"""Standalone VM parser for rosbag2 raw-table export."""

import argparse
import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    yaml = None

try:
    import cv2  # type: ignore
    import numpy as np
    CV2_AVAILABLE = True
except Exception:
    CV2_AVAILABLE = False


@dataclass
class ParseConfig:
    radar_topic: str = "/ti_mmwave/radar_scan_pcl"
    image_topic: str = "/camera/color/image_raw"
    sync_ok_threshold_ms: float = 50.0
    missing_image_threshold_frames: int = 3
    camera_fps: float = 30.0
    extract_video: bool = True
    video_fps: float = 30.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Formal MCAP-first rosbag2 -> raw-table entrypoint for extract_material_features."
    )
    parser.add_argument(
        "--bag-path",
        required=True,
        type=Path,
        help="Path to an .mcap file or a rosbag2 bag directory containing metadata.yaml.",
    )
    parser.add_argument("--output-dir", required=True, type=Path, help="Directory for exported raw tables.")
    parser.add_argument("--session-id", required=True, help="Dataset session id.")
    parser.add_argument("--run-id", required=True, help="Dataset run id.")
    parser.add_argument("--radar-topic", default=ParseConfig.radar_topic)
    parser.add_argument("--image-topic", default=ParseConfig.image_topic)
    parser.add_argument(
        "--camera-fps",
        type=float,
        default=ParseConfig.camera_fps,
        help="Actual camera FPS used to determine image-missing thresholds.",
    )
    parser.add_argument("--video-fps", type=float, default=ParseConfig.video_fps, help="FPS for extracted video")
    parser.add_argument(
        "--no-video",
        action="store_true",
        help="Disable automatic mp4 video extraction even if cv2 is installed",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Only export metadata/topic summaries and empty raw-table schemas.",
    )
    return parser.parse_args()


def ensure_bag_path(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Bag path does not exist: {path}")
    if path.is_file() and path.suffix.lower() != ".mcap":
        raise ValueError(f"Bag file input must be an .mcap file: {path}")
    if not path.is_dir() and not path.is_file():
        raise ValueError(f"Bag path must be an .mcap file or a rosbag2 bag directory: {path}")


def discover_rosbag2_files(path: Path) -> Dict[str, Optional[Path]]:
    if path.is_file():
        metadata_yaml = path.parent / "metadata.yaml"
        sqlite_db = None
        mcap_file = path if path.suffix.lower() == ".mcap" else None
    else:
        metadata_yaml = path / "metadata.yaml"
        sqlite_db = next(iter(sorted(path.glob("*.db3"))), None)
        mcap_file = next(iter(sorted(path.glob("*.mcap"))), None)
    return {
        "metadata_yaml": metadata_yaml if metadata_yaml.exists() else None,
        "sqlite_db": sqlite_db,
        "mcap_file": mcap_file,
    }


def infer_storage_id(bag_path: Path, files: Dict[str, Optional[Path]], metadata_info: Dict[str, Any]) -> str:
    storage_identifier = metadata_info.get("storage_identifier")
    if isinstance(storage_identifier, str) and storage_identifier.strip():
        return storage_identifier.strip()
    if bag_path.is_file() and bag_path.suffix.lower() == ".mcap":
        return "mcap"
    if files.get("mcap_file") is not None:
        return "mcap"
    if files.get("sqlite_db") is not None:
        return "sqlite3"
    print(
        "[WARNING] infer_storage_id: 無法從 metadata.yaml、bag 副檔名或目錄內容判定 storage_id。"
        " 將以空字串傳入 rosbag2_py.StorageOptions，可能導致解析失敗。"
        " 請確認 bag 目錄內含有 .mcap 或 .db3 檔案，或 metadata.yaml 內有 storage_identifier 欄位。"
    )
    return ""


def load_metadata_yaml(metadata_path: Optional[Path]) -> Dict[str, Any]:
    if metadata_path is None or not metadata_path.exists():
        return {}
    if yaml is None:
        return {"_warning": "PyYAML not installed; metadata.yaml content not parsed."}

    raw = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    # rosbag2 metadata usually nests under 'rosbag2_bagfile_information'
    info = raw.get("rosbag2_bagfile_information", raw)
    return info if isinstance(info, dict) else {}


def extract_metadata_topics(metadata_info: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    topic_entries = metadata_info.get("topics_with_message_count", [])
    if not isinstance(topic_entries, list):
        return rows

    for entry in topic_entries:
        if not isinstance(entry, dict):
            continue
        topic_meta = entry.get("topic_metadata", {}) if isinstance(entry.get("topic_metadata", {}), dict) else {}
        rows.append(
            {
                "topic_id": None,
                "topic_name": topic_meta.get("name"),
                "topic_type": topic_meta.get("type"),
                "serialization_format": topic_meta.get("serialization_format"),
                "offered_qos_profiles": topic_meta.get("offered_qos_profiles"),
                "message_count": entry.get("message_count"),
                "source": "metadata_yaml",
                "first_timestamp_ns": None,
                "last_timestamp_ns": None,
            }
        )
    return rows


def inspect_sqlite_topics(sqlite_path: Optional[Path]) -> List[Dict[str, Any]]:
    if sqlite_path is None or not sqlite_path.exists():
        return []

    query = """
    SELECT
        t.id AS topic_id,
        t.name AS topic_name,
        t.type AS topic_type,
        t.serialization_format AS serialization_format,
        t.offered_qos_profiles AS offered_qos_profiles,
        COUNT(m.id) AS message_count,
        MIN(m.timestamp) AS first_timestamp_ns,
        MAX(m.timestamp) AS last_timestamp_ns
    FROM topics t
    LEFT JOIN messages m ON m.topic_id = t.id
    GROUP BY t.id, t.name, t.type, t.serialization_format, t.offered_qos_profiles
    ORDER BY t.id
    """

    conn = sqlite3.connect(str(sqlite_path))
    try:
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()

    if df.empty:
        return []
    df["source"] = "sqlite_db"
    return df.to_dict(orient="records")


def merge_topic_rows(metadata_rows: List[Dict[str, Any]], sqlite_rows: List[Dict[str, Any]]) -> pd.DataFrame:
    merged: Dict[str, Dict[str, Any]] = {}

    def upsert(row: Dict[str, Any]) -> None:
        topic_name = row.get("topic_name")
        if not topic_name:
            return
        if topic_name not in merged:
            merged[topic_name] = {
                "topic_id": row.get("topic_id"),
                "topic_name": topic_name,
                "topic_type": row.get("topic_type"),
                "serialization_format": row.get("serialization_format"),
                "offered_qos_profiles": row.get("offered_qos_profiles"),
                "message_count": row.get("message_count"),
                "first_timestamp_ns": row.get("first_timestamp_ns"),
                "last_timestamp_ns": row.get("last_timestamp_ns"),
                "source": row.get("source"),
            }
            return

        existing = merged[topic_name]
        for key in [
            "topic_id",
            "topic_type",
            "serialization_format",
            "offered_qos_profiles",
            "message_count",
            "first_timestamp_ns",
            "last_timestamp_ns",
        ]:
            if existing.get(key) in (None, "") and row.get(key) not in (None, ""):
                existing[key] = row.get(key)
        existing["source"] = "+".join(sorted(set(str(existing["source"]).split("+") + [str(row.get("source"))])))

    for row in metadata_rows:
        upsert(row)
    for row in sqlite_rows:
        upsert(row)

    topic_df = pd.DataFrame(list(merged.values()))
    if topic_df.empty:
        topic_df = pd.DataFrame(
            columns=[
                "topic_id",
                "topic_name",
                "topic_type",
                "serialization_format",
                "offered_qos_profiles",
                "message_count",
                "first_timestamp_ns",
                "last_timestamp_ns",
                "source",
            ]
        )
    return topic_df.sort_values("topic_name", kind="stable").reset_index(drop=True)


def build_empty_frame_table() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "frame_uid",
            "session_id",
            "run_id",
            "frame_id",
            "radar_stamp_s",
            "frame_relative_time_s",
            "matched_image_stamp_s",
            "delta_ms",
            "sync_quality",
            "num_points",
            "is_drop_frame",
            "notes",
        ]
    )


def build_empty_points_table() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "frame_uid",
            "point_id",
            "x",
            "y",
            "z",
            "snr",
            "doppler",
            "range",
            "azimuth",
            "elevation",
            "intensity",
        ]
    )


def build_empty_alignment_table() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "frame_uid",
            "radar_stamp_s",
            "matched_image_stamp_s",
            "delta_ms",
            "sync_quality",
        ]
    )


def detect_decoder_support() -> Dict[str, Any]:
    try:
        import rosbag2_py  # type: ignore  # noqa: F401

        rosbag2_available = True
    except Exception as exc:  # pragma: no cover - environment dependent
        rosbag2_available = False
        return {
            "rosbag2_py_available": False,
            "decoder_status": "not_available",
            "decoder_note": f"rosbag2_py import failed: {exc}",
        }

    return {
        "rosbag2_py_available": rosbag2_available,
        "decoder_status": "available_for_decode",
        "decoder_note": (
            "rosbag2_py is importable and message deserialization can be attempted when the "
            "runtime provides the required ROS2 Python packages."
        ),
    }


def try_import_rosbag_runtime() -> Dict[str, Any]:
    try:
        import rosbag2_py  # type: ignore
        from rclpy.serialization import deserialize_message  # type: ignore
        from rosidl_runtime_py.utilities import get_message  # type: ignore
        from sensor_msgs_py import point_cloud2  # type: ignore

        return {
            "ok": True,
            "rosbag2_py": rosbag2_py,
            "deserialize_message": deserialize_message,
            "get_message": get_message,
            "point_cloud2": point_cloud2,
            "note": "ROS2 runtime imports succeeded.",
        }
    except Exception as exc:  # pragma: no cover - environment dependent
        return {
            "ok": False,
            "error": str(exc),
            "note": "ROS2 runtime imports failed; falling back to metadata/schema export only.",
        }


def get_message_stamp_ns(msg: Any, fallback_ns: int) -> int:
    header = getattr(msg, "header", None)
    stamp = getattr(header, "stamp", None)
    sec = getattr(stamp, "sec", None)
    nanosec = getattr(stamp, "nanosec", None)
    if sec is None or nanosec is None:
        return int(fallback_ns)
    return int(sec) * 1_000_000_000 + int(nanosec)


def first_present(mapping: Dict[str, Any], names: Sequence[str], default: float = math.nan) -> float:
    for name in names:
        if name in mapping and mapping[name] is not None:
            value = mapping[name]
            try:
                return float(value)
            except Exception:
                return default
    return default


def compute_range_azimuth_elevation(x: float, y: float, z: float) -> Tuple[float, float, float]:
    if any(math.isnan(v) for v in (x, y, z)):
        return math.nan, math.nan, math.nan

    rng = math.sqrt(x * x + y * y + z * z)
    azimuth = math.degrees(math.atan2(y, x)) if not math.isclose(x, 0.0) or not math.isclose(y, 0.0) else 0.0
    elevation = math.degrees(math.atan2(z, math.sqrt(x * x + y * y))) if rng > 0 else 0.0
    return rng, azimuth, elevation


def decode_point_cloud_rows(msg: Any, point_cloud2_module: Any) -> List[Dict[str, Any]]:
    field_names = [field.name for field in getattr(msg, "fields", [])]
    if not field_names:
        return []

    rows: List[Dict[str, Any]] = []
    for point in point_cloud2_module.read_points(msg, field_names=field_names, skip_nans=False):
        raw = dict(zip(field_names, point))
        x = first_present(raw, ["x"])
        y = first_present(raw, ["y"])
        z = first_present(raw, ["z"])
        snr = first_present(raw, ["snr", "SNR", "intensity"])
        doppler = first_present(raw, ["doppler", "velocity", "vel", "v"])
        intensity = first_present(raw, ["intensity", "reflectivity", "power"])
        rng, azimuth, elevation = compute_range_azimuth_elevation(x, y, z)
        rows.append(
            {
                "x": x,
                "y": y,
                "z": z,
                "snr": snr,
                "doppler": doppler,
                "range": rng,
                "azimuth": azimuth,
                "elevation": elevation,
                "intensity": intensity,
            }
        )
    return rows


def decode_image_to_bgr(msg: Any) -> "np.ndarray":
    width = int(msg.width)
    height = int(msg.height)
    encoding = str(getattr(msg, "encoding", "")).lower()
    data = np.frombuffer(msg.data, dtype=np.uint8)

    if encoding in {"bgr8", "rgb8"}:
        img = data.reshape((height, width, 3))
        if encoding == "rgb8":
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        return img

    if encoding in {"bgra8", "rgba8"}:
        img = data.reshape((height, width, 4))
        code = cv2.COLOR_BGRA2BGR if encoding == "bgra8" else cv2.COLOR_RGBA2BGR
        return cv2.cvtColor(img, code)

    if encoding in {"mono8", "8uc1"}:
        img = data.reshape((height, width))
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    if encoding in {"mono16", "16uc1"}:
        img16 = np.frombuffer(msg.data, dtype=np.uint16).reshape((height, width))
        img8 = cv2.convertScaleAbs(img16, alpha=(255.0 / 65535.0))
        return cv2.cvtColor(img8, cv2.COLOR_GRAY2BGR)

    raise ValueError(f"Unsupported image encoding for video export: {encoding or '<empty>'}")


def classify_sync_quality(delta_ms: float, cfg: ParseConfig) -> str:
    if math.isnan(delta_ms):
        return "missing_image"

    camera_interval_ms = 1000.0 / cfg.camera_fps if cfg.camera_fps > 0 else 33.3
    missing_threshold_ms = cfg.missing_image_threshold_frames * camera_interval_ms
    
    if abs(delta_ms) <= cfg.sync_ok_threshold_ms:
        return "ok"
    elif abs(delta_ms) <= missing_threshold_ms:
        return "sync_uncertain"
    else:
        return "missing_image"


def attach_image_alignment(frame_df: pd.DataFrame, image_stamps_ns: Sequence[int], cfg: ParseConfig) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if frame_df.empty:
        return frame_df, build_empty_alignment_table()

    matched_stamps_s: List[float] = []
    delta_ms_list: List[float] = []
    quality_list: List[str] = []

    image_sorted = sorted(int(v) for v in image_stamps_ns)
    for radar_stamp_s in frame_df["radar_stamp_s"].tolist():
        radar_ns = int(round(float(radar_stamp_s) * 1_000_000_000))
        if not image_sorted:
            matched_stamps_s.append(math.nan)
            delta_ms_list.append(math.nan)
            quality_list.append("missing_image")
            continue

        best_ns = min(image_sorted, key=lambda img_ns: abs(img_ns - radar_ns))
        delta_ms = (best_ns - radar_ns) / 1_000_000.0
        matched_stamps_s.append(best_ns / 1_000_000_000.0)
        delta_ms_list.append(delta_ms)
        quality_list.append(classify_sync_quality(delta_ms, cfg))

    frame_df = frame_df.copy()
    frame_df["matched_image_stamp_s"] = matched_stamps_s
    frame_df["delta_ms"] = delta_ms_list
    frame_df["sync_quality"] = quality_list

    align_df = frame_df[["frame_uid", "radar_stamp_s", "matched_image_stamp_s", "delta_ms", "sync_quality"]].copy()
    return frame_df, align_df


def decode_rosbag_topics(
    bag_path: Path,
    files: Dict[str, Optional[Path]],
    metadata_info: Dict[str, Any],
    session_id: str,
    run_id: str,
    output_dir: Path,
    cfg: ParseConfig,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    runtime = try_import_rosbag_runtime()
    if not runtime["ok"]:
        return build_empty_frame_table(), build_empty_points_table(), build_empty_alignment_table(), {
            "decoder_status": "runtime_import_failed",
            "decoder_note": runtime["note"],
            "decoder_error": runtime["error"],
            "radar_frames_decoded": 0,
            "image_messages_seen": 0,
        }

    rosbag2_py = runtime["rosbag2_py"]
    deserialize_message = runtime["deserialize_message"]
    get_message = runtime["get_message"]
    point_cloud2_module = runtime["point_cloud2"]

    storage_id = infer_storage_id(bag_path, files, metadata_info)
    storage_options = rosbag2_py.StorageOptions(uri=str(bag_path), storage_id=storage_id)
    converter_options = rosbag2_py.ConverterOptions(
        input_serialization_format="cdr",
        output_serialization_format="cdr",
    )
    reader = rosbag2_py.SequentialReader()
    reader.open(storage_options, converter_options)

    topic_types = {topic.name: topic.type for topic in reader.get_all_topics_and_types()}
    radar_type = topic_types.get(cfg.radar_topic)
    image_type = topic_types.get(cfg.image_topic)

    if radar_type is None:
        return build_empty_frame_table(), build_empty_points_table(), build_empty_alignment_table(), {
            "decoder_status": "radar_topic_not_found",
            "decoder_note": f"Radar topic not found in bag: {cfg.radar_topic}",
            "storage_id": storage_id,
            "radar_frames_decoded": 0,
            "image_messages_seen": 0,
        }

    radar_msg_type = get_message(radar_type)
    image_msg_type = get_message(image_type) if image_type else None

    frame_rows: List[Dict[str, Any]] = []
    point_rows: List[Dict[str, Any]] = []
    image_stamps_ns: List[int] = []
    first_radar_ns: Optional[int] = None
    frame_index = 1

    video_writer = None
    output_video_path = output_dir / "run_video.mp4"
    if cfg.extract_video and CV2_AVAILABLE:
        output_dir.mkdir(parents=True, exist_ok=True)

    try:
        while reader.has_next():
            topic_name, raw_data, bag_timestamp_ns = reader.read_next()
            if topic_name == cfg.image_topic and image_msg_type is not None:
                image_msg = deserialize_message(raw_data, image_msg_type)
                image_stamps_ns.append(get_message_stamp_ns(image_msg, bag_timestamp_ns))
                
                if cfg.extract_video and CV2_AVAILABLE:
                    width = int(image_msg.width)
                    height = int(image_msg.height)
                    try:
                        img_array = decode_image_to_bgr(image_msg)
                    except Exception:
                        continue

                    if video_writer is None:
                        fourcc = cv2.VideoWriter_fourcc(*'mp4v') # type: ignore
                        video_writer = cv2.VideoWriter(str(output_video_path), fourcc, cfg.video_fps, (width, height))

                    video_writer.write(img_array)
                continue

            if topic_name != cfg.radar_topic:
                continue

            radar_msg = deserialize_message(raw_data, radar_msg_type)
            radar_stamp_ns = get_message_stamp_ns(radar_msg, bag_timestamp_ns)
            if first_radar_ns is None:
                first_radar_ns = radar_stamp_ns

            decoded_points = decode_point_cloud_rows(radar_msg, point_cloud2_module)
            frame_uid = f"{session_id}_{run_id}_f{frame_index:06d}"
            radar_stamp_s = radar_stamp_ns / 1_000_000_000.0
            frame_relative_time_s = (
                (radar_stamp_ns - first_radar_ns) / 1_000_000_000.0 if first_radar_ns is not None else 0.0
            )

            # NOTE: is_drop_frame is always False in the current implementation.
            # UART / CRC / packet-loss drop detection is not yet implemented.
            # All downstream QC logic that relies on drop_frame_count / drop_ratio
            # (e.g. quality_flag = radar_dropout) will see 0 drops until this is added.
            frame_rows.append(
                {
                    "frame_uid": frame_uid,
                    "session_id": session_id,
                    "run_id": run_id,
                    "frame_id": frame_index,
                    "radar_stamp_s": radar_stamp_s,
                    "frame_relative_time_s": frame_relative_time_s,
                    "matched_image_stamp_s": math.nan,
                    "delta_ms": math.nan,
                    "sync_quality": "missing_image",
                    "num_points": len(decoded_points),
                    "is_drop_frame": False,
                    "notes": "",
                }
            )

            for point_id, point in enumerate(decoded_points):
                point_rows.append({"frame_uid": frame_uid, "point_id": point_id, **point})

            frame_index += 1
    finally:
        if video_writer is not None:
            video_writer.release()

    frame_df = pd.DataFrame(frame_rows, columns=build_empty_frame_table().columns)
    points_df = pd.DataFrame(point_rows, columns=build_empty_points_table().columns)
    frame_df, align_df = attach_image_alignment(frame_df, image_stamps_ns, cfg)

    decoder_info = {
        "decoder_status": "decoded",
        "decoder_note": "ROS2 runtime decoding succeeded for radar/image topics.",
        "storage_id": storage_id,
        "radar_topic_type": radar_type,
        "image_topic_type": image_type,
        "radar_frames_decoded": int(len(frame_df)),
        "image_messages_seen": int(len(image_stamps_ns)),
        "is_drop_frame_implemented": False,
        "is_drop_frame_note": (
            "Drop-frame detection (UART/CRC/packet-loss) is not yet implemented. "
            "All frames are exported with is_drop_frame=False. "
            "Downstream drop_frame_count and drop_ratio will reflect 0 drops."
        ),
    }
            
    if cfg.extract_video and not CV2_AVAILABLE:
        decoder_info["decoder_note"] += " (Video extraction skipped: opencv-python not installed)"
        
    return frame_df, points_df, align_df, decoder_info


def write_tables(
    output_dir: Path,
    frame_df: pd.DataFrame,
    points_df: pd.DataFrame,
    align_df: pd.DataFrame,
    topic_df: pd.DataFrame,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    frame_df.to_parquet(output_dir / "frame_table.parquet", index=False)
    points_df.to_parquet(output_dir / "points_table.parquet", index=False)
    align_df.to_csv(output_dir / "image_alignment_table.csv", index=False)
    topic_df.to_csv(output_dir / "topic_summary.csv", index=False)


def build_report(
    bag_path: Path,
    session_id: str,
    run_id: str,
    files: Dict[str, Optional[Path]],
    cfg: ParseConfig,
    metadata_info: Dict[str, Any],
    topic_df: pd.DataFrame,
    decoder_info: Dict[str, Any],
) -> Dict[str, Any]:
    duration_ns = metadata_info.get("duration", {}).get("nanoseconds") if isinstance(metadata_info.get("duration"), dict) else None
    start_ns = metadata_info.get("starting_time", {}).get("nanoseconds_since_epoch") if isinstance(metadata_info.get("starting_time"), dict) else None
    decoder_status = str(decoder_info.get("decoder_status", "unknown"))

    if decoder_status == "decoded":
        status = "decoded_raw_tables_exported"
        note = (
            "Raw tables, topic summary, parser report, and optional run_video.mp4 were exported "
            "from ROS2 bag topics successfully."
        )
    elif decoder_status in {"runtime_import_failed", "radar_topic_not_found"}:
        status = "metadata_and_schema_export_only"
        note = (
            "Raw-table decoding was not completed. The parser exported schemas, topic summary, "
            "and parser report for diagnostics."
        )
    else:
        status = "metadata_and_schema_export_only"
        note = (
            "Formal raw-table schemas, topic summary, and parser report were created. "
            "Topic/message decoding was skipped or is not available in the current runtime."
        )

    return {
        "bag_path": str(bag_path),
        "session_id": session_id,
        "run_id": run_id,
        "discovered_files": {k: (str(v) if v else None) for k, v in files.items()},
        "config": asdict(cfg),
        "storage_identifier": metadata_info.get("storage_identifier"),
        "duration_ns": duration_ns,
        "starting_time_ns": start_ns,
        "message_count": metadata_info.get("message_count"),
        "topics_discovered": topic_df.to_dict(orient="records"),
        "decoder": decoder_info,
        "status": status,
        "note": note,
    }


def write_parser_report(output_dir: Path, report: Dict[str, Any]) -> None:
    (output_dir / "parse_bag_to_raw_tables_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    cfg = ParseConfig(
        radar_topic=args.radar_topic, 
        image_topic=args.image_topic,
        camera_fps=args.camera_fps,
        extract_video=not args.no_video,
        video_fps=args.video_fps
    )
    ensure_bag_path(args.bag_path)

    files = discover_rosbag2_files(args.bag_path)
    metadata_info = load_metadata_yaml(files["metadata_yaml"])
    metadata_rows = extract_metadata_topics(metadata_info)
    sqlite_rows = inspect_sqlite_topics(files["sqlite_db"])
    topic_df = merge_topic_rows(metadata_rows, sqlite_rows)
    decoder_info = detect_decoder_support()

    if args.metadata_only:
        frame_df = build_empty_frame_table()
        points_df = build_empty_points_table()
        align_df = build_empty_alignment_table()
    else:
        frame_df, points_df, align_df, decoder_info = decode_rosbag_topics(
            bag_path=args.bag_path,
            files=files,
            metadata_info=metadata_info,
            session_id=args.session_id,
            run_id=args.run_id,
            output_dir=args.output_dir,
            cfg=cfg,
        )

    write_tables(args.output_dir, frame_df, points_df, align_df, topic_df)
    report = build_report(
        bag_path=args.bag_path,
        session_id=args.session_id,
        run_id=args.run_id,
        files=files,
        cfg=cfg,
        metadata_info=metadata_info,
        topic_df=topic_df,
        decoder_info=decoder_info,
    )
    write_parser_report(args.output_dir, report)

    print("Wrote frame_table.parquet, points_table.parquet, image_alignment_table.csv, topic_summary.csv, and parse_bag_to_raw_tables_report.json.")
    if args.metadata_only:
        print("Metadata-only mode requested; topic/message decoding was skipped.")
    else:
        print(report["note"])
        print(f"Decoder status: {decoder_info['decoder_status']}")


if __name__ == "__main__":
    main()
