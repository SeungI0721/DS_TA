"""향후 C source 검사와 compile 기능을 연결할 extension point.

학생 코드는 신뢰할 수 없으므로 현재 module은 어떤 실행도 하지 않는다.
향후 검사 역시 selected submission head SHA만 사용해야 한다.
"""


def check_c_submission(*_args: object, **_kwargs: object) -> None:
    raise NotImplementedError("C grading is not implemented in Version 1")
