# encoding: utf-8
'''
钉钉通知工具类
用于发送钉钉消息通知
'''
import json
import urllib.request
import urllib.error
import urllib.parse

from mobileperf.common.log import logger


class DingDingNotifier(object):
    """钉钉消息通知类"""
    
    def __init__(self, webhook_url):
        """
        初始化钉钉通知器
        
        :param str webhook_url: 钉钉机器人 Webhook URL
        """
        self.webhook_url = webhook_url
    
    def send_text_message(self, title, content, at_mobiles=None, at_all=False):
        """
        发送文本消息到钉钉
        
        :param str title: 消息标题
        :param str content: 消息内容
        :param list at_mobiles: @的手机号列表，如 ['138xxxx8888']
        :param bool at_all: 是否@所有人
        :return: bool 发送是否成功
        """
        if not self.webhook_url:
            logger.warning("DingDing webhook URL is not configured, skip notification")
            return False
        
        try:
            # 钉钉markdown类型消息不支持@功能，如果需要@人，必须使用text类型
            if at_mobiles or at_all:
                # 使用text类型消息以支持@功能
                # 将markdown内容转换为纯文本（简单处理）
                import re
                
                # 先提取代码块内容（保留内容，只移除标记）
                code_block_pattern = r'```[\s]*\n?(.*?)```'
                def replace_code_block(match):
                    code_content = match.group(1)
                    return code_content.strip()  # 保留代码内容，只移除标记
                
                text_content = re.sub(code_block_pattern, replace_code_block, content, flags=re.DOTALL)
                
                # 移除markdown格式标记
                text_content = re.sub(r'\*\*(.*?)\*\*', r'\1', text_content)  # 移除粗体 **文字**
                text_content = re.sub(r'\*(.*?)\*', r'\1', text_content)  # 移除斜体 *文字*
                text_content = re.sub(r'`([^`]+)`', r'\1', text_content)  # 移除行内代码 `代码`
                
                # 移除标题行（## 标题格式），同时移除标题内容本身，避免与title重复
                text_content = re.sub(r'^##\s+.*?\n', '', text_content, flags=re.MULTILINE)  # 移除整行标题
                text_content = re.sub(r'^>\s+', '', text_content, flags=re.MULTILINE)  # 移除引用标记 >
                
                # 压缩多余的空行：3个或更多连续空行变成一个空行
                text_content = re.sub(r'\n{3,}', '\n\n', text_content)
                # 移除每行开头结尾的空白
                lines = [line.strip() for line in text_content.split('\n')]
                # 合并相邻的空行（连续多个空行变成一个）
                cleaned_lines = []
                prev_empty = False
                for line in lines:
                    if line == '':
                        if not prev_empty:
                            cleaned_lines.append(line)
                        prev_empty = True
                    else:
                        cleaned_lines.append(line)
                        prev_empty = False
                text_content = '\n'.join(cleaned_lines).strip()
                
                # 如果text_content的第一行还是title的内容，也要移除（避免重复）
                first_line = text_content.split('\n')[0] if text_content else ''
                if title in first_line or first_line.strip() == title.strip():
                    text_content = '\n'.join(text_content.split('\n')[1:]).strip()
                
                # 添加标题和@标记，使用更紧凑的格式（只保留必要的换行）
                final_content = f"{title}\n{text_content}\n"
                if at_mobiles:
                    at_text = " ".join([f"@{mobile}" for mobile in at_mobiles])
                    final_content += at_text
                elif at_all:
                    final_content += "@所有人"
                
                # 构建text类型消息
                msg = {
                    "msgtype": "text",
                    "text": {
                        "content": final_content
                    }
                }
                
                # 添加@信息到at字段
                msg["at"] = {}
                if at_mobiles:
                    msg["at"]["atMobiles"] = at_mobiles
                if at_all:
                    msg["at"]["isAtAll"] = True
            else:
                # 不需要@人时，使用markdown类型（格式更美观）
                msg = {
                    "msgtype": "markdown",
                    "markdown": {
                        "title": title,
                        "text": content
                    }
                }
            
            # 发送请求
            data = json.dumps(msg).encode('utf-8')
            req = urllib.request.Request(self.webhook_url, data=data, headers={'Content-Type': 'application/json'})
            response = urllib.request.urlopen(req, timeout=10)
            result = json.loads(response.read().decode('utf-8'))
            
            if result.get('errcode') == 0:
                logger.info("DingDing notification sent successfully")
                return True
            else:
                logger.error(f"Failed to send DingDing notification: {result.get('errmsg', 'Unknown error')}")
                return False
                
        except urllib.error.URLError as e:
            logger.error(f"Failed to send DingDing notification (network error): {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to send DingDing notification: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def notify_exception(self, package, test_path, exception_log_path, at_mobiles=None):
        """
        发送异常通知
        
        :param str package: 包名
        :param str test_path: 测试结果路径
        :param str exception_log_path: 异常日志文件路径
        :param list at_mobiles: @的手机号列表，如 ['138xxxx8888']
        :return: bool 发送是否成功
        """
        title = f"⚠️ 测试异常提醒 - {package}"
        
        # 从路径中提取时间戳信息
        import os
        import socket
        timestamp = os.path.basename(test_path) if test_path else "未知时间"
        
        # 获取Web服务器地址
        web_server_url = ""
        try:
            web_port = 5000
            try:
                hostname = socket.gethostname()
                ip = socket.gethostbyname(hostname)
                web_server_url = f"http://{ip}:{web_port}"
            except:
                web_server_url = f"http://localhost:{web_port}"
        except:
            pass  # 如果获取失败，就不显示web地址
        
        web_url_text = ""
        if web_server_url:
            web_url_text = f"\n**Web查看**: {web_server_url}"
        
        content = f"""## {title}

**包名**: {package}
**测试时间**: {timestamp}{web_url_text}
**异常信息**: 检测到 exception.log 文件中包含该包名的异常信息
**测试路径**: `{test_path}`
**异常日志**: `{exception_log_path}`
> 请及时查看异常日志文件，排查问题原因。
"""
        
        return self.send_text_message(title, content, at_mobiles=at_mobiles, at_all=False)

