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
import json
import argparse
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from enum import Enum
from botocore.exceptions import BotoCoreError, ClientError
import boto3

from .inventory import (
    make_boto3_session,
    list_running_instances,
    list_rds_instances,
    filter_instances_by_keywords
)
from .gateway import (
    validate_key_permissions,
    start_ssm_session,
    start_ssh_session,
    start_port_forwarding_to_rds,
    perform_file_transfer,
    start_ssh_proxyjump_session,
    start_port_forwarding_session,
    find_available_local_port
)

CONFIG_DIR = Path.home() / ".ssm-connect"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(config: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)
    if os.name != 'nt':
        os.chmod(CONFIG_FILE, 0o600)


def load_ssh_defaults() -> Optional[dict]:
    config = load_config()
    return config.get('ssh')


def save_ssh_defaults(key_path: str, username: str):
    config = load_config()
    config['ssh'] = {'key_path': key_path, 'username': username}
    save_config(config)


def load_favorites() -> Dict[str, dict]:
    config = load_config()
    return config.get('favorites', {})


def save_favorite(name: str, details: dict):
    config = load_config()
    if 'favorites' not in config:
        config['favorites'] = {}
    config['favorites'][name] = details
    save_config(config)


def reset_ssh_defaults():
    config = load_config()
    if 'ssh' in config:
        del config['ssh']
        save_config(config)
        print("✓ SSH config reset.")
    else:
        print("No saved SSH config found.")

class TargetType(Enum):
    EC2 = "ec2"
    RDS = "rds"
    FILE_TRANSFER = "file_transfer"
    FAVORITES = "favorites"


class ConnectionType(Enum):
    SSM = "ssm"
    SSH = "ssh"
    SSH_PROXY = "ssh_proxy"
    PORT_FORWARDING = "port_forwarding"

def choose_target_type() -> Optional[TargetType]:
    print("\nWhat do you want to connect to?")
    print("[1] EC2")
    print("[2] RDS")
    print("[3] File Transfer (SCP)")
    print("[4] Favorites")
    try:
        choice = input("\nEnter your choice (1-4): ").strip()
        if choice == "1":
            return TargetType.EC2
        elif choice == "2":
            return TargetType.RDS
        elif choice == "3":
            return TargetType.FILE_TRANSFER
        elif choice == "4":
            return TargetType.FAVORITES
        else:
            return None
    except (ValueError, KeyboardInterrupt):
        return None


def choose_ec2_connection_type() -> Optional[ConnectionType]:
    print("\nSelect Connection Type:")
    print("[1] SSM")
    print("[2] SSH over SSM")
    print("[3] SSH ProxyJump (Connect to remote host via this instance)")
    print("[4] Port Forwarding (Forward local port to remote instance)")
    try:
        choice = input("\nEnter your choice (1, 2, 3, or 4): ").strip()
        if choice == "1":
            return ConnectionType.SSM
        elif choice == "2":
            return ConnectionType.SSH
        elif choice == "3":
            return ConnectionType.SSH_PROXY
        elif choice == "4":
            return ConnectionType.PORT_FORWARDING
        else:
            return None
    except (ValueError, KeyboardInterrupt):
        return None


def prompt_for_keywords() -> Optional[List[str]]:
    raw = input("\n(Optional) Enter instance name/id (fast), or press ENTER to list all (slow): ").strip()
    if not raw:
        return None
    return [s.lower() for s in raw.replace(',', ' ').split() if s.strip()]


def choose_instance(instances: List[Dict[str, str]], purpose: str = "connect to") -> Optional[str]:
    if not instances:
        return None
    print(f"\nSelect an EC2 Instance to {purpose}:")
    for idx, inst in enumerate(instances, start=1):
        print(f"[{idx}] {inst['Name']} ({inst['InstanceId']})")
    print("[0] Exit / Refine Search")
    try:
        raw_choice = input("\nEnter the number of the instance: ").strip()
        if raw_choice == "0":
            return "RETRY"
        choice_idx = int(raw_choice) - 1
        if 0 <= choice_idx < len(instances):
            return instances[choice_idx]["InstanceId"]
    except (ValueError, IndexError):
        return None
    return None


def choose_rds_instance(instances: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    if not instances:
        print("No available RDS instances found.")
        return None
    print("\n=== Step 2: Select target RDS instance ===")
    for idx, db in enumerate(instances, start=1):
        print(f"[{idx}] {db['DBInstanceIdentifier']} ({db['Engine']})")
    print("[0] Exit")
    try:
        choice = input("\nEnter the number of the RDS instance: ").strip()
        if choice == "0":
            return None
        choice_idx = int(choice) - 1
        if 0 <= choice_idx < len(instances):
            return instances[choice_idx]
    except (ValueError, IndexError):
        return None
    return None



def choose_file_transfer_direction() -> Optional[str]:
    print("\nSelect Transfer Direction:")
    print("[1] Upload (Local -> Remote)")
    print("[2] Download (Remote -> Local)")
    try:
        choice = input("\nEnter your choice (1 or 2): ").strip()
        if choice == "1":
            return "upload"
        elif choice == "2":
            return "download"
        else:
            return None
    except (ValueError, KeyboardInterrupt):
        return None


def prompt_for_scp_paths(direction: str) -> Optional[Tuple[str, str]]:
    if direction == "upload":
        local_prompt = "Enter local file path to upload: "
        remote_prompt = "Enter remote destination path (directory/ or full filename): "
    else:
        remote_prompt = "Enter remote file path to download: "
        local_prompt = "Enter local destination path: "
        
    local_path = input(f"\n{local_prompt}").strip().strip("'\"")
    if not local_path:
        print("Error: Local path cannot be empty.")
        return None
        
    remote_path = input(f"{remote_prompt}").strip().strip("'\"")
    if not remote_path:
        print("Error: Remote path cannot be empty.")
        return None
        
    return local_path, remote_path


def prompt_for_ssh_details() -> Optional[Tuple[str, Path]]:
    saved = load_ssh_defaults()
    if saved:
        key_path_str = saved['key_path']
        username = saved['username']
        key_path = Path(key_path_str).expanduser()
        if key_path.is_file():
            print("\nUse saved SSH settings?")
            print(f"  Key: {key_path_str}")
            print(f"  User: {username}")
            use_saved = input("[Y/n]: ").strip().lower()
            if use_saved in ('', 'y', 'yes'):
                return username, key_path
            print("\nEnter new SSH details:")
        else:
            print(f"\nWarning: Saved key not found at {key_path_str}. Please enter new SSH details:")

    key_path_str = input("\nEnter the path to your private key file: ").strip()
    if not key_path_str:
        print("Error: Private key path cannot be empty.", file=sys.stderr)
        return None

    key_path = Path(key_path_str.strip('"\'').strip()).expanduser()
    if not key_path.is_file():
        print(f"Error: Private key file not found at '{key_path}'", file=sys.stderr)
        return None

    if not validate_key_permissions(key_path):
        response = input("Continue anyway? (y/N): ").strip().lower()
        if response != 'y':
            return None

    username = input("Enter SSH username (e.g., ec2-user, ubuntu): ").strip()
    if not username:
        print("Error: Username cannot be empty.", file=sys.stderr)
        return None

    save = input("\nSave these settings for next time? [Y/n]: ").strip().lower()
    if save not in ('n', 'no'):
        try:
            save_ssh_defaults(str(key_path), username)
            print("✓ Settings saved")
        except Exception as e:
            print(f"Warning: Could not save settings: {e}", file=sys.stderr)

    return username, key_path


def select_ec2_instance(session: boto3.Session, purpose: str = "connect to") -> Optional[str]:
    instance_id = None
    
    while not instance_id:
        keywords = prompt_for_keywords()
        
        try:
            print("Fetching instances...", end="\r", flush=True)
            instances = list_running_instances(session, keywords)
            print("                     ", end="\r", flush=True)
        except Exception as e:
             print(f"\nError fetching instances: {e}", file=sys.stderr)
             return None

        filtered_instances = filter_instances_by_keywords(instances, keywords)
        
        if not filtered_instances:
            print("No instances found matching your keywords. Please try again.")
            continue
        
        selection = choose_instance(filtered_instances, purpose)
        if selection is None:
            print("Invalid selection. Please try again.", file=sys.stderr)
            continue
        elif selection == "RETRY":
            continue
        else:
            instance_id = selection
    
    return instance_id


def ask_continue_or_exit():
    choice = input("\nWould you like to open another session? [Y/n]: ").strip().lower()
    return choice != 'n' and choice != 'no'


def print_goodbye():
    try:
        print("Namaste! / നമസ്കാരം!")
    except UnicodeEncodeError:
        print("Namaste! / Namaskaram!")


def prompt_to_save_favorite(fav_data: dict, session: boto3.Session):
    if 'instance_id' in fav_data:
        try:

             instances = list_running_instances(session, [fav_data['instance_id']])
             if instances:
                 name = instances[0]['Name']
                 if name and name != "Unnamed":
                     fav_data['instance_name'] = name
        except Exception:
            pass

    save = input("\nSave this connection as a favorite? [y/N]: ").strip().lower()
    if save != 'y':
        return
    
    while True:
        name = input("Enter a name for this favorite (e.g. 'prod-db', 'bastion'): ").strip()
        if not name:
            print("Name cannot be empty.")
            continue
        
        existing = load_favorites()
        if name in existing:
             overwrite = input(f"Favorite '{name}' already exists. Overwrite? [y/N]: ").strip().lower()
             if overwrite != 'y':
                 continue
        
        save_favorite(name, fav_data)
        print(f"✓ Saved as '{name}'")
        break


def select_and_manage_favorites(session: boto3.Session) -> bool:
    favorites = load_favorites()
    if not favorites:
        print("No favorites saved yet.")
        return False

    print("\n=== Saved Favorites ===")
    fav_names = list(favorites.keys())
    for idx, name in enumerate(fav_names, start=1):
        fav = favorites[name]
        print(f"[{idx}] {name} ({fav['type']})")
    print("[0] Back")
    print("[d] Delete a favorite")
    
    choice = input("\nEnter choice: ").strip()
    if choice == '0':
        return False
    elif choice.lower() == 'd':
        del_choice = input("Enter number to delete: ").strip()
        try:
             del_idx = int(del_choice) - 1
             if 0 <= del_idx < len(fav_names):
                to_delete = fav_names[del_idx]
                confirm = input(f"Delete favorite '{to_delete}'? [y/N]: ").strip().lower()
                if confirm == 'y':
                    config = load_config()
                    if 'favorites' in config and to_delete in config['favorites']:
                        del config['favorites'][to_delete]
                        save_config(config)
                        print("✓ Deleted.")
        except ValueError:
             pass
        return False
        
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(fav_names):
            name = fav_names[idx]
            execute_favorite(name, favorites[name], session)
            return True
    except ValueError:
        pass
    
    return False



def interactive_file_transfer(instance_id: str, username: str, key_path: Path, session: boto3.Session, document_name: Optional[str] = None):
    while True:
        direction = choose_file_transfer_direction()
        if not direction:
            print("Invalid direction.")
            break

        paths = prompt_for_scp_paths(direction)
        if not paths:
            break
        local_path, remote_path = paths

        recursive = False
        if direction == "upload":
            expanded_local_path = os.path.expanduser(local_path)
            if os.path.isdir(expanded_local_path):
                recursive = True
                print("\nDetected directory upload. Recursive mode enabled.")
        
        elif direction == "download":
                is_recursive = input("Is the remote path a directory? [y/N]: ").strip().lower()
                if is_recursive == 'y':
                    recursive = True

        perform_file_transfer(
            instance_id, username, key_path, session,
            local_path, remote_path, direction, recursive,
            document_name=document_name or "AWS-StartSSHSession"
        )
        
        again = input("\nTransfer another file with this instance? [Y/n]: ").strip().lower()
        if again in ('n', 'no'):
            break


def execute_favorite(name: str, fav: dict, session: boto3.Session, interactive_mode: bool = True, override_document_name: Optional[str] = None):
    print(f"Connecting to favorite '{name}'...")
    
    doc_name = override_document_name or fav.get('document_name')
    
    if 'instance_name' in fav:
        target_name = fav['instance_name']
        try:
            candidates = list_running_instances(session, [target_name])
            
            resolved_id = None
            if len(candidates) == 1:
                resolved_id = candidates[0]['InstanceId']
            elif len(candidates) > 1:
                print(f"Multiple instances found matching '{target_name}'. Please select:")
                resolved_id = choose_instance(candidates, "resolve favorite")
            
            if resolved_id:
                fav['instance_id'] = resolved_id
                if 'bastion_id' in fav:
                     pass 
            else:
                print(f"Warning: Could not resolve instance named '{target_name}'. Using saved ID.")
        except Exception as e:
            print(f"Warning: Resolution failed ({e}). Using saved ID.")

    
    target_type = fav.get('type')
    
    if target_type == TargetType.EC2.value:
        conn_type = fav.get('connection_type')
        if conn_type == ConnectionType.SSM.value:
            start_ssm_session(fav['instance_id'], session, interactive_mode=interactive_mode, document_name=doc_name)
        
        elif conn_type == ConnectionType.SSH.value:
            kwargs = {}
            if doc_name:
                kwargs['document_name'] = doc_name
            start_ssh_session(
                fav['instance_id'], 
                fav['username'], 
                Path(fav['key_path']), 
                session,
                interactive_mode=interactive_mode,
                **kwargs
            )

        elif conn_type == ConnectionType.SSH_PROXY.value:
             bastion_id = fav['bastion_id']
             if 'instance_name' in fav and fav['instance_id'] == bastion_id:
                  bastion_id = fav['instance_id']

             kwargs = {}
             if doc_name:
                 kwargs['document_name'] = doc_name
             start_ssh_proxyjump_session(
                 bastion_id, fav['bastion_user'], Path(fav['bastion_key']),
                 fav['target_host'], fav['target_user'], Path(fav['target_key']),
                 session,
                 interactive_mode=interactive_mode,
                 **kwargs
             )

        elif conn_type == ConnectionType.PORT_FORWARDING.value:
            kwargs = {}
            if doc_name:
                kwargs['document_name'] = doc_name
            start_port_forwarding_session(
                fav['instance_id'],
                fav['remote_port'],
                fav['local_port'],
                session,
                interactive_mode=interactive_mode,
                **kwargs
            )

    elif target_type == TargetType.RDS.value:
        bastion_id = fav['bastion_id']
        
        if 'instance_name' in fav and 'instance_id' in fav:
             bastion_id = fav['instance_id']

        rds_info = {
            "DBInstanceIdentifier": fav['db_identifier'],
            "Endpoint": fav['endpoint_address'],
            "Port": fav['port']
        }
        kwargs = {}
        if doc_name:
            kwargs['document_name'] = doc_name
        start_port_forwarding_to_rds(bastion_id, rds_info, session, interactive_mode=interactive_mode, **kwargs)
        
    elif target_type == TargetType.FILE_TRANSFER.value:
        interactive_file_transfer(
            fav['instance_id'],
            fav['username'],
            Path(fav['key_path']),
            session,
            document_name = doc_name
        )
    else:
        print(f"Unknown favorite type: {target_type}", file=sys.stderr)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(description="SSM Connect - AWS SSM/SSH Client")
    parser.add_argument("--reset-config", action="store_true", help="Reset saved SSH configuration")
    parser.add_argument("-d", "--document-name", help="Custom SSM Document name (overrides default)")
    parser.add_argument("-f", "--favorite", help="Connect immediately to a saved favorite alias")
    args = parser.parse_args()

    if args.reset_config:
        reset_ssh_defaults()
        sys.exit(0)
    
    try:
        session = make_boto3_session()
    except (BotoCoreError, ClientError) as e:
        print(f"AWS API Error: Failed to list instances: {e}", file=sys.stderr)
        print("\nTip: Ensure your AWS credentials are configured correctly.", file=sys.stderr)
        sys.exit(1)

    if args.favorite:
        favorites = load_favorites()
        fav = favorites.get(args.favorite)
        if not fav:
            print(f"Error: Favorite '{args.favorite}' not found.", file=sys.stderr)
            sys.exit(1)
        
        
        print(f"Region: {session.region_name}")
        execute_favorite(args.favorite, fav, session, interactive_mode=False, override_document_name=args.document_name)
        sys.exit(0)

    

    
    print(f"Region: {session.region_name}")
    
    try:
        while True:
            target_type = choose_target_type()
            if not target_type:
                print("Invalid selection. Exiting.", file=sys.stderr)
                sys.exit(1)
            
            if target_type == TargetType.EC2:
                connection_type = choose_ec2_connection_type()
                if not connection_type:
                    print("Invalid connection type.")
                    continue
                
                if connection_type == ConnectionType.SSM:
                    instance_id = select_ec2_instance(session, "connect to")
                    if instance_id:
                        fav_data = {
                            'type': TargetType.EC2.value,
                            'connection_type': ConnectionType.SSM.value,
                            'instance_id': instance_id
                        }
                        if args.document_name:
                            fav_data['document_name'] = args.document_name
                        
                        prompt_to_save_favorite(fav_data, session)
                        start_ssm_session(instance_id, session, document_name=args.document_name)
                
                elif connection_type == ConnectionType.SSH:
                    instance_id = select_ec2_instance(session, "connect to")
                    if not instance_id:
                        print("No instance selected.")
                        continue
                    
                    ssh_details = prompt_for_ssh_details()
                    if not ssh_details:
                        print("Failed to get SSH details.")
                        continue
                    username, key_path = ssh_details
                    
                    prompt_to_save_favorite({
                        'type': TargetType.EC2.value,
                        'connection_type': ConnectionType.SSH.value,
                        'instance_id': instance_id,
                        'username': username,
                        'key_path': str(key_path),
                        'document_name': args.document_name
                    } if args.document_name else {
                        'type': TargetType.EC2.value,
                        'connection_type': ConnectionType.SSH.value,
                        'instance_id': instance_id,
                        'username': username,
                        'key_path': str(key_path)
                    }, session)

                    kwargs = {}
                    if args.document_name:
                        kwargs['document_name'] = args.document_name
                    start_ssh_session(instance_id, username, key_path, session, **kwargs)

                elif connection_type == ConnectionType.SSH_PROXY:
                    bastion_id = select_ec2_instance(session, "use as Jump Host")
                    if not bastion_id:
                        print("No instance selected.")
                        continue
                    
                    print("\n--- Bastion SSH Details ---")
                    bastion_details = prompt_for_ssh_details()
                    if not bastion_details:
                        print("Failed to get Bastion SSH details.")
                        continue
                    bastion_user, bastion_key = bastion_details
                    
                    print("\n--- Target Host Details ---")
                    target_host = input("Enter Target Host (IP or DNS): ").strip()
                    if not target_host:
                        print("Error: Target host cannot be empty.", file=sys.stderr)
                        continue

                    target_user_input = input(f"Enter Target Username [default: {bastion_user}]: ").strip()
                    target_user = target_user_input if target_user_input else bastion_user
                    
                    target_key_input = input(f"Enter Target Key Path [default: {bastion_key}]: ").strip()
                    if target_key_input:
                         target_key = Path(target_key_input.strip('"\'')).expanduser()
                         if not target_key.is_file():
                             print(f"Error: Target key file not found at '{target_key}'", file=sys.stderr)
                             continue
                    else:
                        target_key = bastion_key

                    if not validate_key_permissions(target_key):
                        response = input("Continue anyway? (y/N): ").strip().lower()
                        if response != 'y':
                            continue
                    
                    fav_data = {
                        'type': TargetType.EC2.value,
                        'connection_type': ConnectionType.SSH_PROXY.value,
                        'bastion_id': bastion_id,
                        'bastion_user': bastion_user,
                        'bastion_key': str(bastion_key),
                        'target_host': target_host,
                        'target_user': target_user,
                        'target_key': str(target_key),
                        'instance_id': bastion_id
                    }
                    if args.document_name:
                        fav_data['document_name'] = args.document_name
                        
                    prompt_to_save_favorite(fav_data, session)

                    kwargs = {}
                    if args.document_name:
                        kwargs['document_name'] = args.document_name

                    start_ssh_proxyjump_session(
                        bastion_id, bastion_user, bastion_key,
                        target_host, target_user, target_key,
                        session,
                        **kwargs
                    )

                elif connection_type == ConnectionType.PORT_FORWARDING:
                    instance_id = select_ec2_instance(session, "forward ports to")
                    if not instance_id:
                        print("No instance selected.")
                        continue
                    
                    try:
                        remote_port_str = input("Enter Remote Port (e.g. 80, 8080): ").strip()
                        if not remote_port_str:
                             print("Remote port is required.")
                             continue
                        remote_port = int(remote_port_str)
                        
                        local_port_str = input(f"Enter Local Port [default: auto]: ").strip()
                        if local_port_str:
                             local_port = int(local_port_str)
                        else:
                             local_port = find_available_local_port()
                    
                    except ValueError:
                         print("Invalid port number.")
                         continue

                    fav_data = {
                        'type': TargetType.EC2.value,
                        'connection_type': ConnectionType.PORT_FORWARDING.value,
                        'instance_id': instance_id,
                        'remote_port': remote_port,
                        'local_port': local_port
                    }
                    if args.document_name:
                        fav_data['document_name'] = args.document_name

                    prompt_to_save_favorite(fav_data, session)
                    
                    kwargs = {}
                    if args.document_name:
                        kwargs['document_name'] = args.document_name
                    start_port_forwarding_session(instance_id, remote_port, local_port, session, **kwargs)

            elif target_type == TargetType.FAVORITES:
                if not select_and_manage_favorites(session):
                    continue
            
            elif target_type == TargetType.RDS:
                print("\n=== Step 1: Select the EC2 instance acting as a bastion ===")
                bastion_id = select_ec2_instance(session, "use as bastion")
                if not bastion_id:
                    print("No bastion instance selected.")
                    continue
                
                try:
                    rds_instances = list_rds_instances(session)
                    if not rds_instances:
                        print("No available RDS instances found in this region.")
                        continue
                    
                    selected_rds = choose_rds_instance(rds_instances)
                    if not selected_rds:
                        print("No RDS instance selected.")
                        continue
                     
                    fav_data = {
                        'type': TargetType.RDS.value,
                        'bastion_id': bastion_id,
                        'db_identifier': selected_rds['DBInstanceIdentifier'],
                        'endpoint_address': selected_rds['Endpoint'],
                        'port': selected_rds['Port'],
                        'instance_id': bastion_id
                    }
                    if args.document_name:
                         fav_data['document_name'] = args.document_name
                    
                    prompt_to_save_favorite(fav_data, session)

                    kwargs = {}
                    if args.document_name:
                         kwargs['document_name'] = args.document_name
                    start_port_forwarding_to_rds(bastion_id, selected_rds, session, **kwargs)
                except Exception as e:
                    print(f"Error setting up RDS port forwarding: {e}", file=sys.stderr)
                    continue

            elif target_type == TargetType.FILE_TRANSFER:
                instance_id = select_ec2_instance(session, "transfer files with")
                if not instance_id:
                    print("No instance selected.")
                    continue

                ssh_details = prompt_for_ssh_details()
                if not ssh_details:
                    print("Failed to get SSH details.")
                    continue
                username, key_path = ssh_details
                
                fav_data = {
                    'type': TargetType.FILE_TRANSFER.value,
                    'instance_id': instance_id,
                    'username': username,
                    'key_path': str(key_path)
                }
                if args.document_name:
                     fav_data['document_name'] = args.document_name

                prompt_to_save_favorite(fav_data, session)

                interactive_file_transfer(instance_id, username, key_path, session, document_name=args.document_name)
            
            if not ask_continue_or_exit():
                break
    except KeyboardInterrupt:
        print("\n\nYou've cancelled the operation.")
        sys.exit(0)

    
    print_goodbye()


if __name__ == "__main__":
    main()
