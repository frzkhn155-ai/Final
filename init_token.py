#!/usr/bin/env python3
"""
Upstox Token Initialization Script
===================================
Run this ONCE at the start of your trading day to generate/cache the shared token.
All three bots will then use this cached token without regenerating it.
"""

from token_manager import get_token, get_token_status
import sys


def main():
    print("\n" + "=" * 60)
    print("Upstox Token Initialization")
    print("=" * 60 + "\n")
    
    try:
        # Step 1: Get/generate token
        print("[1/2] Retrieving token...")
        token = get_token()
        print(f"✓ Token ready: {token[:50]}...\n")
        
        # Step 2: Show status
        print("[2/2] Token status:")
        status = get_token_status()
        for key, value in status.items():
            print(f"  {key}: {value}")
        
        print("\n" + "=" * 60)
        print("✓ Token ready! Your bots can now run.")
        print("  All three repositories will share this token.")
        print("=" * 60 + "\n")
        
        return 0
    
    except Exception as e:
        print(f"\n❌ Error: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
