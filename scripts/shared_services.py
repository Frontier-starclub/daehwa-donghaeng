"""Install/manage the two project-owned systemd user services on this Linux host."""

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".local/shared-server"
UNITS = ("daehwa-shared.service", "daehwa-gateway.service")


def systemctl(*args, check=True):
    return subprocess.run(["systemctl", "--user", *args], check=check)


def quoted(value):
    return '"' + str(value).replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"') + '"'


def install():
    if not (STATE / "config.json").is_file():
        raise SystemExit("먼저 shared_gateway.py prepare 명령을 실행해주세요.")
    units = STATE / "services"
    units.mkdir(parents=True, exist_ok=True)
    python = ROOT / "apps/backend/.venv/bin/python"
    commands = (
        f"{quoted(python)} {quoted(ROOT / 'apps/backend/scripts/dev_stack.py')} --shared",
        f"{quoted(python)} {quoted(ROOT / 'apps/backend/scripts/shared_gateway.py')} run",
    )
    for name, command in zip(UNITS, commands, strict=True):
        dependency = (
            "After=daehwa-shared.service\nRequires=daehwa-shared.service\n"
            "PartOf=daehwa-shared.service\n"
            if name == UNITS[1] else ""
        )
        (units / name).write_text(
            "[Unit]\nDescription=Daehwa shared Android test server\n"
            + dependency + "\n[Service]\nType=simple\n"
            + f"ExecStart={command}\n"
            + "Restart=on-failure\nRestartSec=5\nTimeoutStopSec=45\n"
            + "KillMode=mixed\nUMask=0077\n\n[Install]\nWantedBy=default.target\n"
        )
    # These names belong to this project. Stop an earlier transient invocation
    # before replacing it with persistent, reboot-enabled user units.
    systemctl("stop", *reversed(UNITS), check=False)
    systemctl("reset-failed", *UNITS, check=False)
    systemctl("daemon-reload")
    systemctl("enable", *(str(units / name) for name in UNITS))
    systemctl("daemon-reload")
    systemctl("start", *UNITS)
    print("공용 서버 서비스를 설치했습니다. 재부팅 후 실행에는 사용자 Linger=yes가 필요합니다.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("install", "status", "restart", "stop"))
    command = parser.parse_args().command
    if command == "install":
        install()
    elif command == "status":
        systemctl("status", "--no-pager", *UNITS, check=False)
    else:
        systemctl(command, *UNITS)


if __name__ == "__main__":
    main()
