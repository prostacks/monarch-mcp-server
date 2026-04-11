#!/usr/bin/env python3
"""Extract Monarch token from local keyring for Railway deployment.

Usage:
    python extract_token.py

Prerequisites:
    Run login_setup.py first to authenticate with Monarch and store the token.
"""

import keyring

KEYRING_SERVICE = "com.mcp.monarch-mcp-server"
KEYRING_USERNAME = "monarch-token"

token = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
if token:
    print(f"Token found ({len(token)} chars)")
    print()
    print("Run this command to set it on Railway:")
    print()
    print(f'railway vars set MONARCH_TOKEN="{token}"')
else:
    print("No token found in keyring. Run login_setup.py first.")
