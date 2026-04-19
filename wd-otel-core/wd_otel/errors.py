class WdOtelConfigError(Exception):
    """Raised when WD-OTel SDK configuration is invalid or missing.

    In local/dev environments, this halts the service at startup.
    In staging/production, the SDK logs a warning and degrades gracefully instead.
    """

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint
