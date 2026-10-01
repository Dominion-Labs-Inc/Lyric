#!/usr/bin/env python3
"""
System Management Tools
=======================
Tools for system configuration and management

Tools:
- set_environment_variable: Set a variable in a project's .env file
- get_environment_variable: Read a variable from a project's .env file
- modify_config_file: Modify configuration files
- reload_config: Have a running service reread its configuration (SIGHUP)
- check_dependencies: Check project dependencies status
- update_system: Update system packages
- manage_docker: Manage Docker containers

Author: Lyric AI Team
"""

import logging
import os
import subprocess
import json
from typing import Any, Dict, List
from pathlib import Path

from .tool_registry import Tool, ToolParameter, ToolResult, ToolCategory, ToolSafety
from .capabilities import Capability, ToolCapabilityProfile, CapabilityMetadata, RiskLevel


logger = logging.getLogger(__name__)

#: The substrate's own folder. These tools work on a user's project, never on the
#: substrate's own settings: its env files hold its passwords.
_SUBSTRATE_ROOT = Path(__file__).resolve().parents[2]


def _is_substrates_own(path: Path) -> bool:
    """Whether `path` is inside the substrate's own folder."""
    try:
        Path(path).expanduser().resolve().relative_to(_SUBSTRATE_ROOT)
        return True
    except ValueError:
        return False


def _substrates_own_processes() -> set:
    """This process, the processes it was started by, and the ones it started."""
    import psutil
    me = psutil.Process(os.getpid())
    own = {me.pid}
    own.update(p.pid for p in me.parents())
    own.update(p.pid for p in me.children(recursive=True))
    return own


class SetEnvironmentVariableTool(Tool):
    """Set environment variable"""

    def __init__(self):
        super().__init__()
        self.name = "set_environment_variable"
        self.description = "Set an environment variable in a project's .env file"
        self.category = ToolCategory.SYSTEM
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="key",
                type="string",
                description="Environment variable name",
                required=True
            ),
            ToolParameter(
                name="value",
                type="string",
                description="Environment variable value",
                required=True
            ),
            ToolParameter(
                name="env_file",
                type="string",
                description="Path to the project's .env file",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="set_environment_variable",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MANAGE_PROCESS,
                    description="SetEnvironmentVariable capability"
                )
            ]
        )

    async def execute(self, key: str, value: str, env_file: str) -> ToolResult:
        try:
            env_path = Path(env_file).expanduser().resolve()
            if _is_substrates_own(env_path):
                return ToolResult(success=False, output=None,
                                  error="that is the substrate's own settings file; this tool works on a user's project")

            # Read existing .env or create new
            if env_path.exists():
                with open(env_path, 'r') as f:
                    lines = f.readlines()
            else:
                lines = []

            # Update or add variable
            updated = False
            new_lines = []

            for line in lines:
                if line.strip() and not line.strip().startswith('#'):
                    if line.startswith(f"{key}="):
                        new_lines.append(f"{key}={value}\n")
                        updated = True
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)

            if not updated:
                new_lines.append(f"{key}={value}\n")

            # Write back
            env_path.parent.mkdir(parents=True, exist_ok=True)
            with open(env_path, 'w') as f:
                f.writelines(new_lines)

            return ToolResult(
                success=True,
                output={
                    'key': key,
                    'value': value,
                    'env_file': str(env_path),
                    'action': 'updated' if updated else 'created'
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class GetEnvironmentVariableTool(Tool):
    """Read a variable from a project's .env file."""

    def __init__(self):
        super().__init__()
        self.name = "get_environment_variable"
        self.description = "Get the value of an environment variable from a project's .env file"
        self.category = ToolCategory.SYSTEM
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="key",
                type="string",
                description="Environment variable name",
                required=True
            ),
            ToolParameter(
                name="env_file",
                type="string",
                description="Path to the project's .env file",
                required=True
            ),
            ToolParameter(
                name="default",
                type="string",
                description="Default value if not found",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="get_environment_variable",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MANAGE_PROCESS,
                    description="GetEnvironmentVariable capability"
                )
            ]
        )

    async def execute(self, key: str, env_file: str, default: str = None) -> ToolResult:
        """Read from the project's file, never the substrate's own environment: that
        holds the substrate's passwords, and this used to hand them to whoever asked."""
        try:
            env_path = Path(env_file).expanduser().resolve()
            if _is_substrates_own(env_path):
                return ToolResult(success=False, output=None,
                                  error="that is the substrate's own settings file; this tool works on a user's project")
            if not env_path.is_file():
                return ToolResult(success=False, output=None, error=f"No such .env file: {env_path}")
            from dotenv import dotenv_values
            values = dotenv_values(env_path)
            value = values.get(key, default)

            return ToolResult(
                success=True,
                output={
                    'key': key,
                    'env_file': str(env_path),
                    'value': value,
                    'exists': key in values,
                    'is_default': key not in values
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ModifyConfigFileTool(Tool):
    """Modify configuration files"""

    def __init__(self):
        super().__init__()
        self.name = "modify_config_file"
        self.description = "Modify JSON or YAML configuration files"
        self.category = ToolCategory.SYSTEM
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="config_file",
                type="string",
                description="Path to configuration file",
                required=True
            ),
            ToolParameter(
                name="key_path",
                type="string",
                description="Dot-separated path to config key (e.g., 'database.host')",
                required=True
            ),
            ToolParameter(
                name="value",
                type="string",
                description="New value",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="modify_config_file",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MANAGE_PROCESS,
                    description="ModifyConfigFile capability"
                ),
                CapabilityMetadata(
                    capability=Capability.MANAGE_CONFIG,
                    description="Modify and manage system configuration files",
                    input_types=["config_path", "key", "value"],
                    output_types=["status"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,
                    priority=8
                )
            ]
        )

    async def execute(self, config_file: str, key_path: str, value: str) -> ToolResult:
        try:
            file = Path(config_file).expanduser().resolve()
            if not file.exists():
                return ToolResult(success=False, output=None, error=f"Config file not found: {file}")

            # Determine file type and load
            if file.suffix in ['.json', '.jsonc']:
                with open(file, 'r') as f:
                    config = json.load(f)
                format_type = 'json'
            elif file.suffix in ['.yaml', '.yml']:
                import yaml
                with open(file, 'r') as f:
                    config = yaml.safe_load(f)
                format_type = 'yaml'
            else:
                return ToolResult(success=False, output=None, error=f"Unsupported config format: {file.suffix}")

            # Navigate to key and update
            keys = key_path.split('.')
            current = config

            for i, key in enumerate(keys[:-1]):
                if key not in current:
                    current[key] = {}
                current = current[key]

            # Set value (try to parse as JSON for complex types)
            try:
                parsed_value = json.loads(value)
                current[keys[-1]] = parsed_value
            except:
                current[keys[-1]] = value

            # Write back
            with open(file, 'w') as f:
                if format_type == 'json':
                    json.dump(config, f, indent=2)
                else:
                    import yaml
                    yaml.dump(config, f, default_flow_style=False)

            return ToolResult(
                success=True,
                output={
                    'config_file': str(file),
                    'key_path': key_path,
                    'value': current[keys[-1]],
                    'format': format_type
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ReloadConfigTool(Tool):
    """Have a running service reread its configuration."""

    def __init__(self):
        super().__init__()
        self.name = "reload_config"
        self.description = ("Have a running service reread its configuration files, by sending it the reload "
                            "signal (SIGHUP) the way most servers expect")
        self.category = ToolCategory.SYSTEM
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="pid",
                type="integer",
                description="Process ID of the service to reload",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="reload_config",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MANAGE_PROCESS,
                    description="Reload a service's configuration"
                )
            ]
        )

    async def execute(self, pid: int) -> ToolResult:
        """Signal the service it is given. It used to reload the substrate's own
        configuration module in place, which served no user."""
        try:
            import psutil
            import signal
            pid = int(pid)
            if pid in _substrates_own_processes():
                return ToolResult(success=False, output=None,
                                  error="that is the substrate's own process; this tool works on a user's service")
            proc = psutil.Process(pid)
            name = proc.name()
            proc.send_signal(signal.SIGHUP)
            return ToolResult(success=True, output={'pid': pid, 'name': name, 'signal': 'SIGHUP',
                                                    'reloaded': True})
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class CheckDependenciesTool(Tool):
    """Check project dependencies status"""

    def __init__(self):
        super().__init__()
        self.name = "check_dependencies"
        self.description = "Check if project dependencies are installed and up to date"
        self.category = ToolCategory.SYSTEM
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="requirements_file",
                type="string",
                description="Path to requirements.txt",
                required=True
            ),
            ToolParameter(
                name="python",
                type="string",
                description="The project's Python interpreter (e.g. its venv's bin/python)",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="check_dependencies",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MANAGE_PROCESS,
                    description="CheckDependencies capability"
                ),
                CapabilityMetadata(
                    capability=Capability.MANAGE_DEPENDENCIES,
                    description="Check and manage system dependencies",
                    input_types=["requirements"],
                    output_types=["dependency_status"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ]
        )

    async def execute(self, requirements_file: str, python: str) -> ToolResult:
        """Checked against the project's own interpreter. It ran whichever `pip3` came
        first on the path, which is the substrate's own environment."""
        try:
            req_file = Path(requirements_file).expanduser().resolve()
            if not req_file.exists():
                return ToolResult(success=False, output=None, error=f"Requirements file not found: {req_file}")

            # Read requirements
            with open(req_file, 'r') as f:
                requirements = [line.strip() for line in f if line.strip() and not line.startswith('#')]

            # Check each package
            installed = []
            missing = []
            outdated = []

            for req in requirements:
                # Parse requirement
                import re
                match = re.match(r'^([a-zA-Z0-9_-]+)', req)
                if not match:
                    continue

                package_name = match.group(1)

                # Check if installed
                result = subprocess.run(
                    [python, '-m', 'pip', 'show', package_name],
                    capture_output=True,
                    text=True
                )

                if result.returncode == 0:
                    # Parse version
                    for line in result.stdout.split('\n'):
                        if line.startswith('Version:'):
                            version = line.split(':', 1)[1].strip()
                            installed.append({
                                'package': package_name,
                                'version': version,
                                'requirement': req
                            })
                            break
                else:
                    missing.append({
                        'package': package_name,
                        'requirement': req
                    })

            return ToolResult(
                success=True,
                output={
                    'requirements_file': str(req_file),
                    'total_requirements': len(requirements),
                    'installed': len(installed),
                    'missing': len(missing),
                    'installed_packages': installed,
                    'missing_packages': missing,
                    'all_satisfied': len(missing) == 0
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class UpdateSystemTool(Tool):
    """Update system packages"""

    def __init__(self):
        super().__init__()
        self.name = "update_system"
        self.description = "Update system packages (Homebrew on macOS, apt on Linux)"
        self.category = ToolCategory.SYSTEM
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="package_name",
                type="string",
                description="Specific package to update (optional, updates all if not specified)",
                required=False
            ),
            ToolParameter(
                name="dry_run",
                type="boolean",
                description="Only check for updates without installing",
                required=False,
                default=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="update_system",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MANAGE_PROCESS,
                    description="UpdateSystem capability"
                )
            ]
        )

    async def execute(self, package_name: str = None, dry_run: bool = True) -> ToolResult:
        try:
            import platform
            system = platform.system()

            if system == "Darwin":  # macOS
                if dry_run:
                    cmd = ["brew", "outdated"]
                else:
                    if package_name:
                        cmd = ["brew", "upgrade", package_name]
                    else:
                        cmd = ["brew", "upgrade"]
            elif system == "Linux":
                if dry_run:
                    cmd = ["apt", "list", "--upgradable"]
                else:
                    if package_name:
                        cmd = ["sudo", "apt", "install", "--only-upgrade", package_name]
                    else:
                        cmd = ["sudo", "apt", "upgrade", "-y"]
            else:
                return ToolResult(success=False, output=None, error=f"Unsupported system: {system}")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            return ToolResult(
                success=result.returncode == 0,
                output={
                    'system': system,
                    'package': package_name or 'all',
                    'dry_run': dry_run,
                    'stdout': result.stdout,
                    'stderr': result.stderr
                },
                error=result.stderr if result.returncode != 0 else None
            )

        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output=None, error="Update timed out after 5 minutes")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ManageDockerTool(Tool):
    """Manage Docker containers"""

    def __init__(self):
        super().__init__()
        self.name = "manage_docker"
        self.description = "Manage Docker containers (list, start, stop, restart)"
        self.category = ToolCategory.SYSTEM
        self.safety_level = ToolSafety.DANGEROUS
        self.parameters = [
            ToolParameter(
                name="action",
                type="string",
                description="Docker action to perform",
                required=True,
                enum=["list", "start", "stop", "restart", "logs", "stats"]
            ),
            ToolParameter(
                name="container_name",
                type="string",
                description="Container name or ID (required for start/stop/restart/logs)",
                required=False
            ),
            ToolParameter(
                name="tail_lines",
                type="number",
                description="Number of log lines to tail (for logs action)",
                required=False,
                default=100
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="manage_docker",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MANAGE_PROCESS,
                    description="ManageDocker capability"
                ),
                CapabilityMetadata(
                    capability=Capability.MANAGE_DOCKER,
                    description="Manage Docker containers and images",
                    input_types=["container_config"],
                    output_types=["container_status"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.HIGH,
                    priority=8
                )
            ]
        )

    async def execute(self, action: str, container_name: str = None, tail_lines: int = 100) -> ToolResult:
        try:
            if action == "list":
                cmd = ["docker", "ps", "-a", "--format", "json"]
            elif action in ["start", "stop", "restart"]:
                if not container_name:
                    return ToolResult(success=False, output=None, error=f"container_name required for {action}")
                cmd = ["docker", action, container_name]
            elif action == "logs":
                if not container_name:
                    return ToolResult(success=False, output=None, error="container_name required for logs")
                cmd = ["docker", "logs", "--tail", str(tail_lines), container_name]
            elif action == "stats":
                cmd = ["docker", "stats", "--no-stream", "--format", "json"]
            else:
                return ToolResult(success=False, output=None, error=f"Unknown action: {action}")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            output_data = {
                'action': action,
                'container': container_name,
                'stdout': result.stdout,
                'stderr': result.stderr
            }

            # Parse JSON output for list/stats
            if action in ["list", "stats"] and result.returncode == 0:
                try:
                    # Docker outputs one JSON object per line
                    containers = []
                    for line in result.stdout.strip().split('\n'):
                        if line:
                            containers.append(json.loads(line))
                    output_data['containers'] = containers
                    output_data['count'] = len(containers)
                except:
                    pass

            return ToolResult(
                success=result.returncode == 0,
                output=output_data,
                error=result.stderr if result.returncode != 0 else None
            )

        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output=None, error="Docker command timed out")
        except FileNotFoundError:
            return ToolResult(success=False, output=None, error="Docker not installed or not in PATH")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))
