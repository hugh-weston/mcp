# AWS Documentation MCP Server

Model Context Protocol (MCP) server for AWS Documentation

This MCP server provides tools to access AWS documentation, search for content, and get recommendations.

## Features

- **Read Documentation**: Fetch and convert AWS documentation pages to markdown format
- **Search Documentation**: Search AWS documentation using the official search API (global only)
- **Recommendations**: Get content recommendations for AWS documentation pages (global only)
- **Get Available Services List**: Get a list of available AWS services in China regions (China only)

## Prerequisites

### Installation Requirements

1. Install `uv` from [Astral](https://docs.astral.sh/uv/getting-started/installation/) or the [GitHub README](https://github.com/astral-sh/uv#installation)
2. Install Python 3.10 or newer using `uv python install 3.10` (or a more recent version)

## Installation

Configure the MCP server in your MCP client configuration (e.g., for Amazon Q Developer CLI, edit `~/.aws/amazonq/mcp.json`):

```json
{
  "mcpServers": {
    "awslabs.aws-documentation-mcp-server": {
      "command": "uvx",
      "args": ["awslabs.aws-documentation-mcp-server@latest"],
      "env": {
        "FASTMCP_LOG_LEVEL": "ERROR",
        "FASTMCP_LOG_FILE": "awslabs/aws-documentation-mcp-server/logs/server_aws.log",
        "AWS_DOCUMENTATION_PARTITION": "aws",
        "CODE_EXAMPLES_S3_VECTOR_BUCKET": "name-of-s3-vector-bucket",
        "CODE_EXAMPLES_S3_VECTOR_INDEX": "name-of-s3-vector-index",
        "S3_VECTORS_REGION": "us-east-1",
        "BEDROCK_TEXT_EMBEDDING_MODEL_ID": "text-embedding-id",
        "BEDROCK_REGION": "us-east-1",
        "SAGEMAKER_CODE_EMBEDDING_MODEL_ID": "code-embedding-id",
        "SAGEMAKER_REGION": "us-east-1",
        "CODE_CONTENT_S3_BUCKET": "code-content-bucket",
        "CODE_CONTENT_S3_REGION": "us-east-1"
      },
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

> **Note**: Set `AWS_DOCUMENTATION_PARTITION` to `aws-cn` to query AWS China documentation instead of global AWS documentation.
> **Note**: For local development, create `.amazonq/mcp.json` file with `python` as command and path to `server.py` as arg.

or docker after a successful `docker build -t mcp/aws-documentation .`:

```json
{
  "mcpServers": {
    "awslabs.aws-documentation-mcp-server": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "--interactive",
        "--env",
        "FASTMCP_LOG_LEVEL=ERROR",
        "--env",
        "AWS_DOCUMENTATION_PARTITION=aws",
        "mcp/aws-documentation:latest"
      ],
      "env": {},
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

## Basic Usage

Example:

- "look up documentation on S3 bucket naming rule. cite your sources"
- "recommend content for page https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucketnamingrules.html"

![AWS Documentation MCP Demo](https://github.com/awslabs/mcp/blob/main/src/aws-documentation-mcp-server/basic-usage.gif?raw=true)

## Tools

### read_documentation

Fetches an AWS documentation page and converts it to markdown format.

```python
read_documentation(url: str) -> str
```

### search_documentation (global only)

Searches AWS documentation using the official AWS Documentation Search API.

```python
search_documentation(search_phrase: str, limit: int) -> list[dict]
```

### recommend (global only)

Gets content recommendations for an AWS documentation page.

```python
recommend(url: str) -> list[dict]
```

### get_available_services (China only)

Gets a list of available AWS services in China regions.

```python
get_available_services() -> str
```
