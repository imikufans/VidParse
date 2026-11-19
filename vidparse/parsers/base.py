"""解析器基类."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import VideoInfo
from ..utils import HttpClient


class BaseParser(ABC):
    """所有平台解析器的抽象基类."""

    platform: str = "base"

    def __init__(self, client: HttpClient | None = None, **options):
        self.client = client or HttpClient()
        self.options = options

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """判断该 URL 是否属于本平台."""

    @abstractmethod
    def parse(self, url: str) -> VideoInfo:
        """解析视频信息, 失败时抛 ParseError."""

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} platform={self.platform}>"
