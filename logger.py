import logging

DEBUG = logging.DEBUG
INFO = logging.INFO
WARNING = logging.WARNING
ERROR = logging.ERROR

logging.basicConfig(format='%(asctime)s ~ %(levelname)-10s %(name)-25s %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logging.addLevelName(DEBUG, '🐛 DEBUG')
logging.addLevelName(INFO, '📑 INFO')
logging.addLevelName(WARNING, '🤔 WARNING')
logging.addLevelName(ERROR, '🚨 ERROR')


def setup_logger(name=__file__, log_file=None, level=DEBUG):
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if log_file:
        formatter = logging.Formatter(
            '%(asctime)s ~ %(levelname)-10s %(name)-25s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler = logging.FileHandler(log_file, encoding='utf-8')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
