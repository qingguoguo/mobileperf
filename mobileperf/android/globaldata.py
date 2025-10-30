# -*- coding: utf-8 -*-
'''
@author:     look

@copyright:  1999-2020 Alibaba.com. All rights reserved.

@license:    Apache Software License 2.0

@contact:    390125133@qq.com
'''
import threading

# 记录运行时需要共享的全局变量
class RuntimeData():
    # 记录pid变更前的pid
    old_pid = None
    packages = None
    package_save_path = None
    start_time = None
    exit_event = threading.Event()
    top_dir = None
    config_dic = {}
    
    # Web控制相关：用于跟踪当前运行的测试实例
    current_startup = None  # 当前运行的StartUp实例
    current_startup_thread = None  # 运行StartUp的线程
    test_status = "stopped"  # 测试状态: "stopped", "running", "stopping"
    test_start_time = None  # 测试启动时间
    test_lock = threading.Lock()  # 用于保护测试实例的线程锁