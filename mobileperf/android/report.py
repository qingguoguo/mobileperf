# encoding: utf-8
'''
@author:     look

@copyright:  1999-2020 Alibaba.com. All rights reserved.

@license:    Apache Software License 2.0

@contact:    390125133@qq.com
'''
import os
import csv
from datetime import datetime

from mobileperf.android.excel import Excel
from mobileperf.common.log import logger
from mobileperf.common.utils import TimeUtils

class Report(object):
    def __init__(self, csv_dir, packages=[]):
        os.chdir(csv_dir)
        # 需要画曲线的csv文件名
        self.summary_csf_file={"cpuinfo.csv":{"table_name":"pid_cpu",
                                          "x_axis":"datetime",  # 修正：cpuinfo.csv使用datetime
                                          "y_axis":"%",
                                          "values":["pid_cpu%","total_pid_cpu%"]},
                               "meminfo.csv":{"table_name":"pid_pss",
                                          "x_axis":"datatime",
                                          "y_axis":"mem(MB)",
                                          "values":["pid_pss(MB)","total_pss(MB)"]},
                               "pid_change.csv": {"table_name": "pid",
                                           "x_axis": "datatime",
                                           "y_axis": "pid_num",
                                           "values": ["pid"]},
                               "thread_num.csv": {"table_name": "thread_num",
                                           "x_axis": "datatime",
                                           "y_axis": "thread_count",
                                           "values": ["thread_num"]},
                               "fps.csv": {"table_name": "fps",
                                           "x_axis": "datetime",
                                           "y_axis": "fps/jank",
                                           "values": ["fps", "jank"]},
                               "traffic.csv": {"table_name": "traffic",
                                           "x_axis": "datetime",
                                           "y_axis": "traffic(KB)",
                                           "values": ["pid_rx(KB)", "pid_tx(KB)", "pid_total(KB)"]},
                               "fd_num.csv": {"table_name": "fd_num",
                                           "x_axis": "datatime",
                                           "y_axis": "fd_count",
                                           "values": ["fd_num"]},
                               }
        self.packages = packages
        if len(self.packages)>0:
            for package in self.packages:
                pss_detail_dic ={"table_name":"pss_detail",
                                          "x_axis":"datatime",
                                          "y_axis":"mem(MB)",
                                          "values":["pss","java_heap","native_heap","system"]
                }
                #        文件名太长会导致写excel失败
                self.summary_csf_file["pss_%s.csv"%package.split(".")[-1].replace(":","_")]= pss_detail_dic
        logger.debug(self.packages)
        logger.debug(self.summary_csf_file)
        logger.info('create report for %s' % csv_dir)
        file_names = self.filter_file_names(csv_dir)
        logger.debug('%s' % file_names)
        if file_names:
            book_name = 'summary_%s.xlsx' % TimeUtils.getCurrentTimeUnderline()
            excel = Excel(book_name)
            for file_name in file_names:
                logger.debug('get csv %s to excel' % file_name)
                values = self.summary_csf_file[file_name]
                # 读取CSV文件的实际列名，只使用存在的列
                actual_columns = self.get_csv_columns(file_name)
                if not actual_columns:
                    logger.warning('Failed to read columns from %s, skipping...' % file_name)
                    continue
                # 过滤掉CSV中不存在的列
                valid_values = [v for v in values["values"] if v in actual_columns]
                if not valid_values:
                    logger.warning('No valid columns found in %s for values: %s, actual columns: %s' % 
                                 (file_name, values["values"], actual_columns))
                    continue
                logger.info('Using columns for %s: %s (requested: %s, actual: %s)' % 
                          (file_name, valid_values, values["values"], actual_columns))
                excel.csv_to_xlsx(file_name, values["table_name"], values["x_axis"], 
                                values["y_axis"], valid_values)
            logger.info('wait to save %s' % book_name)
            excel.save()
    
    def get_csv_columns(self, csv_file):
        '''读取CSV文件的第一行（列名）'''
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                headers = next(reader, None)
                return headers if headers else []
        except Exception as e:
            logger.error('Error reading CSV columns from %s: %s' % (csv_file, e))
            return []
    #
    def filter_file_names(self, device):
        csv_files = []
        logger.debug(device)
        for f in os.listdir(device):
            if os.path.isfile(os.path.join(device, f)) and os.path.basename(f) in self.summary_csf_file.keys():
               logger.debug(os.path.join(device, f))
               csv_files.append(f)
        return csv_files
        #return [f for f in os.listdir(device) if os.path.isfile(os.path.join(device, f)) and os.path.basename(f) in self.summary_csf_file.keys()]

if __name__ == '__main__':
# 根据csv生成excel汇总文件
    from mobileperf.android.globaldata import RuntimeData
    RuntimeData.packages = ["com.alibaba.ailabs.genie.smartapp","com.alibaba.ailabs.genie.smartapp:core","com.alibaba.ailabs.genie.smartapp:business"]
    RuntimeData.package_save_path = "/Users/look/Downloads/mobileperf-turandot-shicun-2-13/results/com.alibaba.ailabs.genie.smartapp/2020_02_13_22_58_14"
    report = Report(RuntimeData.package_save_path,RuntimeData.packages)
    report.filter_file_names(RuntimeData.package_save_path)
