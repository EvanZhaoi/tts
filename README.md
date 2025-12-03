# 本地离线文本转语音项目说明

本项目包含一个**后端 TTS 服务**和一个**前端网页**，支持将文本转换为语音并提供音频下载。  
后端使用 Coqui TTS 的本地模型，部署后**不依赖任何外部云服务**，可完全离线运行。

当前状态：
- 中文 / 英文：已验证可用，支持离线；
- 日语：模型和依赖尚未完全打通，暂不作为稳定功能使用。

---

## 1. 项目结构

- `tts-server/`：后端服务（FastAPI + Coqui TTS）
  - `main.py`：FastAPI 入口，提供 `/api/tts` 接口。
  - `requirements.txt`：后端依赖列表。
  - `Dockerfile`：用于构建完全离线可运行的 Docker 镜像。
  - `models/`：本地 TTS 模型目录（**你需要提前准备好**）
    - `models/zh/`：中文模型文件（baker）
    - `models/en/`：英文模型文件（ljspeech）
    - `models/ja/`：日文模型文件（目前不建议依赖）
  - `outputs/`：接口生成的音频文件（运行时自动创建）。

- `tts-web/`：前端网页
  - `index.html`：简单 UI（文本输入、语言选择、生成语音、下载音频）。
  - `script.js`：调用后端 API。
  - `style.css`：样式。

---

## 2. 后端接口概览

### 2.1 生成语音

- URL：`POST /api/tts`
- 请求体（JSON）：

  ```json
  {
    "text": "要转换的文本",
    "lang": "zh"   // 可选：zh / en / ja，默认为 zh
  }
  ```

- 响应示例：

  ```json
  {
    "file": "tts_1719999999_abcd1234.wav",
    "lang": "zh"
  }
  ```

### 2.2 下载音频

- URL：`GET /api/tts/{filename}`
- 作用：直接返回生成好的 `wav` 文件，用于浏览器下载或播放器播放。

### 2.3 健康检查

- URL：`GET /health`
- 响应：`{"status": "ok"}`

---

## 3. 本地开发环境运行（非 Docker）

> 假设当前目录为项目根：`/Users/.../Project`

### 3.1 准备 Python 环境和依赖

```bash
cd tts-server

python3 -m venv venv
source venv/bin/activate        # Windows 用 venv\Scripts\activate

pip install --upgrade pip
pip install -r requirements.txt
```

### 3.2 准备本地 TTS 模型（中文 / 英文）

**重要：** 后端不会联网下载模型，所有模型必须提前放在 `tts-server/models` 目录中。

#### 3.2.1 在有网的开发机上下载模型

在已经激活的虚拟环境下：

```bash
cd tts-server
source venv/bin/activate

python3 - << 'PY'
from TTS.utils.manage import ModelManager

manager = ModelManager(progress_bar=True, verbose=True)

# 下载中文模型
manager.download_model("tts_models/zh-CN/baker/tacotron2-DDC-GST")

# 下载英文模型
manager.download_model("tts_models/en/ljspeech/vits")
PY
```

下载完成后，Coqui TTS 会把模型放在类似目录中：

- macOS 示例：`$HOME/Library/Application Support/tts`

你可以用以下命令确认：

```bash
ls "$HOME/Library/Application Support/tts"
```

理论上会看到：

- `tts_models--zh-CN--baker--tacotron2-DDC-GST`
- `tts_models--en--ljspeech--vits`

#### 3.2.2 拷贝模型到项目 `models` 目录

```bash
cd /Users/.../Project/tts-server

TTS_ROOT="$HOME/Library/Application Support/tts"

mkdir -p models/zh models/en

# 中文
cp -R "$TTS_ROOT/tts_models--zh-CN--baker--tacotron2-DDC-GST/." models/zh/

# 英文
cp -R "$TTS_ROOT/tts_models--en--ljspeech--vits/." models/en/
```

确保每个目录下至少包含：

- `models/zh/config.json`
- `models/zh/model_file.pth`（或 `model.pth` / `model_file.pth.tar` 之一）
- `models/en/config.json`
- `models/en/model_file.pth`（或 `model.pth` / `model_file.pth.tar` 之一）

> 如果只有 `model.pth`，也可以手动改名为 `model_file.pth`，后端内部会按多个备选名称查找。

> 日语模型（`models/ja`）目前依赖较多（MeCab 等），且还没完全打通，可以暂时忽略，不在此说明。

### 3.3 启动后端服务

```bash
cd /Users/.../Project/tts-server
source venv/bin/activate

uvicorn main:app --host 0.0.0.0 --port 8000
```

此时后端已启动在 `http://127.0.0.1:8000`。

### 3.4 启动前端（本机）

```bash
cd /Users/.../Project/tts-web
open index.html    # macOS，Windows 直接双击 index.html
```

前端会通过 `script.js` 里的 `API_BASE` 调用后端：

```js
const API_BASE = "http://127.0.0.1:8000";
```

在浏览器中：

1. 输入文本；
2. 选择语言（中文 / English）；
3. 点击“生成语音”，等待生成；
4. 点击“下载音频”按钮获取 `.wav` 文件。

---

## 4. 完全离线 Docker 部署流程

目标：在**有网**的构建机上一次性拉齐依赖和模型，打包为 Docker 镜像，之后在**无网**环境中直接运行。

### 4.1 前提准备

在有网的机器上：

1. 按「3.1 ~ 3.2」步骤准备好虚拟环境和 `models/zh`、`models/en` 目录；
2. 确保 `tts-server/models` 目录结构完整：

   ```bash
   ls tts-server/models
   # 应包含：zh en （ja 可选）
   ```

### 4.2 构建 Docker 镜像（有网环境）

```bash
cd /Users/.../Project/tts-server

docker build -t offline-tts:latest .
```

`Dockerfile` 做的事情包括：

- 基于 `python:3.11-slim`；
- 安装系统依赖：`espeak-ng`（英文 / 部分模型需要）、`ffmpeg`（pydub 处理音频用）；
- `pip install -r requirements.txt`；
- `COPY . .`：连同 `models` 目录一起打包进镜像；
- 入口命令：`uvicorn main:app --host 0.0.0.0 --port 8000`。

### 4.3 导出镜像并拷贝到离线环境

在构建机上：

```bash
docker save offline-tts:latest -o offline-tts.tar
```

然后用 U 盘 / 移动硬盘等方式把 `offline-tts.tar` 拷贝到离线服务器。

在离线服务器上：

```bash
docker load -i offline-tts.tar
```

### 4.4 在离线服务器上运行容器

```bash
docker run -d --name offline-tts -p 8000:8000 offline-tts:latest
```

如果希望从网络层面也彻底隔离外网，可以使用：

```bash
docker run -d --name offline-tts --network=none offline-tts:latest
```

（这时只能通过宿主机内部机制访问，可以结合 `--network host` 或反向代理等方案按需调整。）

### 4.5 离线环境中的前端使用

在离线设备上，将 `tts-web` 目录中的文件部署到任意静态服务器，或直接打开 `index.html`：

1. 修改前端 API 地址（例如指向离线服务器 IP）：

   `tts-web/script.js`：

   ```js
   const API_BASE = "http://<离线服务器IP>:8000";
   ```

2. 在浏览器中打开 `index.html`；
3. 按和本地一样的步骤输入文本、选择语言、生成并下载音频。

---

## 5. 常见问题 / 说明

- **Q：运行时会不会偷偷访问外网？**  
  A：后端加载模型时只访问 `tts-server/models/...`，不会再走 Coqui 的下载逻辑。Docker 运行时只要你不给外网路由（比如 `--network=none`），就能保证完全离线。

- **Q：日语支持？**  
  A：当前日语模型需要额外的 MeCab / 词典等依赖，且调试尚未完全稳定；建议先以中文 / 英文为主，日语后续可以在单独分支继续迭代。

- **Q：模型体积较大，Gitee 会不会 push 不上去？**  
  A：如果 Gitee 仓库大小有限，可以考虑：
  - 仓库里只放代码；  
  - 模型通过私有文件服务器 / 内网共享分发；  
  - 构建 Docker 镜像时挂载模型目录（`-v /path/to/models:/app/models`），而不是随镜像分发。

如需针对你的真实部署环境（操作系统 / 内网结构）定制更具体的脚本或自动化流程，可以在此基础上再做扩展。

