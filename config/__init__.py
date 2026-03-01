"""Configuration for grok_reg package.

Loads configuration from environment variables with sensible defaults.
"""
import os
# 尝试在 package 导入时自动加载 grok_reg/.env（如果安装了 python-dotenv）
try:
    from dotenv import load_dotenv, find_dotenv
    pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    dotenv_path = os.path.join(pkg_root, '.env')
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)
    else:
        # 回退到 find_dotenv，以便向上查找 .env
        load_dotenv(find_dotenv())
except Exception:
    # 如果没有安装 python-dotenv 或发生其他错误，则忽略并继续
    pass

class _Config:
    pass

config = _Config()

# HTTP 代理
# 读取顺序：GROK_REG_PROXY -> PROXY；如果环境变量存在但为空字符串，则视为不使用代理（None）
_proxy_val = os.getenv("GROK_REG_PROXY")
if _proxy_val is None:
    _proxy_val = os.getenv("PROXY")
# 如果用户显式设置为空字符串（例如 GROK_REG_PROXY=""），表示禁用代理
config.PROXY = _proxy_val if _proxy_val not in (None, "") else None

# freemail 服务配置
config.FREEMAIL_WORKER_DOMAIN = os.getenv("WORKER_DOMAIN")

# API/token（敏感）
config.FREEMAIL_TOKEN = os.getenv("FREEMAIL_TOKEN")

# 浏览器类型
config.BROWSER_TYPE = os.getenv("GROK_REG_BROWSER", "camoufox")

# 并发线程数默认值
config.THREADS = int(os.getenv("GROK_REG_THREADS", os.getenv("THREADS", "2")))

# 注册目标
config.SIGNUP_URL = os.getenv("GROK_REG_SIGNUP_URL", "https://accounts.x.ai/sign-up")

# 输出目录（指向 package 下的 data 目录）
base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
config.OUTPUT_DIR = os.getenv("GROK_REG_OUTPUT_DIR", os.path.join(base_dir, "data"))

# 调试开关
config.DEBUG = os.getenv("GROK_REG_DEBUG", os.getenv("DEBUG", "1")).lower() in ("1", "true", "True", "yes")

# 是否保持浏览器打开（调试）
config.KEEP_BROWSER_OPEN = os.getenv("GROK_REG_KEEP_BROWSER_OPEN", os.getenv("KEEP_BROWSER_OPEN", "0")).lower() in ("1", "true", "yes")

# 等待进入验证码输入页面的超时时间（秒），默认 30 秒
try:
    config.VERIFICATION_INPUT_WAIT_SECONDS = int(os.getenv("VERIFICATION_INPUT_WAIT_SECONDS", os.getenv("VERIFICATION_WAIT_SECONDS", "30")))
except Exception:
    config.VERIFICATION_INPUT_WAIT_SECONDS = 30

# 总任务数（并发由 config.THREADS 控制）。默认与 threads 相同，可通过环境变量 TOTAL_TASKS 设置
try:
    config.TOTAL_TASKS = int(os.getenv("TOTAL_TASKS", "0")) or config.THREADS
except Exception:
    config.TOTAL_TASKS = config.THREADS
