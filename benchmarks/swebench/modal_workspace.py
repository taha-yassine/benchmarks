"""Modal Sandbox-based remote workspace implementation.

Creates a Modal Sandbox running the OpenHands agent server, exposes it via
encrypted tunnel, and delegates to RemoteWorkspace for HTTP API operations.
"""

from __future__ import annotations

import os
import time
from typing import Any

import modal
import requests
from pydantic import Field, PrivateAttr

from openhands.sdk.logger import get_logger
from openhands.sdk.workspace import RemoteWorkspace


logger = get_logger(__name__)

AGENT_SERVER_PORT = 8000
MODAL_APP_NAME_DEFAULT = "benchmarks-swebench-workspace"
TUNNEL_TIMEOUT_DEFAULT = 120
HEALTH_CHECK_TIMEOUT_DEFAULT = 180


class ModalSandboxWorkspace(RemoteWorkspace):
    """Remote workspace backed by a Modal Sandbox running the agent server.

    Creates a sandbox with the agent server image, starts the server as
    entrypoint, exposes port 8000 via encrypted tunnel, and uses
    RemoteWorkspace HTTP APIs for all operations.

    Example:
        with ModalSandboxWorkspace(
            server_image="ghcr.io/openhands/eval-agent-server:sdk-abc1234-instance-tag",
            app_name="my-swebench-workspace",
        ) as workspace:
            result = workspace.execute_command("ls -la")
    """

    working_dir: str = Field(
        default="/workspace",
        description="Working directory inside the sandbox.",
    )
    host: str = Field(
        default="",
        description="Remote host URL (set from tunnel after sandbox startup).",
    )

    server_image: str = Field(
        description="Container image for the agent server (e.g. ghcr.io/openhands/eval-agent-server:tag).",
    )
    app_name: str = Field(
        default=MODAL_APP_NAME_DEFAULT,
        description="Modal app name for sandbox lifecycle.",
    )
    timeout: int = Field(
        default=3600,
        description="Sandbox max lifetime in seconds (up to 24h).",
    )
    idle_timeout: int | None = Field(
        default=None,
        description="Sandbox idle timeout in seconds (None = disabled).",
    )
    cpu: float = Field(
        default=1.0,
        description="Requested sandbox CPU.",
    )
    memory: int = Field(
        default=2048,
        description="Requested sandbox memory in MiB.",
    )
    tunnel_timeout: int = Field(
        default=TUNNEL_TIMEOUT_DEFAULT,
        description="Seconds to wait for tunnel URL after sandbox start.",
    )
    startup_wait_timeout: float = Field(
        default=HEALTH_CHECK_TIMEOUT_DEFAULT,
        description="Seconds to wait for agent server /health to respond.",
    )
    forward_env: list[str] = Field(
        default_factory=lambda: ["DEBUG"],
        description="Environment variable names to forward from host to sandbox.",
    )
    verbose: bool = Field(
        default=False,
        description="Enable verbose Modal sandbox logging.",
    )

    _sandbox: modal.Sandbox | None = PrivateAttr(default=None)

    def model_post_init(self, context: Any) -> None:
        """Create sandbox, start agent server, resolve tunnel URL, init RemoteWorkspace."""
        env: dict[str, str] = {}
        for key in self.forward_env:
            if key in os.environ:
                env[key] = os.environ[key]

        image = modal.Image.from_registry(self.server_image)
        if env:
            image = image.env(env)

        app = modal.App.lookup(self.app_name, create_if_missing=True)

        sandbox = modal.Sandbox.create(
            "--host",
            "0.0.0.0",
            "--port",
            str(AGENT_SERVER_PORT),
            app=app,
            image=image,
            timeout=self.timeout,
            idle_timeout=self.idle_timeout,
            cpu=self.cpu,
            memory=self.memory,
            workdir=self.working_dir,
            encrypted_ports=[AGENT_SERVER_PORT],
            verbose=self.verbose,
        )
        self._sandbox = sandbox

        try:
            tunnels = sandbox.tunnels(timeout=self.tunnel_timeout)
            tunnel = tunnels.get(AGENT_SERVER_PORT)
            if not tunnel:
                raise RuntimeError(
                    f"Tunnel for port {AGENT_SERVER_PORT} not found. "
                    f"Available: {list(tunnels.keys())}"
                )
            tunnel_url = tunnel.url.rstrip("/")
            self.host = tunnel_url
            self.api_key = None

            logger.info("Modal workspace host: %s", self.host)
            self._wait_for_health()
            logger.info("Modal sandbox workspace ready at %s", self.host)

            super().model_post_init(context)
        except Exception:
            self.cleanup()
            raise

    def _wait_for_health(self) -> None:
        """Wait for the agent server /health endpoint to respond."""
        start = time.time()
        health_url = f"{self.host}/health"

        while time.time() - start < self.startup_wait_timeout:
            try:
                resp = requests.get(health_url, timeout=5.0)
                if 200 <= resp.status_code < 300:
                    return
            except Exception as e:
                logger.info("Health check failed: %s", e)

            if self._sandbox and self._sandbox.poll() is not None:
                raise RuntimeError("Sandbox exited before agent server became healthy")
            time.sleep(2)

        raise RuntimeError(
            f"Agent server /health did not respond within {self.startup_wait_timeout}s"
        )

    def __enter__(self) -> ModalSandboxWorkspace:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.cleanup()

    def __del__(self) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        """Terminate the Modal sandbox."""
        if self._sandbox:
            logger.info("Terminating Modal sandbox")
            try:
                self._sandbox.terminate()
            except Exception as e:
                logger.warning("Sandbox terminate error: %s", e)
            self._sandbox = None

        self.reset_client()
