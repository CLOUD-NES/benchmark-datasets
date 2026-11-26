import shlex
import subprocess
from typing import Any


def run_cmd(template: str, context: dict[str, Any] | None = None) -> None:
    """Render a command template and run it."""
    context = {} if context is None else context
    cmd = template.format(**context)
    subprocess.run(
        shlex.split(cmd),
        check=True
    )

