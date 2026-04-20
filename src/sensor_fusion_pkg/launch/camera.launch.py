from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

def generate_launch_description():
    video_device = LaunchConfiguration('video_device')
    framerate = LaunchConfiguration('framerate')
    image_width = LaunchConfiguration('image_width')
    image_height = LaunchConfiguration('image_height')
    pixel_format = LaunchConfiguration('pixel_format')
    camera_name = LaunchConfiguration('camera_name')
    autofocus = LaunchConfiguration('autofocus')

    return LaunchDescription([
        DeclareLaunchArgument('video_device', default_value='/dev/video0'),
        DeclareLaunchArgument('framerate', default_value='10.0'),
        DeclareLaunchArgument('image_width', default_value='640'),
        DeclareLaunchArgument('image_height', default_value='480'),
        DeclareLaunchArgument('pixel_format', default_value='mjpeg2rgb'),
        DeclareLaunchArgument('camera_name', default_value='logitech_c930e'),
        DeclareLaunchArgument('autofocus', default_value='true'),
        Node(
            package='usb_cam',
            executable='usb_cam_node_exe',
            name='camera_node',
            output='screen',
            parameters=[{
                'video_device': video_device,
                'framerate': framerate,
                'image_width': image_width,
                'image_height': image_height,
                'pixel_format': pixel_format,
                'camera_name': camera_name,
                'autofocus': autofocus
            }]
        )
    ])
