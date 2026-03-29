"""파일 다운로드 — 텔레그램 이미지/문서 다운로드 유틸리티."""

import os
import time

from .config import LOGS_DIR
from .logging_utils import log


async def download_photo(ahttp, bot_token: str, msg_raw: dict, name: str) -> str:
    """텔레그램 이미지를 다운로드하여 로컬 경로 반환."""
    photos = msg_raw.get("photo", [])
    if not photos:
        return ""
    # 가장 큰 해상도 선택
    photo = photos[-1]
    file_id = photo.get("file_id", "")
    if not file_id:
        return ""
    try:
        # getFile API로 파일 경로 조회
        url = f"https://api.telegram.org/bot{bot_token}/getFile"
        r = await ahttp.post(url, json={"file_id": file_id}, timeout=10)
        data = r.json()
        if not data.get("ok"):
            log(f"{name}: getFile 실패: {data}")
            return ""
        file_path = data["result"]["file_path"]
        # 다운로드
        download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
        r = await ahttp.get(download_url, timeout=30)
        # 로컬 저장
        save_dir = os.path.join(LOGS_DIR, "images")
        os.makedirs(save_dir, exist_ok=True)
        ext = os.path.splitext(file_path)[1] or ".jpg"
        save_path = os.path.join(save_dir, f"{name}_{int(time.time())}{ext}")
        with open(save_path, "wb") as f:
            f.write(r.content)
        log(f"{name}: 이미지 다운로드 완료: {save_path}")
        return save_path
    except Exception as e:
        log(f"{name}: 이미지 다운로드 실패: {e}")
        return ""


async def download_photo_via_channel(ch, file_id: str, name: str) -> str:
    """channel.download_file()로 이미지 다운로드하여 로컬 경로 반환."""
    try:
        data = await ch.download_file(file_id)
        if not data:
            return ""
        save_dir = os.path.join(LOGS_DIR, "images")
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, f"{name}_{int(time.time())}.jpg")
        with open(save_path, "wb") as f:
            f.write(data)
        log(f"{name}: 이미지 다운로드 완료: {save_path}")
        return save_path
    except Exception as e:
        log(f"{name}: 이미지 다운로드 실패: {e}")
        return ""


async def download_doc_via_channel(ch, file_id: str, file_name: str, name: str) -> str:
    """channel.download_file()로 문서 다운로드하여 로컬 경로 반환."""
    try:
        data = await ch.download_file(file_id)
        if not data:
            return ""
        save_dir = os.path.join(LOGS_DIR, "files")
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, file_name)
        with open(save_path, "wb") as f:
            f.write(data)
        log(f"{name}: 파일 다운로드 완료: {save_path}")
        return save_path
    except Exception as e:
        log(f"{name}: 파일 다운로드 실패: {e}")
        return ""
