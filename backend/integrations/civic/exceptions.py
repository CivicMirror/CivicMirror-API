class CivicAPIError(Exception):
    pass


class CivicAPIForbidden(CivicAPIError):
    pass


class CivicAPIRetryableError(CivicAPIError):
    pass
