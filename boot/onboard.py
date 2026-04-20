import os
import secrets
import sys

def validate_alpaca_key(key):
    # Basic validation: Alpaca keys are typically 20 characters (Key ID) or 40 (Secret)
    # This is just a hint, but we can check for minimum length and alphanumeric content.
    return len(key) >= 20 and any(c.isalnum() for c in key)

def main():
    try:
        # Resolve paths relative to the script location
        script_dir = os.path.dirname(os.path.abspath(__file__))
        env_path = os.path.normpath(os.path.join(script_dir, "..", ".env"))
        example_path = os.path.normpath(os.path.join(script_dir, "..", ".env.example"))

        if os.path.exists(env_path):
            print("[*] .env file already exists. Skipping onboarding.")
            return 0

        print("\n============================================================")
        print("           MAMMON TRADING ENGINE - ONBOARDING")
        print("============================================================\n")
        print("Welcome! Let's set up your environment credentials.")
        print("You can find your Alpaca keys at: https://alpaca.markets/ \n")
        
        api_key = ""
        while True:
            api_key = input("Enter your Alpaca API Key ID: ").strip()
            if validate_alpaca_key(api_key):
                break
            print("  -> [!] Invalid format. Key ID should be at least 20 characters. Try again.")

        api_secret = ""
        while True:
            api_secret = input("Enter your Alpaca API Secret: ").strip()
            if validate_alpaca_key(api_secret):
                break
            print("  -> [!] Invalid format. Secret should be at least 20 characters. Try again.")

        # Generate secure random tokens
        api_token = secrets.token_hex(16)
        admin_token = secrets.token_hex(16)

        print("\n[*] Writing configuration...")
        
        env_lines = []
        if os.path.exists(example_path):
            with open(example_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if "ALPACA_API_KEY=" in line:
                        env_lines.append(f"ALPACA_API_KEY={api_key}\n")
                    elif "ALPACA_API_SECRET=" in line:
                        env_lines.append(f"ALPACA_API_SECRET={api_secret}\n")
                    elif "MAMMON_API_TOKEN=" in line:
                        env_lines.append(f"MAMMON_API_TOKEN={api_token}\n")
                    elif "MAMMON_ADMIN_TOKEN=" in line:
                        env_lines.append(f"MAMMON_ADMIN_TOKEN={admin_token}\n")
                    else:
                        env_lines.append(line)
        else:
            # Fallback if .env.example is missing
            env_lines = [
                f"ALPACA_API_KEY={api_key}\n",
                f"ALPACA_API_SECRET={api_secret}\n",
                f"MAMMON_API_TOKEN={api_token}\n",
                f"MAMMON_ADMIN_TOKEN={admin_token}\n",
                "MAMMON_MAX_NOTIONAL_PER_ORDER=1000.0\n",
                "MAMMON_MAX_OPEN_POSITIONS=5\n",
                "MAMMON_MAX_DAILY_REALIZED_LOSS=50.0\n",
                "DATA_FETCH_INTERVAL=60\n",
                "LOG_LEVEL=INFO\n"
            ]

        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(env_lines)

        print("[+] .env file created successfully at:")
        print(f"    {env_path}")
        print("\n============================================================\n")
        return 0

    except KeyboardInterrupt:
        print("\n\n[!] Onboarding interrupted by user. Setup incomplete.")
        return 1
    except Exception as e:
        print(f"\n[!] Critical error during onboarding: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
