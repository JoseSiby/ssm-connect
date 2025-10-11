# Copyright 2025 Siby Jose
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import sys
import stat
import socket
import shutil
import shlex
import subprocess
from pathlib import Path
from typing import Dict
import boto3
from .inventory import get_session_credentials


def validate_key_permissions(key_path: Path) -> bool:
    if os.name == 'nt':
        return True
    try:
        mode = key_path.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            print(f"\nWarning: Private key '{key_path}' has overly permissive access.", file=sys.stderr)
            print(f"         To fix, run: chmod 600 {key_path}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"Warning: Could not check key permissions: {e}", file=sys.stderr)
        return True


def find_available_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _prepare_subprocess_env(session: boto3.Session) -> Dict[str, str]:
    env = os.environ.copy()
    creds = get_session_credentials(session)
    env.update(creds)
    if session.region_name:
        env["AWS_REGION"] = session.region_name
        env["AWS_DEFAULT_REGION"] = session.region_name
    return env


def open_in_new_terminal(command: list, env: dict):
    if sys.platform.startswith("linux"):
        if shutil.which("gnome-terminal"):
            safe_command = " ".join(shlex.quote(arg) for arg in command) + "; exec bash"
            subprocess.Popen(["gnome-terminal", "--", "bash", "-c", safe_command], env=env)
        elif shutil.which("konsole"):
            subprocess.Popen(["konsole", "-e"] + command, env=env)
        elif shutil.which("xterm"):
            subprocess.Popen(["xterm", "-e"] + command, env=env)
        elif shutil.which("x-terminal-emulator"):
            subprocess.Popen(["x-terminal-emulator", "-e"] + command, env=env)
        else:
            print("No supported terminal emulator found, running in current window.", file=sys.stderr)
            subprocess.Popen(command, env=env)
    
    elif sys.platform == "darwin":
        safe_command = " ".join(shlex.quote(arg) for arg in command)
        applescript_safe_command = safe_command.replace('"', '\\"')
        subprocess.Popen([
            "osascript",
            "-e",
            f'tell application "Terminal" to do script "{applescript_safe_command}"'
        ], env=env)
    
    elif os.name == "nt":
        safe_command = subprocess.list2cmdline(command)
        
        if shutil.which("wt"):
            subprocess.Popen(["wt", "new-tab", "cmd", "/k", safe_command], env=env)
        elif shutil.which("powershell"):
            subprocess.Popen([
                "powershell", 
                "-Command", 
                f"Start-Process powershell -ArgumentList '-NoExit', '-Command', {repr(safe_command)}"
            ], env=env)
        else:
            subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", safe_command], env=env)
    
    else:
        print("Unknown OS: running the command in the current terminal.")
        subprocess.Popen(command, env=env)


def start_ssm_session(instance_id: str, session: boto3.Session) -> int:
    env = _prepare_subprocess_env(session)
    cmd = ["aws", "ssm", "start-session", "--target", instance_id]
    try:
        print(f"\nOpening SSM session to {instance_id} in a new terminal window.")
        print("You can now open additional sessions by making another selection.\n")
        open_in_new_terminal(cmd, env)
        return 0
    except Exception as e:
        print(f"Error opening terminal: {e}", file=sys.stderr)
        print("Falling back to current terminal session.", file=sys.stderr)
        try:
            result = subprocess.run(cmd, env=env)
            return result.returncode
        except FileNotFoundError:
            print("Error: 'aws' command not found. Please ensure the AWS CLI is installed.", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("\nSSM session terminated.")
            return 0


def get_host_key_checking_choice() -> bool:
    choice = input(
        "Enable strict SSH host key checking? [y/N]: "
    ).strip().lower()
    return choice == "y"


def start_ssh_session(instance_id: str, username: str, key_path: Path, session: boto3.Session) -> int:
    env = _prepare_subprocess_env(session)
    proxy_command = (
        f"aws ssm start-session --target {instance_id} "
        f"--document-name AWS-StartSSHSession --parameters portNumber=%p"
    )
    strict_host_check = get_host_key_checking_choice()
    ssh_cmd = [
        "ssh", "-i", str(key_path.resolve()),
        "-o", f"ProxyCommand={proxy_command}",
        "-o", "IdentitiesOnly=yes"
    ]
    if not strict_host_check:
        ssh_cmd += [
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null"
        ]
    ssh_cmd.append(f"{username}@{instance_id}")
    try:
        print(f"\nOpening SSH over SSM session to {instance_id} as '{username}' in a new terminal window.")
        print("You can now open additional sessions by making another selection.\n")
        open_in_new_terminal(ssh_cmd, env)
        return 0
    except Exception as e:
        print(f"Error opening terminal: {e}", file=sys.stderr)
        print("Falling back to current terminal session.", file=sys.stderr)
        try:
            result = subprocess.run(ssh_cmd, env=env)
            return result.returncode
        except FileNotFoundError:
            print("Error: 'ssh' or 'aws' command not found. Ensure both are installed.", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("\nSSH session terminated.")
            return 0


def start_port_forwarding_to_rds(bastion_id: str, rds_instance: Dict[str, str], session: boto3.Session) -> int:
    env = _prepare_subprocess_env(session)
    local_port = find_available_local_port()
    
    cmd = [
        "aws", "ssm", "start-session",
        "--target", bastion_id,
        "--document-name", "AWS-StartPortForwardingSessionToRemoteHost",
        "--parameters", f"host={rds_instance['Endpoint']},portNumber={rds_instance['Port']},localPortNumber={local_port}"
    ]
    
    try:
        print(f"\nStarting port forwarding to RDS instance '{rds_instance['DBInstanceIdentifier']}' in a new terminal window.")
        print(f"Bastion: {bastion_id}")
        print(f"Local port: {local_port}")
        print(f"Remote host: {rds_instance['Endpoint']}")
        print(f"Remote port: {rds_instance['Port']}")
        print(f"Connect to: localhost:{local_port}")
        print("You can now open additional sessions by making another selection.\n")
        open_in_new_terminal(cmd, env)
        return 0
    except Exception as e:
        print(f"Error opening terminal: {e}", file=sys.stderr)
        print("Falling back to current terminal session.", file=sys.stderr)
        try:
            result = subprocess.run(cmd, env=env)
            return result.returncode
        except FileNotFoundError:
            print("Error: 'aws' command not found. Please ensure the AWS CLI is installed.", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("\nPort forwarding session terminated.")
            return 0
