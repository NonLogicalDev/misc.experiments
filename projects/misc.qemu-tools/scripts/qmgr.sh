#!/bin/bash

_portable_abspath() { local path="$1"; echo "$( cd "$(dirname "$path")" && pwd )/$(basename "$path")"; }

SCRIPT_PATH="$(_portable_abspath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

################################################################################
# Main      
#

_main_usage() {
    echo "Usage: qmgr <command> [args]"
    echo "  vm-build, vm-make-disk, vm-run, vm-utils-mkpasswd, docker-run"
    echo ""
    echo "Run qmgr <command>-help to see more details"
    echo ""
}

_main() {
    local cmd="$1"
    case "$cmd" in
        "help"|"-h"|"--help"|"") shift; _main_usage "$@";;

        "vm-build") shift; cmd_vm_build "$@";;
        "vm-build-help") shift; cmd_vm_build_usage "$@";;

        "vm-make-disk") shift; cmd_vm_make_disk "$@";;
        "vm-make-disk-help") shift; cmd_vm_make_disk_usage "$@";;

        "vm-run") shift; cmd_vm_run "$@";;
        "vm-run-help") shift; cmd_vm_run_usage "$@";;

        "docker-run") shift; cmd_docker_run "$@";;
        "docker-run-help") shift; docker_run_usage "$@";;

        "docker-image-rebuild") shift; cmd_docker_image_rebuild "$@";;
        "docker-image-id") shift; cmd_docker_image_id "$@";;

        "vm-utils-mkpasswd") shift; cmd_vm_utils_mkpasswd "$@";;

        *) "$@";;
    esac
}


################################################################################
# Misc Tools
# 

## vm-utils-mkpasswd [args-for-mkpasswd]
cmd_vm_utils_mkpasswd() {
    cmd_docker_run -- mkpasswd --method=SHA-512 "$@"
}

################################################################################
# VM Utils (make-disk)
#

cmd_vm_make_disk_usage() {
    echo "Usage: vm-make-disk <PROJECT_DIR> <VM_NAME> <DISK_NAME> <DISK_SIZE>"
    echo "  PROJECT_DIR: The project directory"
    echo "  VM_NAME: The VM name"
    echo "  DISK_NAME: The disk name"
    echo "  DISK_SIZE: The disk size"
}

cmd_vm_make_disk() {
    local arg_project_dir=$1

    local arg_vm_name=$2
    local arg_vm_disk_name=$3
    local arg_vm_disk_size=$4

    if [[ -z "$arg_project_dir" ]]; then
        _die "PROJECT_DIR is required"
    fi
    if [[ -z "$arg_vm_name" ]]; then
        _die "VM_NAME is required"
    fi

    local vm_dir=$arg_project_dir/vms/$arg_vm_name
    local vm_disks_dir=$vm_dir/disks

    _hdr "[+] vm-make-disk $arg_vm_name $arg_vm_disk_name $arg_vm_disk_size"
    echo "    * vm_dir: $vm_dir"
    echo "    * vm_disks_dir: $vm_disks_dir"

    local vm_utils_mounts=(
        "$vm_dir:/app/input-vm"
        "$vm_disks_dir:/app/output-disk"
    )

    __vm-utils-run-cmd() {
        docker_run "${vm_utils_mounts[@]}" -- "$@"
    }

    __vm-utils-run-cmd qemu-img create -f qcow2 /app/output-disk/"$arg_vm_disk_name".qcow2 "$arg_vm_disk_size"

    echo "[+] Disk $arg_vm_disk_name.qcow2 : Created"
}

################################################################################
# VM Utils (build)
#

VM_BUILD_DEFAULT_USER_DATA_FILE="#cloud-config
hostname: '{{vm.id.hostname}}'
fqdn: '{{vm.id.hostname_fqdn}}'
manage_etc_hosts: true

users:
  - name: '{{vm.admin.username}}'
    gecos: 'Admin User'
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: false
    passwd: '{{vm.admin.passwd}}'
    ssh_authorized_keys:
      - '{{vm.admin.ssh_key}}'
"

VM_BUILD_DEFAULT_META_DATA_FILE="#cloud-config
dsmode: local
instance-id: '{{vm.id.instance}}'
local-hostname: '{{vm.id.hostname}}'
"

VM_BUILD_DEFAULT_NETWORK_CONFIG_FILE="#cloud-config
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
"

cmd_vm_build_usage() {
    echo "Usage: vm-build <PROJECT_DIR> <VM_NAME>"
    echo "  PROJECT_DIR: The project directory"
    echo "  VM_NAME: The VM name"
}

cmd_vm_build() {
    local arg_project_dir=$1
    local arg_vm_name=$2

    if [[ -z "$arg_project_dir" ]]; then
        _die "PROJECT_DIR is required"
    fi
    if [[ -z "$arg_vm_name" ]]; then
        _die "VM_NAME is required"
    fi

    local project_dir=$(cd "$arg_project_dir" && pwd)
    local images_dir=$project_dir/images

    local vm_name=$arg_vm_name
    local vm_dir=$project_dir/vms/$vm_name
    local vm_disks_dir=$vm_dir/disks
    local vm_gen_dir=$vm_dir/gen
    local vm_gen_cloud_init_dir=$vm_gen_dir/cloud-init

    local vm_disk_root_path=$vm_disks_dir/vm.qcow2
    local vm_disk_cloud_init_path=$vm_disks_dir/cloud-init.iso

    local vm_script_run_path=$vm_gen_dir/run.sh
    local vm_host_os_name=$(_machine_os_name)

    local ssh_key_pub=""
    if [[ -f ~/.ssh/id_rsa.pub ]]; then
        ssh_key_pub=$(cat ~/.ssh/id_rsa.pub)
    elif [[ -f ~/.ssh/id_ed25519.pub ]]; then
        ssh_key_pub=$(cat ~/.ssh/id_ed25519.pub)
    elif [[ -f ~/.ssh/id_ecdsa.pub ]]; then
        ssh_key_pub=$(cat ~/.ssh/id_ecdsa.pub)
    else
        _txt "    ! No SSH key found"
    fi

    _hdr "[+] vm-build <$vm_name>"
    _txt "    * vm_host_os_name: $vm_host_os_name"
    _txt "    * vm_name: $vm_name"
    _txt "    * project_dir: $project_dir"
    _txt "    * images_dir: $images_dir"
    _txt "    Dirs:"
    _txt "      * vm_dir: $vm_dir"
    _txt "      * vm_disks_dir: $vm_disks_dir"
    _txt "      * vm_gen_dir: $vm_gen_dir"
    _txt "      * vm_gen_cloud_init_dir: $vm_gen_cloud_init_dir"
    _txt "    Disks:"
    _txt "      * vm_disk_root_path: $vm_disk_root_path"
    _txt "      * vm_disk_cloud_init_path: $vm_disk_cloud_init_path"
    _txt "    Start script:"
    _txt "      * vm_script_run_path: $vm_script_run_path"


    _hdr "[+] Creating directories"
    ( set -x;
        mkdir -p "$images_dir"
        mkdir -p "$vm_disks_dir"
        mkdir -p "$vm_gen_cloud_init_dir"
        mkdir -p "$vm_gen_dir"
    )

    local vm_utils_mounts=(
        "$vm_dir:/app/input-vm"
        "$images_dir:/app/input-images"
        "$vm_disks_dir:/app/output-disks"
        "$vm_gen_cloud_init_dir:/app/cloud-init-cfg"
    )
    __vm-utils-run-cmd() {
        docker_run "${vm_utils_mounts[@]}" -w /app -- "$@"
    }

    # Convert config.yaml to json
    __vm-utils-run-cmd yq '.' -o json "/app/input-vm/config.yaml" > "$vm_gen_dir/config.json"

    __vm-config-get() {
        local expr=$1
        jq -r --arg vm_host_os_name "$vm_host_os_name" "$expr" "$vm_gen_dir/config.json"
    }

    ## Fetch variables from config.yaml
    local config_vars=$(jq -r --arg vm_host_os_name "$vm_host_os_name" '
        (try(.vm.net.mode[$vm_host_os_name]) // "user") as $vm_net_mode 
        | {
            "vm_system_cmd": (try(.vm.system.cmd) // ""),
            "vm_system_machine": (try(.vm.system.machine) // ""),

            "vm_resources_memory": (try(.vm.resources.memory) // ""),
            "vm_resources_smp": (try(.vm.resources.smp) // ""),

            "vm_image_base": (try(.vm.image.name) // ""),
            "vm_image_base_url": (try(.vm.image.url) // ""),
            "vm_image_base_format": (try(.vm.image.format) // ""),
            "vm_image_base_expand_size": (try(.vm.image.expand_size) // ""),

            "vm_id_hostname": (try(.vm.id.hostname) // ""),
            "vm_id_hostname_fqdn": (try(.vm.id.hostname_fqdn) // ""),
            "vm_id_smbios": (try(.vm.id.smbios) // ""),
            "vm_id_instance": (try(.vm.id.instance) // ""),

            "vm_admin_username": (try(.vm.admin.username) // ""),
            "vm_admin_passwd": (try(.vm.admin.passwd) // ""),
            "vm_admin_ssh_key": (try(.vm.admin.ssh_key) // ""),

            "vm_net_mac": (try(.vm.net.mac) // ""),
            "vm_net_primary_interface": (try(.vm.net.primary_interface) // ""),
            "vm_net_primary_address_v4": (try(.vm.net.primary_address_v4) // ""),
            "vm_net_primary_gateway_v4": (try(.vm.net.primary_gateway_v4) // ""),

            "vm_net_dns_server_1": (try(.vm.net.dns_server_1) // ""),
            "vm_net_dns_server_2": (try(.vm.net.dns_server_2) // ""),
            "vm_net_dns_search": (try(.vm.net.dns_search) // ""),

            "vm_net_mode": $vm_net_mode,
        } | to_entries | .[] | .key + "=" + (.value | @sh)
    ' "$vm_gen_dir/config.json")

    # Load variables into the current shell
    eval "$config_vars"

    _hdr "[+] Variables:"
    _txt "    * {{dir.project}}: $project_dir"
    _txt "    * {{dir.vm}}: $vm_dir"
    _txt "    * {{vm.system.cmd}}: $vm_system_cmd"
    _txt "    * {{vm.system.machine}}: $vm_system_machine"
    _txt "    * {{vm.image.name}}: $vm_image_base"
    _txt "    * {{vm.image.url}}: $vm_image_base_url"
    _txt "    * {{vm.image.format}}: $vm_image_base_format"
    _txt "    * {{vm.image.expand_size}}: $vm_image_base_expand_size"
    _txt "    * {{vm.id.hostname}}: $vm_id_hostname"
    _txt "    * {{vm.id.hostname_fqdn}}: $vm_id_hostname_fqdn"
    _txt "    * {{vm.id.smbios}}: $vm_id_smbios"
    _txt "    * {{vm.id.instance}}: $vm_id_instance"
    _txt "    * {{vm.admin.username}}: $vm_admin_username"
    _txt "    * {{vm.admin.passwd}}: $vm_admin_passwd"
    _txt "    * {{vm.admin.ssh_key}}: $vm_admin_ssh_key"
    _txt "    * {{vm.net.mac}}: $vm_net_mac"
    _txt "    * {{vm.net.ssh_port}}: $vm_net_ssh_port"
    _txt "    * {{vm.net.primary_interface}}: $vm_net_primary_interface"
    _txt "    * {{vm.net.primary_address_v4}}: $vm_net_primary_address_v4"
    _txt "    * {{vm.net.primary_gateway_v4}}: $vm_net_primary_gateway_v4"
    _txt "    * {{vm.net.dns_server_1}}: $vm_net_dns_server_1"
    _txt "    * {{vm.net.dns_server_2}}: $vm_net_dns_server_2"
    _txt "    * {{vm.net.dns_search}}: $vm_net_dns_search"
    _txt "    * {{vm.net.mode}}: $vm_net_mode"
    _txt "    * {{ssh_idrsa_pub}}: $ssh_idrsa_pub"

    __vm_replace_vars() {
        sed \
            -e "s|{{dir.project}}|${project_dir}|g" \
            -e "s|{{dir.vm}}|${vm_dir}|g" \
            -e "s|{{vm.system.cmd}}|${vm_system_cmd}|g" \
            -e "s|{{vm.system.machine}}|${vm_system_machine}|g" \
            -e "s|{{vm.image.name}}|${vm_image_base}|g" \
            -e "s|{{vm.image.url}}|${vm_image_base_url}|g" \
            -e "s|{{vm.image.format}}|${vm_image_base_format}|g" \
            -e "s|{{vm.image.expand_size}}|${vm_image_base_expand_size}|g" \
            -e "s|{{vm.id.hostname}}|${vm_id_hostname}|g" \
            -e "s|{{vm.id.hostname_fqdn}}|${vm_id_hostname_fqdn}|g" \
            -e "s|{{vm.admin.username}}|${vm_admin_username}|g" \
            -e "s|{{vm.admin.passwd}}|${vm_admin_passwd}|g" \
            -e "s|{{vm.admin.ssh_key}}|${vm_admin_ssh_key}|g" \
            -e "s|{{vm.net.mac}}|${vm_net_mac}|g" \
            -e "s|{{vm.net.ssh_port}}|${vm_net_ssh_port}|g" \
            -e "s|{{vm.net.primary_address_v4}}|${vm_net_primary_address_v4}|g" \
            -e "s|{{vm.net.primary_gateway_v4}}|${vm_net_primary_gateway_v4}|g" \
            -e "s|{{vm.id.instance}}|${vm_id_instance}|g" \
            -e "s|{{vm.net.dhcp_start_address_v4}}|${vm_net_dhcp_start_address_v4}|g" \
            -e "s|{{vm.net.dhcp_end_address_v4}}|${vm_net_dhcp_end_address_v4}|g" \
            -e "s|{{vm.net.dhcp_subnet_mask_v4}}|${vm_net_dhcp_subnet_mask_v4}|g" \
            -e "s|{{vm.net.primary_interface}}|${vm_net_primary_interface}|g" \
            -e "s|{{vm.net.dns_server_1}}|${vm_net_dns_server_1}|g" \
            -e "s|{{vm.net.dns_server_2}}|${vm_net_dns_server_2}|g" \
            -e "s|{{vm.net.dns_search}}|${vm_net_dns_search}|g" \
            -e "s|{{ssh_key_pub}}|${ssh_key_pub}|g"
    }

    local vm_system_args=()

    #>> Generic system args
    if [[ -z "$vm_system_cmd" ]]; then
        _die ".vm.system.cmd not found in config.yaml"
    fi
    if [[ -z "$vm_system_machine" ]]; then
        _die ".vm.system.machine not found in config.yaml"
    fi
    vm_system_args+=("-nodefaults -nographic -serial mon:stdio")
    vm_system_args+=("-machine ${vm_system_machine}")

    #>> Set up resources
    if [[ -z "$vm_resources_memory" ]]; then
        _die ".vm.resources.memory not found in config.yaml"
    fi
    if [[ -z "$vm_resources_smp" ]]; then
        _die ".vm.resources.smp not found in config.yaml"
    fi
    vm_system_args+=("-m '${vm_resources_memory}'")
    vm_system_args+=("-smp '${vm_resources_smp}'")

    #>> Set up SMBIOS
    if [[ -z "$vm_id_smbios" ]]; then
        _die ".vm.id.smbios not found in config.yaml"
    fi
    vm_system_args+=("-smbios type=1,uuid=${vm_id_smbios}")
    vm_system_args+=("-device vmgenid,guid=${vm_id_smbios}")

    #>> Set up AHCI
    vm_system_args+=("-device ahci,id=ahci")

    # Create Root disk
    _hdr "[+] Creating root disk"
    if [[ ! -f $vm_disk_root_path ]]; then
        ## Read VM_NAME/config.yaml and fetch vm-image-base/format
        if [[ -z "$vm_image_base" ]]; then
            _die ".vm.image.name not found in config.yaml (but it is required to create root disk)"
        fi
        if [[ -z "$vm_image_base_format" ]]; then
            _die ".vm.image.format not found in config.yaml (but it is required to create root disk)"
        fi
        if [[ -z "$vm_image_base_expand_size" ]]; then
            _die ".vm.image.expand_size not found in config.yaml (but it is required to create root disk)"
        fi

        ## Check if image exists in images directory
        if [[ ! -f $images_dir/$vm_image_base ]]; then
            ## Download image
            if [[ -z "$vm_image_base_url" ]]; then
                _die ".vm.image.url not found in config.yaml (but it is required to download image)"
            fi

            _txt "> Downloading image $vm_image_base from $vm_image_base_url"
            curl -L -o "$images_dir/$vm_image_base" "$vm_image_base_url"
        else
            _txt "> Image $vm_image_base exists in images directory"
        fi

        ## Create/Resize from base image
        __vm-utils-run-cmd qemu-img convert -f "$vm_image_base_format" -O qcow2 "/app/input-images/$vm_image_base" /app/output-disks/vm.qcow2
        __vm-utils-run-cmd qemu-img resize /app/output-disks/vm.qcow2 "$vm_image_base_expand_size"

        _txt "    ! Disk root ($vm_disk_root_path) : Updated"
    else
        _txt "    ! Disk root ($vm_disk_root_path) : Exists"
    fi

    #>> Set up Root disk
    vm_system_args+=("-drive \"file=${vm_disk_root_path},id=disk_root,if=none,media=disk\"")
    vm_system_args+=("-device ide-hd,drive=disk_root,bus=ahci.0")

    # Create / Update Cloudinit
    _hdr "[+] Creating/Updating cloud-init Disk"

    _txt "> {{vm.cloud_init.meta}}"
    jq -r --arg dflt "$VM_BUILD_DEFAULT_META_DATA_FILE" 'try(.vm.cloud_init.meta) // $dflt' "$vm_gen_dir/config.json" | __vm_replace_vars > "$vm_gen_cloud_init_dir/meta-data"
    cat "$vm_gen_cloud_init_dir/meta-data"

    _txt "> {{vm.cloud_init.user}}"
    jq -r --arg dflt "$VM_BUILD_DEFAULT_USER_DATA_FILE" 'try(.vm.cloud_init.user) // $dflt' "$vm_gen_dir/config.json" | __vm_replace_vars > "$vm_gen_cloud_init_dir/user-data"
    cat "$vm_gen_cloud_init_dir/user-data"

    _txt "> {{vm.cloud_init.net}}"
    jq -r --arg dflt "$VM_BUILD_DEFAULT_NETWORK_CONFIG_FILE" 'try(.vm.cloud_init.net) // $dflt'  "$vm_gen_dir/config.json" | __vm_replace_vars > "$vm_gen_cloud_init_dir/network-config"
    cat "$vm_gen_cloud_init_dir/network-config"


	# Validate `user-data`
    _txt "> Validate user-data"
	__vm-utils-run-cmd cloud-init schema --config-file=/app/cloud-init-cfg/user-data --annotate

	# Build ISO
    _txt "> Build ISO"
    __vm-utils-run-cmd genisoimage -volid cidata \
		-rational-rock -joliet \
		-output /app/output-disks/cloud-init.iso \
		/app/cloud-init-cfg

    _hdr "[+] Disk cloud-init.iso ($vm_disk_cloud_init_path) : Updated"

    #>> Set up Cloud-init disk
    vm_system_args+=("-drive \"file=${vm_disk_cloud_init_path},id=disk_cloud_init,if=none,format=raw,media=cdrom\"")
    vm_system_args+=("-device ide-cd,drive=disk_cloud_init,bus=ide.1")

    # Build Shell script for running VM

    if [[ -z "$vm_net_mac" ]]; then
        _die ".vm.net.mac not found in config.yaml"
    fi
    if [[ -z "$vm_resources_memory" ]]; then
        _die ".vm.resources.memory not found in config.yaml"
    fi
    if [[ -z "$vm_resources_smp" ]]; then
        _die ".vm.resources.smp not found in config.yaml"
    fi
    if [[ -z "$vm_net_mode" ]]; then
        _die ".vm.net.mode not found in config.yaml"
    fi

    local vm_run_system=$vm_system
    case "$vm_net_mode" in
        user)
            _hdr "[+] Network: Using <user>"
            local vm_network_hostfwd=$(__vm-config-get '.vm.net.user.hostfwd | map("hostfwd=" + .) | join(",")')
            if [[ $? -ne 0 ]] ||  [[ -z "$vm_network_hostfwd" ]]; then
                _die ".vm.net.user.hostfwd not found in config.yaml"
            fi
            local vm_network_dhcp_net_address_v4=$(__vm-config-get '.vm.net.user.dhcp_net_address_v4')
            if [[ $? -ne 0 ]] ||  [[ -z "$vm_network_dhcp_net_address_v4" ]]; then
                _die ".vm.net.user.dhcp_net_address_v4 not found in config.yaml"
            fi
            local vm_network_dhcp_start_address_v4=$(__vm-config-get '.vm.net.user.dhcp_start_address_v4')
            if [[ $? -ne 0 ]] ||  [[ -z "$vm_network_dhcp_start_address_v4" ]]; then
                _die ".vm.net.user.dhcp_start_address_v4 not found in config.yaml"
            fi
            local vm_network_gateway_v4=$(__vm-config-get '.vm.net.primary_gateway_v4')
            if [[ $? -ne 0 ]] ||  [[ -z "$vm_network_gateway_v4" ]]; then
                _die ".vm.net.primary_gateway_v4 not found in config.yaml"
            fi
            vm_system_args+=("-netdev user,id=net0,net=${vm_network_dhcp_net_address_v4},dhcpstart=${vm_network_dhcp_start_address_v4},host=${vm_network_gateway_v4},${vm_network_hostfwd}")
            vm_system_args+=("-device virtio-net-pci,netdev=net0,mac=${vm_net_mac}")
            ;;
        vmnet)
            _hdr "[+] Network: Using <vmnet>"
            local vm_net_dhcp_start_address_v4=$(__vm-config-get '.vm.net.vmnet.dhcp_start_address_v4')
            if [[ -z "$vm_net_dhcp_start_address_v4" ]]; then
                _die ".vm.net.vmnet.dhcp_start_address_v4 not found in config.yaml"
            fi
            local vm_net_dhcp_end_address_v4=$(__vm-config-get '.vm.net.vmnet.dhcp_end_address_v4')
            if [[ -z "$vm_net_dhcp_end_address_v4" ]]; then
                _die ".vm.net.vmnet.dhcp_end_address_v4 not found in config.yaml"
            fi
            local vm_net_dhcp_subnet_mask_v4=$(__vm-config-get '.vm.net.vmnet.dhcp_subnet_mask_v4')
            if [[ -z "$vm_net_dhcp_subnet_mask_v4" ]]; then
                _die ".vm.net.vmnet.dhcp_subnet_mask_v4 not found in config.yaml"
            fi

            if [[ -n "$vm_net_dhcp_start_address_v4" ]] && [[ -n "$vm_net_dhcp_end_address_v4" ]] && [[ -n "$vm_net_dhcp_subnet_mask_v4" ]]; then
                vm_system_args+=("-netdev vmnet-shared,id=net0,start-address=${vm_net_dhcp_start_address_v4},end-address=${vm_net_dhcp_end_address_v4},subnet-mask=${vm_net_dhcp_subnet_mask_v4}")
            else
                vm_system_args+=("-netdev vmnet-shared,id=net0")
            fi
            #vm_run_system="\"${HOMEBREW_PREFIX}/opt/socket_vmnet/bin/socket_vmnet_client\" /var/run/socket_vmnet \"${vm_system}\""
            ;;
        socket)
            _hdr "[+] Network: Using <socket>"
            vm_system_args+=("-netdev socket,id=net0,fd=3")
            ;;
        *)
            _die "Invalid network mode: $vm_network_mode"
            ;;
    esac

    # Virtio Shares via 9plan
    _hdr "[+] Virtio Shares"

    while IFS=$'\t' read -r tag path; do
        _txt "    * tag: $tag :: path: $path"
        vm_system_args+=("-device virtio-9p-pci,fsdev=fs_${tag},mount_tag=${tag}")
        vm_system_args+=("-fsdev local,id=fs_${tag},path=${path},security_model=none")
        # vm_virtio_shares_args+=("-virtfs local,path=${path},mount_tag=${tag},security_model=none")
    done <<< "$(__vm-config-get '.vm.virtio_shares | map([.tag, .path]|join("\t")) | join("\n")' | __vm_replace_vars)"

    # source extra args from config.yaml
    _hdr "[+] Extra Args"

    while IFS= read -r line; do
        if [[ -z "$line" ]]; then continue; fi

        _txt "    * arg: $line"
        vm_system_args+=("$line")
    done <<< "$(__vm-config-get '.vm.extra_args // [] | join("\n")' | __vm_replace_vars)"

    # ref: https://rubenerd.com/sata-on-qemu/
    # ref: https://serverfault.com/questions/1167260/user-mode-networking-between-multiple-guests-in-qemu

    cat <<EOF > "$vm_script_run_path"
#!/bin/bash
${vm_system_cmd} \\
$(for arg in "${vm_system_args[@]}"; do echo "    ${arg} \\"; done)
EOF
    chmod u+x "$vm_script_run_path"

    _hdr "[+] Shell script: $vm_script_run_path"
    cat "$vm_script_run_path"
}

################################################################################
# VM Utils (run)
#

cmd_vm_run_usage() {
    echo "Usage: vm-run <PROJECT_DIR> <VM_NAME>"
    echo "  PROJECT_DIR: The project directory"
    echo "  VM_NAME: The VM name"
}

cmd_vm_run() {
    local arg_project_dir=$1
    local arg_vm_name=$2

    local project_dir=$(cd "$arg_project_dir" && pwd)
    local vm_dir=$project_dir/$arg_vm_name
    local vm_script_run_path=$vm_dir/gen/run.sh

    "${vm_script_run_path}"
}

################################################################################
# VM Utils (run-macos)
#

cmd_vm_run_macos() {
    # vm-run-macos PROJECT_DIR VM_NAME

    local arg_project_dir=$1
    local arg_vm_name=$2

    local project_dir=$(cd "$arg_project_dir" && pwd)
    local vm_dir=$project_dir/$arg_vm_name

    "${HOMEBREW_PREFIX}/opt/socket_vmnet/bin/socket_vmnet_client" /var/run/socket_vmnet $vm_dir/gen.start.sh
}

################################################################################
# VM Utils (run-macos-net)
#

cmd_vm_run_macos_net() {
    # vm-run-macos-net
	sudo "${HOMEBREW_PREFIX}/opt/socket_vmnet/bin/socket_vmnet" \
		--vmnet-gateway=192.168.105.1 \
		--vmnet-dhcp-end=192.168.105.100 \
		/var/run/socket_vmnet
}

################################################################################
# Docker Utils
#

DOCKER_IMAGE_NAME="c684e245-7f79-vm-utils"

read -r -d '' DOCKER_IMAGE_DOCKERFILE <<'EOF'
FROM alpine:latest

RUN apk add --no-cache \
    bash \
    curl \
    whois \
    qemu-img \
    cloud-init \
    cdrkit \
    jq \
    yq
EOF

docker_image_id() {
    if ! docker image ls | grep -q "$DOCKER_IMAGE_NAME"; then
        docker build -t "$DOCKER_IMAGE_NAME" -f - . <<<"$DOCKER_IMAGE_DOCKERFILE"
    fi
    echo "$DOCKER_IMAGE_NAME"
}

docker_image_rebuild() {
    docker build -t "$DOCKER_IMAGE_NAME" -f - . <<<"$DOCKER_IMAGE_DOCKERFILE"
}

docker_run_usage() {
    echo "Usage: docker-run [--] [--w <path>] [--i] <path>..."
    echo "  --: End of options"
    echo "  -w <path>: Mount path as writable (docker run -w <path>)"
    echo "  -i: Interactive mode (docker run -it)"
    echo "  <path>...: Mount path (docker run -v <path>)"
}

docker_run() {
    local mount_args=()

    # iterate till --
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --) shift; break;;

            "-w") shift; mount_args+=("-w" "$1"); shift 1;;
            "-i") shift; mount_args+=("-it");;

            *) mount_args+=("-v" "$1"); shift 1;;
        esac
    done

    local _docker_image_id="$(docker_image_id)"
    local _script_basename="$(basename "$SCRIPT_PATH")"
    ( set -x; docker run --rm "${mount_args[@]}" -v "$SCRIPT_PATH:/bin/$_script_basename" --entrypoint "/bin/$_script_basename" "$_docker_image_id" "$@" )
}

################################################################################
# Utility functions
#

_die() { # red
    local C="\033[1;31m"
    local R="\033[0m"
    printf >&2 "${C}ERROR: %s${R}\n" "$*"
    exit 1
}

_inf() { # green
    local C="\033[1;32m"
    local R="\033[0m"
    printf "${C}%s${R}\n" "$*"
}

_txt() { # yellow
    local C="\033[1;33m"
    local R="\033[0m"
    printf "${C}%s${R}\n" "$*"
}

_hdr() { # blue
    local C="\033[1;33m"
    local R="\033[0m"
    printf "${C}%s${R}\n" "$*"
}

_machine_os_name() {
    local machine_os_name=$(uname -s)
    case "$machine_os_name" in
        Darwin) echo "macos" ;;
        Linux) echo "linux" ;;
        *)
            _die "Unsupported OS: $machine_os_name"
            ;;
    esac
}

#-------------------------------------------------------------------------------

# Make script callable directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    _main "$@"
fi
