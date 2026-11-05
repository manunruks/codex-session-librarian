"""Run synthetic-only third-party tools with private homes hidden."""
from pathlib import Path
import subprocess


def command(lab, argv, network=False, cwd="/mnt/src", extra_env=None, readonly_binds=()):
    lab = Path(lab).resolve()
    (lab / "home").mkdir(exist_ok=True)
    env = {"HOME": "/mnt/home", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
        "CODEX_HOME": "/mnt/home/.codex", "CLAUDE_CONFIG_DIR": "/mnt/home/.claude",
        "XDG_CONFIG_HOME": "/mnt/home/.config", "XDG_CACHE_HOME": "/mnt/home/.cache",
        "TMPDIR": "/tmp", "PYTHONDONTWRITEBYTECODE": "1", **(extra_env or {})}
    args = ["bwrap", "--ro-bind", "/", "/", "--tmpfs", "/home", "--tmpfs", "/run/user",
        "--tmpfs", "/tmp", "--proc", "/proc", "--dev", "/dev", "--bind", str(lab), "/mnt",
        "--unshare-pid", "--new-session", "--die-with-parent", "--clearenv", "--chdir", cwd]
    if not network:
        args += ["--unshare-net"]
    for source, target in readonly_binds:
        args += ["--ro-bind", str(source), str(target)]
    for key, value in env.items():
        args += ["--setenv", key, str(value)]
    return args + ["--", *map(str, argv)]


def run(lab, argv, **kwargs):
    network = kwargs.pop("network", False)
    cwd = kwargs.pop("cwd", "/mnt/src")
    extra_env = kwargs.pop("extra_env", None)
    readonly_binds = kwargs.pop("readonly_binds", ())
    return subprocess.run(command(lab, argv, network, cwd, extra_env, readonly_binds),
        capture_output=True, text=True, timeout=kwargs.pop("timeout", 90), **kwargs)
