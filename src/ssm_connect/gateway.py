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
from typing import Dict, Optional
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


_AGENT_WARNING_SHOWN = False

def _get_ssh_tool(tool_name: str) -> Optional[str]:
    """
    On Windows, prefer the native System32 OpenSSH tools only if 
    native ssh-agent service execution is expected (SSH_AUTH_SOCK not set).
    Otherwise (e.g. Git Bash), rely on PATH.
    """
    if os.name == 'nt' and not os.environ.get('SSH_AUTH_SOCK'):
        system32 = os.environ.get('SystemRoot', 'C:\\Windows') + '\\System32\\OpenSSH'
        native_tool = os.path.join(system32, f"{tool_name}.exe")
        if os.path.exists(native_tool):
            return native_tool
    
    return shutil.which(tool_name)


def add_key_to_agent(key_path: Path):
    global _AGENT_WARNING_SHOWN
    ssh_add = _get_ssh_tool("ssh-add")
    ssh_keygen = _get_ssh_tool("ssh-keygen")

    if not ssh_add or not ssh_keygen:
        return

    try:
        result = subprocess.run(
            [ssh_add, "-l"], 
            capture_output=True, text=True, stdin=subprocess.DEVNULL
        )
        if result.returncode == 2:
             if os.name == 'nt' and not _AGENT_WARNING_SHOWN:
                 print("\nWarning: ssh-agent service is not running. To avoid passphrase prompts:", file=sys.stderr)
                 print("  Run in Admin PowerShell: Start-Service ssh-agent\n", file=sys.stderr)
                 _AGENT_WARNING_SHOWN = True
             return
        
        keygen = subprocess.run(
            [ssh_keygen, "-lf", str(key_path)], 
            capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL
        )
        if keygen.returncode != 0:
            return

        parts = keygen.stdout.strip().split()
        if len(parts) < 2:
            return
        fingerprint = parts[1]
        
        if fingerprint in result.stdout:
            return

        print(f"Adding key '{key_path.name}' to ssh-agent...")
        add_res = subprocess.run([ssh_add, str(key_path)], check=False)
        
    except Exception as e:
        print(f"Warning: Failed to interact with ssh-agent: {e}", file=sys.stderr)


def quote_arg_for_proxy_command(arg: str) -> str:
    if os.name == 'nt':
        if not arg:
            return '""'
        if ' ' not in arg and '\t' not in arg and '"' not in arg:
            return arg
        
        result = []
        backslashes = 0
        for char in arg:
            if char == '\\':
                backslashes += 1
            elif char == '"':
                result.append('\\' * (backslashes * 2))
                result.append('\\"')
                backslashes = 0
            else:
                if backslashes > 0:
                    result.append('\\' * backslashes)
                result.append(char)
                backslashes = 0
        
        if backslashes > 0:
            result.append('\\' * (backslashes * 2))
            
        return f'"{("".join(result))}"'
    else:
        return shlex.quote(arg)


def _display_label(name: Optional[str], ident: str) -> str:
    if name and name != "Unnamed":
        return f"{name} ({ident})"
    return ident


def _format_banner(kind: str, fields: list) -> list:
    sep = "=" * 50
    lines = [sep, f"  {kind}"]
    for label, value in fields:
        if value not in (None, ""):
            lines.append(f"  {label:<12}{value}")
    lines.append(sep)
    return lines


def _cmd_caret_escape(text: str) -> str:
    # cmd.exe metacharacters must be caret-escaped so 'title'/'echo' see them literally.
    for ch in '^&|<>()':
        text = text.replace(ch, '^' + ch)
    return text


def _posix_session_script(command: list, title: Optional[str], banner_lines: Optional[list], keep_open: bool) -> str:
    stmts = []
    if title:
        # OSC 0 escape sets the window/tab title on virtually any terminal emulator.
        stmts.append("printf '\\033]0;%s\\007' " + shlex.quote(title))
    for line in (banner_lines or []):
        stmts.append("printf '%s\\n' " + shlex.quote(line))
    stmts.append(" ".join(shlex.quote(arg) for arg in command))
    if keep_open:
        stmts.append("exec bash")
    return "; ".join(stmts)


def _windows_session_payload(command: list, title: Optional[str], banner_lines: Optional[list], set_title_builtin: bool) -> str:
    parts = []
    if set_title_builtin and title:
        parts.append("title " + _cmd_caret_escape(title))
    for line in (banner_lines or []):
        parts.append("echo." if line == "" else "echo " + _cmd_caret_escape(line))
    parts.append(subprocess.list2cmdline(command))
    return " & ".join(parts)


def open_in_new_terminal(command: list, env: dict, title: Optional[str] = None, banner_lines: Optional[list] = None):
    if sys.platform.startswith("linux"):
        if shutil.which("gnome-terminal"):
            inner = _posix_session_script(command, title, banner_lines, keep_open=True)
            subprocess.Popen(["gnome-terminal", "--", "bash", "-c", inner], env=env)
        elif shutil.which("konsole"):
            inner = _posix_session_script(command, title, banner_lines, keep_open=False)
            subprocess.Popen(["konsole", "-e", "bash", "-c", inner], env=env)
        elif shutil.which("xterm"):
            inner = _posix_session_script(command, title, banner_lines, keep_open=False)
            subprocess.Popen(["xterm", "-e", "bash", "-c", inner], env=env)
        elif shutil.which("x-terminal-emulator"):
            inner = _posix_session_script(command, title, banner_lines, keep_open=False)
            subprocess.Popen(["x-terminal-emulator", "-e", "bash", "-c", inner], env=env)
        else:
            print("No supported terminal emulator found, running in current window.", file=sys.stderr)
            subprocess.Popen(command, env=env)

    elif sys.platform == "darwin":
        inner = _posix_session_script(command, title, banner_lines, keep_open=False)
        # AppleScript treats backslash and double-quote as escapes inside its string literal,
        # so double them before embedding the shell script.
        applescript_safe = inner.replace('\\', '\\\\').replace('"', '\\"')
        subprocess.Popen([
            "osascript",
            "-e",
            f'tell application "Terminal" to do script "{applescript_safe}"'
        ], env=env)

    elif os.name == "nt":
        if shutil.which("wt"):
            payload = _windows_session_payload(command, title, banner_lines, set_title_builtin=False)
            wt_args = ["wt", "new-tab"]
            if title:
                wt_args += ["--title", title]
            wt_args += ["cmd", "/k", payload]
            subprocess.Popen(wt_args, env=env)
        elif shutil.which("powershell"):
            payload = _windows_session_payload(command, title, banner_lines, set_title_builtin=True)
            subprocess.Popen([
                "powershell",
                "-Command",
                f"Start-Process cmd -ArgumentList '/k', {repr(payload)}"
            ], env=env)
        else:
            payload = _windows_session_payload(command, title, banner_lines, set_title_builtin=True)
            subprocess.Popen(["cmd", "/c", "start", "", "cmd", "/k", payload], env=env)

    else:
        print("Unknown OS: running the command in the current terminal.")
        subprocess.Popen(command, env=env)


def start_ssm_session(instance_id: str, session: boto3.Session, interactive_mode: bool = True, document_name: Optional[str] = None, instance_name: Optional[str] = None) -> int:
    env = _prepare_subprocess_env(session)
    cmd = ["aws", "ssm", "start-session", "--target", instance_id]
    if document_name:
        cmd.extend(["--document-name", document_name])
    short = instance_name if (instance_name and instance_name != "Unnamed") else instance_id
    title = f"SSM - {short}"
    banner = _format_banner("SSM SESSION", [
        ("Instance", _display_label(instance_name, instance_id)),
        ("Region", session.region_name),
    ])
    try:
        print(f"\nOpening SSM session to {_display_label(instance_name, instance_id)} in a new terminal window.")
        if interactive_mode:
            print("You can now open additional sessions by making another selection.\n")
        open_in_new_terminal(cmd, env, title=title, banner_lines=banner)
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


def start_ssh_session(instance_id: str, username: str, key_path: Path, session: boto3.Session, interactive_mode: bool = True, document_name: str = "AWS-StartSSHSession", instance_name: Optional[str] = None) -> int:
    add_key_to_agent(key_path)
    env = _prepare_subprocess_env(session)

    ssh_bin = _get_ssh_tool("ssh") or "ssh"
    
    proxy_command = (
        f"aws ssm start-session --target {instance_id} "
        f"--document-name {document_name} --parameters portNumber=%p"
    )
    strict_host_check = get_host_key_checking_choice()
    ssh_cmd = [
        ssh_bin, "-i", str(key_path.resolve()),
        "-o", f"ProxyCommand={proxy_command}",
        "-o", "IdentitiesOnly=yes"
    ]
    if not strict_host_check:
        ssh_cmd += [
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null"
        ]
    ssh_cmd.append(f"{username}@{instance_id}")
    short = instance_name if (instance_name and instance_name != "Unnamed") else instance_id
    title = f"SSH - {username}@{short}"
    banner = _format_banner("SSH OVER SSM", [
        ("Instance", _display_label(instance_name, instance_id)),
        ("User", username),
        ("Region", session.region_name),
    ])
    try:
        print(f"\nOpening SSH over SSM session to {_display_label(instance_name, instance_id)} as '{username}' in a new terminal window.")
        if interactive_mode:
            print("You can now open additional sessions by making another selection.\n")
        open_in_new_terminal(ssh_cmd, env, title=title, banner_lines=banner)
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



def start_port_forwarding_to_rds(bastion_id: str, rds_instance: Dict[str, str], session: boto3.Session, interactive_mode: bool = True, document_name: str = "AWS-StartPortForwardingSessionToRemoteHost", local_port: int = None, bastion_name: Optional[str] = None) -> int:
    env = _prepare_subprocess_env(session)
    if local_port is None:
        local_port = find_available_local_port()

    cmd = [
        "aws", "ssm", "start-session",
        "--target", bastion_id,
        "--document-name", document_name,
        "--parameters", f"host={rds_instance['Endpoint']},portNumber={rds_instance['Port']},localPortNumber={local_port}"
    ]

    title = f"RDS - {rds_instance['DBInstanceIdentifier']} (local {local_port})"
    banner = _format_banner("RDS PORT FORWARDING", [
        ("Database", rds_instance['DBInstanceIdentifier']),
        ("Bastion", _display_label(bastion_name, bastion_id)),
        ("Endpoint", f"{rds_instance['Endpoint']}:{rds_instance['Port']}"),
        ("Connect to", f"localhost:{local_port}"),
    ])

    try:
        print(f"\nStarting port forwarding to RDS instance '{rds_instance['DBInstanceIdentifier']}' in a new terminal window.")
        print(f"Bastion: {bastion_id}")
        print(f"Local port: {local_port}")
        print(f"Remote host: {rds_instance['Endpoint']}")
        print(f"Remote port: {rds_instance['Port']}")
        print(f"Connect to: localhost:{local_port}")
        if interactive_mode:
            print("You can now open additional sessions by making another selection.\n")
        open_in_new_terminal(cmd, env, title=title, banner_lines=banner)
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
            return 0


def start_port_forwarding_session(instance_id: str, remote_port: int, local_port: int, session: boto3.Session, interactive_mode: bool = True, document_name: str = "AWS-StartPortForwardingSession", instance_name: Optional[str] = None) -> int:
    env = _prepare_subprocess_env(session)

    cmd = [
        "aws", "ssm", "start-session",
        "--target", instance_id,
        "--document-name", document_name,
        "--parameters", f"portNumber={remote_port},localPortNumber={local_port}"
    ]

    short = instance_name if (instance_name and instance_name != "Unnamed") else instance_id
    title = f"PF - {short}:{remote_port} (local {local_port})"
    banner = _format_banner("PORT FORWARDING", [
        ("Instance", _display_label(instance_name, instance_id)),
        ("Remote", str(remote_port)),
        ("Local", str(local_port)),
        ("Connect to", f"localhost:{local_port}"),
    ])

    try:
        print(f"\nStarting port forwarding session to {_display_label(instance_name, instance_id)}")
        print(f"Remote Port: {remote_port}")
        print(f"Local Port:  {local_port}")
        print(f"Connect to:  localhost:{local_port}")
        if interactive_mode:
             print("You can now open additional sessions by making another selection.\n")
        open_in_new_terminal(cmd, env, title=title, banner_lines=banner)
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
            return 0


def perform_file_transfer(
    instance_id: str,
    username: str,
    key_path: Path,
    session: boto3.Session,
    local_path: str,
    remote_path: str,
    direction: str = "upload",
    recursive: bool = False,
    document_name: str = "AWS-StartSSHSession"
) -> int:
    add_key_to_agent(key_path)
    env = _prepare_subprocess_env(session)
    
    scp_bin = _get_ssh_tool("scp") or "scp"
    
    proxy_command = (
        f"aws ssm start-session --target {instance_id} "
        f"--document-name {document_name} --parameters portNumber=%p"
    )
    strict_host_check = get_host_key_checking_choice()
    
    scp_cmd = [
        scp_bin, "-i", str(key_path.resolve()),
        "-o", f"ProxyCommand={proxy_command}",
        "-o", "IdentitiesOnly=yes"
    ]
    
    if not strict_host_check:
        scp_cmd += [
            "-o", "StrictHostKeyChecking=no",
        ]
    
    if recursive:
        scp_cmd.append("-r")
        
    remote_host_str = f"{username}@{instance_id}:{remote_path}"
    
    if direction == "upload":
        scp_cmd += [local_path, remote_host_str]
        action_desc = f"Uploading '{local_path}' to '{remote_path}' on {instance_id}"
    else:
        scp_cmd += [remote_host_str, local_path]
        action_desc = f"Downloading '{remote_path}' from {instance_id} to '{local_path}'"

    try:
        print(f"\n{action_desc}...")
        result = subprocess.run(scp_cmd, env=env)
        if result.returncode == 0:
            print("✓ Transfer complete.")
        else:
            print("✗ Transfer failed.", file=sys.stderr)
        return result.returncode

    except FileNotFoundError:
        print("Error: 'scp' or 'aws' command not found.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nTransfer cancelled.")
        return 1
    except Exception as e:
        print(f"Error during transfer: {e}", file=sys.stderr)
        return 1

def start_ssh_proxyjump_session(
    bastion_id: str,
    bastion_user: str,
    bastion_key: Path,
    target_host: str,
    target_user: str,
    target_key: Path,
    session: boto3.Session,
    interactive_mode: bool = True,
    document_name: str = "AWS-StartSSHSession",
    bastion_name: Optional[str] = None,
    target_name: Optional[str] = None
) -> int:
    add_key_to_agent(bastion_key)
    add_key_to_agent(target_key)
    env = _prepare_subprocess_env(session)
    
    ssh_bin = _get_ssh_tool("ssh") or "ssh"

    ssm_proxy_command = (
        f"aws ssm start-session --target {bastion_id} "
        f"--document-name {document_name} --parameters portNumber=%p"
    )
    
    strict_host_check = get_host_key_checking_choice()
    
    bastion_ssh_args = [
        ssh_bin, "-i", str(bastion_key.resolve()),
        "-o", f"ProxyCommand={ssm_proxy_command}",
        "-o", "IdentitiesOnly=yes"
    ]
    
    if not strict_host_check:
        bastion_ssh_args += [
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null"
        ]
        
    bastion_ssh_args += [
        "-W", "%h:%p",
        f"{bastion_user}@{bastion_id}"
    ]
    
    jump_proxy_command = " ".join(quote_arg_for_proxy_command(arg) for arg in bastion_ssh_args)

    target_ssh_cmd = [
        ssh_bin, "-i", str(target_key.resolve()),
        "-o", f"ProxyCommand={jump_proxy_command}",
        "-o", "IdentitiesOnly=yes"
    ]
    
    if not strict_host_check:
        target_ssh_cmd += [
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null"
        ]
        
    target_ssh_cmd.append(f"{target_user}@{target_host}")

    target_short = target_name if (target_name and target_name != "Unnamed") else target_host
    bastion_short = bastion_name if (bastion_name and bastion_name != "Unnamed") else bastion_id
    title = f"SSH-PJ - {target_short} via {bastion_short}"
    banner = _format_banner("SSH PROXYJUMP", [
        ("Bastion", _display_label(bastion_name, bastion_id)),
        ("Bast User", bastion_user),
        ("Target", _display_label(target_name, target_host)),
        ("Targ User", target_user),
    ])

    try:
        print(f"\nOpening SSH ProxyJump session via {_display_label(bastion_name, bastion_id)} to {_display_label(target_name, target_host)}...")
        print(f"Bastion User: {bastion_user}")
        print(f"Target User:  {target_user}")
        if interactive_mode:
            print("You can now open additional sessions by making another selection.\n")

        open_in_new_terminal(target_ssh_cmd, env, title=title, banner_lines=banner)
        return 0
    except Exception as e:
        print(f"Error opening terminal: {e}", file=sys.stderr)
        print("Falling back to current terminal session.", file=sys.stderr)
        try:
            result = subprocess.run(target_ssh_cmd, env=env)
            return result.returncode
        except FileNotFoundError:
            print("Error: 'ssh' or 'aws' command not found.", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("\nSession terminated.")
            return 0
