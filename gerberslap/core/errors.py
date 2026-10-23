class GerberError(Exception):
    """A file or archive cannot be used. Raised instead of silently dropping geometry; the message names the file.

    `code` is a stable key for the UI catalogues (the message itself is for developers and logs):
      unreadable   the parser failed on the file
      bad_zip      not a valid zip archive
      too_large    archive or member beyond the safety limits
    """

    def __init__(self, name, reason, code="unreadable"):
        super().__init__(f"{name}: {reason}")
        self.name, self.reason, self.code = name, reason, code
