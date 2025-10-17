#!/usr/bin/env python3
"""
Interview scaffold script for Uber Interview Environment
Creates new interview folders with appropriate templates
"""

import argparse
import os
import shutil
import time
from pathlib import Path

# Get templates directory from environment variable or default to relative to script
SCRIPT_DIR = Path(__file__).parent
DEFAULT_TEMPLATES_DIR = SCRIPT_DIR.parent / ".templates"
TEMPLATES_DIR = Path(os.getenv("INTERVIEW_TEMPLATES_DIR", DEFAULT_TEMPLATES_DIR))

AVAILABLE_LANGUAGES = [
    d.name for d in TEMPLATES_DIR.iterdir() if d.is_dir() and TEMPLATES_DIR.exists()
]

def main():
    parser = argparse.ArgumentParser(
        description="Create new interview folders with appropriate templates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""Available languages: {', '.join(AVAILABLE_LANGUAGES)}

Templates directory: {TEMPLATES_DIR}
(Set INTERVIEW_TEMPLATES_DIR environment variable to override)"""
    )
    
    parser.add_argument(
        "language",
        help="Programming language for the interview template"
    )
    
    parser.add_argument(
        "name", 
        help="Name of the interview (will be prefixed with epoch timestamp)"
    )
    
    args = parser.parse_args()
    
    language = args.language
    name = args.name
    
    # Validate templates directory exists
    if not TEMPLATES_DIR.exists():
        parser.error(f"Templates directory not found: {TEMPLATES_DIR}")
    
    # Validate language
    template_dir = TEMPLATES_DIR / language
    if not template_dir.exists():
        parser.error(f"Language '{language}' not found in templates. Available languages: {', '.join(AVAILABLE_LANGUAGES)}")
    
    # Generate folder name with epoch
    epoch = int(time.time())
    folder_name = f"{epoch}_{name}"
    interview_path = Path("interviews") / folder_name
    
    # Create interview directory
    try:
        interview_path.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error(f"Interview folder '{folder_name}' already exists")
    
    # Copy template files
    try:
        print(f"Copying template files from {template_dir} to {interview_path}")
        shutil.copytree(template_dir, interview_path, dirs_exist_ok=True)
        
        print(f"✓ Created {language} interview: {interview_path}")
        template_files = [f.name for f in template_dir.iterdir()]
        for file in template_files:
            print(f"  - {file}")
        
        print()
        print("Available Bazel commands:")
        print(f"  bazel run //interviews/{folder_name}:solution")
        print(f"  bazel run //interviews/{folder_name}:solution_with_input")
        print(f"  bazel build //interviews/{folder_name}:solution")
        print(f"  bazel test //interviews/{folder_name}:test")
            
    except Exception as e:
        # Clean up on failure
        shutil.rmtree(interview_path, ignore_errors=True)
        parser.error(f"Error copying template files: {e}")

if __name__ == "__main__":
    main()