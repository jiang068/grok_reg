## grok_reg — 半自动 grok 注册机

参考项目: https://github.com/syhien/grokzhuce

一个半自动化的注册工具，会在浏览器中执行大部分流程，但在需要通过验证码或 Cloudflare 验证时需要人工介入。

### 准备

- 一个可用的 [freemail](https://github.com/idinging/freemail) 服务（如果没有，请先部署一个）。
- 网络代理（可选，根据目标网站的网络限制决定是否使用）。

### 环境

- Python 3.12
- 使用 uv 工具创建虚拟环境并安装依赖：

```powershell
uv venv --python 3.12
uv pip install -r requirements.txt
```

（如果不使用 uv，请用你常用的虚拟环境工具和 pip 安装依赖）

### 使用方法

1. 在项目根目录创建并填写 `.env`，至少包含：

```properties
WORKER_DOMAIN=mail.example.com
FREEMAIL_TOKEN=your_token_here
```

2. 启动程序：

```powershell
uv run main.py
```

3. 按提示输入并发线程数和总任务数（回车使用默认值）。

### 运行时注意

- 当控制台提示需要人工完成验证码或 Cloudflare 验证时，切换到对应的浏览器窗口完成验证，然后回到控制台按回车继续。脚本已尽量集中提示，减少重复阻塞。

### 输出

- 运行结果文件位于 `data/` 目录，文件名格式为 `key-<时间>-<数量>.csv`，可以用 Excel 打开并复制所需字段。

### 说明

- 本项目为半自动工具 —— 无法完全绕过带有交互验证的保护，需人工配合完成少量操作。
