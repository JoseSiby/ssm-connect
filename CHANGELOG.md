# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.6.0]
### Added
- **Session Window Labels**: Each session now sets its terminal window/tab title to identify the target (e.g. `SSM - web-prod-01`, `RDS - prod-db (local 54321)`), so parallel sessions are easy to tell apart in the taskbar and tab strip. Titles use the OSC escape sequence on Linux/macOS and native `wt --title`/`title` on Windows.
- **Session Banner**: A header is printed inside each new session window showing the connection type, target (Name and Instance ID), region, and other relevant details (ports, bastion, endpoint), giving a durable record that survives even if the title is overwritten by a remote shell.

### Changed
- Instance Name is now threaded through to all connection launchers so labels show the human-readable Name alongside the Instance ID.
- SSH ProxyJump target selection resolves the Private IP from the already-fetched instance list instead of issuing a second AWS API call.

## [1.5.3]
### Fixed
- **RDS Favorites Local Port**: Local port is now persisted when saving an RDS session as a favorite, ensuring the same port is reused on subsequent connections.

## [1.5.1]
### Added
- **Instance ID Resolution**: Automatically resolves Instance IDs (`i-xxxx`) to Private IPs for SSH Proxy Jump targets.
- **Interactive Target Selection**: Select SSH Proxy Jump target host directly from the list of running instances.

## [1.5.0]
### Added
- **Custom SSM Document Support**: Specify a custom SSM document name via `--document-name` (or `-d`) CLI argument.
- **Persistent Document Settings**: Custom document names are saved with favorites and can be overridden via CLI.

## [1.4.1]
### Added
- **Module Execution**: Run the tool via `python -m ssm_connect`.

## [1.4.0]
### Added
- **Favorites & Aliases**: Save frequently used connections for instant access.
- **CLI Shortcuts**: Connect instantly using `ssm-connect -f <alias>`.
- **Interactive Management**: New "Favorites" menu to manage and delete aliases.

## [1.3.1]
### Fixed
- Graceful exit on KeyboardInterrupt.

## [1.3.0]
### Added
- **SSH ProxyJump Support**: New dedicated mode to start an SSH session to a target host *via* an SSM-managed bastion host (`ssh -J bastion target`).
- **SSH Agent Integration**: Detects and uses the correct `ssh-agent` environment to effectively eliminate redundant passphrase prompts.
- **Security Scanning**: Added Gitleaks and Pip-Audit to CI pipeline.
- **Issue Templates**: Updated templates with project-specific fields.


## [1.2.1] - 2025-12-08
### Changed
- Promoted Project Status to "Production/Stable" in PyPI classifiers.
- Added comprehensive AWS and cloud-related keywords to `pyproject.toml` for better discoverability.

## [1.2.0]
### Added
- **File Transfer (SCP)**: New main menu option to securely upload/download files to/from instances
- Interactive prompts for file transfer direction and paths
- Exports `perform_file_transfer` in public API

## [1.1.0]

### Added
- SSH credential persistence: SSH key path and username are now auto-saved to `~/.ssm-connect/config.json` for convenient reuse
- Configuration prompt: one can opt-in to save SSH settings on first use
- `--reset-config` command-line flag to clear saved SSH credentials
- Support for reusing saved credentials with single-keystroke acceptance
- Automatic validation of saved SSH key paths before reuse

### Changed
- Refactored into modular structure.
- Introduced clearer prompts for SSH credential management

### Fixed
- Socket binding now explicitly uses localhost (127.0.0.1) instead of all network interfaces (addresses CodeQL security warning)

### Security
- Only SSH key paths and usernames stored in config (never the actual keys)

## [1.0.5]

### Fixed
- Security: Bind port discovery socket to localhost only (fixes CodeQL alert)

## [1.0.4]

### Added
- RDS port forwarding support via SSM using EC2 bastion hosts
- Two-step workflow for RDS connections (bastion selection → RDS selection)
- Automatic local port selection for RDS forwarding

### Changed
- Enhanced user flow with target-type selection (EC2 vs RDS)
- Improved terminal output formatting for multi-step operations

### Fixed
- Better error handling for RDS connection failures
- Validation for bastion instance connectivity

## [1.0.0]

### Added
- Initial commit
- SSM Session Manager connections to EC2 instances
- SSH over SSM connections with private key authentication
- Keyword-based instance filtering (searches Name, InstanceId, and all tags)
- Multi-session support: each connection opens in a new terminal window
- Automatic AWS credential inheritance from environment
- SSH key permission validation
- Optional strict SSH host key checking

### Security
- Secure AWS credential handling via existing AWS CLI/SDK configuration
- SSH private key validation and permission checks

## Project Links

- [Homepage](https://github.com/JoseSiby/ssm-connect)
- [PyPI Package](https://pypi.org/project/ssm-connect/)
- [Issue Tracker](https://github.com/JoseSiby/ssm-connect/issues)