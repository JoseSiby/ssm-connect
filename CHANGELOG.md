# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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