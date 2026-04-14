import os
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        Node(
            package='usb_cam',
            executable='usb_cam_node_exe',
            name='camera_node',
            output='screen',
            parameters=[{
                'video_device': '/dev/video0',  # 如果筆電有內建鏡頭，C930e 可能是 /dev/video2
                'framerate': 10.0,
                'image_width': 640,
                'image_height': 480,
                'pixel_format': 'mjpeg2rgb',    # 使用 MJPEG 格式傳輸
                'camera_name': 'logitech_c930e',
                'autofocus': True
            }]
        )
    ])
