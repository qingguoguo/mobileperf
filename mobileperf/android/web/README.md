# MobilePerf Web 模块

## 目录结构

```
mobileperf/android/web/
├── __init__.py           # 模块初始化
├── web_server.py         # Web 服务器实现
├── templates/            # HTML 模板
│   └── index.html        # 主页面
├── static/               # 静态资源（CSS、JS等）
└── README.md            # 本文件
```

## 功能说明

Web 模块提供日志查看 Web 服务，支持：
- 查看异常日志（exception.log）
- 查看 Logcat 输出
- 搜索功能
- 历史测试结果浏览

## 使用方法

### 方式一：独立启动（推荐）

**将Web服务与Monkey测试分离，独立运行，更稳定可靠。**

启动Web服务：
```bash
# 使用默认端口5000
python -m mobileperf.android.web.start_web_server

# 或指定端口
python -m mobileperf.android.web.start_web_server 5000

# 或直接运行脚本
python mobileperf/android/web/start_web_server.py
```

停止Web服务：按 `Ctrl+C`

### 方式二：自动启动（测试时）

Web 服务器会在 Monkey 测试启动时自动检测并启动（如果未运行）。

访问地址：
- 本地: http://localhost:5000
- 局域网: http://<你的IP>:5000

### Web 服务管理

#### 查看 Web 服务状态

```bash
# 检查端口5000是否被占用（Web服务是否运行）
lsof -i :5000
# 或者在macOS/Linux上
netstat -an | grep 5000
# 或者在Windows上
netstat -an | findstr 5000
```

#### 停止 Web 服务

方式1：通过进程ID停止
```bash
# 1. 找到Web服务进程ID
ps aux | grep mobileperf  # macOS/Linux
# 或
tasklist | findstr mobileperf  # Windows

# 2. 杀死进程
kill <进程ID>  # macOS/Linux
# 或
taskkill /PID <进程ID> /F  # Windows
```

方式2：通过端口停止
```bash
# macOS/Linux
lsof -ti:5000 | xargs kill
# 或
kill -9 $(lsof -ti:5000)

# Windows
# 1. 找到占用5000端口的进程ID
netstat -ano | findstr :5000
# 2. 停止进程
taskkill /PID <进程ID> /F
```

#### 重启 Web 服务

Web 服务会在下次运行 Monkey 测试时自动检测并启动（如果未运行）。你也可以手动重启：

1. 先停止 Web 服务（使用上面的停止命令）
2. 重新运行 Monkey 测试，Web 服务会自动启动

或者直接重启整个 mobileperf 进程：
```bash
# 停止当前进程后，重新运行
python mobileperf/android/startup.py
```

## 技术细节

### web_server.py
Flask 实现的 Web 服务器，提供以下 API：
- `GET /` - 主页
- `GET /api/results` - 获取所有测试结果
- `GET /api/logs/<package>/<timestamp>` - 获取指定测试的日志
- `GET /api/search?keyword=xxx` - 搜索日志
- `GET /api/live/<package>` - 获取实时日志

### templates/index.html
现代化的 Web 界面，使用原生 JavaScript，无依赖。

## 集成方式

在 `mobileperf/android/monkey.py` 中：
```python
from mobileperf.android.web.web_server import MobilePerfWebServer

# 在 Monkey 初始化时创建
self.web_server = MobilePerfWebServer(port=5000)

# 在 start 时启动
self.web_server.start()

# 在 stop 时停止
self.web_server.stop()
```

## 开发说明

如需修改模板，编辑 `templates/index.html`  
如需修改 API，编辑 `web_server.py`  
如需添加静态资源，放入 `static/` 目录

