"""Abstract base class for all YouTubeSynth agents."""

from abc import ABC

from youtubesynth.services.db import Database
from youtubesynth.services.gemini_client import GeminiClient
from youtubesynth.services.token_tracker import TokenTracker


class BaseAgent(ABC):
    """Shared dependency container injected into every agent."""

    def __init__(
        self,
        db: Database,
        token_tracker: TokenTracker,
        gemini_client: GeminiClient,
    ) -> None:
        self._db = db
        self._token_tracker = token_tracker
        self._gemini_client = gemini_client
