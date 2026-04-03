# Session 17 — 2026-04-03

## Goal
Set up SSH access to Hetzner VM from work laptop.

## What was done
1. Generated ed25519 SSH key at `~/.ssh/id_ed25519_hetzner` (fingerprint: `SHA256:HNT84AN8gyZgTTRew7gp+l58NI3i890Woy6M1T6WYCY`)
2. Created SSH config file at `~/.ssh/config` with `vm` alias pointing to `root@159.69.34.240`
3. Attempted to add public key to VM — **blocked**:
   - Hetzner Cloud dashboard "Add SSH Key" only applies to new servers, not existing ones
   - Hetzner web console requires VM-level login credentials (not Hetzner account credentials)
   - Neither `root` (blank password) nor Hetzner account email/password worked
   - Root credentials from original VM provisioning are not documented anywhere in this project
   - Rescue mode (temporary root password from Hetzner) was identified as an option but not attempted

## Outcome
SSH key pair and config are ready on the work laptop. The public key still needs to be added to the VM's `authorized_keys` — easiest path is a one-liner from the home PC which already has SSH access.

## Next steps
- From home PC: `ssh vm 'echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJv/94DRn7cPQU9eZyRblraOOWDavcOhQiNc6bVyvGCP moltbook-work-laptop" >> ~/.ssh/authorized_keys'`
- Investigate how root access was originally provisioned (check home PC `~/.ssh/` for the key used)
- Document root credentials so VM access isn't single-machine-dependent
