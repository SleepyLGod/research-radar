"""Project-specific exception types."""


class ResearchRadarError(Exception):
    """Base exception for expected ResearchRadar failures."""


class ConfigError(ResearchRadarError):
    """Raised when configuration is missing or invalid."""


class SecretError(ResearchRadarError):
    """Raised when secret storage or retrieval fails."""


class CryptoError(ResearchRadarError):
    """Raised when encryption or decryption fails."""


class DiscoveryError(ResearchRadarError):
    """Raised when source discovery fails."""


class IngestionError(ResearchRadarError):
    """Raised when artifact ingestion fails."""


class AnalysisError(ResearchRadarError):
    """Raised when model analysis fails."""


class ProviderTransportError(AnalysisError):
    """Raised when an LLM provider request fails with transport diagnostics."""

    def __init__(self, message: str, diagnostics: dict[str, object]) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class EvidenceError(ResearchRadarError):
    """Raised when evidence validation fails."""


class PublishError(ResearchRadarError):
    """Raised when a publisher operation fails."""


class PrivacyScanError(ResearchRadarError):
    """Raised when the privacy scanner finds unsafe content."""
