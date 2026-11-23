"""语音转写服务：音频进、句子列表出。

    POST /jobs  {"audio_url": "...", "terms": ["Squeeze", "theorem", ...]}  → {"id": "..."}
    GET  /jobs/{id}  → {"status": "queued|running|done|failed", "sentences": [...], "error": "..."}

句子：{"start_ms", "end_ms", "speaker", "text"}，speaker 是说话人分离的原始标签（SPEAKER_00…）
或 null。谁是老师由后端按累计时长判断，这里不做身份识别。

三步依次加载模型、用完即释放，显存只需要装得下最大的那一个。
"""
import gc
import logging
import os
import tempfile
import threading
import uuid

import httpx
import torch
import whisperx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("asr")

MODEL = os.environ.get("WHISPER_MODEL", "medium")
COMPUTE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8_float16")
BATCH = int(os.environ.get("WHISPER_BATCH_SIZE", "4"))
HF_TOKEN = os.environ.get("HF_TOKEN", "")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
if DEVICE == "cpu":
    COMPUTE = "int8"      # CPU 不支持半精度

if DEVICE == "cuda":
    p = torch.cuda.get_device_properties(0)
    log.info("GPU detected: %s, %.1f GB", p.name, p.total_memory / 1024**3)
else:
    log.warning("No usable GPU (torch.cuda.is_available() is False), running on CPU. Transcription will be "
                "very slow. If nvidia-smi works in the container but CUDA does not, update WSL / Docker Desktop.")
log.info("model=%s compute_type=%s batch_size=%s diarization=%s", MODEL, COMPUTE, BATCH, "on" if HF_TOKEN else "off (HF_TOKEN not set)")

app = FastAPI(title="LessonTrace ASR")
jobs: dict[str, dict] = {}
gpu_lock = threading.Lock()


class JobIn(BaseModel):
    audio_url: str
    terms: list[str] = []


def _free():
    gc.collect()
    if DEVICE == "cuda":
        torch.cuda.empty_cache()


def _diarizer():
    try:
        from whisperx.diarize import DiarizationPipeline
    except ImportError:
        DiarizationPipeline = whisperx.DiarizationPipeline
    try:
        return DiarizationPipeline(token=HF_TOKEN, device=DEVICE)
    except TypeError:
        return DiarizationPipeline(use_auth_token=HF_TOKEN, device=DEVICE)


def transcribe(path: str, terms: list[str]) -> list[dict]:
    audio = whisperx.load_audio(path)

    # 1. 语音活动检测切分 + 识别。课件术语作为提示词，减少术语识别错误。
    # suppress_numerals：数字按单词写出（"0.959" → "zero point nine five nine"）。
    # 阿拉伯数字没法做词级对齐，不这样做的话数字多的句子时间会被压缩，后面的时间戳跟着偏。
    options = {"suppress_numerals": True}
    if terms:
        options["initial_prompt"] = "Glossary: " + ", ".join(terms) + "."
    model = whisperx.load_model(MODEL, DEVICE, compute_type=COMPUTE, language="en", asr_options=options)
    result = model.transcribe(audio, batch_size=BATCH, language="en")
    del model
    _free()

    # 2. 词级时间对齐
    align_model, meta = whisperx.load_align_model(language_code="en", device=DEVICE)
    result = whisperx.align(result["segments"], align_model, meta, audio, DEVICE, return_char_alignments=False)
    del align_model
    _free()

    # 3. 说话人分离（需要 Hugging Face 访问令牌；没有就全部标为未知）
    if HF_TOKEN:
        diarizer = _diarizer()
        diarization = diarizer(audio)
        result = whisperx.assign_word_speakers(diarization, result)
        del diarizer
        _free()

    sentences = []
    for seg in result["segments"]:
        for part in split_on_pauses(seg):
            text = (part.get("text") or "").strip()
            if not text or part.get("start") is None or part.get("end") is None:
                continue
            sentences.append({"start_ms": int(part["start"] * 1000), "end_ms": int(part["end"] * 1000),
                              "speaker": part.get("speaker"), "text": collapse_repeats(text)})
    return sentences


def collapse_repeats(text: str, min_repeats: int = 4, max_ngram: int = 8, min_span: int = 12) -> str:
    """折叠识别模型的重复幻觉：同一个短语（1–8 个词）连续出现 4 遍以上、总共至少 12 个词时只留一遍。

    Whisper 在音乐、影片片段、噪声上偶尔会把一个短语重复几十遍。
    """
    words = text.split()
    out, i = [], 0
    while i < len(words):
        collapsed = False
        for n in range(1, max_ngram + 1):
            gram = [w.lower().strip(".,!?") for w in words[i:i + n]]
            if len(gram) < n:
                break
            k = 1
            while [w.lower().strip(".,!?") for w in words[i + k * n:i + (k + 1) * n]] == gram:
                k += 1
            if k >= min_repeats and k * n >= min_span:   # 短的重复可能是真话，比如念 0.99998
                out += words[i:i + n]
                i += k * n
                collapsed = True
                break
        if not collapsed:
            out.append(words[i])
            i += 1
    return " ".join(out)


PAUSE_SPLIT_S = 2.0


def split_on_pauses(seg: dict) -> list[dict]:
    """一句话中间有长停顿（比如说了个 "And" 然后敲了十秒键盘）时按停顿拆开。

    不拆的话句子起点落在停顿之前，证据跳转会提前，提问后的等待时长也量不出来。
    """
    words = seg.get("words") or []
    groups, last_end = [[]], None
    for w in words:
        start = w.get("start")
        if start is not None and last_end is not None and start - last_end >= PAUSE_SPLIT_S and groups[-1]:
            groups.append([])
        groups[-1].append(w)
        if w.get("end") is not None:
            last_end = w["end"]
    groups = [g for g in groups if g]
    if len(groups) < 2:
        return [seg]
    # 没有时间的词（对不上音的符号等）单独成组时并回前一组
    merged = []
    for g in groups:
        if merged and not any(w.get("start") is not None for w in g):
            merged[-1] += g
        else:
            merged.append(g)
    parts = []
    for g in merged:
        timed = [w for w in g if w.get("start") is not None and w.get("end") is not None]
        if not timed:
            return [seg]
        speakers = [w["speaker"] for w in g if w.get("speaker")]
        parts.append({"start": timed[0]["start"], "end": timed[-1]["end"],
                      "text": " ".join(w["word"].strip() for w in g),
                      "speaker": max(set(speakers), key=speakers.count) if speakers else seg.get("speaker")})
    return parts


def run_job(job_id: str, body: JobIn):
    job = jobs[job_id]
    with gpu_lock:   # 单 GPU，一次只跑一个
        job["status"] = "running"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "audio.wav")
                with httpx.stream("GET", body.audio_url, timeout=600) as r:
                    r.raise_for_status()
                    with open(path, "wb") as f:
                        for chunk in r.iter_bytes(1 << 20):
                            f.write(chunk)
                job["sentences"] = transcribe(path, body.terms)
            job["status"] = "done"
            log.info("job %s done: %d sentences", job_id, len(job["sentences"]))
        except Exception as e:
            log.exception("job %s failed", job_id)
            job.update(status="failed", error=f"{type(e).__name__}: {e}")
            _free()


@app.post("/jobs")
def create_job(body: JobIn):
    job_id = uuid.uuid4().hex
    jobs[job_id] = {"status": "queued"}
    threading.Thread(target=run_job, args=(job_id, body), daemon=True).start()
    return {"id": job_id}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "job not found")   # 服务重启后任务丢失，后端按失败重试
    job = jobs[job_id]
    if job["status"] in ("done", "failed"):
        return jobs.pop(job_id)
    return job


@app.get("/health")
def health():
    return {"ok": True, "device": DEVICE, "model": MODEL}
