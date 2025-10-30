# -*- coding: utf-8 -*-
'''
Web Server for MobilePerf Log Viewer
支持实时查看异常日志和logcat输出
'''
import os
import sys
import threading
import time
import socket
import subprocess
import platform
from datetime import datetime

BaseDir = os.path.dirname(__file__)
sys.path.append(os.path.join(BaseDir, '../../../../'))

from flask import Flask, render_template, jsonify, request, send_file
from mobileperf.common.log import logger
from mobileperf.android.globaldata import RuntimeData
from configparser import ConfigParser
import shutil

# 全局Web服务器实例
_global_web_server = None
_global_web_server_lock = threading.Lock()

def is_port_in_use(port):
    """检查端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('127.0.0.1', port))
            return False
        except OSError:
            return True

def start_web_server_as_background_process(port=5000):
    """在独立的后台守护进程中启动Web服务器（使用nohup完全脱离父进程）"""
    # 获取 start_web_server.py 的路径
    current_dir = os.path.dirname(os.path.abspath(__file__))
    start_script = os.path.join(current_dir, 'start_web_server.py')
    
    if not os.path.exists(start_script):
        logger.error(f"Web server start script not found: {start_script}")
        return None
    
    # 确定Python解释器和项目根目录
    python_exe = sys.executable
    # 获取项目根目录（mobileperf的父目录），确保后台进程在正确的目录下运行
    project_root = os.path.abspath(os.path.join(current_dir, '../../..'))
    
    # 创建日志文件用于调试后台进程错误
    log_dir = os.path.join(project_root, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    error_log = os.path.join(log_dir, 'web_server_error.log')
    # 打开日志文件，保持打开状态以便进程写入
    # 注意：不使用with语句，因为我们需要在Popen后保持文件打开
    error_log_file = open(error_log, 'a')
    
    try:
        # 根据平台选择启动方式
        if platform.system() == 'Windows':
            # Windows: 使用CREATE_NEW_PROCESS_GROUP和DETACHED_PROCESS标志
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE  # 隐藏窗口
            
            process = subprocess.Popen(
                [python_exe, start_script, str(port)],
                stdout=subprocess.DEVNULL,
                stderr=error_log_file,
                stdin=subprocess.DEVNULL,
                cwd=project_root,  # 设置工作目录为项目根目录
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                startupinfo=startupinfo
            )
        else:
            # Unix/Linux/macOS: 使用 nohup 启动真正的后台守护进程
            # nohup + setsid + & 的组合确保进程完全独立，不受父进程影响
            # 注意：Popen启动后立即detach，不等待进程结束
            try:
                # 使用 nohup 启动进程，错误输出重定向到日志文件
                # preexec_fn=os.setsid 创建新的会话，脱离终端控制
                # 注意：close_fds=False，因为我们希望stderr文件描述符传递给子进程
                process = subprocess.Popen(
                    ['nohup', python_exe, start_script, str(port)],
                    stdout=subprocess.DEVNULL,
                    stderr=error_log_file,
                    stdin=subprocess.DEVNULL,
                    cwd=project_root,  # 设置工作目录为项目根目录
                    preexec_fn=os.setsid,  # 创建新的进程组和会话，完全脱离父进程
                    close_fds=False  # 不关闭文件描述符，让stderr传递给子进程
                )
                logger.info(f"Started web server daemon process with nohup (PID: {process.pid})")
                # 立即detach，不等待进程
                process.poll()  # 非阻塞检查，触发进程启动
            except Exception as e:
                logger.warning(f"Failed to start with nohup: {e}, trying alternative method")
                # 如果 nohup 不可用，回退到使用 start_new_session
                try:
                    process = subprocess.Popen(
                        [python_exe, start_script, str(port)],
                        stdout=subprocess.DEVNULL,
                        stderr=error_log_file,
                        stdin=subprocess.DEVNULL,
                        cwd=project_root,  # 设置工作目录为项目根目录
                        start_new_session=True,
                        close_fds=False  # 不关闭文件描述符
                    )
                    logger.info(f"Started web server daemon process (PID: {process.pid})")
                except TypeError:
                    # Python < 3.8，使用 preexec_fn
                    process = subprocess.Popen(
                        [python_exe, start_script, str(port)],
                        stdout=subprocess.DEVNULL,
                        stderr=error_log_file,
                        stdin=subprocess.DEVNULL,
                        cwd=project_root,  # 设置工作目录为项目根目录
                        preexec_fn=os.setsid,
                        close_fds=False  # 不关闭文件描述符
                    )
                    logger.info(f"Started web server daemon process (PID: {process.pid})")
        # 注意：不在这里关闭error_log_file，让它保持打开以便子进程写入
        # 文件会在进程退出时自动关闭，或者由Python垃圾回收器处理
        
        logger.info(f"Web server daemon process started (PID: {process.pid})")
        logger.info(f"Access at: http://localhost:{port}")
        logger.info("Note: Web server runs as independent daemon and won't be affected by parent process termination")
        return process
        
    except Exception as e:
        logger.error(f"Failed to start web server as background process: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return None

def get_or_start_web_server(port=5000):
    """获取或启动Web服务器（优先作为独立后台进程）"""
    global _global_web_server
    
    with _global_web_server_lock:
        # 检查端口是否已经被占用
        port_in_use = is_port_in_use(port)
        
        # 如果端口被占用，检查是否是当前进程的线程模式
        is_thread_mode_in_current_process = False
        if port_in_use and _global_web_server is not None:
            # 检查是否有线程模式的实例在运行
            if (hasattr(_global_web_server, 'server_thread') and 
                _global_web_server.server_thread is not None and
                _global_web_server.server_thread.is_alive()):
                is_thread_mode_in_current_process = True
                logger.warning("Port {} is in use by thread mode web server in current process".format(port))
                logger.info("Switching to background process mode for better stability...")
                # 注意：我们无法直接停止Flask服务器线程，但可以启动后台进程
                # 后台进程启动可能会失败（端口被占用），但我们会尝试
        
        # 如果检测到端口被线程模式占用，无法启动后台进程（端口冲突）
        # 这种情况下，返回现有的线程模式实例（虽然不稳定，但总比没有好）
        if is_thread_mode_in_current_process:
            logger.warning("Cannot switch to background process mode because port is already occupied by thread mode")
            logger.warning("Web server is running in thread mode. To use background process mode, please restart the program.")
            logger.warning("Note: Thread mode web server will be terminated when this process exits (Ctrl+C)")
            return _global_web_server
        
        # 优先使用独立后台进程方式启动
        if not port_in_use:
            logger.info(f"Starting web server as background daemon process on port {port}...")
            process = start_web_server_as_background_process(port)
            
            if process is not None:
                # 等待并重试检查端口，确保服务器启动成功
                # nohup启动的后台进程需要更多时间来完成端口绑定
                max_retries = 10  # 最多重试10次
                retry_interval = 0.5  # 每次间隔0.5秒（总共最多5秒）
                server_started = False
                
                for retry in range(max_retries):
                    time.sleep(retry_interval)
                    if is_port_in_use(port):
                        server_started = True
                        logger.info(f"Web server started successfully as independent daemon process (after {retry + 1} attempts, ~{(retry + 1) * retry_interval:.1f}s)")
                        break
                    else:
                        # 检查进程是否还在运行
                        if process.poll() is not None:
                            # 进程已退出，启动失败
                            logger.warning(f"Web server process exited with code {process.returncode}")
                            break
                        # 进程还在运行，继续等待
                        if retry < max_retries - 1:  # 最后一次不打印debug日志
                            logger.debug(f"Waiting for web server to start... (attempt {retry + 1}/{max_retries})")
                
                if server_started:
                    # 创建一个虚拟实例引用
                    _global_web_server = MobilePerfWebServer(port=port)
                    # 保存进程对象以便后续可能需要管理
                    _global_web_server._background_process = process
                    return _global_web_server
                else:
                    logger.warning(f"Web server process started but port {port} is still not in use after ~{max_retries * retry_interval}s")
                    # 尝试杀掉失败的进程
                    try:
                        process.terminate()
                        process.wait(timeout=2)
                        logger.debug("Terminated failed background process")
                    except Exception as e:
                        logger.debug(f"Failed to terminate process: {e}")
            
            # 如果后台进程启动失败，回退到线程模式（兼容性，但不推荐）
            logger.warning("Background process start failed, falling back to thread mode")
            logger.warning("Note: Thread mode is less stable. Web server will stop when this process exits.")
            try:
                _global_web_server = MobilePerfWebServer(port=port)
                _global_web_server.start()
                time.sleep(0.5)
                return _global_web_server
            except Exception as e:
                logger.error(f"Failed to start web server in thread mode: {e}")
                return None
        
        # 端口已被占用，且不是当前进程的线程模式，说明是独立的后台进程在运行
        if port_in_use and not is_thread_mode_in_current_process:
            logger.info(f"Port {port} is already in use, web server daemon is running")
            # 端口已被占用，说明独立后台进程已经在运行
            # 创建一个虚拟实例引用，但不启动线程
            if _global_web_server is None:
                _global_web_server = MobilePerfWebServer(port=port)
            return _global_web_server
        
        # 其他情况（应该不会到这里）
        logger.error("Unexpected state in web server startup logic")
        return None

class MobilePerfWebServer:
    def __init__(self, port=5000):
        # 确保 RuntimeData.top_dir 已初始化（独立启动Web服务器时可能为None）
        if RuntimeData.top_dir is None:
            # 从 mobileperf/common/utils.py 导入 FileUtils
            from mobileperf.common.utils import FileUtils
            RuntimeData.top_dir = FileUtils.get_top_dir()
            logger.debug(f"Initialized RuntimeData.top_dir: {RuntimeData.top_dir}")
        
        # 使用当前文件所在目录的 templates 和 static
        template_path = os.path.join(os.path.dirname(__file__), 'templates')
        static_path = os.path.join(os.path.dirname(__file__), 'static')
        self.app = Flask(__name__, template_folder=template_path, static_folder=static_path)
        self.port = port
        self.server_thread = None
        self.setup_routes()
    
    def get_logcat_files(self, test_path):
        """获取指定测试目录下的所有logcat文件（按时间戳命名）"""
        logcat_files = []
        if not os.path.exists(test_path):
            return logcat_files
        
        # 查找所有 logcat_*.log 格式的文件
        for filename in os.listdir(test_path):
            if filename.startswith('logcat_') and filename.endswith('.log'):
                logcat_files.append(os.path.join(test_path, filename))
        
        # 按文件名排序（时间戳自然排序）
        logcat_files.sort()
        return logcat_files
    
    def get_xlsx_files(self, test_path):
        """获取指定测试目录下的所有xlsx汇总文件"""
        xlsx_files = []
        if not os.path.exists(test_path):
            return xlsx_files

        for filename in os.listdir(test_path):
            if filename.lower().endswith('.xlsx'):
                xlsx_files.append(os.path.join(test_path, filename))
        xlsx_files.sort()
        return xlsx_files

    def read_single_logcat_file(self, test_path, filename):
        """读取单个logcat文件内容"""
        filepath = os.path.join(test_path, filename)
        if not os.path.exists(filepath):
            return ""
        
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception as e:
            logger.warning(f"Failed to read logcat file {filepath}: {e}")
            return ""
    
    def get_logcat_files_info(self, test_path):
        """获取所有logcat文件信息（文件名和大小）"""
        logcat_files = self.get_logcat_files(test_path)
        if not logcat_files:
            return []
        
        files_info = []
        for logcat_file in logcat_files:
            filename = os.path.basename(logcat_file)
            try:
                size = os.path.getsize(logcat_file)
                files_info.append({
                    'filename': filename,
                    'size': size,
                    'size_mb': round(size / 1024 / 1024, 2) if size > 0 else 0
                })
            except Exception as e:
                logger.warning(f"Failed to get info for logcat file {logcat_file}: {e}")
        
        return files_info

    def get_xlsx_files_info(self, test_path):
        """获取所有xlsx文件信息（文件名和大小）"""
        files = self.get_xlsx_files(test_path)
        if not files:
            return []

        info = []
        for f in files:
            name = os.path.basename(f)
            try:
                size = os.path.getsize(f)
                info.append({
                    'filename': name,
                    'size': size,
                    'size_mb': round(size / 1024 / 1024, 2) if size > 0 else 0
                })
            except Exception as e:
                logger.warning(f"Failed to get info for xlsx file {f}: {e}")
        return info
    
    def setup_routes(self):
        """设置路由"""
        
        @self.app.route('/')
        def index():
            """首页 - 显示所有测试结果"""
            results = self.get_test_results()
            return render_template('index.html', results=results, hostname=self.get_hostname())
        
        @self.app.route('/api/results')
        def api_results():
            """API: 获取所有测试结果"""
            results = self.get_test_results()
            return jsonify(results)
        
        @self.app.route('/api/logs/<package>/<timestamp>')
        def api_logs(package, timestamp):
            """API: 获取某个测试的日志"""
            # 确保 RuntimeData.top_dir 已初始化
            if RuntimeData.top_dir is None:
                from mobileperf.common.utils import FileUtils
                RuntimeData.top_dir = FileUtils.get_top_dir()
            
            log_path = os.path.join(RuntimeData.top_dir, 'results', package, timestamp)
            
            result = {}
            
            # 读取 exception.log
            exception_file = os.path.join(log_path, 'exception.log')
            if os.path.exists(exception_file):
                with open(exception_file, 'r', encoding='utf-8', errors='ignore') as f:
                    result['exception'] = f.read()
            else:
                result['exception'] = ""
            
            # 返回logcat、xlsx文件列表（不读取内容，避免文件过大）
            result['logcat_files'] = self.get_logcat_files_info(log_path)
            result['xlsx_files'] = self.get_xlsx_files_info(log_path)
            
            return jsonify(result)
        
        @self.app.route('/api/logcat/<package>/<timestamp>/<filename>')
        def api_logcat_file(package, timestamp, filename):
            """API: 获取单个logcat文件内容或下载"""
            # 确保 RuntimeData.top_dir 已初始化
            if RuntimeData.top_dir is None:
                from mobileperf.common.utils import FileUtils
                RuntimeData.top_dir = FileUtils.get_top_dir()
            
            log_path = os.path.join(RuntimeData.top_dir, 'results', package, timestamp)
            
            # 安全检查：确保文件名是logcat文件
            if not filename.startswith('logcat_') or not filename.endswith('.log'):
                return jsonify({'error': 'Invalid logcat filename'}), 400
            
            file_path = os.path.join(log_path, filename)
            
            # 是否强制下载
            force_download = request.args.get('download', '0') in ('1', 'true', 'yes')
            if force_download:
                # 下载文件
                if not os.path.exists(file_path):
                    return jsonify({'error': 'File not found'}), 404
                try:
                    return send_file(
                        file_path,
                        mimetype='text/plain',
                        as_attachment=True,
                        download_name=filename
                    )
                except Exception as e:
                    logger.error(f"Failed to send logcat file {file_path}: {e}")
                    return jsonify({'error': 'Failed to read file'}), 500
            
            # 返回文件内容（用于预览）
            content = self.read_single_logcat_file(log_path, filename)
            return jsonify({'filename': filename, 'content': content})
        
        @self.app.route('/api/logfile/<package>/<timestamp>/<filename>')
        def api_logfile(package, timestamp, filename):
            """API: 下载日志文件（exception.log或其他日志文件）"""
            # 确保 RuntimeData.top_dir 已初始化
            if RuntimeData.top_dir is None:
                from mobileperf.common.utils import FileUtils
                RuntimeData.top_dir = FileUtils.get_top_dir()
            
            test_path = os.path.join(RuntimeData.top_dir, 'results', package, timestamp)
            file_path = os.path.join(test_path, filename)
            
            # 安全校验：确保文件在测试路径内且存在
            if not file_path.startswith(test_path) or not os.path.exists(file_path):
                return jsonify({'error': 'Invalid file path or file not found'}), 404
            
            # 检查文件扩展名，只允许日志文件
            allowed_extensions = ['.log', '.txt']
            if not any(filename.lower().endswith(ext) for ext in allowed_extensions):
                return jsonify({'error': 'Invalid file type'}), 400
            
            try:
                return send_file(
                    file_path,
                    mimetype='text/plain',
                    as_attachment=True,
                    download_name=filename
                )
            except Exception as e:
                logger.error(f"Failed to send log file {file_path}: {e}")
                return jsonify({'error': 'Failed to read file'}), 500

        @self.app.route('/api/xlsx/<package>/<timestamp>/<filename>')
        def api_xlsx_file(package, timestamp, filename):
            """API: 下载/获取单个xlsx文件内容（用于前端预览或下载）"""
            # 确保 RuntimeData.top_dir 已初始化
            if RuntimeData.top_dir is None:
                from mobileperf.common.utils import FileUtils
                RuntimeData.top_dir = FileUtils.get_top_dir()

            test_path = os.path.join(RuntimeData.top_dir, 'results', package, timestamp)
            file_path = os.path.join(test_path, filename)

            # 安全校验
            if not file_path.startswith(test_path) or not os.path.exists(file_path) or not filename.lower().endswith('.xlsx'):
                return jsonify({'error': 'Invalid xlsx filename'}), 400

            # 是否强制下载
            force_download = request.args.get('download', '0') in ('1', 'true', 'yes')
            try:
                return send_file(
                    file_path,
                    mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    as_attachment=force_download,
                    download_name=filename
                )
            except Exception as e:
                logger.error(f"Failed to send xlsx file {file_path}: {e}")
                return jsonify({'error': 'Failed to read file'}), 500
        
        @self.app.route('/api/search')
        def api_search():
            """API: 搜索日志"""
            # 确保 RuntimeData.top_dir 已初始化
            if RuntimeData.top_dir is None:
                from mobileperf.common.utils import FileUtils
                RuntimeData.top_dir = FileUtils.get_top_dir()
            
            keyword = request.args.get('keyword', '')
            package = request.args.get('package', '')
            
            if not keyword:
                return jsonify([])
            
            results = []
            results_dir = os.path.join(RuntimeData.top_dir, 'results')
            
            if not os.path.exists(results_dir):
                return jsonify([])
            
            for pkg in os.listdir(results_dir):
                if package and pkg != package:
                    continue
                
                pkg_path = os.path.join(results_dir, pkg)
                if not os.path.isdir(pkg_path):
                    continue
                
                for timestamp in os.listdir(pkg_path):
                    test_path = os.path.join(pkg_path, timestamp)
                    if not os.path.isdir(test_path):
                        continue
                    
                    # 搜索 exception.log
                    exception_log = os.path.join(test_path, 'exception.log')
                    if os.path.exists(exception_log):
                        with open(exception_log, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            if keyword in content:
                                lines = content.split('\n')
                                for idx, line in enumerate(lines):
                                    if keyword in line:
                                        results.append({
                                            'package': pkg,
                                            'timestamp': timestamp,
                                            'line': idx + 1,
                                            'content': line[:200],
                                            'context': '\n'.join(lines[max(0, idx-2):idx+3])
                                        })
                    
                    # 搜索所有 logcat 文件
                    logcat_files = self.get_logcat_files(test_path)
                    for logcat_file in logcat_files:
                        try:
                            with open(logcat_file, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()
                                if keyword in content:
                                    lines = content.split('\n')
                                    for idx, line in enumerate(lines):
                                        if keyword in line:
                                            results.append({
                                                'package': pkg,
                                                'timestamp': timestamp,
                                                'line': idx + 1,
                                                'content': line[:200],
                                                'context': '\n'.join(lines[max(0, idx-2):idx+3])
                                            })
                        except Exception as e:
                            logger.warning(f"Failed to search in logcat file {logcat_file}: {e}")
            
            return jsonify(results[:100])  # 最多返回100条
        
        @self.app.route('/api/live/<package>')
        def api_live(package):
            """API: 获取实时日志（当前运行的测试）"""
            if not RuntimeData.package_save_path:
                return jsonify({'exception': '', 'logcat': ''})
            
            current_path = RuntimeData.package_save_path
            result = {}
            
            # 读取 exception.log（最后1000行）
            exception_file = os.path.join(current_path, 'exception.log')
            if os.path.exists(exception_file):
                try:
                    with open(exception_file, 'rb') as f:
                        try:
                            f.seek(-1024*10, 2)  # 读取最后10KB
                        except:
                            f.seek(0)
                        content = f.read().decode('utf-8', errors='ignore')
                        lines = content.split('\n')
                        result['exception'] = '\n'.join(lines[-1000:])
                except Exception as e:
                    logger.warning(f"Failed to read exception.log: {e}")
                    result['exception'] = ""
            else:
                result['exception'] = ""
            
            # 返回logcat文件列表（不读取内容，避免文件过大）
            result['logcat_files'] = self.get_logcat_files_info(current_path)
            
            return jsonify(result)
        
        @self.app.route('/api/config', methods=['GET'])
        def api_get_config():
            """API: 获取配置文件内容"""
            try:
                # 确保 RuntimeData.top_dir 已初始化
                if RuntimeData.top_dir is None:
                    from mobileperf.common.utils import FileUtils
                    RuntimeData.top_dir = FileUtils.get_top_dir()
                
                config_path = os.path.join(RuntimeData.top_dir, 'config.conf')
                if not os.path.exists(config_path):
                    return jsonify({'error': '配置文件不存在'}), 404
                
                with open(config_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                return jsonify({'content': content, 'path': config_path})
            except Exception as e:
                logger.error(f"Failed to read config: {e}")
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/config', methods=['PUT'])
        def api_save_config():
            """API: 保存配置文件"""
            try:
                # 确保 RuntimeData.top_dir 已初始化
                if RuntimeData.top_dir is None:
                    from mobileperf.common.utils import FileUtils
                    RuntimeData.top_dir = FileUtils.get_top_dir()
                
                config_path = os.path.join(RuntimeData.top_dir, 'config.conf')
                
                # 获取请求数据
                data = request.get_json()
                if not data or 'content' not in data:
                    return jsonify({'error': '缺少content字段'}), 400
                
                content = data['content']
                
                # 验证配置文件格式
                try:
                    # 使用ConfigParser验证格式
                    parser = ConfigParser()
                    import io
                    parser.read_string(content)
                except Exception as e:
                    return jsonify({'error': f'配置文件格式错误: {str(e)}'}), 400
                
                # 检查是否有测试在运行
                with RuntimeData.test_lock:
                    is_running = RuntimeData.test_status == "running"
                
                if is_running:
                    # 备份原文件
                    backup_path = config_path + '.bak'
                    if os.path.exists(config_path):
                        shutil.copy2(config_path, backup_path)
                    
                    # 保存新配置
                    with open(config_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    
                    return jsonify({
                        'message': '配置文件已保存，但当前有测试在运行，需要重启测试后生效',
                        'requires_restart': True
                    })
                else:
                    # 备份原文件
                    backup_path = config_path + '.bak'
                    if os.path.exists(config_path):
                        shutil.copy2(config_path, backup_path)
                    
                    # 保存新配置
                    with open(config_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    
                    return jsonify({'message': '配置文件已保存'})
            except Exception as e:
                logger.error(f"Failed to save config: {e}")
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/monkey/status', methods=['GET'])
        def api_monkey_status():
            """API: 获取Monkey测试状态"""
            try:
                with RuntimeData.test_lock:
                    status = RuntimeData.test_status
                    start_time = RuntimeData.test_start_time
                    package = None
                    device = None
                    
                    # 获取当前运行的包名和设备
                    if RuntimeData.current_startup:
                        try:
                            package = RuntimeData.current_startup.packages[0] if RuntimeData.current_startup.packages else None
                            device = RuntimeData.current_startup.serialnum if hasattr(RuntimeData.current_startup, 'serialnum') else None
                        except:
                            pass
                    
                    # 计算运行时间
                    run_time = None
                    if start_time and status == "running":
                        from mobileperf.common.utils import TimeUtils
                        try:
                            current_time = TimeUtils.getCurrentTime()
                            start_timestamp = TimeUtils.getTimeStamp(start_time, TimeUtils.UnderLineFormatter)
                            current_timestamp = TimeUtils.getTimeStamp(current_time, TimeUtils.UnderLineFormatter)
                            run_seconds = int(current_timestamp - start_timestamp)
                            hours = run_seconds // 3600
                            minutes = (run_seconds % 3600) // 60
                            seconds = run_seconds % 60
                            run_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                        except:
                            run_time = "计算中..."
                
                return jsonify({
                    'status': status,
                    'start_time': start_time,
                    'run_time': run_time,
                    'package': package,
                    'device': device
                })
            except Exception as e:
                logger.error(f"Failed to get monkey status: {e}")
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/monkey/start', methods=['POST'])
        def api_monkey_start():
            """API: 启动Monkey测试"""
            try:
                with RuntimeData.test_lock:
                    # 检查是否已有测试在运行
                    if RuntimeData.test_status == "running":
                        return jsonify({'error': '测试正在运行中，请先停止当前测试'}), 400
                    
                    # 设置状态为启动中
                    RuntimeData.test_status = "starting"
                
                # 确保 RuntimeData.top_dir 已初始化
                if RuntimeData.top_dir is None:
                    from mobileperf.common.utils import FileUtils
                    RuntimeData.top_dir = FileUtils.get_top_dir()
                
                # 重新加载配置
                from mobileperf.android.startup import StartUp
                startup = StartUp()
                
                # 检查设备连接
                if not startup.device.adb.is_connected(startup.serialnum):
                    RuntimeData.test_status = "stopped"
                    return jsonify({'error': f'设备未连接: {startup.serialnum}'}), 400
                
                # 检查应用是否安装
                if not startup.device.adb.is_app_installed(startup.packages[0]):
                    RuntimeData.test_status = "stopped"
                    return jsonify({'error': f'应用未安装: {startup.packages[0]}'}), 400
                
                # 在后台线程中运行测试
                def run_test():
                    try:
                        from mobileperf.common.utils import TimeUtils
                        start_time = TimeUtils.getCurrentTimeUnderline()
                        
                        with RuntimeData.test_lock:
                            RuntimeData.test_status = "running"
                            RuntimeData.test_start_time = start_time
                            RuntimeData.current_startup = startup
                        
                        # 运行测试
                        startup.run()
                        
                        # 测试结束
                        with RuntimeData.test_lock:
                            RuntimeData.test_status = "stopped"
                            RuntimeData.current_startup = None
                            RuntimeData.current_startup_thread = None
                            RuntimeData.test_start_time = None
                    except Exception as e:
                        logger.error(f"Test execution error: {e}")
                        with RuntimeData.test_lock:
                            RuntimeData.test_status = "stopped"
                            RuntimeData.current_startup = None
                            RuntimeData.current_startup_thread = None
                            RuntimeData.test_start_time = None
                
                # 启动测试线程
                test_thread = threading.Thread(target=run_test, daemon=True)
                test_thread.start()
                RuntimeData.current_startup_thread = test_thread
                
                # 等待一下确保启动成功
                import time
                time.sleep(1)
                
                # 检查状态
                with RuntimeData.test_lock:
                    if RuntimeData.test_status == "running":
                        return jsonify({
                            'message': '测试已启动',
                            'package': startup.packages[0],
                            'device': startup.serialnum
                        })
                    else:
                        return jsonify({'error': '测试启动失败'}), 500
                        
            except Exception as e:
                logger.error(f"Failed to start monkey: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                RuntimeData.test_status = "stopped"
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/monkey/stop', methods=['POST'])
        def api_monkey_stop():
            """API: 停止Monkey测试"""
            try:
                with RuntimeData.test_lock:
                    if RuntimeData.test_status != "running":
                        return jsonify({'error': '没有正在运行的测试'}), 400
                    
                    # 设置状态为停止中
                    RuntimeData.test_status = "stopping"
                    startup = RuntimeData.current_startup
                
                if not startup:
                    RuntimeData.test_status = "stopped"
                    return jsonify({'error': '找不到测试实例'}), 400
                
                # 优雅停止：发出退出信号，等待运行线程进入finally生成报告
                try:
                    RuntimeData.exit_event.set()
                    # 等待线程结束一小段时间
                    t = RuntimeData.current_startup_thread
                    if t is not None:
                        t.join(timeout=10)
                    # 兜底：如果线程还未结束，调用stop()
                    if t is not None and t.is_alive():
                        startup.stop()
                    # 确保Monkey进程被杀死
                    if hasattr(startup, 'device'):
                        try:
                            startup.device.adb.kill_process("com.android.commands.monkey")
                        except:
                            pass
                    
                    # 更新状态
                    with RuntimeData.test_lock:
                        RuntimeData.test_status = "stopped"
                        RuntimeData.current_startup = None
                        RuntimeData.current_startup_thread = None
                        RuntimeData.test_start_time = None
                    
                    return jsonify({'message': '测试已停止'})
                except Exception as e:
                    logger.error(f"Failed to stop test: {e}")
                    # 强制更新状态
                    with RuntimeData.test_lock:
                        RuntimeData.test_status = "stopped"
                        RuntimeData.current_startup = None
                        RuntimeData.current_startup_thread = None
                        RuntimeData.test_start_time = None
                    return jsonify({'error': f'停止测试时出错: {str(e)}'}), 500
                    
            except Exception as e:
                logger.error(f"Failed to stop monkey: {e}")
                return jsonify({'error': str(e)}), 500
    
    def get_test_results(self):
        """获取所有测试结果"""
        # 确保 RuntimeData.top_dir 已初始化
        if RuntimeData.top_dir is None:
            from mobileperf.common.utils import FileUtils
            RuntimeData.top_dir = FileUtils.get_top_dir()
        
        results_dir = os.path.join(RuntimeData.top_dir, 'results')
        
        if not os.path.exists(results_dir):
            return []
        
        results = []
        for package in os.listdir(results_dir):
            pkg_path = os.path.join(results_dir, package)
            if not os.path.isdir(pkg_path):
                continue
            
            for timestamp in os.listdir(pkg_path):
                test_path = os.path.join(pkg_path, timestamp)
                if not os.path.isdir(test_path):
                    continue
                
                # 检查日志文件
                exception_file = os.path.join(test_path, 'exception.log')
                has_exception = os.path.exists(exception_file)
                
                # 检查exception.log文件内容是否包含该测试的包名（目录名就是包名）
                exception_contains_package = False
                if has_exception and package:
                    try:
                        with open(exception_file, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            # 检查文件内容中是否包含包名（目录名就是包名）
                            if package in content:
                                exception_contains_package = True
                                logger.debug(f"Found package {package} in exception.log: {package}/{timestamp}")
                    except Exception as e:
                        logger.warning(f"Failed to read exception.log for {package}/{timestamp}: {e}")
                
                # 检查是否存在 logcat_*.log 文件
                has_logcat = len(self.get_logcat_files(test_path)) > 0
                # 检查是否存在 xlsx 报告文件
                has_report = len(self.get_xlsx_files(test_path)) > 0
                
                # 获取测试时间
                try:
                    test_time = datetime.strptime(timestamp, '%Y_%m_%d_%H_%M_%S')
                except:
                    test_time = datetime.fromtimestamp(os.path.getmtime(test_path))
                
                results.append({
                    'package': package,
                    'timestamp': timestamp,
                    'time': test_time.strftime('%Y-%m-%d %H:%M:%S'),
                    'has_exception': has_exception,
                    'has_logcat': has_logcat,
                    'has_report': has_report,
                    'exception_contains_package': exception_contains_package  # 新增字段
                })
        
        # 按时间倒序排序
        results.sort(key=lambda x: x['time'], reverse=True)
        return results
    
    def get_hostname(self):
        """获取主机名和IP"""
        import socket
        hostname = socket.gethostname()
        try:
            ip = socket.gethostbyname(hostname)
        except:
            ip = '127.0.0.1'
        return hostname, ip
    
    def start(self):
        """启动Web服务器（长期运行）"""
        # 如果线程已存在且存活，说明服务器已经在运行
        if self.server_thread is not None and self.server_thread.is_alive():
            logger.info(f"Web server thread already running on port {self.port}")
            return
        
        def run():
            logger.info(f"Starting Web Server on http://0.0.0.0:{self.port}")
            hostname, ip = self.get_hostname()
            logger.info(f"Access at: http://{ip}:{self.port} or http://localhost:{self.port}")
            logger.info("Web server will keep running until process exits")
            # 使用0.0.0.0让局域网可以访问
            self.app.run(host='0.0.0.0', port=self.port, debug=False, use_reloader=False)
        
        # 使用非daemon线程，这样即使主线程退出，Web服务器也能继续运行
        # 但需要小心处理退出逻辑，避免僵尸进程
        self.server_thread = threading.Thread(target=run, daemon=False)
        self.server_thread.start()
    
    def stop(self):
        """停止Web服务器"""
        # Flask没有直接stop方法，daemon线程会在主线程结束时自动结束
        logger.info("Web Server stopped")

if __name__ == '__main__':
    # 测试用
    server = MobilePerfWebServer(port=5000)
    server.start()
    time.sleep(10)
    server.stop()

