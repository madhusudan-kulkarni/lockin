# Security

lockin is a local self-control tool. It is not a security boundary.

- It uses `sudo` to write `/etc/hosts`, install nftables or iptables rules,
  deploy browser policies, and install a root systemd timer.
- Hardcore mode sets `chattr +i` on `/etc/hosts`. Root can still run
  `chattr -i`. The watchdog re-applies rules about once a minute.
- Report vulnerabilities as GitHub issues at
  https://github.com/madhusudan-kulkarni/lockin
