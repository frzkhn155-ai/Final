# Quick test script to verify ORB strategy runs correctly
import os
import sys
import time

# Read original bot and force ORB time check
os.chdir(r"C:\Users\ashra\Final-ORB-Only")

# Set environment variables
os.environ["UPSTOX_EMAIL"] = "frzkhn155@gmail.com"
os.environ["UPSTOX_PASSWORD"] = "vdeahogzvpsmfirv"
os.environ["UPSTOX_MOBILE"] = "7397408750"
os.environ["UPSTOX_PASSCODE"] = "952495"
os.environ["UPSTOX_API_KEY"] = "ea9b2ade-6720-4a0b-a8a5-6e1710f55844"
os.environ["UPSTOX_API_SECRET"] = "csxmppf5zd"

# Read and modify the bot to test ORB immediately
with open("Both4withcache10_headless.py", "r", encoding="utf-8") as f:
    content = f.read()

# Replace the time check to allow ORB to run now (for testing only)
old_check = '''    if current_time < "09:15":'''
new_check = '''    if current_time < "00:00":'''  # TEST: always reset ORB

content = content.replace(old_check, new_check)

# Replace 09:30 check to run now
old_primary = '''    if current_time >= "09:30" and now < cutoff and not ORB_PROCESSED_TODAY:'''
new_primary = '''    if True:  # TEST: force ORB to run now'''
content = content.replace(old_primary, new_primary)

# Save test version
with open("Both4withcache10_headless_test.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Test file created: Both4withcache10_headless_test.py")
print("Run with: python Both4withcache10_headless_test.py")