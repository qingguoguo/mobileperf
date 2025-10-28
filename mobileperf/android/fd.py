#encoding:utf-8
'''
@author:     look

@copyright:  1999-2020 Alibaba.com. All rights reserved.

@license:    Apache Software License 2.0

@contact:    390125133@qq.com
'''
import csv
import os
import re
import sys
import threading
import time
import traceback

BaseDir=os.path.dirname(__file__)
sys.path.append(os.path.join(BaseDir,'../..'))

from mobileperf.android.tools.androiddevice import AndroidDevice
from mobileperf.common.utils import TimeUtils
from mobileperf.common.log import logger
from mobileperf.android.globaldata import RuntimeData

class FdInfoPackageCollector(object):
    def __init__(self, device, pacakgename, interval=1.0, timeout =24 * 60 * 60,fd_queue = None):
        self.device = device
        self.packagename = pacakgename
        self._interval = interval
        self._timeout = timeout
        self._stop_event = threading.Event()
        self.fd_queue = fd_queue


    def start(self,start_time):
        logger.debug("INFO: FdInfoPackageCollector start... ")
        self.collect_fd_thread = threading.Thread(target=self._collect_fd_thread, args=(start_time,))
        self.collect_fd_thread.start()

    def stop(self):
        logger.debug("INFO: FdInfoPackageCollector stop... ")
        if (self.collect_fd_thread.is_alive()):
            self._stop_event.set()
            self.collect_fd_thread.join(timeout=1)
            self.collect_fd_thread = None
            #结束的时候，发送一个任务完成的信号，以结束队列
            if self.fd_queue:
                self.fd_queue.task_done()

    def get_process_fd(self, process):
        pid = self.device.adb.get_pid_from_pck(self.packagename)
        if pid is None:
            return []
        
        global old_pid
        # pid发生变化 ，更新old_pid,这个时间间隔长
        if None == RuntimeData.old_pid or RuntimeData.old_pid!=pid:
            RuntimeData.old_pid = pid
        
        collection_time = time.time()
        logger.debug("collection time in fd info is : " + str(collection_time))
        
        # 先尝试直接获取（适用于adb root或Android 6.0及以下）
        out = self.device.adb.run_shell_cmd('ls /proc/%s/fd 2>/dev/null | wc -l' % pid)
        if out and out.strip().isdigit():
            fd_num = int(out.strip())
            logger.debug(f"FD count (direct access): {fd_num}")
            return [collection_time,self.packagename,pid,fd_num]
        
        # 如果直接获取失败，尝试使用su权限
        out = self.device.adb.run_shell_cmd('su 0 sh -c "ls /proc/%s/fd 2>/dev/null | wc -l"' % pid)
        if out and out.strip().isdigit():
            fd_num = int(out.strip())
            logger.debug(f"FD count (via su): {fd_num}")
            return [collection_time,self.packagename,pid,fd_num]
        
        logger.warning(f"Failed to get FD count for PID {pid}")
        return []

    def _collect_fd_thread(self, start_time):
        end_time = time.time() + self._timeout
        fd_list_titile = ("datatime", "packagename", "pid", "fd_num")
        fd_file = os.path.join(RuntimeData.package_save_path, 'fd_num.csv')
        try:
            with open(fd_file, 'a+') as df:
                csv.writer(df, lineterminator='\n').writerow(fd_list_titile)
                if self.fd_queue:
                    fd_file_dic = {'fd_file': fd_file}
                    self.fd_queue.put(fd_file_dic)
        except RuntimeError as e:
            logger.error(e)

        while not self._stop_event.is_set() and time.time() < end_time:
            try:
                before = time.time()
                logger.debug("-----------into _collect_fd_thread loop, thread is : " + str(threading.current_thread().name))

                # 获取pakagename的fd信息
                fd_pck_info = self.get_process_fd(self.packagename)
                current_time = TimeUtils.getCurrentTime()
                if not fd_pck_info:
                    continue
                else:
                    logger.debug(
                        "current time: " + current_time + ", processname: " +fd_pck_info[1]+ ", pid: " + str(fd_pck_info[2]) +
                        " fd num: " + str(fd_pck_info[3]))
                if self.fd_queue:
                    self.fd_queue.put(fd_pck_info)
                if not self.fd_queue:#为了本地单个文件运行
                    try:
                        with open(fd_file, 'a+',encoding="utf-8") as fd_writer:
                            writer_p = csv.writer(fd_writer, lineterminator='\n')
                            fd_pck_info[0] = current_time
                            writer_p.writerow(fd_pck_info)
                    except RuntimeError as e:
                        logger.error(e)

                after = time.time()
                time_consume = after - before
                delta_inter = self._interval - time_consume
                logger.debug("time_consume  for fd infos: " + str(time_consume))
                if delta_inter > 0:
                    time.sleep(delta_inter)
            except:
                logger.error("an exception hanpend in fdinfo thread, reason unkown!")
                s = traceback.format_exc()
                logger.debug(s)
                if self.fd_queue:
                    self.fd_queue.task_done()

class FdMonitor(object):
    def __init__(self, device_id, packagename, interval = 1.0,timeout=24*60*60, fd_queue = None):
        self.device = AndroidDevice(device_id)
        if not packagename:
            packagename = self.device.adb.get_foreground_process()
        self.fd_package_collector = FdInfoPackageCollector(self.device, packagename, interval, timeout,fd_queue)

    def start(self,start_time):
        self.start_time = start_time
        self.fd_package_collector.start(start_time)

    def stop(self):
        self.fd_package_collector.stop()

    def save(self):
        pass

if __name__ == "__main__":
    monitor = FdMonitor("","com.yunos.tv.alitvasr",3)
    monitor.start(TimeUtils.getCurrentTime())
    time.sleep(20)
    monitor.stop()
#     monitor.save()







