# AWS Code Example Metadata Preprocessing

This directory contains scripts to process AWS code example metadata:
1. Split metadata by language and extract code snippets (process_examples.py)
2. Generate optimized descriptions using Bedrock Claude (generate_bedrock_descriptions.py)

## Scripts

### `process_examples.py`

Fast script for processing metadata with optimized snippet lookups.

**Usage:**
```bash
python process_examples.py [OPTIONS] <input_file> <snippets_file> <output_file>
```

**Options:**
- `--languages, -l`: Filter by specific languages (case-insensitive)
- `--services, -s`: Filter by specific services (case-insensitive)  
- `--no-clean`: Don't clean HTML tags from descriptions
- `--compact`: Output compact JSON without indentation
- `--failed-lookups`: Save failed snippet lookups to specified JSON file
- `--batch-size`: Number of examples per progress update (default: 1000)

**Examples:**
```bash
# Basic usage
python process_examples.py metadata.json example_meta_snippets.json output.json

# Filter by specific languages
python process_examples.py metadata.json example_meta_snippets.json output.json --languages Python Java CLI

# Filter by services
python process_examples.py metadata.json example_meta_snippets.json output.json --services ECS S3 Lambda

# Combine filters and output compact JSON
python process_examples.py metadata.json example_meta_snippets.json output.json --languages Python --services ECS --compact

# Keep original HTML tags
python process_examples.py metadata.json example_meta_snippets.json output.json --no-clean

# Save failed lookups to file
python process_examples.py metadata.json example_meta_snippets.json output.json --failed-lookups failed.json

# Process in larger batches
python process_examples.py metadata.json example_meta_snippets.json output.json --batch-size 5000
```

**Performance Features:**
- Fast snippet lookups using pre-built index
- Efficient batch processing
- Minimal memory overhead
- Progress tracking with configurable batch size

### `generate_bedrock_descriptions.py`

Script to generate optimized descriptions using Bedrock Claude with caching and multi-region support.

**Usage:**
```bash
python generate_bedrock_descriptions.py [OPTIONS] <input_file> <output_file>
```

**Options:**
- `--cache`: Cache file to store generated descriptions
- `--regions`: AWS regions to use for Bedrock API calls
- `--batch-size`: Number of examples to process in each batch
- `--max-concurrent`: Maximum number of concurrent API calls
- `--force-regenerate`: Force regeneration of all descriptions, ignoring cache

**Examples:**
```bash
# Basic usage
python generate_bedrock_descriptions.py processed_examples.json output.json

# With caching
python generate_bedrock_descriptions.py processed_examples.json output.json --cache descriptions.json

# Multi-region with increased concurrency
python generate_bedrock_descriptions.py processed_examples.json output.json \
    --regions us-east-1 us-west-2 \
    --batch-size 50 --max-concurrent 20

# Force regenerate all descriptions
python generate_bedrock_descriptions.py processed_examples.json output.json \
    --cache descriptions.json --force-regenerate
```

**Features:**
- Caching of generated descriptions with content-based invalidation
- Multi-region support with round-robin distribution
- Concurrent processing with configurable batch size
- Statistics on API calls, cache performance, and errors

## Input Format

The scripts expect JSON input with the following structure:

```json
{
  "example_id": {
    "id": "example_id",
    "languages": {
      "LanguageName": {
        "name": "LanguageName",
        "versions": [
          {
            "sdk_version": 1,
            "excerpts": [
              {
                "description": "Example description",
                "snippet_tags": ["tag1", "tag2"],
                "snippet_files": ["file1.ext"]
              }
            ],
            "github": "path/to/github"
          }
        ]
      }
    },
    "title": "Example Title",
    "synopsis": "Example synopsis",
    "service_sdk_id": "SERVICE"
  }
}
```

## Output Format

The scripts produce an array of language-specific examples:

```json
[
  {
    "example_name": "example_id",
    "language": "LanguageName", 
    "version": 1,
    "service": "SERVICE",
    "snippet_tags": ["tag1", "tag2"],
    "snippet_files": ["file1.ext"],
    "github": "path/to/github",
    "title": "Example Title",
    "description": "Combined synopsis and language-specific descriptions",
    "code": "Raw code from combined snippets",
    "vector_input": "Title: Description\nCode:\n[code snippets]"
  }
]
```

## Features

### Code and Description Fields

The scripts process code snippets and descriptions in two steps:

1. `process_examples.py` generates:
- `code`: Contains just the raw code from combined snippets, useful for direct code access
- `vector_input`: A formatted string combining the title, description, and code in a structured format

2. `generate_bedrock_descriptions.py` adds:
- `bedrock_description`: An AI-generated description optimized for natural language search queries
  * For examples with code exceeding 30,000 characters, the description includes "**Read example from github, code truncated**"
  * Descriptions focus on technical keywords, AWS services, programming patterns, and use cases
  * Generated descriptions are cached to avoid unnecessary API calls
  * Multi-region support helps handle large numbers of examples efficiently


### HTML Tag Cleaning

The script automatically cleans HTML/XML tags:
- `<emphasis role="bold">text</emphasis>` → `**text**`
- `<code>text</code>` → `` `text` ``
- `<programlisting>code</programlisting>` → `` ```\ncode\n``` ``
- `<ulink url="...">text</ulink>` → `[text](...)`

### Filtering

- **Language filtering**: Include only specific programming languages
- **Service filtering**: Include only specific AWS services
- Case-insensitive matching for both filters

### Output Options

- **Pretty printing**: Formatted JSON with indentation (default)
- **Compact output**: Minified JSON without indentation
- **Statistics**: Shows processing summary and language distribution
- **Missing Snippets**: Reports any snippet tags or files that couldn't be found in the snippets data. Can be saved to a JSON file with the --failed-lookups option, containing:
  * Total count of missing snippets
  * Detailed breakdown by example
  * Whether each missing snippet was a tag or file