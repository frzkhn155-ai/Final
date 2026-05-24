#!/usr/bin/env python3
"""
Upstox Shared Token Manager
============================
Handles token generation, caching, and validation across all three trading bot repos.
Tokens are cached for 24 hours to avoid regenerating them on every run.
"""

import os
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
import upstox_client
from upstox_client.models.token_request import TokenRequest


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

# Shared cache directory — all three repos read/write here so they share one token
SHARED_CACHE_DIR = Path.home() / ".upstox_bot_cache"
SHARED_CACHE_DIR.mkdir(parents=True, exist_ok=True)

TOKEN_CACHE_FILE = SHARED_CACHE_DIR / "upstox_token.txt"
METADATA_FILE    = SHARED_CACHE_DIR / "upstox_token_metadata.json"
TOKEN_EXPIRY_HOURS = 24
CREDENTIALS_ENV_VARS = ("UPSTOX_API_KEY", "UPSTOX_API_SECRET")
CREDENTIALS_CONFIG_FILE = "upstox_config.json"


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _load_credentials():
    """Load Upstox API credentials from environment or config file."""
    # Try environment variables first
    api_key = os.environ.get("UPSTOX_API_KEY", "").strip()
    api_secret = os.environ.get("UPSTOX_API_SECRET", "").strip()
    
    if api_key and api_secret:
        return api_key, api_secret
    
    # Try config file
    if Path(CREDENTIALS_CONFIG_FILE).exists():
        try:
            with open(CREDENTIALS_CONFIG_FILE, "r") as f:
                config = json.load(f)
                api_key = config.get("api_key", "").strip()
                api_secret = config.get("api_secret", "").strip()
                if api_key and api_secret:
                    return api_key, api_secret
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️  Error reading {CREDENTIALS_CONFIG_FILE}: {e}")
    
    # Credentials not found
    raise ValueError(
        f"Upstox credentials not found!\n\n"
        f"Set environment variables:\n"
        f"  export UPSTOX_API_KEY='your_key'\n"
        f"  export UPSTOX_API_SECRET='your_secret'\n\n"
        f"OR create {CREDENTIALS_CONFIG_FILE}:\n"
        f'{{"api_key": "your_key", "api_secret": "your_secret"}}'
    )


def _load_metadata():
    """Load token metadata (generation time, expiry, etc.)."""
    if not Path(METADATA_FILE).exists():
        return None
    try:
        with open(METADATA_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def _save_metadata(token, generated_at, expiry):
    """Save token metadata."""
    metadata = {
        "token": token,
        "generated_at": generated_at.isoformat(),
        "expiry": expiry.isoformat(),
    }
    with open(METADATA_FILE, "w") as f:
        json.dump(metadata, f, indent=2)


def _is_token_valid(metadata):
    """Check if cached token is still valid."""
    if not metadata:
        return False
    
    try:
        expiry = datetime.fromisoformat(metadata.get("expiry", ""))
        return datetime.now() < expiry
    except (ValueError, KeyError):
        return False


# ══════════════════════════════════════════════════════════════════════════════
# MAIN FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def generate_token(force=False):
    """
    Generate a new Upstox access token.
    
    Args:
        force (bool): If True, ignore cache and generate new token
    
    Returns:
        str: Access token
    """
    # Check cache first (unless force=True)
    if not force:
        metadata = _load_metadata()
        if metadata and _is_token_valid(metadata):
            print(f"✓ Using cached token (expires at {metadata['expiry']})")
            return metadata["token"]
    
    print("🔄 Generating new Upstox token...")
    
    try:
        api_key, api_secret = _load_credentials()
    except ValueError as e:
        print(f"❌ {e}")
        raise
    
    try:
        # Create client and generate token
        client = upstox_client.Client(api_key=api_key, api_secret=api_secret)
        token_request = TokenRequest(
            code=None,  # Not needed for token refresh
            client_id=api_key,
            secret=api_secret,
            grant_type="client_credentials"
        )
        
        # Fetch token
        response = client.get_token(token_request)
        access_token = response.access_token
        
        # Calculate expiry (24 hours from now)
        generated_at = datetime.now()
        expiry = generated_at + timedelta(hours=TOKEN_EXPIRY_HOURS)
        
        # Save to cache files
        with open(TOKEN_CACHE_FILE, "w") as f:
            f.write(access_token)
        _save_metadata(access_token, generated_at, expiry)
        
        print(f"✓ Token generated successfully")
        print(f"  Generated: {generated_at.isoformat()}")
        print(f"  Expires:   {expiry.isoformat()}")
        
        return access_token
    
    except Exception as e:
        print(f"❌ Failed to generate token: {e}")
        raise


def get_token():
    """
    Get current Upstox access token.
    Returns cached token if valid, otherwise generates a new one.
    
    Returns:
        str: Access token
    """
    metadata = _load_metadata()
    
    # Check if cache is valid
    if metadata and _is_token_valid(metadata):
        token = metadata.get("token", "").strip()
        if token:
            return token
    
    # Cache invalid or missing, generate new token
    return generate_token(force=True)


def refresh_token_if_needed():
    """
    Refresh token if expired or about to expire (within 1 hour).
    
    Returns:
        str: Access token (new or cached)
    """
    metadata = _load_metadata()
    
    if not metadata:
        return generate_token(force=True)
    
    try:
        expiry = datetime.fromisoformat(metadata.get("expiry", ""))
        time_remaining = expiry - datetime.now()
        
        # Refresh if less than 1 hour remaining
        if time_remaining < timedelta(hours=1):
            print(f"⚠️  Token expiring soon ({time_remaining}). Refreshing...")
            return generate_token(force=True)
        else:
            token = metadata.get("token", "").strip()
            if token:
                return token
    except ValueError:
        pass
    
    return generate_token(force=True)


def get_token_status():
    """
    Get detailed token status.
    
    Returns:
        dict: Token status information
    """
    metadata = _load_metadata()
    
    if not metadata:
        return {
            "token_exists": False,
            "valid": False,
            "generated_at": None,
            "expiry": None,
            "hours_remaining": None,
        }
    
    try:
        generated_at = datetime.fromisoformat(metadata.get("generated_at", ""))
        expiry = datetime.fromisoformat(metadata.get("expiry", ""))
        now = datetime.now()
        valid = now < expiry
        hours_remaining = (expiry - now).total_seconds() / 3600
        
        return {
            "token_exists": bool(metadata.get("token")),
            "valid": valid,
            "generated_at": generated_at.isoformat(),
            "expiry": expiry.isoformat(),
            "hours_remaining": round(hours_remaining, 1),
        }
    except ValueError:
        return {
            "token_exists": bool(metadata.get("token")),
            "valid": False,
            "generated_at": None,
            "expiry": None,
            "hours_remaining": None,
        }


def clear_token_cache():
    """Clear cached token files."""
    for file in [TOKEN_CACHE_FILE, METADATA_FILE]:
        if Path(file).exists():
            Path(file).unlink()
            print(f"✓ Deleted {file}")


# ══════════════════════════════════════════════════════════════════════════════
# CLI INTERFACE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "generate":
            print("Generating fresh token (ignoring cache)...")
            try:
                token = generate_token(force=True)
                print(f"✓ New token: {token[:50]}...")
            except Exception as e:
                print(f"❌ {e}")
                sys.exit(1)
        
        elif command == "get":
            try:
                token = get_token()
                print(f"✓ Token: {token[:50]}...")
            except Exception as e:
                print(f"❌ {e}")
                sys.exit(1)
        
        elif command == "status":
            status = get_token_status()
            print("\nToken Status:")
            print("=" * 50)
            for key, value in status.items():
                print(f"  {key}: {value}")
            print("=" * 50)
        
        elif command == "refresh":
            try:
                token = refresh_token_if_needed()
                print(f"✓ Token: {token[:50]}...")
            except Exception as e:
                print(f"❌ {e}")
                sys.exit(1)
        
        elif command == "clear":
            clear_token_cache()
        
        else:
            print(f"Unknown command: {command}")
            print("\nUsage:")
            print("  python token_manager.py generate  - Generate fresh token")
            print("  python token_manager.py get       - Get current token (from cache)")
            print("  python token_manager.py status    - Show token status")
            print("  python token_manager.py refresh   - Refresh if needed")
            print("  python token_manager.py clear     - Clear cache")
    else:
        # Default: print usage
        print("Token Manager CLI")
        print("\nUsage: python token_manager.py <command>")
        print("\nCommands:")
        print("  generate  - Generate fresh token (force)")
        print("  get       - Get current token (cached or new)")
        print("  status    - Show token metadata")
        print("  refresh   - Refresh if expiring soon")
        print("  clear     - Clear all cached tokens")
