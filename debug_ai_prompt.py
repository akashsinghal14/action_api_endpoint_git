#!/usr/bin/env python3
"""
Debug AI prompt for glazing measurement
"""

from app_with_auto_warming import create_claude_prompt

def debug_glazing_prompt():
    """Debug what prompt is generated for glazing"""
    
    # Simulate the survey data that would be created
    survey_data = {'contains_glazing': 'no'}
    
    print("Debug Glazing AI Prompt")
    print("=" * 40)
    print(f"Survey Data: {survey_data}")
    print()
    
    # Generate the prompt
    prompt = create_claude_prompt(survey_data)
    
    print("Generated Prompt:")
    print("-" * 40)
    print(prompt)
    print("-" * 40)
    
    # Check if the data is correctly formatted
    if "Contains Glazing: no" in prompt:
        print("✅ Data correctly formatted in prompt")
    else:
        print("❌ Data not correctly formatted in prompt")
    
    if "Boolean: Only \"yes\" compliant" in prompt:
        print("✅ Boolean rule correctly included")
    else:
        print("❌ Boolean rule missing")

if __name__ == "__main__":
    debug_glazing_prompt()
