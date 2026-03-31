from setuptools import setup
import os           # <--- 修正 1: 加入這行
from glob import glob # <--- 修正 1: 加入這行

package_name = 'sensor_fusion_pkg'

setup(
    name=package_name,
    version='0.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        
        # ▼▼▼ 修正 2: 加入下面這一行 (這是要把 launch 檔複製過去的關鍵！) ▼▼▼
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='chris',
    maintainer_email='chris@todo.todo',
    description='TODO: Package description',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            # 之後如果要寫 Python 節點程式，會在這裡註冊
        ],
    },
)