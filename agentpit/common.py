import inspect


def check_state(expression: bool, expr_text: str, msg: str = "") -> None:
    """
    Raises LogicError if `expression` is False, formatting a message similar to the C++ macro.

    Example:
        check_state2(x > 0, "x > 0", "x must be positive")
    """
    if expression:
        return

    caller = inspect.currentframe().f_back  # type: ignore[union-attr]
    info = inspect.getframeinfo(caller)

    func = caller.f_code.co_name if caller else "<unknown>"
    file = info.filename
    line = info.lineno

    base = f"Check failed::{expr_text} {file}:{line} {func}"
    detail = f"(): {msg}" if msg else "()"
    raise LogicError(base + detail)


class LogicError(Exception):
    """Python analogue of `std::logic_error`."""
    pass
