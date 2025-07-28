#!/bin/bash

# Function to pause execution until a key is pressed
pause() {
    read -n 1 -s -r -p "Press any key to continue..."
    echo ""
}

# Cleanup function
cleanup() {
    if [[ -f "generate_embeddings.py" ]]; then
        rm -f generate_embeddings.py
        echo -e "\033[1;90mCleaned up temporary files\033[0m"
    fi
}

# Set up cleanup on script exit
trap cleanup EXIT

VECTOR_BUCKET_NAME=""
VECTOR_INDEX_NAME=""
REGION="us-east-1"
DIMENSION=1024  # Titan Text Embeddings V2 dimension
BEDROCK_MODEL_ID="amazon.titan-embed-text-v2:0"
METADATA_FILE="" 
# Expected JSON structure for METADATA_FILE:
# Array of objects, each containing:
# - example_name: string - Unique identifier for the code example
# - language: string - Programming language (e.g., ".NET", "Rust", "Python")
# - version: number - Version number of the example
# - service: string - AWS service name (e.g., "ECS", "S3", "Lambda")
# - snippet_tags: array - List of snippet tag identifiers (can be empty)
# - snippet_files: array - List of associated files (can be empty)
# - github: string - GitHub path relative to repository root
# - title: string - Human-readable title of the example
# - description: string - Brief description of what the example does
# - vector_input: string - Combined text used for embedding generation

echo -e "\n\033[1;36m=== Code Example S3 Vector Endpoints Setup ===\033[0m\n"
echo -e "\033[1;33mStep 1: Creating example vector bucket\033[0m"
echo -e "\033[1;32mCommand:\033[0m aws s3vectors create-vector-bucket --vector-bucket-name $VECTOR_BUCKET_NAME --region $REGION"
pause

# Create vector bucket
aws s3vectors create-vector-bucket \
    --vector-bucket-name $VECTOR_BUCKET_NAME \
    --region $REGION

echo -e "\033[1;32mVector bucket '$VECTOR_BUCKET_NAME' created successfully!\033[0m"
pause

echo -e "\n\033[1;34mUsing Amazon Bedrock Titan Text Embeddings V2 with model ID: $BEDROCK_MODEL_ID and dimension $DIMENSION\033[0m"
pause

echo -e "\n\033[1;33mCreating vector index in $VECTOR_BUCKET_NAME bucket\033[0m"
echo -e "\033[1;32mCommand:\033[0m aws s3vectors create-index --vector-bucket-name $VECTOR_BUCKET_NAME --index-name $VECTOR_INDEX_NAME --dimension $DIMENSION --distance-metric \"cosine\" --data-type \"float32\" --region $REGION"
pause

# Create vector index
aws s3vectors create-index \
    --vector-bucket-name $VECTOR_BUCKET_NAME \
    --index-name $VECTOR_INDEX_NAME \
    --dimension $DIMENSION \
    --distance-metric "cosine" \
    --data-type "float32" \
    --region $REGION

echo -e "\033[1;32mVector index '$VECTOR_INDEX_NAME' created successfully!\033[0m"
pause

echo -e "\033[1;32mUsing metadata from '$METADATA_FILE' ...\033[0m"

echo -e "\n\033[1;33mGenerating embeddings for each code example ...\033[0m"
echo -e "\033[1;32mCommand:\033[0m Creating Python script to generate embeddings using Bedrock"
pause

cat > generate_embeddings.py << EOL
import json
import boto3
import numpy as np
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Initialize clients
bedrock = boto3.client(service_name='bedrock-runtime', region_name=sys.argv[1])
s3vectors = boto3.client('s3vectors', region_name=sys.argv[1])
model_id = '${BEDROCK_MODEL_ID}'

# Constants
BATCH_SIZE = 10
MAX_RETRIES = 3
VECTOR_BUCKET_NAME = '${VECTOR_BUCKET_NAME}'
VECTOR_INDEX_NAME = '${VECTOR_INDEX_NAME}'

def generate_embedding(text, retries=MAX_RETRIES):
    for attempt in range(retries):
        try:
            response = bedrock.invoke_model(
                modelId=model_id,
                contentType='application/json',
                accept='application/json',
                body=json.dumps({"inputText": text})
            )
            embedding = json.loads(response['body'].read())['embedding']

            # Check dimensions
            if len(embedding) != ${DIMENSION}:
                if len(embedding) < ${DIMENSION}:
                    embedding = embedding + [0.0] * (${DIMENSION} - len(embedding))
                else:
                    embedding = embedding[:${DIMENSION}]
            return embedding

        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)

def process_batch(batch):
    vectors = []
    for code_example in batch:
        text = f"{code_example['vector_input']}"
        embedding = generate_embedding(text)

        vector = {
            "key": f"{code_example['example_name']}.{code_example['language']}.{code_example['version']}",
            "data": {"float32": embedding},
            "metadata": {
                "example_name": code_example['example_name'],
                "language": code_example['language'],
                "version": code_example['version'],
                "service": code_example['service'],
                "snippet_tags": code_example['snippet_tags'] if code_example['snippet_tags'] else "empty",
                "snippet_files": code_example['snippet_files'] if code_example['snippet_files'] else "empty",
                "github": code_example['github'] if code_example['github'] else "empty",
                "title": code_example['title']
            }
        }
        vectors.append(vector)

    try:
        s3vectors.put_vectors(
            vectorBucketName=VECTOR_BUCKET_NAME,
            indexName=VECTOR_INDEX_NAME,
            vectors=vectors
        )
        print(f"\033[1;32m✓ Uploaded batch of {len(vectors)} vectors\033[0m")
        return len(vectors)
    except Exception as e:
        print(f"\033[1;31mError uploading batch: {e}\033[0m")
        return 0

# Load code example metadata
with open("${METADATA_FILE}", 'r') as f:
    code_examples_metadata = json.load(f)

total_processed = 0
total_examples = len(code_examples_metadata)
print(f"\033[1;34mProcessing {total_examples} examples in batches of {BATCH_SIZE}\033[0m")

# Process in batches with ThreadPoolExecutor
with ThreadPoolExecutor(max_workers=5) as executor:
    futures = []

    for i in range(0, total_examples, BATCH_SIZE):
        batch = code_examples_metadata[i:i + BATCH_SIZE]
        futures.append(executor.submit(process_batch, batch))

    # Process results as they complete
    for future in as_completed(futures):
        try:
            batch_count = future.result()
            total_processed += batch_count
            print(f"\033[1;36mProgress: {total_processed}/{total_examples} examples processed\033[0m")
        except Exception as e:
            print(f"\033[1;31mBatch processing failed: {e}\033[0m")

print(f"\n\033[1;32m✓ Completed processing {total_processed} examples!\033[0m")
EOL

echo -e "\033[1;32mCommand:\033[0m python3 generate_embeddings.py $REGION"
python3 generate_embeddings.py $REGION

echo -e "\n\033[1;32m✓ Setup completed successfully!\033[0m"