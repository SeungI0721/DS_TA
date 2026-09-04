"""Future C inspection and compilation extension point.

Student code is untrusted. This module intentionally performs no execution.
All future inspection must use the selected submission head SHA.
"""


def check_c_submission(*_args: object, **_kwargs: object) -> None:
    raise NotImplementedError("C grading is outside Version 1")

