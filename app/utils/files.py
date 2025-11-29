"""파일 처리 유틸리티

Express poc-bridge.js의 sanitizeFilename, 파일 MIME 타입 감지 등 포팅
주요 기능:
- 파일명 정규화/살균
- MIME 타입 감지
- 파일 확장자 추출
- 파일 크기 포맷팅
"""
import mimetypes
import re
import unicodedata
from typing import Optional


# 허용된 MIME 타입 (보안)
ALLOWED_MIME_TYPES = {
    # 이미지
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/bmp",
    "image/svg+xml",
    # 문서
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    # 텍스트
    "text/plain",
    "text/csv",
    "text/html",
    "text/markdown",
    # 압축
    "application/zip",
    "application/x-zip-compressed",
    "application/x-rar-compressed",
    "application/x-7z-compressed",
    # 비디오
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/webm",
    # 오디오
    "audio/mpeg",
    "audio/wav",
    "audio/ogg",
    # 기타
    "application/json",
    "application/xml",
    "application/octet-stream",
}

# 파일명에서 제거할 위험 문자
DANGEROUS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# 연속 공백/언더스코어 정리
MULTIPLE_SPACES = re.compile(r'[\s_]+')


def sanitize_filename(filename: str, max_length: int = 255) -> str:
    """
    파일명 정규화/살균

    Express sanitizeFilename 포팅:
    - 위험 문자 제거
    - 유니코드 정규화
    - 길이 제한

    Args:
        filename: 원본 파일명
        max_length: 최대 길이 (기본 255)

    Returns:
        정규화된 파일명
    """
    if not filename:
        return "unnamed_file"

    # 1. 유니코드 정규화 (NFD → NFC)
    filename = unicodedata.normalize("NFC", filename)

    # 2. 경로 구분자 제거 (디렉토리 순회 공격 방지)
    filename = filename.replace("/", "_").replace("\\", "_")

    # 3. 위험 문자 제거
    filename = DANGEROUS_CHARS.sub("_", filename)

    # 4. 연속 공백/언더스코어 정리
    filename = MULTIPLE_SPACES.sub("_", filename)

    # 5. 앞뒤 공백/점 제거
    filename = filename.strip(" ._")

    # 6. 숨김 파일 방지 (점으로 시작하는 경우)
    if filename.startswith("."):
        filename = "_" + filename[1:]

    # 7. 빈 파일명 처리
    if not filename:
        filename = "unnamed_file"

    # 8. 길이 제한 (확장자 보존)
    if len(filename) > max_length:
        name, ext = split_extension(filename)
        max_name_length = max_length - len(ext) - 1 if ext else max_length
        filename = name[:max_name_length] + (f".{ext}" if ext else "")

    return filename


def split_extension(filename: str) -> tuple[str, str]:
    """
    파일명에서 확장자 분리

    Args:
        filename: 파일명

    Returns:
        (이름, 확장자) - 확장자 없으면 빈 문자열
    """
    if "." not in filename:
        return (filename, "")

    # 마지막 점 기준 분리
    parts = filename.rsplit(".", 1)
    if len(parts) == 2 and parts[1]:
        return (parts[0], parts[1].lower())

    return (filename, "")


def get_extension_from_mime(mime_type: str) -> str:
    """
    MIME 타입에서 확장자 추출

    Args:
        mime_type: MIME 타입 (예: "image/png")

    Returns:
        확장자 (점 제외, 예: "png")
    """
    if not mime_type:
        return ""

    # mimetypes 모듈 사용
    ext = mimetypes.guess_extension(mime_type, strict=False)
    if ext:
        return ext.lstrip(".")

    # 수동 매핑 (mimetypes에 없는 경우)
    mime_to_ext = {
        "image/webp": "webp",
        "video/webm": "webm",
        "audio/webm": "webm",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    }

    return mime_to_ext.get(mime_type, "")


def get_mime_from_extension(filename: str) -> str:
    """
    파일 확장자에서 MIME 타입 추출

    Args:
        filename: 파일명

    Returns:
        MIME 타입 (알 수 없으면 application/octet-stream)
    """
    if not filename:
        return "application/octet-stream"

    # mimetypes 모듈 사용
    mime_type, _ = mimetypes.guess_type(filename, strict=False)
    if mime_type:
        return mime_type

    # 수동 매핑
    _, ext = split_extension(filename)
    ext_to_mime = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "webp": "image/webp",
        "webm": "video/webm",
        "md": "text/markdown",
    }

    return ext_to_mime.get(ext, "application/octet-stream")


def is_image(mime_type: str) -> bool:
    """이미지 MIME 타입 확인"""
    return mime_type.startswith("image/")


def is_video(mime_type: str) -> bool:
    """비디오 MIME 타입 확인"""
    return mime_type.startswith("video/")


def is_audio(mime_type: str) -> bool:
    """오디오 MIME 타입 확인"""
    return mime_type.startswith("audio/")


def is_document(mime_type: str) -> bool:
    """문서 MIME 타입 확인"""
    document_types = {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "text/plain",
        "text/csv",
        "text/markdown",
    }
    return mime_type in document_types


def is_allowed_mime_type(mime_type: str) -> bool:
    """허용된 MIME 타입 확인"""
    return mime_type in ALLOWED_MIME_TYPES


def format_file_size(size_bytes: int) -> str:
    """
    파일 크기 포맷팅

    Args:
        size_bytes: 바이트 단위 크기

    Returns:
        포맷된 문자열 (예: "1.5 MB")
    """
    if size_bytes < 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)

    for unit in units:
        if size < 1024:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024

    return f"{size:.1f} PB"


def ensure_extension(filename: str, mime_type: Optional[str] = None) -> str:
    """
    파일명에 확장자 보장

    확장자가 없으면 MIME 타입에서 추론하여 추가

    Args:
        filename: 파일명
        mime_type: MIME 타입 (선택)

    Returns:
        확장자가 포함된 파일명
    """
    name, ext = split_extension(filename)

    if ext:
        return filename

    if mime_type:
        inferred_ext = get_extension_from_mime(mime_type)
        if inferred_ext:
            return f"{filename}.{inferred_ext}"

    return filename


def make_unique_filename(filename: str, existing_names: set[str]) -> str:
    """
    중복되지 않는 파일명 생성

    Args:
        filename: 원본 파일명
        existing_names: 기존 파일명 집합

    Returns:
        유니크한 파일명
    """
    if filename not in existing_names:
        return filename

    name, ext = split_extension(filename)
    counter = 1

    while True:
        new_name = f"{name}_{counter}" + (f".{ext}" if ext else "")
        if new_name not in existing_names:
            return new_name
        counter += 1


def get_file_category(mime_type: str) -> str:
    """
    MIME 타입에서 파일 카테고리 반환

    Args:
        mime_type: MIME 타입

    Returns:
        카테고리 (image, video, audio, document, file)
    """
    if is_image(mime_type):
        return "image"
    elif is_video(mime_type):
        return "video"
    elif is_audio(mime_type):
        return "audio"
    elif is_document(mime_type):
        return "document"
    else:
        return "file"
