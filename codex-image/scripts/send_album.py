#!/usr/bin/env python3
"""
Telegram 媒体组发送脚本
使用 OpenClaw 的 Telegram Bot 配置
"""

import sys
import requests
import os
import json

BOT_TOKEN = "8459669153:AAEUE_X-LH__vXA90DcDKNcq_rRsBNhIRcE"
CHAT_ID = "44095775"

def send_media_group(image_paths, caption=None):
    """发送媒体组（最多10张图片）"""
    
    if len(image_paths) > 10:
        print("Error: Maximum 10 images allowed")
        return False
    
    if len(image_paths) < 2:
        print("Error: Media group requires at least 2 images")
        return False
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMediaGroup"
    
    # 构建 media 数组
    media = []
    files = {}
    
    for i, img_path in enumerate(image_paths):
        if not os.path.exists(img_path):
            print(f"Warning: File not found: {img_path}")
            continue
        
        field_name = f"photo_{i}"
        item = {
            "type": "photo",
            "media": f"attach://{field_name}"
        }
        # 只在第一张图添加 caption
        if i == 0 and caption:
            item["caption"] = caption
            item["parse_mode"] = "HTML"
        
        media.append(item)
        
        files[field_name] = open(img_path, 'rb')
    
    if len(media) < 2:
        print("Error: Need at least 2 valid images")
        return False
    
    # media 参数需要是 JSON 字符串
    data = {
        "chat_id": CHAT_ID,
        "media": json.dumps(media)
    }
    
    try:
        print(f"Sending {len(media)} photos as album...")
        response = requests.post(url, data=data, files=files)
        
        result = response.json()
        if result.get("ok"):
            print("✅ Album sent successfully!")
            return True
        else:
            print(f"❌ Error: {result.get('description', 'Unknown error')}")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    finally:
        for f in files.values():
            f.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 send_album.py <image1> [image2] ... ['caption']")
        print("Example: python3 send_album.py ./pic1.png ./pic2.png 'My photos'")
        print("Note: Put caption in quotes if it has spaces")
        sys.exit(1)
    
    args = sys.argv[1:]
    caption = None
    
    # 判断最后一个参数是否是 caption（不含路径分隔符且不以图片扩展名结尾）
    last_arg = args[-1]
    valid_exts = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')
    
    if not last_arg.lower().endswith(valid_exts) and '/' not in last_arg and len(args) > 1:
        caption = last_arg
        image_paths = args[:-1]
    else:
        image_paths = args
    
    send_media_group(image_paths, caption)
