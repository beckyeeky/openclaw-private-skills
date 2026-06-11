#!/usr/bin/env python3
"""
Send multiple photos as a Telegram media group (album).

Requires TELEGRAM_BOT_TOKEN env var and --chat-id / CHAT_ID env var.
No hardcoded credentials.

Usage:
    TELEGRAM_BOT_TOKEN="xxx" python3 send_album.py --chat-id "-10012345" pic1.png pic2.png "Album caption"
    python3 send_album.py --chat-id "-10012345" --thread-id 55 pic1.png pic2.png
"""

import sys
import os
import json
import argparse
import requests


def send_media_group(bot_token, chat_id, image_paths, caption=None, thread_id=None):
    """Send a media group (up to 10 images). No shell injection — uses params, not string building."""
    if len(image_paths) > 10:
        print("Error: Maximum 10 images allowed", file=sys.stderr)
        return False

    if len(image_paths) < 2:
        print("Error: Media group requires at least 2 images", file=sys.stderr)
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMediaGroup"

    media = []
    files = {}

    for i, img_path in enumerate(image_paths):
        if not os.path.exists(img_path):
            print(f"Warning: File not found: {img_path}", file=sys.stderr)
            continue

        field_name = f"photo_{i}"
        item = {
            "type": "photo",
            "media": f"attach://{field_name}",
        }
        # Caption only on first photo
        if i == 0 and caption:
            item["caption"] = caption

        media.append(item)
        files[field_name] = open(img_path, 'rb')

    if len(media) < 2:
        print("Error: Need at least 2 valid images", file=sys.stderr)
        return False

    data = {
        "chat_id": chat_id,
        "media": json.dumps(media),
    }
    if thread_id:
        data["message_thread_id"] = thread_id

    try:
        response = requests.post(url, data=data, files=files, timeout=30)
        result = response.json()
        if result.get("ok"):
            print("Album sent successfully", file=sys.stderr)
            return True
        else:
            print(f"Error: {result.get('description', 'Unknown')}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return False
    finally:
        for f in files.values():
            f.close()


def main():
    parser = argparse.ArgumentParser(description="Send Telegram photo album")
    parser.add_argument("images", nargs="+", help="Image file paths")
    parser.add_argument("--chat-id", "-c", help="Chat ID (overrides CHAT_ID env)")
    parser.add_argument("--thread-id", "-t", type=int, help="Thread/topic ID")
    parser.add_argument("--caption", "-m", nargs="*", help="Caption text")

    args = parser.parse_args()

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        print("Error: TELEGRAM_BOT_TOKEN env var not set", file=sys.stderr)
        sys.exit(1)

    chat_id = args.chat_id or os.environ.get("CHAT_ID")
    if not chat_id:
        print("Error: No chat_id. Set --chat-id or CHAT_ID env var", file=sys.stderr)
        sys.exit(1)

    caption = " ".join(args.caption) if args.caption else None

    send_media_group(bot_token, chat_id, args.images, caption, args.thread_id)


if __name__ == "__main__":
    main()
