import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import IncludeLaunchDescription
from launch.substitutions import LaunchConfiguration
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():

    rviz_arg = DeclareLaunchArgument('rviz', default_value='false', description='Enable RViz')
    command_port_arg = DeclareLaunchArgument('command_port', default_value='/dev/ti_radar_command')
    data_port_arg = DeclareLaunchArgument('data_port', default_value='/dev/ti_radar_data')

    # include IWR6843.py
    package_dir = get_package_share_directory('ti_mmwave_rospkg')
    iwr6843_include = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(package_dir,'launch','IWR6843.py')),
        launch_arguments={
            "cfg_file": '6843AOP_StaticTracking.cfg',
            "command_port": LaunchConfiguration('command_port'),
            "data_port": LaunchConfiguration('data_port'),
            "rviz": LaunchConfiguration('rviz'),
        }.items()
    )

    ld = LaunchDescription()
    ld.add_action(rviz_arg)
    ld.add_action(command_port_arg)
    ld.add_action(data_port_arg)
    ld.add_action(iwr6843_include)

    return ld
