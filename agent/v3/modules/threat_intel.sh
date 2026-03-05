#!/bin/bash
# ============================================================================
# ZA Support Diagnostics — Threat Intelligence Module
# Queries external reputation databases for running processes, IPs, and emails.
# All output branded as "ZA Support Threat Intelligence" — no vendor names.
# ============================================================================

run_threat_intel() {
    local JSON_FILE="${1:-}"
    local REPORT_FILE="${2:-}"

    section "ZA SUPPORT THREAT INTELLIGENCE"
    echo "  Cross-referencing system activity against global threat databases..."
    echo "  This section may take several minutes due to API rate limits."
    echo ""

    local PROC_CHECKED=0 IP_CHECKED=0 EMAIL_CHECKED=0
    local PROC_THREATS=0 IP_THREATS=0 EMAIL_THREATS=0

    # ── 1. PROCESS BINARY HASH CHECK ─────────────────────────────────────────
    echo "── Running Process Binary Integrity Check ──"
    if [[ -z "${ZA_VT_API_KEY:-}" ]]; then
        : # not configured — skip silently
    else
        echo "  Collecting process binary hashes..."
        TOP_PROCS=$(ps -eo comm 2>/dev/null | sort -u | grep -v '^COMMAND$' | head -20)
        while IFS= read -r proc_name; do
            # Find the full path of the binary
            proc_path=$(which "$proc_name" 2>/dev/null || ps -eo comm,args | grep "^$proc_name " | awk '{print $2}' | head -1)
            [[ -z "$proc_path" || ! -f "$proc_path" ]] && continue

            sha256=$(shasum -a 256 "$proc_path" 2>/dev/null | awk '{print $1}')
            [[ -z "$sha256" ]] && continue

            PROC_CHECKED=$((PROC_CHECKED + 1))

            response=$(curl -s --max-time 10 \
                -H "x-apikey: $ZA_VT_API_KEY" \
                "https://www.virustotal.com/api/v3/files/$sha256" 2>/dev/null)

            malicious=$(echo "$response" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('data',{}).get('attributes',{}).get('last_analysis_stats',{}).get('malicious',0))
except:
    print(0)
" 2>/dev/null || echo "0")

            if [[ "${malicious:-0}" -gt 0 ]]; then
                echo "  [THREAT] $proc_name — flagged by $malicious engine(s)"
                echo "    Path: $proc_path"
                echo "    Hash: $sha256"
                echo "    Status: Cross-referenced against global malware signature databases — POSITIVE MATCH"
                PROC_THREATS=$((PROC_THREATS + 1))
            else
                echo "  [OK] $proc_name — no threats detected"
            fi

            # Rate limit: 4 requests/minute on free tier
            sleep 15
        done <<< "$TOP_PROCS"
    fi
    echo ""

    # ── 2. EXTERNAL IP REPUTATION CHECK ──────────────────────────────────────
    echo "── External IP Reputation Check ──"
    if [[ -z "${ZA_ABUSEIPDB_KEY:-}" ]]; then
        : # not configured — skip silently
    else
        echo "  Extracting established external connections..."
        EXTERNAL_IPS=$(netstat -an 2>/dev/null | awk '/ESTABLISHED/{print $5}' | \
            grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | \
            grep -v '^10\.\|^127\.\|^0\.\|^255\.' | \
            grep -vE '^172\.(1[6-9]|2[0-9]|3[01])\.' | \
            grep -v '^192\.168\.' | \
            sort -u | head -20)

        if [[ -z "$EXTERNAL_IPS" ]]; then
            echo "  [INFO] No external established connections found."
        else
            while IFS= read -r ip; do
                [[ -z "$ip" ]] && continue
                IP_CHECKED=$((IP_CHECKED + 1))

                response=$(curl -s --max-time 10 \
                    -H "Key: $ZA_ABUSEIPDB_KEY" \
                    -H "Accept: application/json" \
                    -G "https://api.abuseipdb.com/api/v2/check" \
                    --data-urlencode "ipAddress=$ip" \
                    --data "maxAgeInDays=90" 2>/dev/null)

                abuse_score=$(echo "$response" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('data',{}).get('abuseConfidenceScore',0))
except:
    print(0)
" 2>/dev/null || echo "0")

                country=$(echo "$response" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('data',{}).get('countryCode','Unknown'))
except:
    print('Unknown')
" 2>/dev/null || echo "Unknown")

                isp=$(echo "$response" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('data',{}).get('isp','Unknown'))
except:
    print('Unknown')
" 2>/dev/null || echo "Unknown")

                reports=$(echo "$response" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('data',{}).get('totalReports',0))
except:
    print(0)
" 2>/dev/null || echo "0")

                if [[ "${abuse_score:-0}" -gt 25 ]]; then
                    echo "  [SUSPICIOUS] $ip — Abuse score: ${abuse_score}%"
                    echo "    Country: $country | ISP: $isp | Reports: $reports"
                    echo "    Status: Checked against global IP reputation databases — FLAGGED"
                    IP_THREATS=$((IP_THREATS + 1))
                else
                    echo "  [OK] $ip ($country) — score: ${abuse_score}%"
                fi
            done <<< "$EXTERNAL_IPS"
        fi
    fi
    echo ""

    # ── 3. EMAIL BREACH CHECK ─────────────────────────────────────────────────
    echo "── Email Account Breach Check ──"
    if [[ -z "${ZA_HIBP_API_KEY:-}" ]]; then
        : # not configured — skip silently
    else
        echo "  Collecting configured email addresses..."
        # Extract from Mail accounts
        MAIL_EMAILS=$(defaults read com.apple.mail MailAccounts 2>/dev/null | \
            grep -oE '[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}' | sort -u)
        # Extract from iCloud
        ICLOUD_EMAILS=$(defaults read MobileMeAccounts 2>/dev/null | \
            grep -oE '[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}' | sort -u)

        ALL_EMAILS=$(echo -e "$MAIL_EMAILS\n$ICLOUD_EMAILS" | sort -u | grep -v '^$')

        if [[ -z "$ALL_EMAILS" ]]; then
            echo "  [INFO] No email accounts found in system preferences."
        else
            while IFS= read -r email; do
                [[ -z "$email" ]] && continue
                EMAIL_CHECKED=$((EMAIL_CHECKED + 1))

                response=$(curl -s --max-time 10 \
                    -H "hibp-api-key: $ZA_HIBP_API_KEY" \
                    -H "user-agent: ZA-Support-Diagnostics/3.3" \
                    "https://haveibeenpwned.com/api/v3/breachedaccount/$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote('$email'))" 2>/dev/null || echo "$email")" \
                    2>/dev/null)

                if [[ "$response" == "null" || -z "$response" ]]; then
                    echo "  [OK] ${email} — no breaches found"
                else
                    breach_count=$(echo "$response" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(len(d))
except:
    print(0)
" 2>/dev/null || echo "0")

                    breach_names=$(echo "$response" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    names = [b.get('Name','?') for b in d[:5]]
    print(', '.join(names))
except:
    print('Unknown')
" 2>/dev/null || echo "Unknown")

                    echo "  [BREACH] ${email} — found in ${breach_count} breach(es)"
                    echo "    Checked against a database of over 14 billion compromised credentials"
                    echo "    Breaches include: $breach_names"
                    EMAIL_THREATS=$((EMAIL_THREATS + 1))
                fi
                # HIBP rate limit
                sleep 2
            done <<< "$ALL_EMAILS"
        fi
    fi
    echo ""

    # ── SUMMARY ──────────────────────────────────────────────────────────────
    echo "── ZA Support Threat Intelligence Summary ──"
    echo "  Processes checked:    $PROC_CHECKED  |  Threats found: $PROC_THREATS"
    echo "  IPs checked:          $IP_CHECKED    |  Suspicious:    $IP_THREATS"
    echo "  Email accounts:       $EMAIL_CHECKED |  Breached:      $EMAIL_THREATS"
    echo ""

    TOTAL_TI_THREATS=$((PROC_THREATS + IP_THREATS + EMAIL_THREATS))
    if [[ "$TOTAL_TI_THREATS" -gt 0 ]]; then
        echo "  [ACTION REQUIRED] $TOTAL_TI_THREATS threat indicator(s) detected."
        echo "  Contact ZA Support immediately: admin@zasupport.com | 064 529 5863"
    else
        echo "  [CLEAR] No threat indicators detected in this scan."
    fi
    echo ""

    write_json "threat_intel" \
        "processes_checked"   "$PROC_CHECKED" \
        "process_threats"     "$PROC_THREATS" \
        "ips_checked"         "$IP_CHECKED" \
        "ip_threats"          "$IP_THREATS" \
        "emails_checked"      "$EMAIL_CHECKED" \
        "email_breaches"      "$EMAIL_THREATS" \
        "total_threats"       "$TOTAL_TI_THREATS"
}
