# -*- coding: utf-8 -*-
'''
@author:     look

@copyright:  1999-2020 Alibaba.com. All rights reserved.

@license:    Apache Software License 2.0

@contact:    390125133@qq.com
'''
'''logcat监控器 
'''
import os,sys,csv
import re
import time
import threading
import hashlib

BaseDir=os.path.dirname(__file__)
sys.path.append(os.path.join(BaseDir,'../..'))

from mobileperf.android.tools.androiddevice import AndroidDevice
from mobileperf.common.basemonitor import Monitor
from mobileperf.common.utils import TimeUtils,FileUtils
from mobileperf.common.utils import ms2s
from mobileperf.common.log import logger
from mobileperf.android.globaldata import RuntimeData

class LogcatMonitor(Monitor):
    '''logcat监控器
    '''
    def __init__(self, device_id, package=None, dingding_webhook=None, dingding_mobiles=None, **regx_config):
        '''构造器
        
        :param str device_id: 设备id
        :param list package : 监控的进程列表，列表为空时，监控所有进程
        :param str dingding_webhook: 钉钉webhook地址，用于实时通知异常
        :param list dingding_mobiles: 钉钉通知@的手机号列表，如 ['138xxxx8888', '139xxxx9999']
        :param dict regx_config : 日志匹配配置项{conf_id = regx}，如：AutoMonitor=ur'AutoMonitor.*:(.*), cost=(\d+)'
        '''
        super(LogcatMonitor, self).__init__(**regx_config)
        self.package = package    # 监控的进程列表
        self.device_id = device_id
        self.device = AndroidDevice(device_id)  # 设备
        self.running = False    # logcat监控器的启动状态(启动/结束)
        self.launchtime = LaunchTime(self.device_id, self.package)
        self.exception_log_list = []
        self.start_time = None
        self.dingding_webhook = dingding_webhook  # 钉钉webhook配置
        self.dingding_mobiles = dingding_mobiles if dingding_mobiles else []  # 钉钉通知@的手机号列表
        self.test_package = package  # 当前测试的包名，用于检查异常日志
        self.last_notification_time = {}  # 记录已发送通知的日志内容hash和发送时间，用于去重

        self.append_log_line_num = 0
        self.file_log_line_num = 0
        self.log_file_create_time = None
    
    def start(self,start_time):
        '''启动logcat日志监控器 
        '''
        self.start_time = start_time
        # 注册启动日志处理回调函数为handle_lauchtime
        self.add_log_handle(self.launchtime.handle_launchtime)
        logger.debug("logcatmonitor start...")
        # 捕获所有进程日志
        # https://developer.android.com/studio/command-line/logcat #alternativeBuffers
        # 默认缓冲区 main system crash,输出全部缓冲区
        if not self.running:
            self.device.adb.start_logcat(RuntimeData.package_save_path, [], ' -b all')
            time.sleep(1)
            self.running = True
    
    def stop(self):
        '''结束logcat日志监控器
        '''
        logger.debug("logcat monitor: stop...")
        self.remove_log_handle(self.launchtime.handle_launchtime)  # 删除回调
        logger.debug("logcat monitor: stopped")
        if self.exception_log_list:
            self.remove_log_handle(self.handle_exception)
        self.device.adb.stop_logcat()
        self.running = False

    def parse(self, file_path):
        pass

    def set_exception_list(self,exception_log_list):
        self.exception_log_list = exception_log_list

    def add_log_handle(self, handle):
        '''添加实时日志处理器，每产生一条日志，就调用一次handle
        '''
        self.device.adb._logcat_handle.append(handle)
        
    def remove_log_handle(self, handle):
        '''删除实时日志处理器
        '''
        self.device.adb._logcat_handle.remove(handle)

    def handle_exception(self, log_line):
        '''
        这个方法在每次有log时回调
        :param log_line:最近一条的log 内容
        异常日志写一个文件
        :return:void
        '''
        # 检查日志是否匹配任何异常标签
        matched_tags = [tag for tag in self.exception_log_list if tag in log_line]
        
        if matched_tags:
            logger.debug("exception Info: " + log_line)
            tmp_file = os.path.join(RuntimeData.package_save_path, 'exception.log')
            with open(tmp_file, 'a+',encoding="utf-8") as f:
                f.write(log_line + '\n')
            #     这个路径 空格会有影响
            process_stack_log_file = os.path.join(RuntimeData.package_save_path, 'process_stack_%s_%s.log' % (
            self.package, TimeUtils.getCurrentTimeUnderline()))
            # 如果进程挂了，pid会变 ，抓变后进程pid的堆栈没有意义
            # self.logmonitor.device.adb.get_process_stack(self.package,process_stack_log_file)
            if RuntimeData.old_pid:
                self.device.adb.get_process_stack_from_pid(RuntimeData.old_pid, process_stack_log_file)
            
            # 实时钉钉通知：如果异常日志中包含当前测试的包名，立即发送通知
            # 去重策略：使用日志内容的hash作为key，5分钟内相同内容的日志只发送一次通知
            if (self.test_package and 
                self.dingding_webhook and 
                self.test_package in log_line):
                
                # 使用日志内容的hash作为去重key（截取前200字符避免hash过长）
                log_hash = hashlib.md5(log_line[:200].encode('utf-8')).hexdigest()
                
                # 检查是否需要发送通知（5分钟内不重复）
                current_time = time.time()
                last_notification_info = self.last_notification_time.get(log_hash, None)
                time_interval = 300  # 5分钟（300秒）去重间隔
                
                should_send = True
                if last_notification_info:
                    last_time = last_notification_info.get('time', 0)
                    if current_time - last_time < time_interval:
                        should_send = False
                        remaining_time = int(time_interval - (current_time - last_time))
                        logger.debug(f"Skip duplicate notification (same content sent {remaining_time}s ago, min interval: {time_interval}s)")
                
                if should_send:
                    # 更新最后通知时间
                    self.last_notification_time[log_hash] = {
                        'time': current_time,
                        'tag': matched_tags[0]  # 使用第一个匹配的标签
                    }
                    # 使用第一个匹配的标签作为异常类型
                    tag = matched_tags[0]
                    # 异步发送通知，避免阻塞日志处理
                    threading.Thread(target=self._send_dingding_notification_async, 
                                   args=(log_line, tag), 
                                   daemon=True).start()
    
    def _send_dingding_notification_async(self, log_line, exception_tag):
        """
        异步发送钉钉通知
        :param str log_line: 异常日志内容
        :param str exception_tag: 异常标签
        """
        try:
            from mobileperf.common.dingding import DingDingNotifier
            
            if not self.dingding_webhook:
                return
            
            notifier = DingDingNotifier(self.dingding_webhook)
            
            # 提取时间戳信息，使用带冒号的时间格式
            current_time = time.strftime(TimeUtils.ColonFormatter, time.localtime(time.time()))
            test_path = RuntimeData.package_save_path if RuntimeData.package_save_path else "未知路径"
            
            # 获取Web服务器地址
            web_server_url = ""
            try:
                import socket
                # 默认端口5000
                web_port = 5000
                try:
                    hostname = socket.gethostname()
                    ip = socket.gethostbyname(hostname)
                    web_server_url = f"http://{ip}:{web_port}"
                except:
                    web_server_url = f"http://localhost:{web_port}"
            except:
                pass  # 如果获取失败，就不显示web地址
            
            # 构建通知内容，限制日志长度避免消息过长
            log_preview = log_line[:500] if len(log_line) > 500 else log_line
            title = f"🚨 实时异常提醒 - {self.test_package}"
            
            # 如果有web服务器地址，添加到消息中
            web_url_text = ""
            if web_server_url:
                web_url_text = f"\n**Web查看**: {web_server_url}"
            
            content = f"""## {title}

**包名**: {self.test_package}
**异常类型**: {exception_tag}
**检测时间**: {current_time}{web_url_text}
**异常日志**: 
```
{log_preview}
```
**测试路径**: `{test_path}`
> ⚠️ monkey执行过程中检测到异常，请及时查看日志分析！！！
"""
            
            # 如果配置了手机号列表，则@指定人员
            at_mobiles = self.dingding_mobiles if self.dingding_mobiles else None
            success = notifier.send_text_message(title, content, at_mobiles=at_mobiles, at_all=False)
            if success:
                logger.info(f"DingDing notification sent for exception: {exception_tag}")
                if at_mobiles:
                    logger.info(f"@人员: {', '.join(at_mobiles)}")
            else:
                logger.warning(f"Failed to send DingDing notification for exception: {exception_tag}")
                
        except Exception as e:
            logger.error(f"Error sending DingDing notification: {e}")
            import traceback
            logger.debug(traceback.format_exc())


class LaunchTime(object):

    def __init__(self,deviceid, packagename = ""):
        # 列表的容积应该不用担心，与系统有一定关系，一般存几十万条数据没问题的
        self.launch_list = [("datetime","packagenme/activity","this_time(s)","total_time(s)","launchtype")]
        self.packagename = packagename

    def handle_launchtime(self, log_line):
        '''
        这个方法在每次一个启动时间的log产生时回调
        :param log_line:最近一条的log 内容
        :param tag:启动的方式，是normal的启动，还是自定义方式的启动：fullydrawnlaunch
        #如果监控到到fully drawn这样的log，则优先统计这种log，它表示了到起始界面自定义界面的启动时间
        :return:void
        '''
        # logger.debug(log_line)
        # 08-28 10:57:30.229 18882 19137 D IC5: CLogProducer == > code = 0, uuid = 4FE71E350379C64611CCD905938C10CA, eventType = performance, eventName = am_activity_launch_timeme, \
        #    log_time = 2019-08-28 10:57:30.229, contextInfo = {"tag": "am_activity_launch_time", "start_time": "2019-08-28 10:57:16",
        #                              "activity_name_original": "com.android.settings\/.FallbackHome",
        #                              "activity_name": "com.android.settings#com.android.settings.FallbackHome",
        #                              "this_time": "916", "total_time": "916", "start_type": "code_start",
        #                              "gmt_create": "2019-08-28 10:57:16.742", "uploadtime": "2019-08-28 10:57:30.173",
        #                              "boottime": "2019-08-28 10:57:18.502", "firstupload": "2019-08-28 10:57:25.733"}
        ltag = ""
        if ("am_activity_launch_time" in log_line or "am_activity_fully_drawn_time" in log_line):
            # 最近增加的一条如果是启动时间相关的log，那么回调所有注册的_handle
            if "am_activity_launch_time" in log_line:
                ltag = "normal launch"
            elif "am_activity_fully_drawn_time" in log_line:
                ltag = "fullydrawn launch"
            logger.debug("launchtime log:"+log_line)
        if ltag:
            content = []
            timestamp = time.time()
            content.append(TimeUtils.formatTimeStamp(timestamp))
            temp_list = log_line.split()[-1].replace("[", "").replace("]", "").split(',')[2:5]
            for i in range(len(temp_list)):
                content.append(temp_list[i])
            content.append(ltag)
            logger.debug("Launch Info: "+str(content))
            if len(content) == 5:
                content = self.trim_value(content)
                if content:
                    self.update_launch_list(content,timestamp)

    def trim_value(self, content):
        try:
            content[2] = ms2s(float(content[2]))#将this_time转化单位转化为s
            content[3] = ms2s(float(content[3]))#将total_time 转化为s
        except Exception as e:
            logger.error(e)
            return []
        return content

    def update_launch_list(self, content,timestamp):
        # if self.packagename in content[1]:
        self.launch_list.append(content)
        tmp_file = os.path.join(RuntimeData.package_save_path, 'launch_logcat.csv')
        perf_data = {"task_id":"",'launch_time':[],'cpu':[],"mem":[],
                         'traffic':[], "fluency":[],'power':[],}
        dic = {"time": timestamp,
                 "act_name": content[1],
                 "this_time": content[2],
                 "total_time": content[3],
                 "launch_type": content[4]}
        perf_data['launch_time'].append(dic)
        # perf_queue.put(perf_data)

        with open(tmp_file,"a+",encoding="utf-8") as f:
            csvwriter = csv.writer(f, lineterminator='\n')#这种方式可以去除csv的空行
            logger.debug("save launchtime data to csv: " + str(self.launch_list))
            csvwriter.writerows(self.launch_list)
            del self.launch_list[:]

if __name__ == '__main__':
    logcat_monitor = LogcatMonitor("85I7UO4PFQCINJL7", "com.yunos.tv.alitvasr")
    # 如果有异常日志标志，才启动这个模块
    exceptionlog_list=["fatal exception","has died"]
    if exceptionlog_list:
        logcat_monitor.set_exception_list(exceptionlog_list)
        logcat_monitor.add_log_handle(logcat_monitor.handle_exception)
    start_time = TimeUtils.getCurrentTimeUnderline()
    RuntimeData.package_save_path = os.path.join(FileUtils.get_top_dir(), 'results', "com.yunos.tv.alitvasr", start_time)
    logcat_monitor.start(start_time)
