#encoding:utf-8
'''
@author:     look

@copyright:  1999-2020 Alibaba.com. All rights reserved.

@license:    Apache Software License 2.0

@contact:    390125133@qq.com
'''
import re
import time,datetime
import os
import sys
import queue
import base64
import json
import subprocess
from shutil import copyfile,rmtree
# import objgraph
from configparser import ConfigParser

BaseDir=os.path.dirname(__file__)
sys.path.append(os.path.join(BaseDir,'../..'))

from mobileperf.common.log import logger
from mobileperf.android.tools.androiddevice import AndroidDevice
from mobileperf.common.utils import TimeUtils,FileUtils,ZipUtils
from mobileperf.android.cpu_top import CpuMonitor
from mobileperf.android.meminfos import MemMonitor
from mobileperf.android.trafficstats import TrafficMonitor
from mobileperf.android.fps import FPSMonitor
from mobileperf.android.powerconsumption import PowerMonitor
from mobileperf.android.thread_num import ThreadNumMonitor
from mobileperf.android.fd import FdMonitor
from mobileperf.android.logcat import LogcatMonitor
from mobileperf.android.devicemonitor import DeviceMonitor
from mobileperf.android.monkey import Monkey
from mobileperf.android.globaldata import RuntimeData
from mobileperf.android.report import Report
# 尝试导入 Web 服务器的启动函数（若不可用则忽略，不影响核心功能）
try:
    from mobileperf.android.web.web_server import get_or_start_web_server
    WEB_SERVER_AVAILABLE = True
except Exception:
    WEB_SERVER_AVAILABLE = False

class StartUp(object):

    def __init__(self, device_id=None, package=None,interval=None):
        RuntimeData.top_dir = os.getcwd()
        if "android" in RuntimeData.top_dir:
            RuntimeData.top_dir  = FileUtils.get_top_dir()
        logger.debug("RuntimeData.top_dir:"+RuntimeData.top_dir)
        self.config_dic = self.parse_data_from_config()
        RuntimeData.config_dic = self.config_dic
        self.serialnum = device_id if device_id != None else self.config_dic['serialnum']#代码中重新传入device_id 则会覆盖原来配置文件config.conf的值，主要为了debug方便
        self.packages = package if package != None else self.config_dic['package']#代码中重新传入package 则会覆盖原来配置文件config.conf的值，为了debug方便
        self.frequency = interval if interval != None else self.config_dic['frequency']#代码中重新传入interval 则会覆盖原来配置文件config.conf的值，为了debug方便
        self.timeout = self.config_dic['timeout']
        self.exceptionlog_list = self.config_dic["exceptionlog"]
        self.device = AndroidDevice(self.serialnum)
        # 如果config文件中 packagename为空，就获取前台进程，匹配图兰朵，测的app太多，支持配置文件不传package
        if not self.packages:
            # 进程名不会有#，转化为list
            self.packages = self.device.adb.get_foreground_process().split("#")
        RuntimeData.packages = self.packages

        #与终端交互有关
        self.keycode = ''
        self.pid = 0

        self._init_queue()
        self.monitors = []
        self.logcat_monitor = None

    def _init_queue(self):
        self.cpu_queue = queue.Queue()
        self.mem_queue = queue.Queue()
        self.power_queue = queue.Queue()
        self.traffic_queue = queue.Queue()
        self.fps_queue = queue.Queue()
        self.activity_queue = queue.Queue()
        self.fd_queue = queue.Queue()
        self.thread_queue = queue.Queue()

    def get_queue_dic(self):
        queue_dic = {}
        queue_dic['cpu_queue'] = self.cpu_queue
        queue_dic['mem_queue'] = self.mem_queue
        queue_dic['power_queue'] = self.power_queue
        queue_dic['traffic_queue'] = self.traffic_queue
        queue_dic['fps_queue'] = self.fps_queue
        queue_dic['fd_queue'] = self.fd_queue
        queue_dic['thread_queue'] = self.thread_queue
        queue_dic['activity_queue'] = self.activity_queue
        return queue_dic

    def add_monitor(self, monitor):
        self.monitors.append(monitor)

    def remove_monitor(self, monitor):
        self.monitors.remove(monitor)

    def parse_data_from_config(self):
        '''
        从配置文件中解析出需要的信息，包名，时间间隔，设备的序列号等
        :return:配置文件中读出来的数值的字典
        '''
        config_dic = {}
        configpath = os.path.join(RuntimeData.top_dir, "config.conf")
        logger.debug("configpath:%s" % configpath)
        if not os.path.isfile(configpath):
            logger.error("the config file didn't exist: " + configpath)
            raise RuntimeError("the config file didn't exist: " + configpath)
        # 避免windows会用系统默认的gbk打开
        with open(configpath, encoding="utf-8") as f:
            content = f.read()
            # Window下用记事本打开配置文件并修改保存后，编码为UNICODE或UTF-8的文件的文件头
            # 会被相应的加上\xff\xfe（\xff\xfe）或\xef\xbb\xbf，然后再传递给ConfigParser解析的时候会出错
            # ，因此解析之前，先替换掉
            content = re.sub(r"\xfe\xff", "", content)
            content = re.sub(r"\xff\xfe", "", content)
            content = re.sub(r"\xef\xbb\xbf", "", content)
            open(configpath, 'w', encoding="utf-8").write(content)
        paser = ConfigParser()
        paser.read(configpath, encoding="utf-8")
        config_dic = self.check_config_option(config_dic, paser, "Common", "package")
        config_dic = self.check_config_option(config_dic, paser, "Common", "pid_change_focus_package")
        config_dic = self.check_config_option(config_dic, paser, "Common","frequency")
        config_dic = self.check_config_option(config_dic, paser, "Common", "dumpheap_freq")
        config_dic = self.check_config_option(config_dic, paser, "Common", "timeout")
        config_dic = self.check_config_option(config_dic, paser, "Common", "serialnum")
        config_dic = self.check_config_option(config_dic, paser, "Common", "mailbox")
        config_dic = self.check_config_option(config_dic, paser, "Common", "exceptionlog")
        config_dic = self.check_config_option(config_dic, paser, "Common", "save_path")
        config_dic = self.check_config_option(config_dic,paser,"Common","phone_log_path")

        # 读取monkey配置
        config_dic = self.check_config_option(config_dic, paser, "Common", "monkey")
        config_dic = self.check_config_option(config_dic, paser, "Common", "main_activity")
        config_dic = self.check_config_option(config_dic, paser, "Common", "activity_list")
        config_dic = self.check_config_option(config_dic, paser, "Common", "monkey_disable_syskeys")
        # 单独的页面监控间隔时间
        config_dic = self.check_config_option(config_dic, paser, "Common", "monitor_interval")

        logger.debug(config_dic)
        return config_dic

    def check_config_option(self, config_dic, parse, section, option):
        if parse.has_option(section, option):

            try:
                config_dic[option] = parse.get(section, option)
                if option == 'frequency' or option == 'monitor_interval':
                    config_dic[option] = (int)(parse.get(section, option))
                if option == 'dumpheap_freq':#dumpheap 的单位是分钟
                    config_dic[option] = (int)(parse.get(section, option))*60
                if option == 'timeout':#timeout 的单位是分钟
                    config_dic[option] = (int)(parse.get(section, option))*60
                if option in ["exceptionlog" ,"phone_log_path","space_size_check_path","package","pid_change_focus_package",
                              "watcher_users","main_activity","activity_list"]:
                    if option == "activity_list" or option == "main_activity":
                        config_dic[option] = parse.get(section, option).strip().replace("\n","").split(";")
                    else:
                        config_dic[option] = parse.get(section, option).split(";")
                if option == 'monkey_disable_syskeys':
                    config_dic[option] = parse.get(section, option).lower() == 'true'
            except:#配置项中数值发生错误
                if option != 'serialnum':
                    logger.debug("config option error:"+option)
                    self._config_error()
                else:
                    config_dic[option] = ''
        else:#配置项没有配置
            if option not in ['serialnum',"main_activity","activity_list","pid_change_focus_package","shell_file","monkey_disable_syskeys"]:
                logger.debug("config option error:" + option)
                self._config_error()
            else:
                if option == 'monkey_disable_syskeys':
                    config_dic[option] = False  # 默认不禁用系统按键
                else:
                    config_dic[option] = ''
        return config_dic

    def _config_error(self):
        logger.error("config error, please config it correctly")
        sys.exit(1)

    # @profile
    def run(self, time_out=None):
        self.clear_heapdump()
        # 在任何设备/应用检查之前，优先确保 Web 服务已启动，
        # 这样即使设备未连接，Web 也可用于查看历史结果、编辑配置、手动控制
        try:
            if WEB_SERVER_AVAILABLE:
                get_or_start_web_server(port=5000)
        except Exception as e:
            logger.debug(f"Auto start web server skipped: {e}")
        # objgraph.show_growth()
#       对设备连接情况的检查
        if not self.serialnum:
#           androiddevice 没传  serialnum，默认执行adb shell
            logger.info("serialnum in config file is null,default get connected phone")
        is_device_connect = False
        for i in range(0,5):
            if self.device.adb.is_connected(self.serialnum):
                is_device_connect = True
                break
            else:
                logger.error("device not found:"+self.serialnum)
                time.sleep(2)
        if not is_device_connect:
            logger.error("after 5 times check,device not found:" + self.serialnum)
            return
  # 对是否安装被测app的检查 只在最开始检查一次
        if not self.device.adb.is_app_installed(self.packages[0]):
            logger.error("test app not installed:" + self.packages[0])
            return
        try:
            # 提前创建结果目录，确保即使早停也能生成报告
            if not RuntimeData.start_time:
                start_time = TimeUtils.getCurrentTimeUnderline()
                RuntimeData.start_time = start_time
                if self.config_dic["save_path"]:
                    RuntimeData.package_save_path = os.path.join(self.config_dic["save_path"], self.packages[0], start_time)
                else:
                    RuntimeData.package_save_path = os.path.join(RuntimeData.top_dir, 'results', self.packages[0], start_time)
                FileUtils.makedir(RuntimeData.package_save_path)
                # 先写入初始设备信息文件，后续 stop() 会补充信息
                self.save_device_info()
            #初始化数据处理的类,将没有消息队列传递过去，以便获取数据，并处理
            # datahandle = DataWorker(self.get_queue_dic())
            # 将queue传进去，与datahandle那个线程交互
            self.add_monitor(CpuMonitor(self.serialnum, self.packages, self.frequency, self.timeout))
            self.add_monitor(MemMonitor(self.serialnum, self.packages, self.frequency, self.timeout))
            self.add_monitor(TrafficMonitor(self.serialnum, self.packages, self.frequency, self.timeout))
            # 软件方式 获取电量不准，已用硬件方案测试功耗
            # self.add_monitor(PowerMonitor(self.serialnum, self.frequency,self.timeout))
            self.add_monitor(FPSMonitor(self.serialnum,self.packages[0],self.frequency,self.timeout))
            # fd监控：需要root权限才能访问/proc/pid/fd（Android 4.3+都受SELinux限制）
            sdk_version = self.device.adb.get_sdk_version()
            has_root = False
            try:
                # 方法1：检查当前shell用户是否是root
                id_result = self.device.adb.run_shell_cmd("id")
                if id_result and "uid=0(root)" in id_result:
                    has_root = True
                    logger.info("ADB is running as root (adb root)")
                else:
                    # 方法2：尝试使用su获取root权限
                    su_id_result = self.device.adb.run_shell_cmd("su 0 id")
                    if su_id_result and "uid=0(root)" in su_id_result:
                        has_root = True
                        logger.info("Su root permission available, attempting adb root...")
                        # 尝试执行adb root以提升权限
                        try:
                            # adb root需要在PC端执行，不是shell命令
                            adb_root_result = self.device.adb._run_cmd_once("root")
                            # 等待adb root生效
                            time.sleep(2)  # 增加等待时间，确保adb root生效
                            id_check = self.device.adb.run_shell_cmd("id")
                            if id_check and "uid=0(root)" in id_check:
                                logger.info("Successfully switched to adb root mode")
                            else:
                                logger.info("adb root verification failed, will use su command for fd collection")
                        except Exception as e:
                            logger.debug(f"adb root execution failed: {e}")
                    else:
                        logger.info(f"No root permission available for Android {sdk_version}")
            except Exception as e:
                logger.debug(f"Root check failed: {e}")
            
            if has_root:
                self.add_monitor(FdMonitor(self.serialnum, self.packages[0], self.frequency, self.timeout))
                logger.info(f"Added FdMonitor for Android {sdk_version}")
            else:
                logger.warning(f"Skipping FdMonitor for Android {sdk_version} without root permission")
            
            self.add_monitor(ThreadNumMonitor(self.serialnum,self.packages[0],self.frequency,self.timeout))
            if self.config_dic["monkey"] == "true":
                self.add_monitor(Monkey(self.serialnum, self.packages[0], self.timeout))
            # 只要配置了 main_activity 就启动页面监控
            # 如果只配置 main_activity：检测应用是否在前台，不在则拉起应用
            # 如果同时配置了 activity_list：使用白名单功能，检测当前 Activity 是否在白名单中
            if self.config_dic["main_activity"]:
                # 使用配置中的 monitor_interval 参数，如果不存在则使用默认值 1
                monitor_interval = self.config_dic.get("monitor_interval", 1)
                # activity_list 如果未配置则为空列表
                activity_list = self.config_dic.get("activity_list", [])
                self.add_monitor(DeviceMonitor(self.serialnum, self.packages[0], monitor_interval, self.config_dic["main_activity"],
                                               activity_list, RuntimeData.exit_event))

            if len(self.monitors):
                for monitor in self.monitors:
                    #启动所有的monitors
                    try:
                        monitor.start(start_time)
                    except Exception as e:
                        logger.error(e)
                # logcat的代码可能会引起死锁，拎出来单独处理logcat
                try:
                    self.logcat_monitor = LogcatMonitor(self.serialnum, self.packages[0])
                    # 如果有异常日志标志，才启动这个模块
                    if self.exceptionlog_list:
                        self.logcat_monitor.set_exception_list(self.exceptionlog_list)
                        self.logcat_monitor.add_log_handle(self.logcat_monitor.handle_exception)
                    time.sleep(1)
                    self.logcat_monitor.start(start_time)
                    logger.info("Logcat monitor started")
                except Exception as e:
                    logger.error("Failed to start logcat monitor: %s" % e)
                
                timeout = time_out if time_out != None else self.config_dic['timeout']
                endtime = time.time() + timeout
                while (time.time() < endtime):#吊着主线程防止线程中断
                    # 时间到或测试过程中检测到异常
                    if self.check_exit_signal_quit():
                        logger.error("app " + str(self.packages[0]) + " exit signal, quit!")
                        break
                    time.sleep(self.frequency)
                logger.debug("time is up,finish!!!")
                self.stop()

                # try:
                #     datahandle.stop()
                #     time.sleep(self.frequency*2)
                #     #               延迟一点时间结束上报，已让数据上报完
                #     # report.stop()
                # except:
                #     logger.debug("report or datahandle stop exception")
                # finally:
                #     logger.info("time is up, end")
                #     os._exit(0)

        except KeyboardInterrupt:#捕获键盘异常的事件，例如ctrl c
            logger.debug(" catch keyboardInterrupt, goodbye!!!")
            # 收尾工作
            self.stop()
            # stop()方法会检查Web服务器状态，如果Web服务器在运行则不会退出进程
            # 如果没有Web服务器，stop()方法会调用os._exit(0)
        except Exception as e:
            logger.error("Exception in run")
            logger.error(e)

    #     测试前清空 tmp 目录下dump文件 清理超过一周的文件，避免同时测试会有冲突
    def clear_heapdump(self):
        filelist = self.device.adb.list_dir("/data/local/tmp")
        if filelist:
            for file in filelist:
                if self.packages[0] in file and self.device.adb.is_overtime_days("/data/local/tmp/"+file,3):
                    self.device.adb.delete_file("/data/local/tmp/%s" % file)

    def stop(self):
        # 使用 try...finally 确保报告生成一定会执行，即使被 Ctrl+C 中断
        try:
            for monitor in self.monitors:
                try:
                    monitor.stop()
                except (KeyboardInterrupt, SystemExit):
                    # 如果是中断信号，直接抛出，让外层处理
                    raise
                except Exception as e:  # 捕获所有的异常，防止其中一个monitor的stop操作发生异常退出时，影响其他的monitor的stop操作
                    logger.error(e)

            try:
                if self.logcat_monitor:
                    self.logcat_monitor.stop()
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as e:
                logger.error("stop exception for logcat monitor")
                logger.error(e)
            if self.config_dic["monkey"] =="true":
                self.device.adb.kill_process("com.android.commands.monkey")
            # 统计测试时长
            cost_time =round((float) (time.time() - TimeUtils.getTimeStamp(RuntimeData.start_time,TimeUtils.UnderLineFormatter))/3600,2)
            self.add_device_info("test cost time:",str(cost_time)+"h")
        except (KeyboardInterrupt, SystemExit):
            # 即使被中断，也要生成报告
            logger.warning("Process interrupted, but will still generate report...")
        finally:
            # 根据csv生成excel汇总文件 - 无论是否中断，都要生成报告
            try:
                # 若目录未建立，尝试兜底：使用results/<package>/最新时间目录
                if not RuntimeData.package_save_path:
                    base_dir = os.path.join(RuntimeData.top_dir, 'results', self.packages[0])
                    if os.path.isdir(base_dir):
                        # 选择时间戳最大的目录
                        candidates = [os.path.join(base_dir, d) for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
                        if candidates:
                            candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                            RuntimeData.package_save_path = candidates[0]
                if RuntimeData.package_save_path and os.path.exists(RuntimeData.package_save_path):
                    logger.info("Generating summary report...")
                    Report(RuntimeData.package_save_path, self.packages)
                    logger.info("Summary report generated successfully")
            except Exception as e:
                logger.error("Failed to generate report: %s" % e)
                import traceback
                logger.error(traceback.format_exc())
            
            # 执行清理工作
            try:
                self.pull_heapdump()
                self.pull_log_files()
            except KeyboardInterrupt:
                logger.warning("Cleanup interrupted by user, skipping...")
            except Exception as e:
                logger.error("Error during cleanup: %s" % e)
            # self.memory_analyse()
            # self.device.adb.bugreport(RuntimeData.package_save_path)
            
            # 检查是否有Web服务器在运行
            # 如果Web服务器在当前进程中运行，需要保持进程运行
            # 如果Web服务器在独立进程中运行，可以安全退出
            try:
                from mobileperf.android.web.web_server import is_port_in_use, _global_web_server
                if is_port_in_use(5000):
                    # 优先检查是否是独立后台进程模式
                    is_background_process = (
                        _global_web_server is not None and 
                        hasattr(_global_web_server, '_background_process') and
                        _global_web_server._background_process is not None
                    )
                    
                    if is_background_process:
                        # Web服务器在独立后台进程中运行，当前进程可以安全退出
                        bg_pid = _global_web_server._background_process.pid if hasattr(_global_web_server._background_process, 'pid') else 'unknown'
                        logger.info(f"Web server is running in a separate background process (PID: {bg_pid})")
                        logger.info("Access web UI at: http://localhost:5000")
                        logger.info("This process can exit safely. Web server will continue running.")
                        os._exit(0)
                    
                    # 检查Web服务器是否在当前进程的线程中启动（线程模式）
                    is_thread_mode = (
                        _global_web_server is not None and 
                        hasattr(_global_web_server, 'server_thread') and
                        _global_web_server.server_thread is not None and
                        _global_web_server.server_thread.is_alive()
                    )
                    
                    if is_thread_mode:
                        # Web服务器在当前进程的线程中，需要保持进程运行
                        logger.info("Web server is running in this process (thread mode)")
                        logger.info("Access web UI at: http://localhost:5000")
                        logger.info("Process will keep running for web service.")
                        logger.info("Note: If you want to stop web server, press Ctrl+C again or kill this process.")
                        # 不调用os._exit(0)，让主线程自然结束
                        # 由于Web服务器线程是non-daemon的，Python解释器会保持进程运行
                        return
                    else:
                        # 端口被占用，但没有找到当前进程的实例
                        # 可能是之前的独立进程在运行，当前进程可以安全退出
                        logger.info("Web server is running on port 5000 (likely in a separate process)")
                        logger.info("This process can exit safely.")
                        os._exit(0)
            except Exception as e:
                logger.debug(f"Failed to check web server status: {e}")
            
            # 如果没有Web服务器或检查失败，正常退出
            os._exit(0)

    # windows可能没装 自测用
    def memory_analyse(self):
        pass
        # 增加内存分析
        # logger.debug("show_growth")
        # objgraph.show_growth()
        # objgraph.show_most_common_types(limit=10)
        # logger.debug("gc.garbage")
        # logger.debug(gc.garbage)
        # logger.debug("collect()")
        # logger.debug(gc.collect())
        # logger.debug("gc.garbage")
        # logger.debug(gc.garbage)



    def pull_heapdump(self):
        # 把dumpheap文件拷贝出来
        filelist = self.device.adb.list_dir("/data/local/tmp")
        if filelist:
            for file in filelist:
                if self.packages[0] in file:
                    self.device.adb.pull_file("/data/local/tmp/%s" % file, RuntimeData.package_save_path)

    def pull_log_files(self):
        if self.config_dic["phone_log_path"]:
            for src_path in self.config_dic["phone_log_path"]:
                self.device.adb.pull_file(src_path, RuntimeData.package_save_path)
                # self.device.adb.pull_file_between_time(src_path,RuntimeData.package_save_path,
                #             TimeUtils.getTimeStamp(RuntimeData.start_time,TimeUtils.UnderLineFormatter),time.time())
        #         release系统pull  /sdcard/mtklog/可以  没有权限/sdcard/mtklog/mobilelog


    def save_device_info(self):
        device_file = os.path.join(RuntimeData.package_save_path,"device_test_info.txt")
        with open(device_file,"w+",encoding="utf-8") as writer:
            writer.write("device serialnum:"+self.serialnum+"\n")
            writer.write("device model:"+self.device.adb.get_phone_brand()+" "+self.device.adb.get_phone_model()+"\n")
            writer.write("test package:" + self.packages[0] + "\n")
            writer.write("system version:"+self.device.adb.get_system_version()+"\n")
            writer.write("test package ver:" + self.device.adb.get_package_ver(self.packages[0]) + "\n")

    def add_device_info(self,key,value):
        device_file = os.path.join(RuntimeData.package_save_path,"device_test_info.txt")
        with open(device_file,"a+",encoding="utf-8") as writer:
            writer.write(key+":"+value+"\n")

    def check_exit_signal_quit(self):
        if(RuntimeData.exit_event.is_set()):
            return True
        else:
            return False


class App():
    def __init__(self,package,name="",version=""):
        self.package = package
        self.name = name
        self.version = version

if __name__ == "__main__":
    # 来自于pyintaller的官网，多进程在windows系统下需要添加这句，否则会创建多个重复的进程，在mac和linux下不会有影响
    # multiprocessing.freeze_support()
    #startup = StartUp("351BBJN3DJC8","com.taobao.taobao",2)
    startup = StartUp()
    
    try:
        startup.run()
    except KeyboardInterrupt:
        # 处理在run()执行期间（测试运行中）的Ctrl+C
        logger.info("\nTest interrupted by user")
        startup.stop()
        
        # stop()之后检查Web服务器是否在当前进程中运行
        try:
            from mobileperf.android.web.web_server import _global_web_server
            if (_global_web_server is not None and 
                _global_web_server.server_thread is not None and
                _global_web_server.server_thread.is_alive()):
                logger.info("\nWeb server is still running in this process.")
                logger.info("Access at: http://localhost:5000")
                logger.info("Press Ctrl+C again to stop web server and exit.")
                logger.info("Or leave it running and use it independently.")
                # 设置信号处理，允许用户再次按Ctrl+C停止
                import signal
                def graceful_exit(sig, frame):
                    logger.info("\nStopping web server and exiting...")
                    import sys
                    sys.exit(0)
                signal.signal(signal.SIGINT, graceful_exit)
                # 保持进程运行（等待Web服务器线程）
                try:
                    _global_web_server.server_thread.join()
                except KeyboardInterrupt:
                    logger.info("\nExiting...")
        except Exception:
            pass
    
    # 如果run()正常返回了，说明测试正常结束
    # stop()方法会检查Web服务器状态：
    # - 如果Web服务器在当前进程中运行，stop()会return而不调用os._exit(0)
    # - 此时主线程自然结束，由于Web服务器线程是non-daemon的，Python会保持进程运行
    # - 但用户按Ctrl+C时，需要在这里处理信号，而不是让进程直接退出
    # RuntimeData.start_time = "2019_03_07_10_57_58"
    # RuntimeData.package_save_path = "/Users/look/Desktop/project/mobileperf-mac/results/com.alibaba.ailabs.genie.contacts/2019_03_07_10_57_58"
    # RuntimeData.start_time = "2019_03_07_10_54_59"
    # RuntimeData.package_save_path = "/Users/look/Desktop/project/mobileperf-mac/results/com.alibaba.ailabs.ar.fireeye2/2019_03_07_10_54_59"
    # startup.deal_error()
