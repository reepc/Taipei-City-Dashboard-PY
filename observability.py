"""Logfire setup. Call `setup_logfire()` once at app/test entry point.

Modes:
- If `LOGFIRE_TOKEN` env is set, traces ship to Logfire cloud.
- Otherwise traces print to stdout (local-only, no signup needed).

Instruments pydantic-ai automatically. Also instruments httpx so raw
TWCC HTTP calls (twcc_completion.py) show up as spans too.
"""

import os

import logfire

_CONFIGURED = False


def setup_logfire(service_name: str = "taipei-dashboard") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    token = os.getenv("LOGFIRE_TOKEN")
    logfire.configure(
        service_name=service_name,
        token=token,
        send_to_logfire=bool(token),
        console=logfire.ConsoleOptions(colors="auto"),
    )

    logfire.instrument_pydantic_ai()
    logfire.instrument_httpx(capture_all=True)

    _CONFIGURED = True
