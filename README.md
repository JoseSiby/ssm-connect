# ssm-connect

Interactive CLI to connect to AWS EC2 instances and RDS databases via:

- **SSM Session Manager** (interactive shell)
- **SSH over SSM** (with your SSH key)
- **RDS Port Forwarding** (via EC2 bastion host)
- **File Transfer (SCP)** (Securely upload/download files)

Multiple sessions in parallel (each opens in a new terminal). Keyword search across Name, Instance ID, and all tag values. Simple, cross-platform, and secure-by-default.

## Features

- **Target Selection**: Choose to connect to EC2 instances or RDS databases
- **EC2 Connections**:
  - SSM Session Manager (interactive shell)
  - SSH over SSM (with private key authentication)
- **RDS Connections**:
  - Port forwarding to RDS databases via EC2 bastion host
  - Auto-selects available local port
- **File Transfer**:
  - Upload/Download files to/from EC2 instances using SCP
  - Uses existing SSH key configuration
- **Smart Search**: Filter instances by keywords (matches Name, InstanceId, and all tag values)
- **Multi-Session**: Opens each connection in a new terminal window (Linux, macOS, Windows) allowing for multiple simultaneous sessions.
- **AWS Session**: Automatically inherits AWS credentials
- **Security**: All code undergoes automated CodeQL static analysis on every PR and merge

## Install

Latest release from PyPI: pip install --upgrade ssm-connect

Run the tool: ssm-connect


## Requirements

- **User should already be logged in to AWS**
- **AWS CLI v2**
- **SSM Session Manager plugin** ([installation guide](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html))
- **OpenSSH client** (`ssh` command) - for SSH over SSM
- **Python 3.8+**
- **Appropriate IAM role**

### Terminal Apps

The tool automatically detects and uses available terminal emulators:

- **Windows**: Windows Terminal (`wt`), PowerShell, or `cmd`
- **macOS**: Terminal.app
- **Linux**: `gnome-terminal`, `konsole`, `xterm`, or `x-terminal-emulator`


## Usage

Start the CLI: ssm-connect


### Connection Flow

1. **Choose Target Type**:
   - `[1] EC2` - Connect directly to an EC2 instance
   - `[2] RDS` - Forward port to an RDS database via bastion

2. **For EC2 Connections**:
   - Choose connection type:
     - `[1] SSM` - Interactive shell via Session Manager
     - `[2] SSH over SSM` - SSH session with your private key
   - Filter and select target EC2 instance
   - For SSH: Provide private key path and username

3. **For RDS Connections**:
   - **Step 1**: Select EC2 bastion instance (must have SSM access)
   - **Step 2**: Select target RDS database
   - Connect to `localhost:[auto-selected-port]` with your database client

4. **For File Transfer (SCP)**:
   - Select remote instance
   - Choose direction (Upload / Download)
   - Specify local and remote file paths
   - Tool handles the secure copy tunneling


## Troubleshooting

### Command not found
Ensure `aws`, `session-manager-plugin`, and `ssh` are installed and on PATH.

### SSO expired
Refresh your AWS SSO session: aws sso login --profile your-profile

### SSH key errors
Ensure the key exists and has proper permissions

### No terminal found (Linux)
Install a terminal emulator

### RDS connection refused
Ensure:
- The bastion EC2 instance has network connectivity to the RDS
- The bastion is running
- You have the appropriate role


## Uninstall
pip uninstall ssm-connect

## Security

### Static Code Analysis

All pull requests and merges undergo automated [CodeQL](https://codeql.github.com/) security analysis to detect:
- Security vulnerabilities
- Code quality issues
- Potential bugs
- Unsafe coding patterns

### Reporting Security Issues

If you discover a security vulnerability, please report it privately via GitHub's Security Advisory feature rather than opening a public issue.


## Contributing

Issues and pull requests are welcome. Please keep changes focused and include brief notes if behavior changes.


## License

Apache License 2.0. See LICENSE for details.