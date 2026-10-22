class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 422, field: str | None = None):
        self.code, self.message, self.status, self.field = code, message, status, field
        super().__init__(message)


def fail(code, message, status=422, field=None):
    raise AppError(code, message, status, field)
