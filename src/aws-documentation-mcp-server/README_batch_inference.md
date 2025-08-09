# Bedrock Batch Inference Data Generator

Converts processed AWS code examples into JSONL format for Amazon Bedrock batch inference using Claude 3 or 3.5 Haiku. This is an alternative to the real-time `generate_bedrock_descriptions.py` script.

## Pipeline Integration

This script fits into the preprocessing pipeline as **Step 3 (Alternative)**:

```
Step 1: process_examples.py
  metadata.json + snippets.json → processed_examples.json

Step 2: Choose processing method:
  Option A: generate_bedrock_descriptions.py (real-time)
  Option B: generate_batch_inference_data.py (batch)

Step 3 (if using batch): Process batch results
  process_batch_results.py → final_examples_with_descriptions.json
```

## Usage

### Generate Batch Data
```bash
./generate_batch_inference_data.py processed_examples.json batch_input.jsonl --create-processor
```

### Complete Batch Workflow
```bash
# 1. Generate batch data
./generate_batch_inference_data.py processed_examples.json batch_input.jsonl --create-processor

# 2. Upload to S3
aws s3 cp batch_input.jsonl s3://your-bucket/batch-input/

# 3. Create Bedrock batch job (for Claude 3 Haiku, use "anthropic.claude-3-haiku-20240307-v1:0")
aws bedrock create-model-invocation-job \
    --region "us-east-1" \
    --job-name "description-generation" \
    --role-arn "arn:aws:iam::account:role/BedrockBatchRole" \
    --model-id "anthropic.claude-3-5-haiku-20241022-v1:0" \
    --input-data-config '{"s3InputDataConfig":{"s3Uri":"s3://your-bucket/batch-input/batch_input.jsonl"}}' \
    --output-data-config '{"s3OutputDataConfig":{"s3Uri":"s3://your-bucket/batch-output/"}}'

# 4. Monitor job (wait for completion)
aws bedrock get-model-invocation-job --job-identifier "job-id"

# 5. Download and process results
aws s3 cp s3://your-bucket/batch-output/results.jsonl ./
./process_batch_results.py processed_examples.json results.jsonl batch_input.metadata.json final_examples.json
```

## Arguments

| Argument | Description |
|----------|-------------|
| `input_file` | Processed examples JSON from `process_examples.py` |
| `output_file` | JSONL file for batch inference |
| `--model-id` | Bedrock model ID (default: Claude 3.5 Haiku) |
| `--create-processor` | Generate result processing script |

## Output Files

- **`batch_input.jsonl`**: JSONL formatted for Bedrock batch inference
- **`batch_input.metadata.json`**: Metadata for processing results
- **`process_batch_results.py`**: Script to merge results back (if `--create-processor` used)

## Key Features

- **Same prompts**: Uses identical prompt generation as `generate_bedrock_descriptions.py`
- **Code truncation**: Handles examples with code > 30,000 characters
- **Statistics**: Reports total examples, truncated code, and examples with no code

## Example Output

```
Processing 1000 examples for batch inference...

Batch inference data generation complete!

Total examples: 1000
Batch records created: 1000
Examples with truncated code: 25
Examples with no code: 150
Model ID: anthropic.claude-3-5-haiku-20241022-v1:0

Files created:
  JSONL file: batch_input.jsonl
  Metadata file: batch_input.metadata.json

Next steps:
1. Upload batch_input.jsonl to S3
2. Create a Bedrock batch inference job
3. Use metadata file to process results when job completes
```
