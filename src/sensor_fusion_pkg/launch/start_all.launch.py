import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction, LogInfo
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    command_port = LaunchConfiguration('command_port')
    data_port = LaunchConfiguration('data_port')
    camera_device = LaunchConfiguration('camera_device')
    startup_delay = LaunchConfiguration('startup_delay')

    radar_pkg_dir = get_package_share_directory('ti_mmwave_rospkg')
    radar_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(radar_pkg_dir, 'launch', '6843AOP_StaticTracking.py')
        ),
        launch_arguments={
            'command_port': command_port,
            'data_port': data_port,
            'rviz': 'false',
        }.items()
    )

    camera_pkg_dir = get_package_share_directory('sensor_fusion_pkg')
    camera_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(camera_pkg_dir, 'launch', 'camera.launch.py')
        ),
        launch_arguments={
            'video_device': camera_device,
        }.items()
    )

    delayed_camera_action = TimerAction(
        period=startup_delay,
        actions=[
            LogInfo(msg="=========================================="),
            LogInfo(msg="雷達已啟動 5 秒，現在準備啟動攝影機..."),
            LogInfo(msg="=========================================="),
            camera_launch
        ]
    )

    return LaunchDescription([
        DeclareLaunchArgument('command_port', default_value='/dev/ti_radar_command'),
        DeclareLaunchArgument('data_port', default_value='/dev/ti_radar_data'),
        DeclareLaunchArgument('camera_device', default_value='/dev/video0'),
        DeclareLaunchArgument('startup_delay', default_value='5.0'),
        radar_launch,
        delayed_camera_action
    ])
