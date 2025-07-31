#!/usr/bin/env python3
"""
Script to preprocess AWS code example metadata for use with s3 vector buckets.
Takes a JSON file with examples and splits each into separate language-specific 
entries with additional filtering and formatting options.
"""

import json
import sys
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict
import re


def build_snippet_index(snippets_data: Dict[str, Any]) -> Dict[str, str]:
    """Build an index of snippet identifiers to code."""
    index = {}
    snippets_section = snippets_data.get("snippets", {})
    
    for snippet_key, snippet_value in snippets_section.items():
        if isinstance(snippet_value, dict) and "code" in snippet_value:
            index[snippet_key] = snippet_value["code"]
            # Also index any nested identifiers
            if isinstance(snippet_value.get("identifiers"), list):
                for identifier in snippet_value["identifiers"]:
                    index[identifier] = snippet_value["code"]
    
    return index


def find_snippet_code(snippet_index: Dict[str, str], snippet_identifier: str) -> Optional[str]:
    """
    Find code for a snippet tag or snippet file in the index.
    
    Args:
        snippet_index: The indexed snippets data
        snippet_identifier: Either a snippet_tag or snippet_file path
        
    Returns:
        The code string if found, None otherwise
    """
    return snippet_index.get(snippet_identifier)


def get_combined_code(example: Dict[str, Any], snippet_index: Dict[str, str]) -> tuple[str, List[str]]:
    """
    Get combined code from all snippets for an example.
    
    Args:
        example: Single example dictionary from split metadata
        snippets_data: The loaded snippets JSON data
        
    Returns:
        Tuple of (combined code string, list of missing snippet identifiers)
    """
    code_parts = []
    missing_snippets = []
    
    # Process snippet_tags
    for tag in example.get("snippet_tags", []):
        if tag:  # Skip empty tags
            code = find_snippet_code(snippet_index, tag)
            if code:
                code_parts.append(code)
            else:
                missing_snippets.append(f"tag:{tag}")
    
    # Process snippet_files
    for file_path in example.get("snippet_files", []):
        if file_path:  # Skip empty file paths
            code = find_snippet_code(snippet_index, file_path)
            if code:
                code_parts.append(code)
            else:
                missing_snippets.append(f"file:{file_path}")
    
    # Combine all code snippets
    return "\n\n".join(code_parts) if code_parts else "", missing_snippets


def create_vector_input(example: Dict[str, Any], code: str) -> str:
    """
    Create the vector_input string by combining title, description, and code.
    
    Args:
        example: Single example dictionary from split metadata
        code: Combined code from snippets
        
    Returns:
        Formatted vector_input string
    """
    title = example.get("title", "")
    description = example.get("description", "")
    
    # Create the vector_input format
    return f"{title}: {description}\nCode:\n{code}"


def clean_html_tags(text: str) -> str:
    """Clean XML/HTML markup and convert to markdown format."""
    if not text:
        return text
    
    clean_text = text.replace("<emphasis role=\"bold\">", "**")
    clean_text = clean_text.replace("<emphasis>", "**")
    clean_text = clean_text.replace("</emphasis>", "**")
    clean_text = clean_text.replace("<code>", "`")
    clean_text = clean_text.replace("</code>", "`")
    clean_text = clean_text.replace("<programlisting language=\"none\" role=\"nocopy\">", "")
    clean_text = clean_text.replace("</programlisting>", "")
    clean_text = clean_text.replace("<ulink url=\"", "[")
    clean_text = clean_text.replace("\">", "](")
    clean_text = clean_text.replace("</ulink>", ")")
    
    return clean_text


def extract_language_examples(
    example_id: str, 
    example_data: Dict[str, Any],
    language_filter: Optional[List[str]] = None,
    clean_descriptions: bool = True
) -> List[Dict[str, Any]]:
    """
    Extract language-specific examples from a single example entry.
    
    Args:
        example_id: The example identifier (e.g., "ecs_CreateCluster")
        example_data: The example metadata dictionary
        language_filter: Optional list of languages to include (case-insensitive)
        clean_descriptions: Whether to clean HTML tags from descriptions
        
    Returns:
        List of language-specific example dictionaries
    """
    language_examples = []
    
    # Get common fields
    synopsis = example_data.get("synopsis", "")
    title = example_data.get("title", "")
    service_sdk_id = example_data.get("service_sdk_id", "")
    
    # Process each language
    languages = example_data.get("languages", {})
    
    for lang_key, lang_data in languages.items():
        language_name = lang_data.get("name", lang_key)
        
        # Apply language filter if specified
        if language_filter:
            if not any(lang.lower() == language_name.lower() for lang in language_filter):
                continue
        
        # Process each version for this language
        versions = lang_data.get("versions", [])
        
        for version_data in versions:
            # Collect all descriptions for this language version
            descriptions = []
            if synopsis and synopsis.strip():
                descriptions.append(synopsis)
            
            excerpts = version_data.get("excerpts", [])
            for excerpt in excerpts:
                desc = excerpt.get("description")
                if desc and desc.strip():
                    if clean_descriptions:
                        desc = clean_html_tags(desc)
                    descriptions.append(desc)
            
            # Collect all snippet tags and files
            snippet_tags = []
            snippet_files = []
            
            for excerpt in excerpts:
                tags = excerpt.get("snippet_tags", [])
                files = excerpt.get("snippet_files", [])
                snippet_tags.extend(tags)
                snippet_files.extend(files)
            
            # Remove duplicates while preserving order
            snippet_tags = list(dict.fromkeys(snippet_tags))
            snippet_files = list(dict.fromkeys(snippet_files))
            
            # Clean up title HTML/XML tags if cleaning is enabled
            clean_title = title
            if clean_descriptions and clean_title:
                clean_title = clean_html_tags(clean_title)

            # Create the language-specific example
            language_example = {
                "example_name": example_id,
                "language": language_name,
                "version": version_data.get("sdk_version"),
                "service": service_sdk_id,
                "snippet_tags": snippet_tags,
                "snippet_files": snippet_files,
                "github": version_data.get("github"),
                "title": clean_title,
                "description": " ".join(filter(None, descriptions)),
                "category": example_data.get("category")
            }
            
            language_examples.append(language_example)
    
    return language_examples


def process_example(
    example_id: str,
    example_data: Dict[str, Any],
    snippet_index: Dict[str, str],
    settings: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Process a single example."""
    
    # Skip if not a valid example
    if not isinstance(example_data, dict) or "languages" not in example_data:
        return [], []
    
    # Apply service filter if specified
    if settings.get("service_filter"):
        service_sdk_id = example_data.get("service_sdk_id", "")
        if not any(svc.lower() == service_sdk_id.lower() for svc in settings["service_filter"]):
            return [], []
    
    # Extract language examples
    language_examples = extract_language_examples(
        example_id,
        example_data,
        language_filter=settings.get("language_filter"),
        clean_descriptions=settings.get("clean_descriptions", True)
    )
    
    # Process each language example
    missing_snippets = []
    for example in language_examples:
        # Get code and track missing snippets
        code, missing = get_combined_code(example, snippet_index)
        example["code"] = code
        example["vector_input"] = create_vector_input(example, code)
        missing_snippets.extend(missing)
    
    return language_examples, missing_snippets


def process_metadata_file(
    input_file: Path,
    output_file: Path,
    snippets_file: Path,
    failed_lookups_file: Optional[Path] = None,
    language_filter: Optional[List[str]] = None,
    service_filter: Optional[List[str]] = None,
    clean_descriptions: bool = True,
    pretty_print: bool = True,
    batch_size: int = 1000
) -> Dict[str, Any]:
    """
    Process the metadata file.
    
    Args:
        input_file: Path to input JSON file
        output_file: Path to output JSON file
        snippets_file: Path to snippets JSON file
        failed_lookups_file: Optional path to save failed lookups
        language_filter: Optional list of languages to include
        service_filter: Optional list of services to include
        clean_descriptions: Whether to clean HTML tags from descriptions
        pretty_print: Whether to format JSON output with indentation
        batch_size: Number of examples per progress update
    """
    try:
        # Read input files
        with open(input_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        
        print(f"Loading snippets from: {snippets_file}")
        with open(snippets_file, 'r', encoding='utf-8') as f:
            snippets_data = json.load(f)
        
        # Build snippet index for faster lookups
        print("Building snippet index...")
        snippet_index = build_snippet_index(snippets_data)
        
        # Settings dictionary
        settings = {
            "language_filter": language_filter,
            "service_filter": service_filter,
            "clean_descriptions": clean_descriptions
        }
        
        # Process all examples
        all_examples = []
        missing_snippets_map = defaultdict(list)
        processed_count = 0
        
        # Process in batches just for progress reporting
        items = list(metadata.items())
        total_items = len(items)
        
        for i in range(0, total_items, batch_size):
            batch = items[i:i + batch_size]
            
            # Process batch
            for example_id, example_data in batch:
                examples, missing = process_example(
                    example_id,
                    example_data,
                    snippet_index,
                    settings
                )
                
                if examples:
                    all_examples.extend(examples)
                    processed_count += 1
                if missing:
                    missing_snippets_map[example_id].extend(missing)
            
            print(f"Processed {min(i + batch_size, total_items)}/{total_items} examples...")
        
        # Write output file
        indent = 2 if pretty_print else None
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_examples, f, indent=indent, ensure_ascii=False)
        
        # Print summary
        print(f"\nProcessing complete!")
        print(f"Total examples processed: {processed_count}")
        print(f"Total language-specific examples created: {len(all_examples)}")
        
        if language_filter:
            print(f"Language filter applied: {', '.join(language_filter)}")
        if service_filter:
            print(f"Service filter applied: {', '.join(service_filter)}")
            
        print(f"Output written to: {output_file}")
        
        # Show language distribution
        lang_counts = {}
        for example in all_examples:
            lang = example["language"]
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
        
        if lang_counts:
            print(f"\nLanguage distribution:")
            for lang, count in sorted(lang_counts.items()):
                print(f"  {lang}: {count}")
        
        # Save missing snippets to file if path provided
        if missing_snippets_map and failed_lookups_file:
            print(f"\nSaving failed lookups to: {failed_lookups_file}")
            with open(failed_lookups_file, 'w', encoding='utf-8') as f:
                json.dump(
                    {
                        "total_missing": sum(len(m) for m in missing_snippets_map.values()),
                        "missing_by_example": dict(missing_snippets_map)
                    },
                    f,
                    indent=2
                )
        
        # Return processing results
        return {
            "processed_count": processed_count,
            "total_examples": len(all_examples),
            "language_counts": lang_counts,
            "missing_snippets": dict(missing_snippets_map)
        }
        
    except FileNotFoundError as e:
        print(f"Error: File not found: {e}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error processing file: {e}")
        sys.exit(1)


def main():
    """Main function to handle command line arguments and execute processing."""
    parser = argparse.ArgumentParser(
        description="Split AWS code example metadata by language",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s input.json snippets.json output.json
  %(prog)s input.json snippets.json output.json --languages Python Java
  %(prog)s input.json snippets.json output.json --batch-size 1000
  %(prog)s input.json snippets.json output.json --failed-lookups failed.json
        """
    )
    
    parser.add_argument("input_file", help="Input JSON file with metadata")
    parser.add_argument("snippets_file", help="Path to example_meta_snippets.json file")
    parser.add_argument("output_file", help="Output JSON file for split examples")
    parser.add_argument(
        "--languages", "-l", 
        nargs="+", 
        help="Filter by specific languages (case-insensitive)"
    )
    parser.add_argument(
        "--services", "-s", 
        nargs="+", 
        help="Filter by specific services (case-insensitive)"
    )
    parser.add_argument(
        "--no-clean", 
        action="store_true", 
        help="Don't clean HTML tags from descriptions"
    )
    parser.add_argument(
        "--compact", 
        action="store_true", 
        help="Output compact JSON without indentation"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Number of examples per progress update"
    )
    parser.add_argument(
        "--failed-lookups",
        help="Save failed snippet lookups to this file"
    )
    
    args = parser.parse_args()
    
    # Convert paths
    args.input_file = Path(args.input_file)
    args.snippets_file = Path(args.snippets_file)
    args.output_file = Path(args.output_file)
    
    # Check files exist
    if not args.input_file.exists():
        print(f"Error: Input file '{args.input_file}' does not exist.")
        sys.exit(1)
    if not args.snippets_file.exists():
        print(f"Error: Snippets file '{args.snippets_file}' does not exist.")
        sys.exit(1)
    
    # Run processing
    process_metadata_file(
        input_file=args.input_file,
        output_file=args.output_file,
        snippets_file=args.snippets_file,
        failed_lookups_file=Path(args.failed_lookups) if args.failed_lookups else None,
        language_filter=args.languages,
        service_filter=args.services,
        clean_descriptions=not args.no_clean,
        pretty_print=not args.compact,
        batch_size=args.batch_size
    )


if __name__ == "__main__":
    main()
