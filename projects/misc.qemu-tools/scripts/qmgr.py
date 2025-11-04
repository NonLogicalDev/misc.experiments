#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = [
#   "click>=8.1.0",
#   "pydantic>=2.0.0",
#   "pyyaml>=6.0.0",
#   "jinja2>=3.1.0",
# ]
# ///

"""
QEMU Manager - Python port of qmgr.sh
Manages QEMU VMs with cloud-init configuration
"""

import hashlib
import json
import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

import click
import yaml
from jinja2 import Template
from pydantic import BaseModel, Field


# ============================================================================
# Pydantic Models
# ============================================================================

class VMSystemConfig(BaseModel):
    """VM system configuration"""
    cmd: str = Field(..., description="QEMU command (e.g., qemu-system-x86_64)")
    machine: str = Field(..., description="Machine type (e.g., q35)")
    stdout_mode: Optional[Literal["serial", "monitor", "none"]] = Field(
        default=None,
        description="Stdout output mode: serial (serial+monitor), monitor (monitor only), none (no stdout)"
    )
    display: Optional[Literal["default", "none", "sdl", "gtk", "vnc", "cocoa"]] = Field(
        default=None,
        description="Display backend: default (QEMU auto), none (headless), sdl, gtk, vnc, cocoa"
    )
    vga: Optional[Literal["std", "virtio", "qxl", "cirrus"]] = Field(
        default=None,
        description="VGA device: std (VGA), virtio (virtio-vga), qxl (qxl-vga), cirrus (cirrus-vga), null (no VGA)"
    )


class VMImageConfig(BaseModel):
    """VM image configuration"""
    name: str = Field(..., description="Base image name")
    format: str = Field(..., description="Image format (qcow2, raw, etc.)")
    url: Optional[str] = Field(None, description="Download URL for base image")
    expand_size: str = Field(..., description="Size to expand image to (e.g., 15G)")


class VMIdConfig(BaseModel):
    """VM identification configuration"""
    hostname: str = Field(..., description="VM hostname")
    hostname_fqdn: str = Field(..., description="VM FQDN")
    smbios: str = Field(..., description="SMBIOS UUID")
    instance: str = Field(..., description="Cloud-init instance ID")


class VMResourcesConfig(BaseModel):
    """VM resource configuration"""
    memory: str = Field(..., description="RAM allocation (e.g., 2G)")
    smp: Union[int, str] = Field(..., description="Number of CPUs")


class VMAdminConfig(BaseModel):
    """VM admin user configuration"""
    username: str = Field(..., description="Admin username")
    passwd: str = Field(..., description="Password hash")
    ssh_key: str = Field(..., description="SSH public key")


class VMNetUserConfig(BaseModel):
    """VM user-mode networking configuration"""
    ssh_port: Optional[int] = Field(None, description="SSH port mapping")
    dhcp_start_address_v4: str = Field(..., description="DHCP start address")
    dhcp_net_address_v4: str = Field(..., description="DHCP network address")
    hostfwd: List[str] = Field(default_factory=list, description="Port forwarding rules")


class VMNetVmnetConfig(BaseModel):
    """VM vmnet networking configuration"""
    dhcp_start_address_v4: str = Field(..., description="DHCP start address")
    dhcp_end_address_v4: str = Field(..., description="DHCP end address")
    dhcp_subnet_mask_v4: str = Field(..., description="DHCP subnet mask")


class VMNetConfig(BaseModel):
    """VM network configuration"""
    mac: str = Field(..., description="MAC address")
    primary_interface: str = Field(..., description="Primary network interface")
    primary_address_v4: str = Field(..., description="Primary IPv4 address")
    primary_gateway_v4: str = Field(..., description="Primary IPv4 gateway")
    dns_server_1: str = Field(..., description="Primary DNS server")
    dns_server_2: Optional[str] = Field(None, description="Secondary DNS server")
    dns_search: str = Field(..., description="DNS search domain")
    mode: Dict[str, str] = Field(..., description="Network mode per OS")
    user: Optional[VMNetUserConfig] = Field(None, description="User-mode network config")
    vmnet: Optional[VMNetVmnetConfig] = Field(None, description="Vmnet network config")


class VMVirtioShare(BaseModel):
    """Virtio 9p share configuration"""
    tag: str = Field(..., description="Share tag")
    path: str = Field(..., description="Host path to share")
    kind: str = Field(default="9p", description="Share type")


class VMCloudInitConfig(BaseModel):
    """Cloud-init configuration"""
    meta: Optional[str] = Field(None, description="meta-data content")
    user: Optional[str] = Field(None, description="user-data content")
    net: Optional[str] = Field(None, description="network-config content")


# ============================================================================
# Params Models (New Schema)
# ============================================================================

class ParamsHostname(BaseModel):
    """Hostname configuration for params"""
    short: str = Field(..., description="Short hostname")
    fqdn: str = Field(..., description="Fully qualified domain name")


class ParamsUser(BaseModel):
    """User configuration for params"""
    name: str = Field(..., description="Username")
    gecos: Optional[str] = Field(None, description="User description")
    groups: List[str] = Field(default_factory=list, description="User groups")
    shell: str = Field(default="/bin/bash", description="User shell")
    sudo: Optional[str] = Field(None, description="Sudo privileges")
    password_hash: str = Field(..., description="Password hash")
    ssh_authorized_keys: List[str] = Field(default_factory=list, description="SSH authorized keys")


class ParamsNetworkIPv4(BaseModel):
    """IPv4 configuration for network_primary"""
    address: str = Field(..., description="IPv4 address with CIDR (e.g., 192.168.15.2/24)")
    gateway: str = Field(..., description="IPv4 gateway")


class ParamsNetworkDNS(BaseModel):
    """DNS configuration for network_primary"""
    servers: List[str] = Field(..., description="DNS servers")
    search: str = Field(..., description="DNS search domain")


class ParamsNetworkDHCP(BaseModel):
    """DHCP configuration for network_primary"""
    net: str = Field(..., description="DHCP network address with CIDR (e.g., 192.168.15.0/24)")
    start: str = Field(..., description="DHCP start address")


class ParamsNetworkPrimary(BaseModel):
    """Primary network configuration for cloud-init"""
    interface: str = Field(..., description="Primary network interface name")
    mac: str = Field(..., description="MAC address")
    ipv4: ParamsNetworkIPv4 = Field(..., description="IPv4 configuration")
    dns: ParamsNetworkDNS = Field(..., description="DNS configuration")
    dhcp: Optional[ParamsNetworkDHCP] = Field(None, description="DHCP configuration")


class Params(BaseModel):
    """Template parameters section"""
    hostname: ParamsHostname = Field(..., description="Hostname configuration")
    users: List[ParamsUser] = Field(..., description="User configurations")
    network_primary: ParamsNetworkPrimary = Field(..., description="Primary network configuration")


# ============================================================================
# Network Models (New Schema)
# ============================================================================

class NetworkInterface(BaseModel):
    """Network interface definition (id/type/params pattern like disks)"""
    id: str = Field(..., description="Network device ID (net0, net1, etc.)")
    type: Literal["user", "tap", "bridge", "vmnet-shared", "vmnet-bridged", "socket"] = Field(
        ..., description="Interface type"
    )
    params: Dict[str, Any] = Field(..., description="Type-specific parameters")


class NetworkProfile(BaseModel):
    """Network profile with interfaces"""
    interfaces: List[NetworkInterface] = Field(..., description="Network interfaces")


class NetworkConfig(BaseModel):
    """Multi-profile network configuration"""
    default: Dict[str, str] = Field(..., description="OS -> profile_name mapping")
    profiles: Dict[str, NetworkProfile] = Field(..., description="Named profiles")


# ============================================================================
# Identity Model (New Schema)
# ============================================================================

class VMIdentity(BaseModel):
    """VM identity configuration"""
    smbios: str = Field(..., description="SMBIOS UUID")
    instance_id: str = Field(..., description="Cloud-init instance ID")


# ============================================================================
# Disk Models
# ============================================================================

class DiskImageInit(BaseModel):
    """Image initialization configuration for image-type disks"""
    url: str = Field(..., description="Download URL for base image")
    expand_size: bool = Field(True, description="Whether to expand disk after creation")
    size: Optional[str] = Field(None, description="Target size after expansion (e.g., 15G)")


class DiskRawInit(BaseModel):
    """Raw disk initialization configuration"""
    create: bool = Field(True, description="Create disk if it doesn't exist")
    size: Optional[str] = Field(None, description="Disk size (e.g., 10G) - required if create=true")


class DiskParams(BaseModel):
    """Disk parameters for QEMU -drive and -device options"""
    file: str = Field(..., description="Disk filename (relative to vm/disks/)")
    format: str = Field(..., description="Disk format (qcow2, raw, etc.)")
    media: str = Field(..., description="Media type (disk, cdrom)")
    bus: Optional[str] = Field(None, description="Bus attachment (ahci.0, ide.1, etc.)")


class VMDisk(BaseModel):
    """VM disk configuration with type-specific initialization"""
    id: str = Field(..., description="Disk ID for QEMU (used as device name)")
    type: Literal["image", "cloud-init", "raw"] = Field(..., description="Disk type")
    params: DiskParams = Field(..., description="Disk parameters")
    init: Optional[Union[DiskImageInit, DiskRawInit]] = Field(None, description="Disk initialization config")
    device: Optional[str] = Field("ide-hd", description="Device type (ide-hd, ide-cd, virtio-blk, etc.)")


class VMConfig(BaseModel):
    """Top-level VM configuration (LEGACY - for backward compatibility)"""
    system: VMSystemConfig
    image: Optional[VMImageConfig] = Field(None, description="Legacy image config (deprecated, use disks)")
    disks: List[VMDisk] = Field(default_factory=list, description="Disk configurations")
    id: VMIdConfig
    resources: VMResourcesConfig
    admin: VMAdminConfig
    net: VMNetConfig
    virtio_shares: List[VMVirtioShare] = Field(default_factory=list)
    extra_args: List[Union[str, List[str]]] = Field(default_factory=list)
    cloud_init: Optional[VMCloudInitConfig] = Field(None)


class RootConfig(BaseModel):
    """Root configuration (NEW SCHEMA)"""
    system: VMSystemConfig = Field(..., description="System configuration")
    resources: VMResourcesConfig = Field(..., description="Resource configuration")
    identity: VMIdentity = Field(..., description="Identity configuration")
    disks: List[VMDisk] = Field(default_factory=list, description="Disk configurations")
    virtio_shares: List[VMVirtioShare] = Field(default_factory=list, description="Virtio shares")
    params: Params = Field(..., description="Template parameters")
    network: NetworkConfig = Field(..., description="Network configuration")
    cloud_init: Optional[VMCloudInitConfig] = Field(None, description="Cloud-init configuration")
    extra_args: List[Union[str, List[str]]] = Field(default_factory=list, description="Extra QEMU args")


class Config(BaseModel):
    """Root configuration wrapper (supports both old and new schema)"""
    vm: Optional[VMConfig] = Field(None, description="Legacy VM config (old schema)")

    # New schema fields (optional for backward compatibility)
    system: Optional[VMSystemConfig] = None
    resources: Optional[VMResourcesConfig] = None
    identity: Optional[VMIdentity] = None
    disks: Optional[List[VMDisk]] = None
    virtio_shares: Optional[List[VMVirtioShare]] = None
    params: Optional[Params] = None
    network: Optional[NetworkConfig] = None
    cloud_init: Optional[VMCloudInitConfig] = None
    extra_args: Optional[List[Union[str, List[str]]]] = None

    def is_new_schema(self) -> bool:
        """Check if using new schema (no vm: wrapper)"""
        return self.vm is None and self.system is not None

    def to_root_config(self) -> RootConfig:
        """Convert to RootConfig (new schema)"""
        if self.is_new_schema():
            return RootConfig(
                system=self.system,
                resources=self.resources,
                identity=self.identity,
                disks=self.disks or [],
                virtio_shares=self.virtio_shares or [],
                params=self.params,
                network=self.network,
                cloud_init=self.cloud_init,
                extra_args=self.extra_args or []
            )
        else:
            # Legacy schema - convert to new format
            raise NotImplementedError("Legacy schema auto-migration not yet implemented")


# ============================================================================
# Default Cloud-Init Templates
# ============================================================================

# New schema templates (use params.*)
DEFAULT_USER_DATA_NEW = """#cloud-config
hostname: {{params.hostname.short}}
fqdn: {{params.hostname.fqdn}}
manage_etc_hosts: true

# Locale configuration
locale: en_US.UTF-8

# Install packages
packages:
  - openssh-server
  - locales

# SSH host key generation
ssh_genkeytypes:
  - rsa
  - ecdsa
  - ed25519

# Ensure SSH service is enabled and started
runcmd:
  - systemctl enable ssh
  - systemctl start ssh
  - locale-gen en_US.UTF-8
  - update-locale LANG=en_US.UTF-8

users:
{% for user in params.users %}
  - name: {{user.name}}
{% if user.gecos %}
    gecos: '{{user.gecos}}'
{% endif %}
{% if user.groups %}
    groups: {{user.groups | tojson}}
{% endif %}
    shell: {{user.shell}}
{% if user.sudo %}
    sudo: {{user.sudo}}
{% endif %}
    lock_passwd: false
    passwd: '{{user.password_hash}}'
{% if user.ssh_authorized_keys %}
    ssh_authorized_keys:
{% for key in user.ssh_authorized_keys %}
      - '{{key}}'
{% endfor %}
{% endif %}
{% endfor %}
"""

DEFAULT_META_DATA_NEW = """#cloud-config
dsmode: local
instance-id: '{{identity.instance_id}}'
local-hostname: '{{params.hostname.short}}'
"""

DEFAULT_NETWORK_CONFIG_NEW = """#cloud-config
version: 1
config:
  - type: physical
    name: {{params.network_primary.interface}}
    mac_address: {{params.network_primary.mac}}
    subnets:
      - type: static
        address: {{params.network_primary.ipv4.address}}
        gateway: {{params.network_primary.ipv4.gateway}}
  - type: nameserver
    address:
      {% for server in params.network_primary.dns.servers %}
      - {{server}}
      {% endfor %}
    search:
      - {{params.network_primary.dns.search}}
"""

# Legacy schema templates (use vm.*)
DEFAULT_USER_DATA_LEGACY = """#cloud-config
hostname: '{{vm.id.hostname}}'
fqdn: '{{vm.id.hostname_fqdn}}'
manage_etc_hosts: true

# Locale configuration
locale: en_US.UTF-8

# Install packages
packages:
  - openssh-server
  - locales

# SSH host key generation
ssh_genkeytypes:
  - rsa
  - ecdsa
  - ed25519

# Ensure SSH service is enabled and started
runcmd:
  - systemctl enable ssh
  - systemctl start ssh
  - locale-gen en_US.UTF-8
  - update-locale LANG=en_US.UTF-8

users:
  - name: '{{vm.admin.username}}'
    gecos: 'Admin User'
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: false
    passwd: '{{vm.admin.passwd}}'
    ssh_authorized_keys:
      - '{{vm.admin.ssh_key}}'
"""

DEFAULT_META_DATA_LEGACY = """#cloud-config
dsmode: local
instance-id: '{{vm.id.instance}}'
local-hostname: '{{vm.id.hostname}}'
"""

DEFAULT_NETWORK_CONFIG_LEGACY = """#cloud-config
version: 1
config:
  - type: physical
    name: '{{vm.net.primary_interface}}'
    mac_address: '{{vm.net.mac}}'
    subnets:
      - type: static
        address: '{{vm.net.primary_address_v4}}'
        gateway: '{{vm.net.primary_gateway_v4}}'
  - type: nameserver
    address:
    - '{{vm.net.dns_server_1}}'
    search:
    - '{{vm.net.dns_search}}'
"""


# ============================================================================
# Utilities
# ============================================================================

def get_os_name() -> str:
    """Get normalized OS name"""
    system = platform.system()
    if system == "Darwin":
        return "macos"
    elif system == "Linux":
        return "linux"
    else:
        raise RuntimeError(f"Unsupported OS: {system}")


def print_header(msg: str):
    """Print colored header message"""
    click.secho(msg, fg="yellow", bold=True)


def print_text(msg: str):
    """Print colored text message"""
    click.secho(msg, fg="yellow")


def print_error(msg: str):
    """Print error message and exit"""
    click.secho(f"ERROR: {msg}", fg="red", bold=True, err=True)
    sys.exit(1)


def get_ssh_public_key() -> str:
    """Find and read SSH public key"""
    home = Path.home()
    for key_file in [".ssh/id_rsa.pub", ".ssh/id_ed25519.pub", ".ssh/id_ecdsa.pub"]:
        key_path = home / key_file
        if key_path.exists():
            return key_path.read_text().strip()
    print_text("    ! No SSH key found")
    return ""


def render_template(template_str: str, context: Dict[str, Any]) -> str:
    """Render Jinja2 template with context"""
    template = Template(template_str)
    return template.render(**context)


def load_config(config_path: Path) -> Config:
    """Load and parse VM configuration"""
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return Config(**data)


def hash_url(url: str) -> str:
    """Generate SHA256 hash of URL for cache filename"""
    return hashlib.sha256(url.encode()).hexdigest()


def load_image_index(images_dir: Path) -> Dict[str, str]:
    """
    Load images.txt index file.

    Format: sha256(url)<TAB>url
    Returns: {hash: url} dict
    """
    index_file = images_dir / "images.txt"
    index = {}

    if index_file.exists():
        with open(index_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split("\t", 1)
                    if len(parts) == 2:
                        index[parts[0]] = parts[1]

    return index


def save_image_index(images_dir: Path, index: Dict[str, str]):
    """
    Save images.txt index file.

    Format: sha256(url)<TAB>url
    """
    index_file = images_dir / "images.txt"

    with open(index_file, "w") as f:
        f.write("# Auto-generated image cache index\n")
        f.write("# Format: sha256(url)<TAB>url\n")
        for url_hash, url in sorted(index.items()):
            f.write(f"{url_hash}\t{url}\n")


def get_cached_image(images_dir: Path, url: str) -> Optional[Path]:
    """
    Check if image URL is already cached.

    Returns: Path to cached image if exists, None otherwise
    """
    url_hash = hash_url(url)
    index = load_image_index(images_dir)

    if url_hash in index:
        cached_path = images_dir / f"{url_hash}.img"
        if cached_path.exists():
            return cached_path

    return None


# ============================================================================
# QEMU Builder
# ============================================================================

class QEMUBuilder:
    """
    Type-safe QEMU command-line argument builder.

    Constructs QEMU arguments with proper escaping and formatting.
    Uses builder pattern for fluent API.
    """

    def __init__(self):
        self.args: List[str] = []

    def add_flag(self, flag: str) -> "QEMUBuilder":
        """
        Add a standalone flag (e.g., "-nodefaults")

        Args:
            flag: Flag name (should include leading dash)

        Returns:
            self for chaining
        """
        self.args.append(flag)
        return self

    def add_option(self, key: str, value: str) -> "QEMUBuilder":
        """
        Add a key-value option (e.g., "-machine", "q35")

        Args:
            key: Option name (should include leading dash)
            value: Option value

        Returns:
            self for chaining
        """
        self.args.extend([key, value])
        return self

    def add_device(self, device_type: str, **params) -> "QEMUBuilder":
        """
        Add a device with parameters (e.g., -device ahci,id=ahci)

        Args:
            device_type: Device type
            **params: Device parameters (underscores converted to hyphens)

        Returns:
            self for chaining
        """
        param_str = self._format_params(device_type, **params)
        self.args.extend(["-device", param_str])
        return self

    def add_drive(self, **params) -> "QEMUBuilder":
        """
        Add a drive configuration (e.g., -drive file=/path,id=disk,if=none)

        Args:
            **params: Drive parameters (use if_="none" for if=none)

        Returns:
            self for chaining
        """
        param_str = self._format_params(**params)
        self.args.extend(["-drive", param_str])
        return self

    def add_netdev(self, netdev_type: str, hostfwd: Optional[List[str]] = None, **params) -> "QEMUBuilder":
        """
        Add a network device backend (e.g., -netdev user,id=net0,...)

        Args:
            netdev_type: Network device type (user, tap, vmnet-shared, socket, etc.)
            hostfwd: Optional list of hostfwd rules (for user-mode networking)
            **params: Network device parameters

        Returns:
            self for chaining
        """
        # Handle hostfwd specially - it can appear multiple times
        if hostfwd:
            hostfwd_str = ",".join([f"hostfwd={rule}" for rule in hostfwd])
            param_str = self._format_params(netdev_type, **params)
            param_str = f"{param_str},{hostfwd_str}"
        else:
            param_str = self._format_params(netdev_type, **params)

        self.args.extend(["-netdev", param_str])
        return self

    def add_fsdev(self, fsdev_type: str, **params) -> "QEMUBuilder":
        """
        Add a filesystem device backend (e.g., -fsdev local,id=fs_tag,path=/path)

        Args:
            fsdev_type: Filesystem device type (local, proxy, synth, etc.)
            **params: Filesystem device parameters

        Returns:
            self for chaining
        """
        param_str = self._format_params(fsdev_type, **params)
        self.args.extend(["-fsdev", param_str])
        return self

    def add_raw(self, *args: str) -> "QEMUBuilder":
        """
        Add raw argument(s) - use sparingly, prefer typed methods

        Args:
            *args: Raw arguments to add

        Returns:
            self for chaining
        """
        self.args.extend(args)
        return self

    def _format_params(self, prefix: Optional[str] = None, **params) -> str:
        """
        Format parameters as comma-separated key=value pairs.

        Handles special cases:
        - if_ -> if (Python keyword workaround - trailing underscore removed)
        - Some underscores preserved (security_model, etc.)
        - Other underscores converted to hyphens (mount_tag -> mount-tag)
        - Path objects -> strings

        Args:
            prefix: Optional prefix to prepend (e.g., device type)
            **params: Parameters to format

        Returns:
            Formatted parameter string
        """
        # Parameters that should keep underscores instead of converting to hyphens
        KEEP_UNDERSCORES = {"security_model", "mount_tag"}

        parts = []

        if prefix:
            parts.append(prefix)

        for key, value in params.items():
            # Handle Python keyword workarounds (trailing underscore)
            if key.endswith("_") and key not in KEEP_UNDERSCORES:
                key = key.rstrip("_")

            # Convert underscores to hyphens for QEMU parameters (except special cases)
            if key not in KEEP_UNDERSCORES:
                key = key.replace("_", "-")

            # Convert Path to string
            if isinstance(value, Path):
                value = str(value)

            # Handle boolean values
            if isinstance(value, bool):
                value = "on" if value else "off"

            parts.append(f"{key}={value}")

        return ",".join(parts)

    def get_args(self) -> List[str]:
        """
        Get the list of arguments.

        Returns:
            List of QEMU arguments
        """
        return self.args.copy()

    def to_script(self, cmd: str, line_continuation: str = " \\") -> str:
        """
        Generate a bash script with properly escaped arguments.

        Args:
            cmd: QEMU command (e.g., "qemu-system-x86_64")
            line_continuation: Line continuation character(s)

        Returns:
            Formatted bash script content
        """
        lines = ["#!/bin/bash", cmd + line_continuation]

        for arg in self.args:
            # Escape argument for shell
            escaped = shlex.quote(arg)
            lines.append(f"    {escaped}{line_continuation}")

        # Remove trailing continuation from last line
        if lines:
            lines[-1] = lines[-1].rstrip(line_continuation).rstrip()

        return "\n".join(lines) + "\n"


# ============================================================================
# Docker Controller
# ============================================================================

class DockerController:
    """Controller for Docker-based utilities"""

    IMAGE_NAME = "c684e245-7f79-vm-utils"

    DOCKERFILE = """FROM alpine:latest

RUN apk add --no-cache \\
    bash \\
    curl \\
    whois \\
    qemu-img \\
    cloud-init \\
    cdrkit \\
    jq \\
    yq
"""

    def __init__(self):
        pass

    def get_image_id(self) -> str:
        """Get or build Docker image"""
        result = subprocess.run(
            ["docker", "image", "ls"],
            capture_output=True,
            text=True
        )
        if self.IMAGE_NAME not in result.stdout:
            self.rebuild_image()
        return self.IMAGE_NAME

    def rebuild_image(self):
        """Rebuild Docker image"""
        print_header("[+] Building Docker image...")
        subprocess.run(
            ["docker", "build", "-t", self.IMAGE_NAME, "-f", "-", "."],
            input=self.DOCKERFILE,
            text=True,
            check=True
        )

    def run(self, mounts: List[str], workdir: Optional[str] = None,
            interactive: bool = False, cmd: List[str] = None):
        """Run command in Docker container"""
        image_id = self.get_image_id()

        docker_args = ["docker", "run", "--rm"]

        # Add mounts
        for mount in mounts:
            docker_args.extend(["-v", mount])

        # Add workdir
        if workdir:
            docker_args.extend(["-w", workdir])

        # Add interactive
        if interactive:
            docker_args.append("-it")

        # Add image
        docker_args.append(image_id)

        # Add command
        if cmd:
            docker_args.extend(cmd)

        subprocess.run(docker_args, check=True)


# ============================================================================
# VM Controller
# ============================================================================

class VMController:
    """Controller for VM operations"""

    def __init__(self, project_dir: Path, vm_name: str):
        self.project_dir = project_dir.resolve()
        self.vm_name = vm_name
        self.images_dir = self.project_dir / "images"
        self.vm_dir = self.project_dir / "vms" / vm_name
        self.vm_disks_dir = self.vm_dir / "disks"
        self.vm_gen_dir = self.vm_dir / "gen"
        self.vm_gen_cloud_init_dir = self.vm_gen_dir / "cloud-init"
        self.config_path = self.vm_dir / "config.yaml"

        # Load configuration
        if not self.config_path.exists():
            print_error(f"Config file not found: {self.config_path}")

        raw_config = load_config(self.config_path)
        self.is_new_schema = raw_config.is_new_schema()

        # Convert to RootConfig for internal use
        if self.is_new_schema:
            self.config = raw_config.to_root_config()
        else:
            # Use legacy config directly for now
            self.config = raw_config

        self.os_name = get_os_name()
        self.ssh_key_pub = get_ssh_public_key()

        # Docker controller
        self.docker = DockerController()

    def _get_template_context(self) -> Dict[str, Any]:
        """Build template context for variable replacement"""
        if self.is_new_schema:
            # NEW SCHEMA: Build context from RootConfig
            # Replace {{ssh_key_pub}} in params.users if needed
            params_dict = self.config.params.model_dump()
            for user in params_dict.get("users", []):
                for i, key in enumerate(user.get("ssh_authorized_keys", [])):
                    if key == "{{ssh_key_pub}}":
                        user["ssh_authorized_keys"][i] = self.ssh_key_pub

            context = {
                "dir": {
                    "project": str(self.project_dir),
                    "vm": str(self.vm_dir),
                },
                "system": self.config.system.model_dump(),
                "resources": self.config.resources.model_dump(),
                "identity": self.config.identity.model_dump(),
                "params": params_dict,
                "ssh_key_pub": self.ssh_key_pub,
            }
            return context

        else:
            # LEGACY SCHEMA: Build context from vm.* structure
            context = {
                "dir": {
                    "project": str(self.project_dir),
                    "vm": str(self.vm_dir),
                },
                "vm": {
                    "system": {
                        "cmd": self.config.vm.system.cmd,
                        "machine": self.config.vm.system.machine,
                    },
                    "id": {
                        "hostname": self.config.vm.id.hostname,
                        "hostname_fqdn": self.config.vm.id.hostname_fqdn,
                        "smbios": self.config.vm.id.smbios,
                        "instance": self.config.vm.id.instance,
                    },
                    "admin": {
                        "username": self.config.vm.admin.username,
                        "passwd": self.config.vm.admin.passwd,
                        "ssh_key": self.ssh_key_pub if self.config.vm.admin.ssh_key == "{{ssh_key_pub}}" else self.config.vm.admin.ssh_key,
                    },
                    "net": {
                        "mac": self.config.vm.net.mac,
                        "primary_interface": self.config.vm.net.primary_interface,
                        "primary_address_v4": self.config.vm.net.primary_address_v4,
                        "primary_gateway_v4": self.config.vm.net.primary_gateway_v4,
                        "dns_server_1": self.config.vm.net.dns_server_1,
                        "dns_server_2": self.config.vm.net.dns_server_2 or "",
                        "dns_search": self.config.vm.net.dns_search,
                    },
                    "resources": {
                        "memory": self.config.vm.resources.memory,
                        "smp": str(self.config.vm.resources.smp),
                    },
                },
                "ssh_key_pub": self.ssh_key_pub,
            }

            # Legacy image support (deprecated)
            if self.config.vm.image:
                context["vm"]["image"] = {
                    "name": self.config.vm.image.name,
                    "url": self.config.vm.image.url or "",
                    "format": self.config.vm.image.format,
                    "expand_size": self.config.vm.image.expand_size,
                }

            return context

    def _render_vars(self, text: str) -> str:
        """
        Render template with full Jinja2 support (two-pass for nested refs).

        Uses Jinja2 Environment for advanced features like loops, filters, conditionals.
        Two-pass rendering allows params to reference other params.
        """
        from jinja2 import Environment

        env = Environment(
            trim_blocks=True,
            lstrip_blocks=True,
            autoescape=False
        )

        context = self._get_template_context()

        # First pass: render with context
        template = env.from_string(text)
        rendered = template.render(**context)

        # Second pass: resolve any nested templates (for params referencing params)
        try:
            template2 = env.from_string(rendered)
            return template2.render(**context)
        except Exception:
            # If second pass fails, return first pass result
            return rendered

    def _get_or_download_image(self, url: str) -> Path:
        """
        Get cached image or download if not cached.

        Uses URL hash for cache filename and maintains images.txt index.

        Args:
            url: Image download URL

        Returns:
            Path to cached image file
        """
        url_hash = hash_url(url)
        index = load_image_index(self.images_dir)

        # Check if already cached
        if url_hash in index and index[url_hash] == url:
            cached_path = self.images_dir / f"{url_hash}.img"
            if cached_path.exists():
                print_text(f"> Using cached image: {url_hash}.img")
                return cached_path

        # Download
        image_path = self.images_dir / f"{url_hash}.img"
        print_text(f"> Downloading image from {url}")
        print_text(f">   Cache file: {url_hash}.img")

        subprocess.run(
            ["curl", "-L", "-o", str(image_path), url],
            check=True
        )

        # Update index
        index[url_hash] = url
        save_image_index(self.images_dir, index)

        return image_path

    def make_disk(self, disk_name: str, disk_size: str):
        """Create a new disk for the VM"""
        print_header(f"[+] vm-make-disk {self.vm_name} {disk_name} {disk_size}")
        print_text(f"    * vm_dir: {self.vm_dir}")
        print_text(f"    * vm_disks_dir: {self.vm_disks_dir}")

        # Create directories
        self.vm_disks_dir.mkdir(parents=True, exist_ok=True)

        # Setup mounts
        mounts = [
            f"{self.vm_dir}:/app/input-vm",
            f"{self.vm_disks_dir}:/app/output-disk",
        ]

        # Create disk
        disk_path = f"/app/output-disk/{disk_name}.qcow2"
        self.docker.run(mounts, cmd=["qemu-img", "create", "-f", "qcow2", disk_path, disk_size])

        print_text(f"[+] Disk {disk_name}.qcow2 : Created")

    def build(self):
        """Build VM configuration and cloud-init ISO"""
        print_header(f"[+] vm-build <{self.vm_name}>")
        print_text(f"    * vm_host_os_name: {self.os_name}")
        print_text(f"    * vm_name: {self.vm_name}")
        print_text(f"    * project_dir: {self.project_dir}")
        print_text(f"    Dirs:")
        print_text(f"      * vm_dir: {self.vm_dir}")
        print_text(f"      * vm_disks_dir: {self.vm_disks_dir}")
        print_text(f"      * vm_gen_dir: {self.vm_gen_dir}")

        # Create directories
        print_header("[+] Creating directories")
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.vm_disks_dir.mkdir(parents=True, exist_ok=True)
        self.vm_gen_cloud_init_dir.mkdir(parents=True, exist_ok=True)
        self.vm_gen_dir.mkdir(parents=True, exist_ok=True)

        # Setup mounts for Docker
        mounts = [
            f"{self.vm_dir}:/app/input-vm",
            f"{self.images_dir}:/app/input-images",
            f"{self.vm_disks_dir}:/app/output-disks",
            f"{self.vm_gen_cloud_init_dir}:/app/cloud-init-cfg",
        ]

        # Print variables
        print_header("[+] Variables:")
        context = self._get_template_context()
        for key, value in context.items():
            if isinstance(value, dict):
                for subkey, subvalue in value.items():
                    if isinstance(subvalue, dict):
                        for subsubkey, subsubvalue in subvalue.items():
                            print_text(f"    * {{{{{key}.{subkey}.{subsubkey}}}}}: {subsubvalue}")
                    else:
                        print_text(f"    * {{{{{key}.{subkey}}}}}: {subvalue}")
            else:
                print_text(f"    * {{{{{key}}}}}: {value}")

        # Process disks
        print_header("[+] Processing Disks")

        disks = self.config.disks if self.is_new_schema else self.config.vm.disks
        for disk in disks:
            disk_path = self.vm_disks_dir / disk.params.file

            if disk.type == "image":
                # Image-based disk (bootable OS image)
                print_header(f"[+] Disk '{disk.id}' (type: image)")

                if not disk_path.exists():
                    if not disk.init or not isinstance(disk.init, DiskImageInit):
                        print_error(f"Disk '{disk.id}': init.url required but not found")

                    # Get or download base image
                    base_image = self._get_or_download_image(disk.init.url)

                    # Convert to VM disk
                    print_text(f"> Converting image to {disk.params.file}")
                    self.docker.run(
                        mounts,
                        workdir="/app",
                        cmd=[
                            "qemu-img", "convert",
                            "-f", disk.params.format,
                            "-O", "qcow2",
                            f"/app/input-images/{base_image.name}",
                            f"/app/output-disks/{disk.params.file}"
                        ]
                    )

                    # Expand if requested
                    if disk.init.expand_size:
                        size = disk.init.size or "15G"  # Default to 15G if not specified
                        print_text(f"> Expanding disk to {size}")
                        self.docker.run(
                            mounts,
                            workdir="/app",
                            cmd=[
                                "qemu-img", "resize",
                                f"/app/output-disks/{disk.params.file}",
                                size
                            ]
                        )

                    print_text(f"    ! Disk {disk.params.file} : Created")
                else:
                    print_text(f"    ! Disk {disk.params.file} : Exists")

            elif disk.type == "cloud-init":
                # Cloud-init ISO
                print_header(f"[+] Disk '{disk.id}' (type: cloud-init)")

                # Get cloud-init templates
                cloud_init_cfg = self.config.cloud_init if self.is_new_schema else (self.config.vm.cloud_init or VMCloudInitConfig())

                # Select defaults based on schema
                if self.is_new_schema:
                    default_meta = DEFAULT_META_DATA_NEW
                    default_user = DEFAULT_USER_DATA_NEW
                    default_net = DEFAULT_NETWORK_CONFIG_NEW
                else:
                    default_meta = DEFAULT_META_DATA_LEGACY
                    default_user = DEFAULT_USER_DATA_LEGACY
                    default_net = DEFAULT_NETWORK_CONFIG_LEGACY

                # Meta-data
                print_text("> cloud_init.meta")
                meta_template = cloud_init_cfg.meta if cloud_init_cfg else default_meta
                meta_template = meta_template or default_meta
                meta_content = self._render_vars(meta_template)
                (self.vm_gen_cloud_init_dir / "meta-data").write_text(meta_content)
                click.echo(meta_content)

                # User-data
                print_text("> cloud_init.user")
                user_template = cloud_init_cfg.user if cloud_init_cfg else default_user
                user_template = user_template or default_user
                user_content = self._render_vars(user_template)
                (self.vm_gen_cloud_init_dir / "user-data").write_text(user_content)
                click.echo(user_content)

                # Network-config
                print_text("> cloud_init.net")
                net_template = cloud_init_cfg.net if cloud_init_cfg else default_net
                net_template = net_template or default_net
                net_content = self._render_vars(net_template)
                (self.vm_gen_cloud_init_dir / "network-config").write_text(net_content)
                click.echo(net_content)

                # Validate user-data
                print_text("> Validate user-data")
                self.docker.run(
                    mounts,
                    workdir="/app",
                    cmd=[
                        "cloud-init", "schema",
                        "--config-file=/app/cloud-init-cfg/user-data",
                        "--annotate"
                    ]
                )

                # Build ISO
                print_text("> Build ISO")
                self.docker.run(
                    mounts,
                    workdir="/app",
                    cmd=[
                        "genisoimage", "-volid", "cidata",
                        "-rational-rock", "-joliet",
                        "-output", f"/app/output-disks/{disk.params.file}",
                        "/app/cloud-init-cfg"
                    ]
                )

                print_text(f"    ! Disk {disk.params.file} : Created")

            elif disk.type == "raw":
                # Raw disk - verify exists or create if init.create=true
                print_header(f"[+] Disk '{disk.id}' (type: raw)")

                if not disk_path.exists():
                    # Check if we should create it
                    if disk.init and isinstance(disk.init, DiskRawInit) and disk.init.create:
                        if not disk.init.size:
                            print_error(f"Disk '{disk.id}': init.size required when init.create=true")

                        print_text(f"> Creating raw disk {disk.params.file} ({disk.init.size})")
                        self.docker.run(
                            mounts,
                            workdir="/app",
                            cmd=[
                                "qemu-img", "create",
                                "-f", disk.params.format,
                                f"/app/output-disks/{disk.params.file}",
                                disk.init.size
                            ]
                        )
                        print_text(f"    ! Disk {disk.params.file} : Created")
                    else:
                        print_error(f"Raw disk {disk_path} does not exist and init.create is not true")
                else:
                    print_text(f"    ! Disk {disk.params.file} : Exists")

        # Build run script
        self._build_run_script()

    def _add_network_interface(self, builder: QEMUBuilder, iface: NetworkInterface):
        """
        Add network interface to QEMU builder based on type.

        Supports: user, tap, bridge, vmnet-shared, vmnet-bridged, socket
        """
        # Render params (supports {{params.network_primary.mac}} etc)
        rendered_params = {}
        for key, value in iface.params.items():
            if isinstance(value, str):
                rendered_params[key] = self._render_vars(value)
            elif isinstance(value, list):
                rendered_params[key] = [
                    self._render_vars(v) if isinstance(v, str) else v
                    for v in value
                ]
            else:
                rendered_params[key] = value

        print_text(f"  * Interface {iface.id} (type: {iface.type})")

        if iface.type == "user":
            # User-mode networking: -netdev user,id=net0,net=...,dhcpstart=...,host=...,hostfwd=...
            hostfwd = rendered_params.pop("hostfwd", [])
            mac = rendered_params.pop("mac", None)

            # Rename 'gateway' to 'host' for QEMU compatibility
            if "gateway" in rendered_params:
                rendered_params["host"] = rendered_params.pop("gateway")

            builder.add_netdev(
                "user",
                hostfwd=hostfwd,
                id=iface.id,
                **rendered_params
            )
            if mac:
                builder.add_device(
                    "virtio-net-pci",
                    netdev=iface.id,
                    mac=mac
                )

        elif iface.type in ["vmnet-shared", "vmnet-bridged"]:
            # VMNet networking
            mac = rendered_params.pop("mac", None)
            builder.add_netdev(iface.type, id=iface.id, **rendered_params)
            if mac:
                builder.add_device("virtio-net-pci", netdev=iface.id, mac=mac)

        elif iface.type in ["tap", "bridge"]:
            # TAP/Bridge networking
            mac = rendered_params.pop("mac", None)
            ifname = rendered_params.pop("ifname", None)
            br = rendered_params.pop("bridge", None)

            netdev_params = {"id": iface.id}
            if ifname:
                netdev_params["ifname"] = ifname
            if br:
                netdev_params["br"] = br

            builder.add_netdev("tap", **netdev_params)
            if mac:
                builder.add_device("virtio-net-pci", netdev=iface.id, mac=mac)

        elif iface.type == "socket":
            # Socket networking
            mac = rendered_params.pop("mac", None)
            fd = rendered_params.get("fd", "3")
            builder.add_netdev("socket", id=iface.id, fd=str(fd))
            if mac:
                builder.add_device("virtio-net-pci", netdev=iface.id, mac=mac)

        else:
            print_error(f"Unsupported network interface type: {iface.type}")

    def _build_run_script(self):
        """Build the VM run script"""
        # Build QEMU arguments using builder
        builder = QEMUBuilder()

        # System args - always add nodefaults
        builder.add_flag("-nodefaults")

        # Get system config for stdout_mode/display/vga
        system_config = self.config.system if self.is_new_schema else self.config.vm.system

        # stdout_mode - what goes to stdout (orthogonal to display)
        stdout_mode = system_config.stdout_mode or "none"  # default: none
        if stdout_mode == "serial":
            builder.add_option("-serial", "mon:stdio")
        elif stdout_mode == "monitor":
            builder.add_option("-monitor", "stdio")
        # else: none - no stdout

        # display - graphics backend (orthogonal to stdout)
        display = system_config.display or "none"  # default: none
        if display == "none":
            builder.add_option("-display", "none")
        elif display in ["sdl", "gtk", "cocoa"]:
            builder.add_option("-display", display)
        elif display == "vnc":
            builder.add_option("-vnc", ":0")
        # else: "default" - no display flag, QEMU auto-selects

        # vga - VGA device (needed for graphical display)
        # Auto-set vga to "std" if display is "default" and vga is not explicitly set
        vga = system_config.vga
        if vga is None and display == "default":
            vga = "std"

        if vga == "std":
            builder.add_device("VGA")
        elif vga == "virtio":
            builder.add_device("virtio-vga")
        elif vga == "qxl":
            builder.add_device("qxl-vga")
        elif vga == "cirrus":
            builder.add_device("cirrus-vga")
        # else: null - no VGA device

        if self.is_new_schema:
            builder.add_option("-machine", self.config.system.machine)
            builder.add_option("-m", self.config.resources.memory)
            builder.add_option("-smp", str(self.config.resources.smp))
            builder.add_option("-smbios", f"type=1,uuid={self.config.identity.smbios}")
            builder.add_device("vmgenid", guid=self.config.identity.smbios)
        else:
            builder.add_option("-machine", self.config.vm.system.machine)
            builder.add_option("-m", self.config.vm.resources.memory)
            builder.add_option("-smp", str(self.config.vm.resources.smp))
            builder.add_option("-smbios", f"type=1,uuid={self.config.vm.id.smbios}")
            builder.add_device("vmgenid", guid=self.config.vm.id.smbios)

        # AHCI controller
        builder.add_device("ahci", id="ahci")

        # Add all disks from configuration
        disks = self.config.disks if self.is_new_schema else self.config.vm.disks
        for disk in disks:
            disk_path = self.vm_disks_dir / disk.params.file

            # Add drive
            builder.add_drive(
                file=disk_path,
                id=disk.id,
                if_="none",
                format=disk.params.format,
                media=disk.params.media
            )

            # Add device if specified
            if disk.device:
                device_params = {"drive": disk.id}
                if disk.params.bus:
                    device_params["bus"] = disk.params.bus
                builder.add_device(disk.device, **device_params)

        # Network configuration
        if self.is_new_schema:
            # NEW SCHEMA: Use network profiles
            profile_name = self.config.network.default.get(self.os_name)
            if not profile_name:
                print_error(f"No default network profile for OS: {self.os_name}")

            profile = self.config.network.profiles.get(profile_name)
            if not profile:
                print_error(f"Network profile not found: {profile_name}")

            print_header(f"[+] Network: Using profile '{profile_name}'")

            # Add each interface
            for iface in profile.interfaces:
                self._add_network_interface(builder, iface)

        else:
            # LEGACY SCHEMA: Use hardcoded network modes
            net_mode = self.config.vm.net.mode.get(self.os_name, "user")

            if net_mode == "user":
                print_header("[+] Network: Using <user>")
                if not self.config.vm.net.user:
                    print_error("vm.net.user config required for user mode")

                # Build user-mode network with hostfwd support
                builder.add_netdev(
                    "user",
                    hostfwd=self.config.vm.net.user.hostfwd,
                    id="net0",
                    net=self.config.vm.net.user.dhcp_net_address_v4,
                    dhcpstart=self.config.vm.net.user.dhcp_start_address_v4,
                    host=self.config.vm.net.primary_gateway_v4
                )
                builder.add_device("virtio-net-pci", netdev="net0", mac=self.config.vm.net.mac)

            elif net_mode == "vmnet":
                print_header("[+] Network: Using <vmnet>")
                if not self.config.vm.net.vmnet:
                    print_error("vm.net.vmnet config required for vmnet mode")

                builder.add_netdev(
                    "vmnet-shared",
                    id="net0",
                    start_address=self.config.vm.net.vmnet.dhcp_start_address_v4,
                    end_address=self.config.vm.net.vmnet.dhcp_end_address_v4,
                    subnet_mask=self.config.vm.net.vmnet.dhcp_subnet_mask_v4
                )
                builder.add_device("virtio-net-pci", netdev="net0", mac=self.config.vm.net.mac)

            elif net_mode == "socket":
                print_header("[+] Network: Using <socket>")
                builder.add_netdev("socket", id="net0", fd="3")
                builder.add_device("virtio-net-pci", netdev="net0", mac=self.config.vm.net.mac)

            else:
                print_error(f"Invalid network mode: {net_mode}")

        # Virtio shares
        print_header("[+] Virtio Shares")
        virtio_shares = self.config.virtio_shares if self.is_new_schema else self.config.vm.virtio_shares
        for share in virtio_shares:
            share_path = self._render_vars(share.path)
            print_text(f"    * tag: {share.tag} :: path: {share_path}")
            builder.add_device("virtio-9p-pci", fsdev=f"fs_{share.tag}", mount_tag=share.tag)
            builder.add_fsdev("local", id=f"fs_{share.tag}", path=share_path, security_model="none")

        # Extra args
        print_header("[+] Extra Args")
        extra_args = self.config.extra_args if self.is_new_schema else self.config.vm.extra_args
        for extra_arg in extra_args:
            if isinstance(extra_arg, list):
                # Array format: ["-drive", "file=path,id=x"]
                rendered_args = [self._render_vars(arg) for arg in extra_arg]
                print_text(f"    * arg: {' '.join(rendered_args)}")
                builder.add_raw(*rendered_args)
            else:
                # String format (legacy): '-drive "file=path,id=x"'
                rendered_arg = self._render_vars(extra_arg)
                if rendered_arg.strip():
                    print_text(f"    * arg: {rendered_arg}")
                    # Parse the arg string to handle quotes properly
                    try:
                        parsed_args = shlex.split(rendered_arg)
                        builder.add_raw(*parsed_args)
                    except ValueError:
                        # If shlex fails, just add as-is
                        builder.add_raw(rendered_arg)

        # Build script using builder
        system_cmd = self.config.system.cmd if self.is_new_schema else self.config.vm.system.cmd
        script_content = builder.to_script(system_cmd)

        vm_script_run_path = self.vm_gen_dir / "run.sh"
        vm_script_run_path.write_text(script_content)
        vm_script_run_path.chmod(0o755)

        print_header(f"[+] Shell script: {vm_script_run_path}")
        click.echo(script_content)

    def run(self):
        """Run the VM"""
        vm_script_run_path = self.vm_gen_dir / "run.sh"

        if not vm_script_run_path.exists():
            print_error(f"Run script not found: {vm_script_run_path}. Run vm-build first.")

        subprocess.run([str(vm_script_run_path)], check=True)


# ============================================================================
# Click CLI
# ============================================================================

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """QEMU Manager - Manage QEMU VMs with cloud-init"""
    if ctx.invoked_subcommand is None:
        click.echo("Usage: qmgr <command> [args]")
        click.echo("  vm-build, vm-make-disk, vm-run, vm-utils-mkpasswd, docker-run")
        click.echo("")
        click.echo("Run qmgr <command> --help to see more details")
        click.echo("")


@cli.command("vm-build")
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
@click.argument("vm_name")
def vm_build(project_dir: Path, vm_name: str):
    """Build VM configuration and cloud-init ISO"""
    controller = VMController(project_dir, vm_name)
    controller.build()


@cli.command("vm-make-disk")
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
@click.argument("vm_name")
@click.argument("disk_name")
@click.argument("disk_size")
def vm_make_disk(project_dir: Path, vm_name: str, disk_name: str, disk_size: str):
    """Create a new disk for the VM"""
    controller = VMController(project_dir, vm_name)
    controller.make_disk(disk_name, disk_size)


@cli.command("vm-run")
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
@click.argument("vm_name")
def vm_run(project_dir: Path, vm_name: str):
    """Run the VM"""
    controller = VMController(project_dir, vm_name)
    controller.run()


@cli.command("vm-utils-mkpasswd")
@click.argument("args", nargs=-1)
def vm_utils_mkpasswd(args):
    """Generate password hash using mkpasswd"""
    docker = DockerController()
    docker.run([], cmd=["mkpasswd", "--method=SHA-512"] + list(args))


@cli.command("docker-run")
@click.argument("args", nargs=-1)
def docker_run(args):
    """Run command in Docker container"""
    docker = DockerController()

    # Parse arguments (simplified version)
    mounts = []
    workdir = None
    interactive = False
    cmd = []

    i = 0
    while i < len(args):
        if args[i] == "--":
            cmd = list(args[i+1:])
            break
        elif args[i] == "-w":
            workdir = args[i+1]
            i += 2
        elif args[i] == "-i":
            interactive = True
            i += 1
        else:
            mounts.append(args[i])
            i += 1

    docker.run(mounts, workdir=workdir, interactive=interactive, cmd=cmd)


@cli.command("docker-image-rebuild")
def docker_image_rebuild():
    """Rebuild Docker image"""
    docker = DockerController()
    docker.rebuild_image()


@cli.command("docker-image-id")
def docker_image_id():
    """Get Docker image ID"""
    docker = DockerController()
    click.echo(docker.get_image_id())


if __name__ == "__main__":
    cli()
