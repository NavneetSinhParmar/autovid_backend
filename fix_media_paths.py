"""
Migration script to fix duplicate /media/ paths in database

This script fixes URLs like:
  /media/app/media/company/file.mp4 -> /media/company/file.mp4
  https://domain.com/media/app/media/company/file.mp4 -> https://domain.com/media/company/file.mp4
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
import re

load_dotenv()

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "autovid")

async def fix_duplicate_media_paths():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    
    # Pattern to match duplicate /media/ paths
    # Matches: /media/app/media/ or /media/./media/ or media/app/media/
    duplicate_pattern = re.compile(r'(/media/)(app/media/|\.\/media/|media/)')
    
    print("🔍 Scanning database for duplicate /media/ paths...")
    
    # Fix media collection
    media_docs = await db.media.find({}).to_list(length=None)
    media_fixed = 0
    
    for doc in media_docs:
        file_url = doc.get("file_url", "")
        if duplicate_pattern.search(file_url):
            # Remove duplicate /media/ or ./media/ or app/media/
            fixed_url = re.sub(r'(app/media/|\.\/media/|media/)', '', file_url, count=1)
            
            await db.media.update_one(
                {"_id": doc["_id"]},
                {"$set": {"file_url": fixed_url}}
            )
            print(f"  ✓ Fixed media: {file_url} -> {fixed_url}")
            media_fixed += 1
    
    # Fix templates collection
    template_docs = await db.templates.find({}).to_list(length=None)
    template_fixed = 0
    
    for doc in template_docs:
        needs_update = False
        updates = {}
        
        # Fix base_video_url (can be string or array)
        if "base_video_url" in doc:
            base_video = doc["base_video_url"]
            if isinstance(base_video, list):
                fixed_videos = [re.sub(r'(app/media/|\.\/media/|/media/media/)', '/media/', url) for url in base_video]
                if fixed_videos != base_video:
                    updates["base_video_url"] = fixed_videos
                    needs_update = True
            elif isinstance(base_video, str) and duplicate_pattern.search(base_video):
                updates["base_video_url"] = re.sub(r'(app/media/|\.\/media/|/media/media/)', '/media/', base_video)
                needs_update = True
        
        # Fix base_image_url
        if "base_image_url" in doc:
            base_image = doc["base_image_url"]
            if isinstance(base_image, list):
                fixed_images = [re.sub(r'(app/media/|\.\/media/|/media/media/)', '/media/', url) for url in base_image]
                if fixed_images != base_image:
                    updates["base_image_url"] = fixed_images
                    needs_update = True
            elif isinstance(base_image, str) and duplicate_pattern.search(base_image):
                updates["base_image_url"] = re.sub(r'(app/media/|\.\/media/|/media/media/)', '/media/', base_image)
                needs_update = True
        
        # Fix base_audio_url
        if "base_audio_url" in doc:
            base_audio = doc["base_audio_url"]
            if isinstance(base_audio, list):
                fixed_audios = [re.sub(r'(app/media/|\.\/media/|/media/media/)', '/media/', url) for url in base_audio]
                if fixed_audios != base_audio:
                    updates["base_audio_url"] = fixed_audios
                    needs_update = True
            elif isinstance(base_audio, str) and duplicate_pattern.search(base_audio):
                updates["base_audio_url"] = re.sub(r'(app/media/|\.\/media/|/media/media/)', '/media/', base_audio)
                needs_update = True
        
        # Fix template_json.design.trackItemsMap items
        if "template_json" in doc:
            template_json = doc["template_json"]
            if "design" in template_json and "trackItemsMap" in template_json["design"]:
                track_items = template_json["design"]["trackItemsMap"]
                
                for item_id, item in track_items.items():
                    if "details" in item and "src" in item["details"]:
                        src = item["details"]["src"]
                        if duplicate_pattern.search(src):
                            fixed_src = re.sub(r'(app/media/|\.\/media/|/media/media/)', '/media/', src)
                            item["details"]["src"] = fixed_src
                            needs_update = True
                            print(f"  ✓ Fixed template item src: {src} -> {fixed_src}")
                
                if needs_update:
                    updates["template_json"] = template_json
        
        if needs_update:
            await db.templates.update_one(
                {"_id": doc["_id"]},
                {"$set": updates}
            )
            template_fixed += 1
            print(f"  ✓ Fixed template: {doc.get('template_name', 'Unknown')}")
    
    print(f"\n✅ Migration complete!")
    print(f"   Media records fixed: {media_fixed}")
    print(f"   Template records fixed: {template_fixed}")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(fix_duplicate_media_paths())
