#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
独立启动Web服务的脚本
用法: python -m mobileperf.android.web.start_web_server
或者: python mobileperf/android/web/start_web_server.py
'''
import os
import sys
import signal

# 获取项目根目录（mobileperf的父目录）
BaseDir = os.path.dirname(__file__)  # mobileperf/android/web/
project_root = os.path.abspath(os.path.join(BaseDir, '../../..'))  # 项目根目录

# 确保项目根目录在sys.path中
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mobileperf.android.web.web_server import MobilePerfWebServer, start_web_server_as_background_process
from mobileperf.common.log import logger

def signal_handler(sig, frame):
    """处理Ctrl+C信号"""
    logger.info("\nReceived interrupt signal. Stopping web server...")
    sys.exit(0)

def main():
    """启动Web服务"""
    port = 5000
    daemon = False
    # 支持: python -m ... 5000 --daemon
    args = sys.argv[1:]
    for a in list(args):
        if a in ("--daemon", "-d", "daemon"):
            daemon = True
            args.remove(a)
    if args:
        try:
            port = int(args[0])
        except ValueError:
            logger.error(f"Invalid port number: {args[0]}")
            sys.exit(1)
    
    # 设置信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("=" * 60)
    logger.info("MobilePerf Web Server")
    logger.info("=" * 60)
    if daemon:
        logger.info(f"Starting web server (daemon) on port {port}...")
        proc = start_web_server_as_background_process(port)
        if proc is None:
            logger.error("Failed to start daemon process")
            sys.exit(1)
        logger.info("Started. Access at: http://localhost:%d" % port)
        logger.info("This command will exit now; the web server keeps running in background.")
        return
    else:
        logger.info(f"Starting web server on port {port}...")
        logger.info(f"Access at: http://localhost:{port}")
        logger.info("Press Ctrl+C to stop the server")
        logger.info("=" * 60)
    
    server = MobilePerfWebServer(port=port)
    server.start()
    
    try:
        # 保持主线程运行，等待Web服务器线程
        # 使用join()会阻塞，但可以响应信号
        if server.server_thread:
            server.server_thread.join()
    except KeyboardInterrupt:
        logger.info("\nShutting down web server...")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        logger.info("Web server stopped.")

if __name__ == '__main__':
    main()

