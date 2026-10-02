"""Docker tools."""

import subprocess

from .registry import tool
from ._common import host_env
from ._common import limit_lines


@tool(
    "docker_ps",
    readonly=True,
    requires=("docker",),
    description=(
        "List Docker containers. Shows running and stopped containers "
        "when show_all=True. A successful execution proves that the "
        "Docker command is available on the host. If the result says "
        "Docker available: yes, Docker is installed and available. "
        "If the result says Docker daemon: available, the Docker daemon "
        "is running and responding. If the result says Docker daemon: "
        "unavailable, Docker is installed but the daemon is not running. "
        "Exited containers are stopped containers and do not indicate "
        "that Docker is missing. An empty result means that no containers "
        "were found; it does not mean that Docker is not installed. "
        "Use this tool for questions about Docker installation, "
        "availability, the Docker daemon, containers, or container status."
    ),
    params={
        "show_all": (
            "True = show both running and stopped containers. "
            "False = show only running containers."
        )
    },
)
def docker_ps(show_all: bool = True) -> str:
    cmd = ["docker", "ps"]

    if show_all:
        cmd.append("-a")

    cmd += [
        "--format",
        "table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=host_env(),
            timeout=10,
        )
    except FileNotFoundError:
        return (
            "Docker available: no.\n"
            "The docker command was not found on the system."
        )
    except subprocess.TimeoutExpired:
        return "[error] docker ps timed out."
    except Exception as e:
        return f"[error] {e}"

    output = result.stdout.strip()
    stderr = result.stderr.strip()

    if "Cannot connect to the Docker daemon" in stderr:
        return (
            "Docker available: yes.\n"
            "Docker daemon: unavailable.\n"
            "The Docker daemon is not running."
        )

    if "permission denied" in stderr.lower():
        return (
            "Docker available: yes.\n"
            "Docker daemon: unavailable.\n"
            "Permission denied when accessing the Docker daemon."
        )

    if not output:
        if show_all:
            return (
                "Docker available: yes.\n"
                "Docker daemon: available.\n"
                "Docker container query succeeded. "
                "Containers found: 0."
            )

        return (
            "Docker available: yes.\n"
            "Docker daemon: available.\n"
            "Docker container query succeeded. "
            "Running containers found: 0."
        )

    return (
        "Docker available: yes.\n"
        "Docker daemon: available.\n"
        + limit_lines(
            output,
            30,
            note="showing the first {n} lines",
        )
    )

@tool(
    "docker_version",
    readonly=True,
    requires=("docker",),
    description=(
        "Show the installed Docker version. A successful result "
        "reports the Docker version available on the host system. "
        "If the docker command is not found, Docker is not available."
    ),
)
def docker_version() -> str:
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            env=host_env(),
            timeout=10,
        )
    except FileNotFoundError:
        return (
            "Docker available: no.\n"
            "The docker command was not found on the system."
        )
    except subprocess.TimeoutExpired:
        return "[error] docker --version timed out."
    except Exception as e:
        return f"[error] {e}"

    output = result.stdout.strip()
    stderr = result.stderr.strip()

    if result.returncode != 0:
        return (
            "Docker available: yes.\n"
            f"[error] docker --version failed: {stderr or output}"
        )

    return (
        "Docker available: yes.\n"
        f"Docker version: {output}"
    )
