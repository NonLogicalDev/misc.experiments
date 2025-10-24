#!/bin/bash

_portable_abspath() { local path="$1"; echo "$( cd "$(dirname "$path")" && pwd )/$(basename "$path")"; }

SCRIPT_PATH="$(_portable_abspath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

################################################################################
#
# Example usage:
#
# Via script:
#
#   isomgr.sh patch ./images/grml.iso ./images/grml-patched.iso
#       --speed 9600 --unit 1 --word 8 --parity even --stop 1
#
# Via docker:
#
#   ./isomgr.sh docker-run "$(pwd):/work" -w /work \
#     patch ./images/grml.iso ./images/grml-patched.iso \
#       --speed 9600 --unit 1 --word 8 --parity even --stop 1

_main_usage() {
    echo "Usage: isomgr <command> [args]"
    echo "  info, unpack, patch, docker-run"
    echo ""
    echo "Run isomgr <command>-help to see more details"
    echo ""
}

_main() {
    local cmd="$1"
    case "$cmd" in
        "help"|"-h"|"--help"|"") shift; _main_usage "$@";;

        "info") shift; cmd_info_iso "$@";;
        "info-help") shift; cmd_info_iso_usage "$@";;

        "unpack") shift; cmd_iso_unpack "$@";;
        "unpack-help") shift; cmd_iso_unpack_usage "$@";;

        "patch") shift; cmd_patch_iso_serial "$@";;
        "patch-help") shift; cmd_patch_iso_serial_usage "$@";;

        "docker-run") shift; docker_run "$@";;
        "docker-run-help") shift; docker_run_usage "$@";;

        "docker-image-id") shift; docker_image_id "$@";;
        "docker-image-rebuild") shift; docker_image_rebuild "$@";;

        *) "$@";;
    esac
}

################################################################################
#
# Constants
#

EFI_PARTITION_GUID="C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
EFI_PARTITION_TYPE="0xef"

################################################################################
# Command (iso-info)
#

cmd_info_iso_usage() {
    echo "Usage: patch_iso_serial info <input.iso>"
    echo ""
    echo "Show information about an ISO image"
    echo ""
    echo "This command shows information about an ISO image"
}

cmd_info_iso() {
    local iso_path=$1

    xorriso -indev "$iso_path" \
        -toc -pvd_info \
        -print " --- # System Area: (plain) # ---" \
        -report_system_area plain \
        -print " --- # El Torito: (plain) # ---" \
        -report_el_torito plain \
        -print " --- # System Area: (as_mkisofs) # ---" \
        -report_system_area as_mkisofs \
        -print " --- # Boot Image: (any) # ---" \
        -boot_image any show_status
}

################################################################################
# Command (iso-unpack)
#

cmd_iso_unpack_usage() {
    echo "Usage: patch_iso_serial unpack <input.iso> <output.dir>"
    echo ""
    echo "Unpack an ISO image to a directory"
    echo ""
    echo "This command unpacks an ISO image to a directory"
    echo "It can be used directly or via docker"
    echo ""
}

cmd_iso_unpack() {
    local input_iso="$1"
    local work_dir="$2"
    shift 1
    
    # Check for required tools
    if ! command -v xorriso >/dev/null 2>&1; then
        _die "xorriso not found. Install with: apt install xorriso (or apk add xorriso)"
    fi
    
    local iso_contents="$work_dir/iso_contents"

    mkdir -p "$work_dir"

    if ! xorriso -osirrox on -indev "$input_iso" -extract / "$iso_contents" 2>/dev/null; then
        _die "Failed to extract ISO"
    fi

    echo "$iso_contents"
}

cmd_patch_iso_serial_usage() {
    echo "Usage: patch_iso_serial patch <input.iso> <output.iso> [--efi] [--speed <speed>] [--unit <unit>] [--word <word>] [--parity <parity>] [--stop <stop>] [--add-kernel-console <add_kernel_console>]"
    echo ""
    echo "Patch serial console to ISO image (so that it can be used with qemu serial console)"
    echo ""
    echo "This script patches the ISO image to enable serial console"
    echo "It supports GRUB, SYSLINUX, and Systemd Boot config files."
    echo ""
    echo "It can be used directly or via docker"
    echo ""
    echo "Docker usage:"
    echo "Parameters:"
    echo "  input.iso          - Source ISO file"
    echo "  output.iso         - Output ISO file"
    echo "  speed              - Serial speed (default: 115200)"
    echo "  unit               - Serial unit/port (default: 0 = COM1/ttyS0)"
    echo "  word               - Word bits (default: 8)"
    echo "  parity             - Parity: no/even/odd (default: no)"
    echo "  stop               - Stop bits (default: 1)"
    echo "  add_kernel_console - Add kernel console param (default: true)"
    echo ""
    echo "Examples:"
    echo "  patch_iso_serial patch original.iso patched.iso"
    echo "  patch_iso_serial patch original.iso patched.iso 9600 0 8 even 1 false"
}

cmd_patch_iso_serial_argparse() {
    local -n __efi="$1";
    local -n __speed="$2";
    local -n __unit="$3";
    local -n __word="$4";
    local -n __parity="$5";
    local -n __stop="$6";
    local -n __add_kernel_console="$7";

    shift 7

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --efi) __efi=true; shift 1;;
            --speed) __speed="$2"; shift 2;;
            --unit) __unit="$2"; shift 2;;
            --word) __word="$2"; shift 2;;
            --parity) __parity="$2"; shift 2;;
            --stop) __stop="$2"; shift 2;;
            --add-kernel-console) __add_kernel_console=true; shift 1;;
            *) break;;
        esac
    done
}

cmd_patch_iso_serial() {
    local input_iso="$1"
    local output_iso="$2"
    shift 2

    local efi=false
    local speed="115200"
    local unit="0"
    local word="8"
    local parity="no"
    local stop="1"
    local add_kernel_console=

    cmd_patch_iso_serial_argparse efi speed unit word parity stop add_kernel_console "$@"

    local image_mode="bios"
    if [[ "$efi" == "true" ]]; then
        image_mode="uefi"
    fi

    _hdr "=== ISO Serial Console Patcher ==="
    _inf "Input:  $input_iso"
    _inf "Output: $output_iso"
    _inf "Mode:   $image_mode"
    _inf "Serial: COM$((unit+1))/ttyS$unit at speed=$speed, word=$word, parity=$parity, stop=$stop"
    _inf "Kernel console: $add_kernel_console"
    echo ""
    
    # Validate required parameters
    if [[ -z "$input_iso" || -z "$output_iso" ]]; then
        _die "input_iso and output_iso are required"
    fi

    # Check if input file exists
    if [[ ! -f "$input_iso" ]]; then
        _die "Input ISO '$input_iso' not found"
    fi

    # Create working directory
    local work_dir="/tmp/iso_patch_$$"
    mkdir -p "$work_dir"

    local iso_contents=$(cmd_iso_unpack "$input_iso" "$work_dir")
    
    # Cleanup function
    cleanup() {
        echo "Cleaning up..."
        rm -rf "$work_dir"
    }
    trap cleanup EXIT
    
    # Find and patch all GRUB config files
    _patch_grub_configs "$iso_contents/boot/grub" "$speed" "$unit" "$word" "$parity" "$stop" "$add_kernel_console"

    # Find and patch all isolinux/syslinux config files
    _patch_syslinux_configs "$iso_contents/boot/syslinux" "$speed" "$unit" "$word" "$parity" "$stop" "$add_kernel_console"
    _patch_syslinux_configs "$iso_contents/boot/isolinux" "$speed" "$unit" "$word" "$parity" "$stop" "$add_kernel_console"

    # Find and patch all systemd-boot config files
    _patch_systemd_boot_configs "$iso_contents/loader" "$speed" "$unit" "$word" "$parity" "$stop" "$add_kernel_console"
    
    # Build command array
    local cmd_args=(
        "xorriso" "-as" "mkisofs" 
        "-V" "linux-iso"
        "-o" "$output_iso" 
        "-J" "-joliet-long" 
        "-rational-rock"
    )
    
    # Strict mode handling based on user input
    if [[ "$image_mode" == "uefi" ]]; then
        _inf "Creating UEFI-only ISO..."

        # Check for UEFI
        local has_uefi=false
        local efi_boot_file=""
        for file in "${efi_check_files[@]}"; do
            file_path=$(_case_correct_path "$iso_contents" "$file")
            _inf "Checking for $file @ $file_path"

            if [[ -f "$file_path" ]]; then
                has_uefi=true
                efi_boot_file="$file_path"
                _inf "Found UEFI boot support"
                break
            fi
        done
        
        if [[ "$has_uefi" != "true" ]]; then
            _die "UEFI mode requested but no UEFI boot files found in ISO"
        fi
        
        # Create a FAT32 disk image for UEFI boot
        local fat32_disk_image="$work_dir/fat32_disk.img"
        dd if=/dev/zero of="$fat32_disk_image" bs=1M count=300
        mformat -i "$fat32_disk_image" -F ::

        # Create directory structure in FAT32 image
        find "$iso_contents" -type d -print0 | while IFS= read -r -d '' dir; do
            local rel_path="${dir#$iso_contents}"
            if [[ -n "$rel_path" ]]; then
                mmd -i "$fat32_disk_image" ::"$rel_path" 2>/dev/null || true
            fi
        done

        # Copy all files to FAT32 image
        find "$iso_contents" -type f -print0 | while IFS= read -r -d '' file; do
            local rel_path="${file#$iso_contents}"
            mcopy -i "$fat32_disk_image" "$file" ::"$rel_path" 2>/dev/null || true
        done

        cmd_args+=(
            "-eltorito-platform" "efi"
            "-isohybrid-gpt-basdat"
            "-partition_offset" "16"
            "-append_partition" "2" "$EFI_PARTITION_GUID" "$fat32_disk_image"
            "-eltorito-alt-boot"
            "-e" "--interval:appended_partition_2:all::"
            "-no-emul-boot"
        )
    else
        # BIOS mode
        _inf "Creating BIOS-only ISO..."

        local boot_bin=""
        local boot_cat=""
        local mbr_file=""

        local isolinux_check_files=(
            "isolinux/isolinux.bin"
            "boot/isolinux/isolinux.bin"
            "syslinux/isolinux.bin"
            "boot/syslinux/isolinux.bin"
        )

        local efi_check_files=(
            "efi/boot/bootx64.efi"
        )
        
        # Check for various boot loaders
        for file in "${isolinux_check_files[@]}"; do
            file_path=$(_case_correct_path "$iso_contents" "$file")
            _inf "Checking for $file @ $file_path"

            if [[ -f "$file_path" ]]; then
                boot_bin="$file_path"
                boot_dir=$(dirname "$file_path")
                boot_cat="$boot_dir/boot.cat"

                if [[ -f "$boot_dir/isohdpfx.bin" ]]; then
                    mbr_file="$boot_dir/isohdpfx.bin"
                fi

                _inf "Found ISOLINUX boot loader"
                break
            fi
        done
        
        if [[ -z "$boot_bin" ]]; then
            _die "BIOS mode requested but no BIOS boot files found in ISO"
        fi
        
        cmd_args+=(
            "-b" "${boot_bin#$iso_contents}" 
            "-c" "${boot_cat#$iso_contents}" 
            "-boot-load-size" "4" 
            "-boot-info-table"
            "-no-emul-boot" 
        )
        
        # Add MBR if available
        if [[ -n "$mbr_file" ]]; then
            cmd_args+=(
                "-isohybrid-mbr" "$mbr_file"
                "-partition_cyl_align" "off"
                "--mbr-force-bootable"
            )
        fi
    fi
    
    # Add source directory
    cmd_args+=("$iso_contents")
    
    _inf "Repacking ISO with command:"
    for arg in "${cmd_args[@]}"; do
        _inf "ARG:  $arg"
    done
    
    # Execute repack command
    if "${cmd_args[@]}"; then
        _inf ""
        _inf "✓ Successfully created: $output_iso"
        _inf "  Mode: $image_mode"
        _inf "  Serial console enabled on COM$((unit+1))/ttyS$unit"
        _inf "  Connect with: screen /dev/ttyS$unit $speed"
        return 0
    else
        _die "Failed to repack ISO"
        return 1
    fi
}

_patch_grub_configs() {
    local grub_dir="$1"
    local speed="$2"
    local unit="$3"
    local word="$4"
    local parity="$5"
    local stop="$6"
    local add_kernel_console="$7"

    _hdr "=== GRUB Config Patcher ($grub_dir) ==="

    local grub_configs
    grub_configs=$(find "$grub_dir" -name "*.cfg" | sort | uniq)

    if [[ -z "$grub_configs" ]]; then
        _inf "Warning: No GRUB config files found"
        _inf "Proceeding without GRUB modification..."
        return 0
    fi

    _inf "Found config files:"
    for grub_cfg in $grub_configs; do
        _inf "> $grub_cfg"
    done

    local grub_serial_config="serial --unit=$unit --speed=$speed --word=$word --parity=$parity --stop=$stop"
    local grub_terminal_input_config="terminal_input console serial"
    local grub_terminal_output_config="terminal_output console serial"

    local kernel_console_config="console=ttyS$unit,${speed}n${word} earlyprintk=serial,ttyS$unit,$speed"

    echo "$grub_configs" | while read -r grub_cfg; do
        _inf "Patching: ${grub_cfg}"
        
        # Create backup and patch
        cp "$grub_cfg" "$grub_cfg.bak"
        
        # Remove existing serial/terminal lines and add new ones at the top
        awk -v serial="$grub_serial_config" -v terminal_input="$grub_terminal_input_config" -v terminal_output="$grub_terminal_output_config" '
            BEGIN { 
                print serial
                print terminal_input
                print terminal_output
                print ""
            }
            /^serial / { next }
            /^terminal_input/ { next }
            /^terminal_output/ { next }
            { print }
        ' "$grub_cfg" > "$grub_cfg.tmp" && mv "$grub_cfg.tmp" "$grub_cfg"
        
        # Add kernel console parameter if requested
        if [[ -n "$add_kernel_console" ]]; then
            awk -v console="$kernel_console_config" '
                /^\s*linux.*vmlinuz/ {
                    if (!/console=ttyS/ && !/earlyprintk=serial/) {
                        print $0 " " console
                        next
                    }
                }
                { print }
            ' "$grub_cfg" > "$grub_cfg.tmp" && mv "$grub_cfg.tmp" "$grub_cfg"
        fi

        _inf "${grub_cfg} :: GRUB config patching completed"
        _inf "---------------------------------------------------------"
        diff -U 5 "$grub_cfg.bak" "$grub_cfg"

        if [[ -f "$grub_cfg.bak" ]]; then
            rm "$grub_cfg.bak"
        fi
        if [[ -f "$grub_cfg.tmp" ]]; then
            rm "$grub_cfg.tmp"
        fi
    done
}

_patch_syslinux_configs() {
    local syslinux_dir="$1"
    local speed="$2"
    local unit="$3"
    local word="$4"
    local parity="$5"
    local stop="$6"
    local add_kernel_console="$7"

    _hdr "=== SYSLINUX Config Patcher ($syslinux_dir) ==="

    local syslinux_configs
    syslinux_configs=$(find "$syslinux_dir" -name "*.cfg" | sort | uniq)


    if [[ -z "$syslinux_configs" ]]; then
        _inf "Warning: No syslinux config files found"
        _inf "Proceeding without syslinux modification..."
        return 0
    fi

    _inf "Found config files:"
    for syslinux_cfg in $syslinux_configs; do
        _inf "> $syslinux_cfg"
    done

    local syslinux_serial_config="SERIAL 0 $speed"
    local kernel_console_config="console=ttyS$unit,${speed}n${word} earlyprintk=serial,ttyS$unit,$speed"

    if [[ -z "$syslinux_configs" ]]; then
        _inf "Warning: No syslinux config files found"
        _inf "Proceeding without syslinux modification..."
        return 0
    fi

    _inf "Found config files:"
    _inf "$syslinux_configs" | sed "s|$syslinux_dir/||"

    echo "$syslinux_configs" | while read -r syslinux_cfg; do
        _inf "Patching: ${syslinux_cfg}"

        cp "$syslinux_cfg" "$syslinux_cfg.bak"
        awk -v serial="$syslinux_serial_config" 'BEGIN { IGNORECASE=1 }
            BEGIN { 
                print serial
                print ""
            }
            /^SERIAL/ { next }
            { print }
        ' "$syslinux_cfg" > "$syslinux_cfg.tmp" && mv "$syslinux_cfg.tmp" "$syslinux_cfg"

        if [[ -n "$add_kernel_console" ]]; then
            awk -v console="$kernel_console_config" 'BEGIN { IGNORECASE=1 }
            /^\s*label/ {
                linux_block=0;
                print $0;
                next
            }
            /^\s*linux/ {
                linux_block=1;
                print $0;
                next
            }
            linux_block && /^\s*append/ {
                print $0 " " console;
                linux_block=0;
                next
            }
            { print }
            ' "$syslinux_cfg" > "$syslinux_cfg.tmp" && mv "$syslinux_cfg.tmp" "$syslinux_cfg"

            # Handle append lines for kernel/vmlinuz using awk to add console params
            awk -v console="$kernel_console_config" '
            /^\s*kernel.*vmlinuz/ {
                kernel_block=1;
                print $0;
                next
            }
            kernel_block && /^\s*append/ {
                print $0 " " console;
                kernel_block=0;
                next
            }
            { print }
            ' "$syslinux_cfg" > "$syslinux_cfg.tmp" && mv "$syslinux_cfg.tmp" "$syslinux_cfg"
        fi

        _inf "${syslinux_cfg} :: SYSLINUX config patching completed"
        _inf "---------------------------------------------------------"
        diff -U 5 "$syslinux_cfg.bak" "$syslinux_cfg"

        if [[ -f "$syslinux_cfg.bak" ]]; then
            rm "$syslinux_cfg.bak"
        fi
        if [[ -f "$syslinux_cfg.tmp" ]]; then
            rm "$syslinux_cfg.tmp"
        fi
    done
}

_patch_systemd_boot_configs() {
    local systemd_boot_dir="$1"
    local speed="$2"
    local unit="$3"
    local word="$4"
    local parity="$5"
    local stop="$6"
    local add_kernel_console="$7"

    _hdr "=== Systemd Boot Config Patcher ($systemd_boot_dir) ==="

    local systemd_boot_configs
    systemd_boot_configs=$(find "$systemd_boot_dir" -name "*.conf" | sort | uniq)

    if [[ -z "$systemd_boot_configs" ]]; then
        _inf "Warning: No systemd boot config files found"
        _inf "Proceeding without systemd boot modification..."
        return 0
    fi

    _inf "Found config files:"
    for systemd_boot_cfg in $systemd_boot_configs; do
        _inf "> $systemd_boot_cfg"
    done

    local kernel_console_config="console=ttyS$unit,${speed}n${word} earlyprintk=serial,ttyS$unit,$speed"

    echo "$systemd_boot_configs" | while read -r systemd_boot_cfg; do
        _inf "Patching: ${systemd_boot_cfg}"

        cp "$systemd_boot_cfg" "$systemd_boot_cfg.bak"

        # Overwrite options
        awk -v console="$kernel_console_config" 'BEGIN { IGNORECASE=1 }
            /^\s*options/ {
                print $0 " " console;
                next
            }
            { print }
        ' "$systemd_boot_cfg" > "$systemd_boot_cfg.tmp" && mv "$systemd_boot_cfg.tmp" "$systemd_boot_cfg"

        _inf "${systemd_boot_cfg} :: Systemd Boot config patching completed"
        _inf "---------------------------------------------------------"
        diff -U 5 "$systemd_boot_cfg.bak" "$systemd_boot_cfg"

        if [[ -f "$systemd_boot_cfg.bak" ]]; then
            rm "$systemd_boot_cfg.bak"
        fi
        if [[ -f "$systemd_boot_cfg.tmp" ]]; then
            rm "$systemd_boot_cfg.tmp"
        fi
    done
}

################################################################################
# Docker image Utils
#

DOCKER_IMAGE_NAME="96d75c30-5059-iso-patch"

read -r -d '' DOCKER_IMAGE_DOCKERFILE <<'EOF'
FROM alpine:latest
RUN apk add --no-cache xorriso bash mtools
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
    ( set -x; docker run -it --rm "${mount_args[@]}" -v "$SCRIPT_PATH:/bin/$_script_basename" --entrypoint "/bin/$_script_basename" "$_docker_image_id" "$@" )
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

_hdr() { # blue
    local C="\033[1;33m"
    local R="\033[0m"
    printf "${C}%s${R}\n" "$*"
}

_case_correct_path() {
    # given a lowercase path, find the file and return the correctly cased path
    # Example:
    #   given path_dir = /tmp/iso
    #   and path_file = efi/boot/bootx64.efi
    #   return /tmp/iso/EFI/BOOT/BOOTX64.EFI

    local base_dir="$1"
    local target_path="$2"
    
    # Use find with case-insensitive name matching
    local result=$(find "$base_dir" -ipath "*/$target_path" -print -quit 2>/dev/null)
    
    # Return the result (empty if not found)
    echo "$result"
}

# Make script callable directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    _main "$@"
fi

