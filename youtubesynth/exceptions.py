class YouTubeSynthError(Exception):
    """Base exception for all YouTubeSynth errors."""


class ExtractionError(YouTubeSynthError):
    """Raised when URL extraction from a file or playlist fails."""


class TranscriptError(YouTubeSynthError):
    """Raised when transcript fetching fails unexpectedly."""


class GeminiError(YouTubeSynthError):
    """Raised when Gemini API calls fail after all retries."""


class SynthesisError(YouTubeSynthError):
    """Raised when synthesis cannot proceed (e.g. no summary files found)."""


class JobNotFoundError(YouTubeSynthError):
    """Raised when a job_id does not exist in the database."""
