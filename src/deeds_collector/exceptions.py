class DeedError(Exception):
    """Base class for deed_collector module exceptions"""
    def __init__(self, msg, error=None):
        super().__init__(msg)
        self.error = error

class DetailsError(DeedError):
    def __init__(self, msg, error):
        super().__init__(msg, error)
        self.error = error

class PDFError(DeedError):
    def __init__(self, msg, error):
        super().__init__(msg, error)
        self.error = error