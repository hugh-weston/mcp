#!/usr/bin/env python3
"""
Script to generate optimized descriptions using Bedrock Claude.
Takes processed examples and generates AI descriptions with caching and multi-region support.
"""

import json
import sys
import asyncio
import hashlib
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict
import boto3
from botocore.exceptions import ClientError


class BedrockClient:
    """Manages a Bedrock client with rate limiting."""
    
    def __init__(self, region: str):
        """Initialize client for a specific region."""
        self.client = boto3.client('bedrock-runtime', region_name=region)
        self.region = region
        self.calls = 0
        self.errors = 0
    
    async def generate_description(self, example: Dict[str, Any]) -> tuple[str, bool]:
        """
        Generate description for an example.
        Returns tuple of (description, success).
        """
        try:
            # Construct the prompt
            title = example.get("title", "")
            description = example.get("description", "")
            code = example.get("code", "")
            
            # Check if code is too long
            if len(code) > 30000:
                prefix = "**Read example from github, code truncated** "
            else:
                prefix = ""
            
            prompt = f"""Given this AWS code example:
Title: {title}
Description: {description}
Code:
{code}

Write a detailed 1-5 sentence description of what this example does. Include relevant technical keywords and concepts that someone might use when searching for this type of example. Focus on the specific AWS services, programming patterns, and use cases demonstrated. Make the description clear and informative for developers looking to solve similar problems.

Description:"""

            # Format request
            request = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1500,
                "temperature": 0.7,
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": prompt}]
                    }
                ]
            })

            # Call Bedrock
            response = self.client.invoke_model(
                modelId='anthropic.claude-3-haiku-20240307-v1:0',
                body=request
            )
            
            # Parse response
            response_body = json.loads(response['body'].read())
            generated_description = response_body['content'][0]['text']
            
            # Update stats
            self.calls += 1
            
            # Add prefix if code was truncated
            return prefix + generated_description.strip(), True
            
        except ClientError as e:
            print(f"Error calling Bedrock API in {self.region}: {e}")
            self.errors += 1
            return "", False
        except Exception as e:
            print(f"Unexpected error in {self.region}: {e}")
            self.errors += 1
            return "", False


class DescriptionCache:
    """Manages caching of generated descriptions."""
    
    def __init__(self, cache_file: Optional[Path] = None):
        """Initialize cache from file if provided."""
        self.cache_file = cache_file
        self.cache = {}
        self.hits = 0
        self.misses = 0
        
        if cache_file and cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
            except Exception as e:
                print(f"Warning: Failed to load cache file: {e}")
    
    def get_content_hash(self, example: Dict[str, Any]) -> str:
        """Generate hash of example content to detect changes."""
        content = json.dumps({
            "title": example.get("title", ""),
            "description": example.get("description", ""),
            "code": example.get("code", "")
        }, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()
    
    def get_cached_description(self, example: Dict[str, Any]) -> Optional[str]:
        """Get cached description if available and content hasn't changed."""
        example_id = example.get("example_name")
        if not example_id:
            return None
            
        content_hash = self.get_content_hash(example)
        cached = self.cache.get(example_id)
        
        if cached and cached.get("hash") == content_hash:
            self.hits += 1
            return cached.get("description")
        
        self.misses += 1
        return None
    
    def cache_description(self, example: Dict[str, Any], description: str):
        """Cache a generated description."""
        example_id = example.get("example_name")
        if not example_id:
            return
            
        self.cache[example_id] = {
            "hash": self.get_content_hash(example),
            "description": description
        }
    
    def save(self):
        """Save cache to file if configured."""
        if self.cache_file:
            try:
                with open(self.cache_file, 'w', encoding='utf-8') as f:
                    json.dump(self.cache, f, indent=2)
            except Exception as e:
                print(f"Warning: Failed to save cache file: {e}")


class DescriptionGenerator:
    """Manages description generation across multiple regions."""
    
    def __init__(
        self,
        regions: List[str] = None,
        cache_file: Optional[Path] = None,
        batch_size: int = 20,
        max_concurrent: int = 10
    ):
        """Initialize with list of regions to use."""
        self.regions = regions or ['us-east-1', 'us-west-2']
        self.clients = {r: BedrockClient(r) for r in self.regions}
        self.cache = DescriptionCache(cache_file)
        self.current_region = 0
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
    
    def _next_client(self) -> BedrockClient:
        """Get next client in round-robin fashion."""
        client = self.clients[self.regions[self.current_region]]
        self.current_region = (self.current_region + 1) % len(self.regions)
        return client
    
    async def generate_description(self, example: Dict[str, Any]) -> Optional[str]:
        """Generate description for an example with retries."""
        # Try each region once
        for _ in range(len(self.regions)):
            client = self._next_client()
            description, success = await client.generate_description(example)
            if success:
                return description
        return None
    
    async def process_example(self, example: Dict[str, Any], force_regenerate: bool = False) -> bool:
        """Process a single example."""
        async with self.semaphore:
            # Check cache first
            if not force_regenerate:
                cached = self.cache.get_cached_description(example)
                if cached:
                    example["bedrock_description"] = cached
                    return True
            
            # Generate new description
            description = await self.generate_description(example)
            if description:
                example["bedrock_description"] = description
                self.cache.cache_description(example, description)
                return True
            
            return False
    
    async def process_examples(
        self,
        examples: List[Dict[str, Any]],
        force_regenerate: bool = False
    ) -> Dict[str, Any]:
        """Process all examples in batches."""
        processed = 0
        success = 0
        
        # Process in batches
        for i in range(0, len(examples), self.batch_size):
            batch = examples[i:i + self.batch_size]
            
            # Process batch concurrently
            tasks = []
            for example in batch:
                task = self.process_example(example, force_regenerate)
                tasks.append(task)
            
            # Wait for batch to complete
            results = await asyncio.gather(*tasks)
            success += sum(1 for r in results if r)
            processed += len(batch)
            
            print(f"Processed {processed}/{len(examples)} examples...")
        
        # Collect stats
        stats = {
            "total_examples": len(examples),
            "successful": success,
            "cache_hits": self.cache.hits,
            "cache_misses": self.cache.misses,
            "api_calls_by_region": {
                region: client.calls for region, client in self.clients.items()
            },
            "errors_by_region": {
                region: client.errors for region, client in self.clients.items()
            }
        }
        
        return stats


async def process_file(
    input_file: Path,
    output_file: Path,
    cache_file: Optional[Path] = None,
    regions: Optional[List[str]] = None,
    batch_size: int = 20,
    max_concurrent: int = 10,
    force_regenerate: bool = False
):
    """Process input file and generate descriptions."""
    try:
        # Read input file
        with open(input_file, 'r', encoding='utf-8') as f:
            examples = json.load(f)
        
        if not isinstance(examples, list):
            print("Error: Input file must contain a list of examples")
            sys.exit(1)
        
        # Create generator
        generator = DescriptionGenerator(
            regions=regions,
            cache_file=cache_file,
            batch_size=batch_size,
            max_concurrent=max_concurrent
        )
        
        # Process examples
        stats = await generator.process_examples(examples, force_regenerate)
        
        # Save results
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(examples, f, indent=2)
        
        # Save cache
        generator.cache.save()
        
        # Print summary
        print("\nProcessing complete!")
        print(f"Total examples: {stats['total_examples']}")
        print(f"Successfully processed: {stats['successful']}")
        print(f"\nCache performance:")
        print(f"  Hits: {stats['cache_hits']}")
        print(f"  Misses: {stats['cache_misses']}")
        print(f"\nAPI calls by region:")
        for region, calls in stats['api_calls_by_region'].items():
            print(f"  {region}: {calls} calls")
        print(f"\nErrors by region:")
        for region, errors in stats['errors_by_region'].items():
            print(f"  {region}: {errors} errors")
        
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
    """Main function to handle command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate optimized descriptions using Bedrock Claude",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s input.json output.json
  %(prog)s input.json output.json --cache cache.json
  %(prog)s input.json output.json --regions us-east-1 us-west-2
  %(prog)s input.json output.json --batch-size 50 --max-concurrent 20
  %(prog)s input.json output.json --force-regenerate
        """
    )
    
    parser.add_argument("input_file", help="Input JSON file with examples")
    parser.add_argument("output_file", help="Output JSON file for results")
    parser.add_argument(
        "--cache",
        help="Cache file to store generated descriptions"
    )
    parser.add_argument(
        "--regions",
        nargs="+",
        help="AWS regions to use for Bedrock API calls"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Number of examples to process in each batch"
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=10,
        help="Maximum number of concurrent API calls"
    )
    parser.add_argument(
        "--force-regenerate",
        action="store_true",
        help="Force regeneration of all descriptions, ignoring cache"
    )
    
    args = parser.parse_args()
    
    # Convert paths
    input_file = Path(args.input_file)
    output_file = Path(args.output_file)
    cache_file = Path(args.cache) if args.cache else None
    
    # Check input file exists
    if not input_file.exists():
        print(f"Error: Input file '{input_file}' does not exist.")
        sys.exit(1)
    
    # Run async process
    asyncio.run(process_file(
        input_file=input_file,
        output_file=output_file,
        cache_file=cache_file,
        regions=args.regions,
        batch_size=args.batch_size,
        max_concurrent=args.max_concurrent,
        force_regenerate=args.force_regenerate
    ))


if __name__ == "__main__":
    main()
