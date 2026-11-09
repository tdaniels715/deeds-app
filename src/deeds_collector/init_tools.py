import sys, argparse
import datetime
import logging, logging.handlers
from queue import SimpleQueue

def init_logger(
    log_console_level = "INFO",
    log_file_level = "DEBUG",
    log_file = "client.log"
) -> logging.Logger :
    logger = logging.getLogger("client")
    logger.setLevel(log_console_level)

    info_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] : %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    error_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] in %(filename)s:%(lineno)d : %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    log_queue = SimpleQueue()  # Create a queue and hook it up to a QueueHandler
    queue_handler = logging.handlers.QueueHandler(log_queue)
    logger.addHandler(queue_handler)  # Bind the QueueHandler to your application's root logger

    file_handler = logging.FileHandler(log_file, mode="w")
    file_handler.setFormatter(error_formatter)
    file_handler.setLevel(log_file_level)

    # Create a QueueListener to pull messages off the queue in a background thread
    log_listener = logging.handlers.QueueListener(log_queue, file_handler)
    log_listener.respect_handler_level = True

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(error_formatter)
    console_handler.setLevel(log_console_level)
    logger.addHandler(console_handler)

    return logger, log_listener

def init_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrapes, parses, and saves Deed records from search.jeffersondeeds.com."
    )

    # flags
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",  # boolean flag
        help="Do not log progress; default=False"
    )

    parser.add_argument(
        "--log-file",
        type=str,
        default="client.log",
        help="file to use for logging"
    )

    parser.add_argument(
        "--log-file-level",
        type=str,
        default="DEBUG",
        help="logging.LEVEL to use for log-file"
    )

    parser.add_argument(
        "--log-console-level",
        type=str,
        default="INFO",
        help="logging.LEVEL to use for stdout"
    )

    parser.add_argument(
        "-u", "--user",
        type=str,
        default="",
        help="username"
    )

    parser.add_argument(
        "-p", "--password",
        type=str,
        default="",
        help="password"
    )

    parser.add_argument(
        "--date",
        type=str,
        default="",
        help="date (MM/DD/YYYY)"
    )

    return parser

def get_YMD(date: str) -> (str,str,str):
    dt = datetime.date.strptime(date, "%m/%d/%Y")
    Y, M, D = dt.isoformat().split('-')
    return (Y, M, D)


def get_date() -> (str,str,str):
    date_valid = False
    while (not date_valid):
        try:
            date = input("Enter date to search (MM/DD/YYYY): ")
            Y, M, D = get_YMD(date)
            date_valid = True
        except KeyboardInterrupt:
            raise KeyboardInterrupt
        except Exception as e:
            print(f"Invalid date, please use MM/DD/YYYY format (or CTRL-C (^C) to quit)")
    return (Y, M, D)