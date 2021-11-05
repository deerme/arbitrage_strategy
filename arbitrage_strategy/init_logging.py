import logging
import sys
from pprint import pformat
from typing import cast
from types import FrameType

from loguru import logger


LOGURU_FORMAT = (
    "<green>{time:DD.MM.YY HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | <level>{message}</level>"
)


class InterceptHandler(logging.Handler):
    """Logs to loguru from Python logging module"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = str(record.levelno)

        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:  # noqa: WPS609
            frame = cast(FrameType, frame.f_back)
            # frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level,
            record.getMessage(),
        )


def format_record(record: dict) -> str:
    """
    Custom format for loguru loggers.
    Uses pformat for log any data like request/response body during debug.
    Works with logging if loguru handler it.
    Example:
    >>> payload = [
        {"users":[{"name": "Nick", "age": 87, "is_active": True},
        {"name": "Alex", "age": 27, "is_active": True}], "count": 2}
    ]
    >>> logger.bind(payload=).debug("users payload")
    >>> [   {   'count': 2,
    >>>         'users': [   {'age': 87, 'is_active': True, 'name': 'Nick'},
    >>>                      {'age': 27, 'is_active': True, 'name': 'Alex'}]}]
    """

    format_string = LOGURU_FORMAT
    if record["extra"].get("payload") is not None:
        record["extra"]["payload"] = pformat(
            record["extra"]["payload"], indent=4, compact=True, width=88
        )
        format_string += "\n<level>{extra[payload]}</level>"

    format_string += "{exception}\n"
    return format_string


def setup_logging():
    # intercept everything at the root logger
    logging.root.handlers = [InterceptHandler()]
    logging.root.setLevel("INFO")

    # remove every other logger's handlers
    # and propagate to root logger
    for name in logging.root.manager.loggerDict.keys():
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True

    # configure loguru
    logger.configure(
        handlers=[
            {
                "sink": sys.stdout,
                "level": logging.DEBUG,
                "format": format_record,
            }
        ]
    )
    logger.level("TIMEIT", no=22, color="<cyan>")
