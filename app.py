#!/usr/bin/env python3
# encoding: UTF-8

"""JSON storage webservice

Provides REST webservices to store and retrieve json objects.
"""

__author__ = "Rogier Steehouder"
__date__ = "2022-01-29"
__version__ = "2.0"

import sys
import logging
from pathlib import Path

import click
import uvicorn
from loguru import logger

import jsonstorage
from jsonstorage.config import cfg


# Logging handler to redirect everything to loguru
class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).bind(
            logtype=record.name
        ).log(level, record.getMessage())


# Click documentation: https://click.palletsprojects.com/
@click.command()
@click.option(
    "--loglevel",
    type=click.Choice(logger._core.levels.keys(), case_sensitive=False),
    help="""Log level (overrides config file)""",
)
@click.option(
    "-c",
    "--cfg",
    "cfg_file",
    type=click.Path(exists=True, path_type=Path),
    default="instance",
    show_default='directory "instance"',
    help="""Configuration file (or directory: uses any "config.*" file)""",
)
def main(loglevel, cfg_file):
    #####
    # Config
    #####
    cfg.load(cfg_file)
    server_dir = (
        Path(cfg.get("server.directory", cfg.path.parent)).expanduser().resolve()
    )
    cfg["server.directory"] = server_dir

    #####
    # Logging
    #####
    if loglevel is not None:
        cfg["logging.console level"] = loglevel
        cfg["logging.file level"] = loglevel

    logger.configure(handlers=[], extra={"logtype": "main"})

    # console logging
    loglevel = cfg.get("logging.console level", "error").upper()
    if loglevel != "DISABLE":
        loglevel = logger.level(loglevel)
        levelstr = (
            "{level.icon: ^3}" if sys.stderr.encoding == "utf-8" else "{level: <8}"
        )
        debug = loglevel.no <= logger.level("DEBUG").no
        debugstr = (
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            if debug
            else ""
        )
        logger.add(
            sys.stderr,
            level=loglevel.name,
            format="<light-black>{time:YYYY-MM-DD HH:mm:ss}</light-black> | <level>"
            + levelstr
            + "</level> | {extra[logtype]} | "
            + debugstr
            + "{message}",
            filter=None,
            backtrace=debug,
            diagnose=debug,
        )

    # file logging
    loglevel = cfg.get("logging.file level", "error").upper()
    if loglevel != "DISABLE":
        loglevel = logger.level(loglevel)
        debug = loglevel.no <= logger.level("DEBUG").no
        debugstr = "{name}:{function}:{line} - " if debug else ""
        logdir = Path(cfg.get("logging.directory", server_dir)).expanduser().resolve()
        logger.add(
            logdir / "app-{time:YYYY-MM-DD}.log",
            level=loglevel.name,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {extra[logtype]} | "
            + debugstr
            + "{message}",
            filter=None,
            backtrace=debug,
            diagnose=debug,
            enqueue=True,
            encoding="utf-8",
            rotation="00:00",
            retention=5,
            compression=None if debug else "zip",
        )

    # install handler in stdlib logging to redirect to loguru (see loguru docs)
    logging.basicConfig(handlers=[InterceptHandler()], level=0)
    # and redirect uvicorn logging to the default logger
    logging.getLogger("uvicorn").handlers = []
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = True

    with logger.catch(onerror=lambda _: sys.exit(1)):

        #####
        # Server
        #####
        logger.debug("Server directory: {}", server_dir)

        ssl_keyfile = cfg.get("server.ssl-key")
        if ssl_keyfile is not None:
            ssl_keyfile = server_dir / ssl_keyfile
        ssl_certfile = cfg.get("server.ssl-cert")
        if ssl_certfile is not None:
            ssl_certfile = server_dir / ssl_certfile

        # TODO: properly handle IPv6
        protocol = (
            "https"
            if (ssl_keyfile is not None and ssl_certfile is not None)
            else "http"
        )
        host = cfg.get("server.host", "localhost")
        port = cfg.get("server.port", 8000)
        logger.success("Serving on {}://{}:{}", protocol, host, port)

        uvicorn.run(
            jsonstorage.make_app(),
            host=host,
            port=port,
            log_config=dict(version=1, disable_existing_loggers=False),
            log_level="debug",  # log everything, then let loguru handle the filtering
            ssl_keyfile=ssl_keyfile,
            ssl_certfile=ssl_certfile,
        )


if __name__ == "__main__":
    main()
