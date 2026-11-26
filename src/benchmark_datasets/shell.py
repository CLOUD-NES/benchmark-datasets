import logging
import os
import shlex
import subprocess

logger = logging.getLogger(__name__)


def run_cmd(args: list[str], env: dict[str, str] | None = None) -> None:
    """Run a command, with extra environment variables on top of the current ones."""
    logger.info(shlex.join(args))
    subprocess.run(args, check=True, env={**os.environ, **(env or {})})
