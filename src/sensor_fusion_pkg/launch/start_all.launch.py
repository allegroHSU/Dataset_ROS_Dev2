import os
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, TimerAction, LogInfo
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():

    # 1. 定義雷達啟動檔的位置 (TI Radar)
    radar_pkg_dir = get_package_share_directory('ti_mmwave_rospkg')
    radar_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(radar_pkg_dir, 'launch', '6843AOP_StaticTracking.py')
        )
    )

    # 2. 定義攝影機啟動檔的位置 (Camera)
    camera_pkg_dir = get_package_share_directory('sensor_fusion_pkg')
    camera_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(camera_pkg_dir, 'launch', 'camera.launch.py')
        )
    )

    # 3. 建立「延遲啟動」機制
    # 這就是您要的功能：等待 5 秒後，才執行 camera_launch
    delayed_camera_action = TimerAction(
        period=5.0,  # 延遲 5 秒
        actions=[
            LogInfo(msg="=========================================="),
            LogInfo(msg="雷達已啟動 5 秒，現在準備啟動攝影機..."),
            LogInfo(msg="=========================================="),
            camera_launch
        ]
    )

    # 4. 回傳流程描述 (順序：先雷達 -> 計時器會自己算 5 秒 -> 攝影機)
    return LaunchDescription([
        radar_launch,
        delayed_camera_action
    ])