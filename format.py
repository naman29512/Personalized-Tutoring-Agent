import os
from pathlib import Path
import json
from docling.document_converter import DocumentConverter
from youtube_transcript_api import YouTubeTranscriptApi

INPUT_DIR = Path("material")
OUTPUT_DIR = Path("processed")

# FIX 1: Use Path joining. 
YOUTUBE_LINK_FILE = INPUT_DIR / "youtube.jsonl"
# Check against just the filename, not the full path
IGNORED_FILES = ["youtube.jsonl", ".DS_Store"]

print("Starting Docling Engine...")
converter = DocumentConverter()

OUTPUT_DIR.mkdir(exist_ok=True)

def youtube_format():
    print("\nExtracting YouTube Video...")
    
    if not YOUTUBE_LINK_FILE.exists():
        print("No youtube.jsonl file found. Skipping YouTube extraction.")
        return

    with open(YOUTUBE_LINK_FILE, "r", encoding="utf-8") as file:
        for i, line in enumerate(file, 1):
            line = line.strip()
            if not line:
                continue
                
            try:
                log = json.loads(line)
                raw_link = log["link"]
                
                if "youtu.be/" in raw_link:
                    video_id = raw_link.split("youtu.be/")[1].split("?")[0]
                elif "v=" in raw_link:
                    video_id = raw_link.split("v=")[1].split("&")[0]
                else:
                    video_id = raw_link
                
                transcript = YouTubeTranscriptApi().fetch(video_id)
                
                # --- NEW TIMESTAMP FORMATTING BLOCK ---
                formatted_lines = []
                for line in transcript:
                    # Safely grab the start time and text (handles both dict and object formats)
                    start_time = line['start'] if isinstance(line, dict) else line.start
                    text = line['text'] if isinstance(line, dict) else line.text
                    
                    # Convert raw seconds into minutes and seconds
                    minutes = int(start_time // 60)
                    seconds = int(start_time % 60)
                    
                    # Create the [MM:SS] tag and clean up random YouTube newlines
                    timestamp = f"[{minutes:02d}:{seconds:02d}]"
                    clean_text = text.replace('\n', ' ')
                    
                    formatted_lines.append(f"{timestamp} {clean_text}")

                # Join it all together with standard paragraph breaks
                full_text = "\n".join(formatted_lines)

                # Save it to the processed folder
                output_filepath = OUTPUT_DIR / f"{video_id}.md"
                with open(output_filepath, "w", encoding="utf-8") as f:
                    f.write(full_text)
                    
                print(f"✅ Saved full transcript WITH timestamps to {video_id}.md")
                # ----------------------------------------
                    
            except Exception as e:
                print(f"❌ Error processing line {i}: {e}")
                continue

def format_word():
    for file_path in INPUT_DIR.rglob("*"):
        if file_path.is_dir() or file_path.name in IGNORED_FILES:
            continue

        # FIX 3: Everything below is now correctly indented INSIDE the for loop
        print(f"Processing: {file_path.name}...")
        
        try:
            # This converts the entire document, preserving tables and structure
            result = converter.convert(str(file_path))
            
            # Export directly to markdown (this is much smarter than pulling raw text)
            markdown_text = result.document.export_to_markdown()
            
            output_filename = f"{file_path.stem}.md"
            output_filepath = OUTPUT_DIR / output_filename
            
            with open(output_filepath, "w", encoding="utf-8") as f:
                f.write(markdown_text)
                
            print(f"✅ Saved multimodal markdown to {output_filename}")
            
        except Exception as e:
            print(f"❌ Failed to process {file_path.name}: {e}")

    print("\nBatch extraction complete.")

if __name__ == "__main__":
    youtube_format()
    format_word()