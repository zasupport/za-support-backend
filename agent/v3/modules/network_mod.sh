#!/bin/bash
# ============================================================================
# ZA Support — Network Module
# Collects: interfaces, WiFi SSID/signal, DNS, gateway, open ports,
#           VPN configs, proxy, IPv6 state
# Writes:   "network" section via write_json
# ============================================================================

collect_network() {
    local gateway dns_servers wifi_ssid wifi_rssi wifi_channel wifi_band
    local listen_ports_count vpn_configs interfaces_up ipv6_enabled

    # Default gateway
    gateway=$(netstat -rn 2>/dev/null | awk '/^default/{print $2; exit}')

    # Primary DNS servers (first 3)
    dns_servers=$(scutil --dns 2>/dev/null \
        | awk '/nameserver\[/{print $3}' | sort -u | head -3 | tr '\n' ' ' | xargs)

    # WiFi info via airport
    local airport_bin
    airport_bin="/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
    if [ -x "$airport_bin" ]; then
        wifi_ssid=$("$airport_bin" -I 2>/dev/null | awk -F': ' '/ SSID/{print $2}' | xargs)
        wifi_rssi=$("$airport_bin" -I 2>/dev/null | awk -F': ' '/agrCtlRSSI/{print $2}' | xargs)
        wifi_channel=$("$airport_bin" -I 2>/dev/null | awk -F': ' '/channel/{print $2}' | head -1 | xargs)
        # Determine band from channel
        local ch_num
        ch_num=$(printf '%s' "$wifi_channel" | grep -oE '^[0-9]+')
        if [ -n "$ch_num" ]; then
            [ "$ch_num" -le 14 ] && wifi_band="2.4 GHz" || wifi_band="5/6 GHz"
        else
            wifi_band="Unknown"
        fi
    else
        wifi_ssid="airport not available"
        wifi_rssi="N/A"
        wifi_channel="N/A"
        wifi_band="Unknown"
    fi

    # Count listening TCP/UDP ports
    listen_ports_count=$(lsof -i -P -n 2>/dev/null | grep -c LISTEN || echo "0")

    # VPN configuration count
    vpn_configs=$(scutil --nc list 2>/dev/null | grep -c ":" || echo "0")

    # Active interfaces (non-loopback, UP)
    interfaces_up=$(ifconfig 2>/dev/null \
        | awk '/^[a-z].*: flags/{iface=$1} /status: active/{print iface}' \
        | grep -v lo | tr '\n' ' ' | xargs)

    # IPv6 state on primary interface
    local primary_iface
    primary_iface=$(route get default 2>/dev/null | awk '/interface:/{print $2}' | head -1)
    if [ -n "$primary_iface" ]; then
        if ifconfig "$primary_iface" 2>/dev/null | grep -q "inet6"; then
            ipv6_enabled="YES"
        else
            ipv6_enabled="NO"
        fi
    else
        ipv6_enabled="Unknown"
    fi

    # Proxy settings
    local proxy_status
    proxy_status=$(scutil --proxy 2>/dev/null \
        | grep -E "HTTPEnable|HTTPSEnable" | awk '{print $1"="$3}' | tr '\n' ',' | sed 's/,$//')
    proxy_status="${proxy_status:-none}"

    write_json "network" \
        "gateway"            "${gateway:-N/A}" \
        "dns_servers"        "${dns_servers:-N/A}" \
        "wifi_ssid"          "${wifi_ssid:-Not connected}" \
        "wifi_rssi_dbm"      "${wifi_rssi:-N/A}" \
        "wifi_channel"       "${wifi_channel:-N/A}" \
        "wifi_band"          "$wifi_band" \
        "listen_ports_count" "$listen_ports_count" \
        "vpn_configs"        "$vpn_configs" \
        "active_interfaces"  "${interfaces_up:-N/A}" \
        "ipv6_enabled"       "$ipv6_enabled" \
        "proxy_config"       "$proxy_status"
}

collect_network
