from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
import time
import uuid
import collections
import builtins

import torch
from torch.serialization import add_safe_globals
from TTS.api import TTS
from TTS.utils.radam import RAdam
from pydub import AudioSegment
from pydub.silence import detect_nonsilent


app = FastAPI()

# 允许来自任意来源的跨域请求，方便本地开发和前端静态页面访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 如需限制来源，可改为具体域名列表
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 允许 Coqui TTS 使用的类被安全反序列化（兼容 PyTorch 2.6 的 weights_only 机制）
add_safe_globals(
    [
        RAdam,
        collections.defaultdict,
        dict,
        list,
        set,
        tuple,
        builtins.object,
    ]
)

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

MODELS_DIR = BASE_DIR / "models"

# 离线模型目录映射：要求在打包前将对应模型复制到这些目录中
LANG_MODEL_DIRS = {
    "zh": MODELS_DIR / "zh",
    "en": MODELS_DIR / "en",
    "ja": MODELS_DIR / "ja",
}

_tts_models = {}


class TTSRequest(BaseModel):
    text: str
    # 语言：zh / en / ja（或别名，如 zh-CN、english、japanese 等）
    lang: str | None = None


def normalize_lang(lang: str | None) -> str:
    if not lang:
        return "zh"
    l = lang.strip().lower()
    if l in {"zh", "zh-cn", "cn", "chinese"}:
        return "zh"
    if l in {"en", "en-us", "en-gb", "english"}:
        return "en"
    if l in {"ja", "jp", "ja-jp", "japanese"}:
        return "ja"
    return "zh"


def trim_wav_silence(wav_path: Path, silence_thresh: int = -40, min_silence_ms: int = 500) -> None:
    """
    简单去掉音频开头和结尾的长静音/底噪，减少“读完后长时间乱音”的情况。
    """
    audio = AudioSegment.from_wav(str(wav_path))
    # 找到非静音区间（毫秒）
    nonsilent = detect_nonsilent(
        audio,
        min_silence_len=min_silence_ms,
        silence_thresh=silence_thresh,
    )
    if not nonsilent:
        return

    start = max(nonsilent[0][0] - 200, 0)
    end = min(nonsilent[-1][1] + 200, len(audio))
    trimmed = audio[start:end]
    trimmed.export(str(wav_path), format="wav")


def _find_model_files(model_dir: Path) -> tuple[Path, Path]:
    """
    在给定的模型目录中查找 checkpoint 和 config 文件。
    约定文件名与 Coqui 默认下载保持一致：
    - model_file.pth / model_file.pth.tar / model.pth
    - config.json
    """
    if not model_dir.exists():
        raise HTTPException(status_code=500, detail=f"离线模型目录不存在: {model_dir}")

    model_path = None
    for name in ("model_file.pth", "model_file.pth.tar", "model.pth"):
        candidate = model_dir / name
        if candidate.exists():
            model_path = candidate
            break

    config_path = model_dir / "config.json"

    if model_path is None or not config_path.exists():
        raise HTTPException(
            status_code=500,
            detail=f"离线模型目录缺少必要文件: {model_dir}（需要 model_file.pth 和 config.json）",
        )

    return model_path, config_path


def get_tts(lang: str):
    key = normalize_lang(lang)
    # 不支持的语言统一退回中文
    if key not in LANG_MODEL_DIRS:
        key = "zh"

    if key not in _tts_models:
        model_dir = LANG_MODEL_DIRS[key]
        model_path, config_path = _find_model_files(model_dir)
        # 使用本地 checkpoint + config 加载模型，不触发任何在线下载逻辑
        _tts_models[key] = TTS(model_path=str(model_path), config_path=str(config_path), progress_bar=False).to("cpu")
    return _tts_models[key], key


@app.post("/api/tts")
def generate_tts(req: TTSRequest):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本不能为空")

    lang = normalize_lang(req.lang)
    tts, model_key = get_tts(lang)

    ts = int(time.time())
    file_id = uuid.uuid4().hex[:8]
    wav_path = OUTPUT_DIR / f"tts_{ts}_{file_id}.wav"

    tts.tts_to_file(text=text, file_path=str(wav_path))

    # 去掉音频头尾的长静音/底噪
    try:
        trim_wav_silence(wav_path)
    except Exception:
        # 裁剪失败不影响主流程
        pass

    return {"file": wav_path.name, "lang": lang}


@app.get("/api/tts/{filename}")
def download_tts(filename: str):
    file_path = OUTPUT_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(
        path=file_path,
        media_type="audio/wav",
        filename=filename,
    )


@app.get("/health")
def health():
    return {"status": "ok"}
