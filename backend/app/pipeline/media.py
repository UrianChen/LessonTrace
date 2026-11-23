"""预处理和语音转写的外部调用：FFmpeg、对象存储、语音转写服务。

转写模块对外只有「音频进、句子列表出」一个接口（transcribe_audio），
换成云厂商的录音文件识别只改这一个函数。
"""
import json
import os
import subprocess
import tempfile
import time

import httpx

from .. import storage
from ..config import MAX_DURATION_MS, get_settings
from .slides import extract_terms, parse_slides


class PermanentError(Exception):
    """重试也没用的错误（文件损坏、超出时长上限等），直接进入失败状态。"""


def _run(cmd: list[str]):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {p.stderr.strip()[-600:]}")
    return p.stdout


def probe(path: str) -> dict:
    try:
        out = _run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    except RuntimeError as e:
        raise PermanentError(f"video file cannot be read: {e}") from e
    info = json.loads(out)
    streams = {s["codec_type"]: s for s in reversed(info.get("streams", []))}   # 每类取第一路
    if "audio" not in streams:
        raise PermanentError("video has no audio track")
    return {
        "duration_ms": int(float(info["format"]["duration"]) * 1000),
        "vcodec": streams.get("video", {}).get("codec_name"),
        "acodec": streams["audio"].get("codec_name"),
    }


def extract_wav(src: str, dst: str):
    """抽音轨，转成 16 kHz 单声道 WAV。"""
    _run(["ffmpeg", "-y", "-v", "error", "-i", src, "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", dst])


def make_hls(src: str, out_dir: str, info: dict):
    """转一份 HLS 供网页播放和按时间跳转。H.264 + AAC 的源直接换封装，否则转码。"""
    os.makedirs(out_dir, exist_ok=True)
    if info["vcodec"] == "h264" and info["acodec"] == "aac":
        codec = ["-map", "0:v:0", "-map", "0:a:0", "-c", "copy"]
    elif info["vcodec"] is None:
        codec = ["-map", "0:a:0", "-vn", "-c:a", "aac", "-b:a", "128k"]
    else:
        # 只取第一路视频和音频：录像文件里常带封面图流、字幕流，不能让 FFmpeg 自己挑
        codec = ["-map", "0:v:0", "-map", "0:a:0","-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
                 "-force_key_frames", "expr:gte(t,n_forced*4)", "-c:a", "aac", "-b:a", "128k"]
    _run(["ffmpeg", "-y", "-v", "error", "-i", src, *codec,
          "-f", "hls", "-hls_time", "4", "-hls_playlist_type", "vod",
          "-hls_segment_filename", os.path.join(out_dir, "seg%05d.ts"),
          os.path.join(out_dir, "index.m3u8")])


def upload_hls(out_dir: str, lesson_id: int):
    prefix = storage.lesson_prefix(lesson_id) + "hls/"
    storage.delete_prefix(prefix)
    for name in sorted(os.listdir(out_dir)):
        ctype = "application/vnd.apple.mpegurl" if name.endswith(".m3u8") else "video/mp2t"
        storage.upload(os.path.join(out_dir, name), prefix + name, ctype)


def transcribe_audio(audio_key: str, terms: list[str]) -> list[dict]:
    """音频进、句子列表出：[{start_ms, end_ms, speaker, text}]，speaker 是分离模型的原始标签。"""
    s = get_settings()
    body = {"audio_url": storage.presign_get_internal(audio_key), "terms": terms}
    with httpx.Client(base_url=s.asr_url, timeout=60) as c:
        job = c.post("/jobs", json=body).raise_for_status().json()
        while True:
            time.sleep(5)
            st = c.get(f"/jobs/{job['id']}").raise_for_status().json()
            if st["status"] == "done":
                return st["sentences"]
            if st["status"] == "failed":
                raise RuntimeError(f"ASR failed: {st.get('error')}")


def slide_terms(slides_key: str | None) -> list[str]:
    if not slides_key:
        return []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "slides" + os.path.splitext(slides_key)[1])
            storage.download(slides_key, path)
            return extract_terms(parse_slides(path))
    except Exception:
        return []   # 术语提示只是锦上添花，课件有问题留到对齐阶段报


def process_media(lesson_id: int, video_key: str, slides_key: str | None) -> tuple[int, list[dict]]:
    """转写阶段的全部外部工作。返回 (时长毫秒, 原始句子列表)。"""
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "video" + os.path.splitext(video_key)[1])
        storage.download(video_key, src)
        info = probe(src)
        if info["duration_ms"] > MAX_DURATION_MS:
            raise PermanentError("recording is longer than the 2 hour limit")
        wav = os.path.join(tmp, "audio.wav")
        extract_wav(src, wav)
        audio_key = storage.lesson_prefix(lesson_id) + "audio.wav"
        storage.upload(wav, audio_key, "audio/wav")
        hls_dir = os.path.join(tmp, "hls")
        make_hls(src, hls_dir, info)
        upload_hls(hls_dir, lesson_id)
    sentences = transcribe_audio(audio_key, slide_terms(slides_key))
    return info["duration_ms"], sentences


def load_slide_pages(slides_key: str | None) -> list[str]:
    if not slides_key:
        return []
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "slides" + os.path.splitext(slides_key)[1])
        storage.download(slides_key, path)
        try:
            return parse_slides(path)
        except Exception as e:
            raise PermanentError(f"slides file cannot be read: {e}") from e
