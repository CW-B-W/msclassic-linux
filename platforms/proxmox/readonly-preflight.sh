#!/usr/bin/env bash
set -euo pipefail

PVE_CONF_DIR="${PVE_CONF_DIR:-/etc/pve/qemu-server}"
PVE_RENDER_NODE="${PVE_RENDER_NODE:-/dev/dri/renderD128}"
PVE_VIRGL_RENDER_SERVER="${PVE_VIRGL_RENDER_SERVER:-/usr/libexec/virgl_render_server}"

usage() {
  printf 'Usage: %s check VMID\n' "$0" >&2
  printf '       %s webui-plan VMID\n' "$0" >&2
  printf 'This tool is read-only. It never changes a VM or starts/stops one.\n' >&2
  exit 2
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

validate_vmid() {
  local vmid="$1"
  [[ "$vmid" =~ ^[0-9]+$ ]] || die "VMID must contain digits only"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

require_stopped_vm() {
  local vmid="$1"
  local status
  status="$(qm status "$vmid" 2>&1)" || die "cannot read VM $vmid status: $status"
  [[ "$status" == "status: stopped" ]] || die "VM $vmid must be stopped (reported: $status)"
}

preflight() {
  local vmid="$1"
  local config="$PVE_CONF_DIR/$vmid.conf"
  local pve_version pci qemu_help mesa_status

  require_command pveversion
  require_command lspci
  require_command kvm
  require_command qm
  require_command dpkg-query

  [[ -f "$config" ]] || die "VM configuration does not exist: $config"
  [[ -e "$PVE_RENDER_NODE" ]] || die "render node does not exist: $PVE_RENDER_NODE"
  [[ -x "$PVE_VIRGL_RENDER_SERVER" ]] || die "virgl_render_server is missing or not executable: $PVE_VIRGL_RENDER_SERVER (install virgl-server)"
  mesa_status="$(dpkg-query -W -f='${db:Status-Abbrev}' mesa-vulkan-drivers 2>/dev/null || true)"
  [[ "$mesa_status" == ii* ]] || die "mesa-vulkan-drivers is not installed on the PVE host"
  require_stopped_vm "$vmid"

  pve_version="$(pveversion 2>&1)" || die "pveversion failed: $pve_version"
  [[ "$pve_version" =~ pve-manager/9\.[12]([./-]|$) ]] || die "this profile requires Proxmox VE 9.1 or 9.2 (reported: $pve_version)"

  pci="$(lspci -nnk 2>&1)" || die "lspci failed: $pci"
  [[ "$pci" =~ [Ii]ntel ]] || die "an Intel host GPU was not found"
  [[ "$pci" =~ i915 ]] || die "the host Intel GPU is not bound to i915"

  qemu_help="$(kvm -device virtio-vga-gl,help 2>&1 || true)"
  [[ "$qemu_help" =~ hostmem ]] || die "PVE QEMU lacks virtio-vga-gl hostmem support"
  [[ "$qemu_help" =~ blob ]] || die "PVE QEMU lacks virtio-vga-gl blob support"
  [[ "$qemu_help" =~ venus ]] || die "PVE QEMU lacks virtio-vga-gl Venus support"

  if grep -Eq '^args:' "$config"; then
    die "VM $vmid already has custom args; merge must be reviewed manually"
  fi

  printf 'PVE VirGL/Venus preflight passed for stopped VM %s (read-only).\n' "$vmid"
}

webui_plan() {
  local vmid="$1"
  local config="$PVE_CONF_DIR/$vmid.conf"
  local original_vga qemu_args apply_cmd rollback_cmd

  preflight "$vmid"
  original_vga="$(sed -n 's/^vga: //p' "$config" | head -n 1)"
  [[ -n "$original_vga" ]] || original_vga="std"
  [[ "$original_vga" =~ ^virtio-gl(,|$) ]] || die "select VirGL GPU in VM $vmid Hardware → Display before generating the Venus plan"
  [[ "$PVE_RENDER_NODE" =~ ^/[A-Za-z0-9_./-]+$ ]] || die "render node contains unsupported characters"
  [[ "$original_vga" =~ ^[A-Za-z0-9_,=.-]+$ ]] || die "original display value contains unsupported characters"
  qemu_args="-set device.vga.hostmem=2G -set device.vga.blob=on -set device.vga.venus=on"
  apply_cmd="qm set $vmid --args '$qemu_args'"
  rollback_cmd="qm set $vmid --delete args"

  printf '\n# Proxmox WebUI change sheet — VM %s\n\n' "$vmid"
  printf 'This sheet is generated read-only. No command below has been executed.\n\n'
  printf '1. In Proxmox WebUI, select VM %s, choose **Shutdown**, and wait until its status is stopped.\n' "$vmid"
  printf '2. Open **Backup** for VM %s, choose **Backup now**, and retain that backup as the rollback point.\n' "$vmid"
  printf '3. Select the PVE node, open **Shell** in the WebUI, and verify the host Vulkan driver.\n\n'
  printf '   `dpkg-query -W mesa-vulkan-drivers virgl-server`\n\n'
  printf '   If either is absent: `apt update && apt install -y mesa-vulkan-drivers virgl-server`\n\n'
  printf '4. In that same visible WebUI Shell, review and then run this one VM-scoped command:\n\n'
  printf '   `%s`\n\n' "$apply_cmd"
  printf '5. Return to VM %s in the WebUI. Confirm **Hardware → Display** remains `VirGL GPU (virtio-gl)`; do not add a PCI device.\n' "$vmid"
  printf '6. Start the VM from the WebUI and reconnect using AnyDesk.\n\n'
  printf 'Rollback (with the VM stopped) is the retained WebUI backup, or this visible WebUI Shell command:\n\n'
  printf '   `%s`\n\n' "$rollback_cmd"
  printf 'Display retained by both apply and rollback: `%s`\n' "$original_vga"
}

[[ "$#" -eq 2 ]] || usage
command_name="$1"
vmid="$2"
validate_vmid "$vmid"

case "$command_name" in
  check) preflight "$vmid" ;;
  webui-plan) webui_plan "$vmid" ;;
  *) usage ;;
esac

