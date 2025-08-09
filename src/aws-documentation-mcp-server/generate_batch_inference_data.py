#!/usr/bin/env python3
"""
Script to generate JSONL data for Bedrock batch inference.
Takes processed examples and formats them for Claude 3.5 Haiku batch processing.
"""

import json
import sys
import argparse
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional


class BatchInferenceFormatter:
    """Formats examples for Bedrock batch inference."""
    
    def __init__(self, output_file: Path, model_id: str = "anthropic.claude-3-5-haiku-20241022-v1:0"):
        """
        Initialize formatter.
        
        Args:
            output_file: Path to save JSONL file
            model_id: Bedrock model ID to use
        """
        self.output_file = output_file
        self.model_id = model_id
    
    def generate_prompt(self, example: Dict[str, Any]) -> str:
        """
        Generate the same prompt used in the original script.
        """
        example_name = example.get("example_name", "")
        description = example.get("description", "")
        code = example.get("code", "")
        
        # Check if code is too long (same logic as original)
        if len(code) > 30000:
            prefix_note = "**Read example from github, code truncated** "
        else:
            prefix_note = ""
        
        prompt = f"""Given this AWS code example:
Example name: {example_name}
Description: {description}
Code:
{code}

Write a concise 1-4 sentence description of what this code example accomplishes. Focus on the specific functionality, key parameters, and practical use case without repeating common terms like "AWS," "example," "demonstrates," or "developers." 
Emphasize unique technical details, service-specific operations, and the business problem it solves. Use varied vocabulary and avoid generic phrases.

Description:"""
        
        return prompt, prefix_note
    
    def format_example_for_batch(self, example: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format a single example for batch inference.
        
        Returns a dictionary that will be written as one line in the JSONL file.
        """
        prompt, prefix_note = self.generate_prompt(example)
        
        # Use example_name.language.version as recordId for uniqueness
        example_name = example.get("example_name", f"example_{hash(str(example))}")
        language = example.get("language", "unknown")
        version = example.get("version", "unknown")
        record_id = f"{example_name}.{language}.{version}"
        
        # Format for Claude 3 Haiku batch inference
        batch_record = {
            "recordId": record_id,
            "modelInput": {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1500,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ],
                "temperature": 0.7
            }
        }
        
        # Store metadata for later processing (not part of the batch request)
        batch_record["_metadata"] = {
            "example_name": example.get("example_name"),
            "language": example.get("language"),
            "version": example.get("version"),
            # "title": example.get("title", ""),
            "prefix_note": prefix_note,
            "original_example": example
        }
        
        return batch_record
    
    def process_examples(self, examples: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Process all examples and create JSONL file for batch inference.
        
        Returns statistics about the processing.
        """
        batch_records = []
        metadata_file = self.output_file.with_suffix('.metadata.json')
        
        print(f"Processing {len(examples)} examples for batch inference...")
        
        # Process each example
        for i, example in enumerate(examples, 1):
            batch_record = self.format_example_for_batch(example)
            batch_records.append(batch_record)
            
            if i % 100 == 0:
                print(f"Processed {i}/{len(examples)} examples")
        
        # Separate batch data from metadata
        jsonl_records = []
        metadata_records = {}
        
        for record in batch_records:
            # Extract metadata
            metadata = record.pop("_metadata")
            metadata_records[record["recordId"]] = metadata
            
            # Keep only the batch inference data
            jsonl_records.append(record)
        
        # Write JSONL file (one JSON object per line)
        with open(self.output_file, 'w', encoding='utf-8') as f:
            for record in jsonl_records:
                f.write(json.dumps(record) + '\n')
        
        # Write metadata file for later processing of results
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata_records, f, indent=2)
        
        # Calculate statistics
        stats = {
            "total_examples": len(examples),
            "batch_records_created": len(jsonl_records),
            "output_file": str(self.output_file),
            "metadata_file": str(metadata_file),
            "model_id": self.model_id,
            "truncated_examples": sum(1 for record in batch_records 
                                    if metadata_records[record["recordId"]]["prefix_note"]),
            "examples_with_no_code": sum(1 for example in examples 
                                       if not example.get("code", "").strip())
        }
        
        return stats


def process_file(
    input_file: Path,
    output_file: Path,
    model_id: str = "anthropic.claude-3-5-haiku-20241022-v1:0"
):
    """Process input file and generate batch inference JSONL."""
    try:
        # Read input file
        with open(input_file, 'r', encoding='utf-8') as f:
            examples = json.load(f)
        
        if not isinstance(examples, list):
            print("Error: Input file must contain a list of examples")
            sys.exit(1)
        
        # Create formatter
        formatter = BatchInferenceFormatter(
            output_file=output_file,
            model_id=model_id
        )
        
        # Process examples
        stats = formatter.process_examples(examples)
        
        # Print summary
        print("\nBatch inference data generation complete!")
        print(f"\nTotal examples: {stats['total_examples']}")
        print(f"Batch records created: {stats['batch_records_created']}")
        print(f"Examples with truncated code: {stats['truncated_examples']}")
        print(f"Examples with no code: {stats['examples_with_no_code']}")
        print(f"Model ID: {stats['model_id']}")
        print(f"\nFiles created:")
        print(f"  JSONL file: {stats['output_file']}")
        print(f"  Metadata file: {stats['metadata_file']}")
        
        print(f"\nNext steps:")
        print(f"1. Upload {stats['output_file']} to S3")
        print(f"2. Create a Bedrock batch inference job using the uploaded file")
        print(f"3. Use the metadata file to process results when the job completes")
        
    except FileNotFoundError as e:
        print(f"Error: File not found: {e}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error processing file: {e}")
        sys.exit(1)


def create_result_processor_script(output_dir: Path):
    """Create a companion script to process batch inference results."""
    processor_script = output_dir / "process_batch_results.py"
    
    script_content = '''#!/usr/bin/env python3
"""
Script to process Bedrock batch inference results and merge them back with original examples.
"""

import json
import sys
import argparse
from pathlib import Path
from typing import Dict, List, Any


def process_batch_results(
    original_examples_file: Path,
    batch_results_file: Path,
    metadata_file: Path,
    output_file: Path
):
    """Process batch inference results and merge with original examples."""
    
    # Load original examples
    with open(original_examples_file, 'r', encoding='utf-8') as f:
        examples = json.load(f)
    
    # Load metadata
    with open(metadata_file, 'r', encoding='utf-8') as f:
        metadata = json.load(f)
    
    # Load batch results (JSONL format)
    results = {}
    with open(batch_results_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                result = json.loads(line)
                record_id = result.get("recordId")
                if record_id:
                    results[record_id] = result
    
    # Create mapping from composite key to example
    example_map = {}
    for ex in examples:
        if ex.get("example_name") and ex.get("language") and ex.get("version"):
            composite_key = f"{ex['example_name']}.{ex['language']}.{ex['version']}"
            example_map[composite_key] = ex
    
    # Process results
    processed = 0
    for record_id, result in results.items():
        if record_id in metadata and record_id in example_map:
            meta = metadata[record_id]
            prefix_note = meta.get("prefix_note", "")
            
            # Extract the generated description
            model_output = result.get("modelOutput", {})
            content = model_output.get("content", [])
            
            if content and len(content) > 0:
                description = content[0].get("text", "").strip()
                
                # Add prefix if code was truncated
                final_description = prefix_note + description
                
                # Add to original example using composite key
                example_map[record_id]["bedrock_description"] = final_description
                processed += 1
    
    # Save updated examples
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(examples, f, indent=2)
    
    print(f"Processed {processed} batch inference results")
    print(f"Updated examples saved to: {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Process Bedrock batch inference results")
    parser.add_argument("original_examples", help="Original examples JSON file")
    parser.add_argument("batch_results", help="Batch inference results JSONL file")
    parser.add_argument("metadata", help="Metadata JSON file")
    parser.add_argument("output", help="Output JSON file with merged results")
    
    args = parser.parse_args()
    
    process_batch_results(
        Path(args.original_examples),
        Path(args.batch_results),
        Path(args.metadata),
        Path(args.output)
    )


if __name__ == "__main__":
    main()
'''
    
    with open(processor_script, 'w', encoding='utf-8') as f:
        f.write(script_content)
    
    # Make it executable
    processor_script.chmod(0o755)
    
    return processor_script


def main():
    """Main function to handle command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate JSONL data for Bedrock batch inference",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s input.json batch_input.jsonl
  %(prog)s input.json batch_input.jsonl --model-id anthropic.claude-3-5-haiku-20241022-v1:0
        """
    )
    
    parser.add_argument("input_file", help="Input JSON file with examples")
    parser.add_argument("output_file", help="Output JSONL file for batch inference")
    parser.add_argument(
        "--model-id",
        default="anthropic.claude-3-5-haiku-20241022-v1:0",
        help="Bedrock model ID to use for batch inference"
    )
    parser.add_argument(
        "--create-processor",
        action="store_true",
        help="Also create a script to process batch results"
    )
    
    args = parser.parse_args()
    
    # Convert paths
    input_file = Path(args.input_file)
    output_file = Path(args.output_file)
    
    # Check input file exists
    if not input_file.exists():
        print(f"Error: Input file '{input_file}' does not exist.")
        sys.exit(1)
    
    # Process file
    process_file(
        input_file=input_file,
        output_file=output_file,
        model_id=args.model_id
    )
    
    # Create result processor script if requested
    if args.create_processor:
        processor_script = create_result_processor_script(output_file.parent)
        print(f"\nResult processor script created: {processor_script}")


if __name__ == "__main__":
    main()
