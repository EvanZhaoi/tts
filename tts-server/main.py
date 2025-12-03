from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
import time
import uuid
import collections
import builtins
import re

import numpy as np
import torch
from torch.serialization import add_safe_globals
from TTS.utils.synthesizer import Synthesizer
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


def normalize_zh_text(text: str) -> str:
    """
    对中文文本做基础清洗：
    - 将特殊省略号、引号等统一为普通标点；
    - 去掉模型词表中明显无法处理的控制字符。
    """
    # 统一各种引号
    text = text.replace("“", "\"").replace("”", "\"")
    text = text.replace("‘", "'").replace("’", "'")
    # 统一省略号：视作句号处理，便于分句
    text = text.replace("……", "。").replace("…", "。")
    # 可以按需扩展更多替换规则
    return text


def split_zh_sentences(text: str) -> list[str]:
    """
    按中文标点手动切分句子，避免英文分句器对中文长段落切分不当。
    """
    parts = re.split(r"([。！？!?…])", text)
    segments: list[str] = []
    buf = ""
    for part in parts:
        if not part:
            continue
        buf += part
        if part in "。！？!?…":
            seg = buf.strip()
            if seg:
                segments.append(seg)
            buf = ""
    if buf.strip():
        segments.append(buf.strip())
    return [s for s in segments if s.strip()]


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
        # 直接使用 Synthesizer 加载离线模型，绕过 TTS 包装层，避免版本差异带来的属性问题
        _tts_models[key] = Synthesizer(
            tts_checkpoint=str(model_path),
            tts_config_path=str(config_path),
            tts_speakers_file=None,
            tts_languages_file=None,
            vocoder_checkpoint=None,
            vocoder_config=None,
            encoder_checkpoint=None,
            encoder_config=None,
            use_cuda=False,
        )
    return _tts_models[key], key


@app.post("/api/tts")
def generate_tts(req: TTSRequest):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本不能为空")

    lang = normalize_lang(req.lang)
    # 中文提前做一层文本清洗，规范省略号和特殊引号，避免影响分句和发音
    if lang == "zh":
        text = normalize_zh_text(text)
    tts, model_key = get_tts(lang)

    ts = int(time.time())
    file_id = uuid.uuid4().hex[:8]
    wav_path = OUTPUT_DIR / f"tts_{ts}_{file_id}.wav"

    # 使用 Synthesizer 接口生成波形并保存为 wav
    try:
        if model_key == "zh":
            # 中文：按中文标点手动分句，逐句合成并拼接，避免单句过长或切分不当导致内容丢失
            sentences = split_zh_sentences(text)
            wav_all: list[float] = []
            for sent in sentences:
                sent = sent.strip()
                if not sent:
                    continue
                try:
                    w = tts.tts(text=sent, split_sentences=False)
                except RuntimeError as e:
                    msg = str(e)
                    if "Kernel size can't be greater than actual input size" in msg:
                        # 该子句过短或异常，跳过这一句，继续后面的内容
                        continue
                    raise
                wav_all.extend(list(w))
                # 句子之间加一点静音
                wav_all.extend([0.0] * 8000)
            if not wav_all:
                raise HTTPException(
                    status_code=400,
                    detail="当前文本无法被中文语音模型正常处理，请尝试简化或分段输入。",
                )
            wav = np.array(wav_all, dtype=np.float32)
        else:
            # 英文/日文：使用 Synthesizer 内置分句逻辑
            split = model_key == "en"
            wav = tts.tts(text=text, split_sentences=split)
    except RuntimeError as e:
        msg = str(e)
        if "Kernel size can't be greater than actual input size" in msg:
            raise HTTPException(
                status_code=400,
                detail="当前文本过短或包含无法处理的内容，导致语音模型出错，请尝试输入更长、语句更完整的文本。",
            ) from e
        raise

    tts.save_wav(wav=wav, path=str(wav_path))

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
