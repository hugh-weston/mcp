# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""awslabs AWS Documentation MCP Server implementation."""

import httpx
import json
import os
import re

# Import models
from awslabs.aws_documentation_mcp_server.models import (
    RecommendationResult,
    SearchResult,
    CodeExampleResult,
)
from awslabs.aws_documentation_mcp_server.server_utils import (
    DEFAULT_USER_AGENT,
    read_documentation_impl,
)

# Import utility functions
from awslabs.aws_documentation_mcp_server.util import (
    parse_recommendation_results,
)
from loguru import logger

# from mcp.server.fastmcp import Context, FastMCP
from fastmcp import Context, FastMCP
from pathlib import Path
from pydantic import Field
from typing import Dict, List, Literal, Tuple, Union, Optional

import boto3
from constants import LanguageType, ServiceType, CategoryType, VersionType, LANGUAGE_VERSIONS

SEARCH_API_URL = "https://proxy.search.docs.aws.amazon.com/search"
RECOMMENDATIONS_API_URL = "https://contentrecs-api.docs.aws.amazon.com/v1/recommendations"
CODE_EXAMPLES_GITHUB_URL = "https://raw.githubusercontent.com/awsdocs/aws-doc-sdk-examples/refs/heads/main/"

CODE_EXAMPLES_S3_BUCKET = os.getenv("CODE_EXAMPLES_S3_VECTOR_BUCKET")
CODE_EXAMPLES_S3_INDEX = os.getenv("CODE_EXAMPLES_S3_VECTOR_INDEX")
TEXT_EMBEDDING_MODEL_ID = os.getenv("BEDROCK_TEXT_EMBEDDING_MODEL_ID")
CODE_EMBEDDING_MODEL_ID = os.getenv("SAGEMAKER_CODE_EMBEDDING_MODEL_ID")

bedrock = boto3.client("bedrock-runtime", region_name=os.getenv("BEDROCK_REGION"))
s3vectors = boto3.client("s3vectors", region_name=os.getenv("S3_VECTORS_REGION"))

mcp = FastMCP(
    "awslabs.aws-documentation-mcp-server",
    instructions="""
    # AWS Documentation MCP Server

    This server provides tools to access public AWS documentation, search for content, and get recommendations.

    ## Best Practices

    - For long documentation pages, make multiple calls to `read_documentation` with different `start_index` values for pagination
    - For very long documents (>30,000 characters), stop reading if you've found the needed information
    - When searching, use specific technical terms rather than general phrases
    - Use `recommend` tool to discover related content that might not appear in search results
    - For recent updates to a service, get an URL for any page in that service, then check the **New** section of the `recommend` tool output on that URL
    - If multiple searches with similar terms yield insufficient results, pivot to using `recommend` to find related pages.
    - Always cite the documentation URL when providing information to users

    ## Tool Selection Guide

    - Use `search_documentation` when: You need to find documentation about a specific AWS service or feature
    - Use `read_documentation` when: You have a specific documentation URL and need its content
    - Use `recommend` when: You want to find related content to a documentation page you're already viewing or need to find newly released information
    - Use `recommend` as a fallback when: Multiple searches have not yielded the specific information needed
    - Use `search_code_examples` when: You need to find the available code examples related to a specific AWS service, action, and SDK
    - Use `read_code_example` when: You have a specific code example name and need its content
    """,
    dependencies=[
        "pydantic",
        "httpx",
        "beautifulsoup4",
    ],
)

@mcp.tool()
async def search_code_examples(
    ctx: Context,
    query: str = Field(description="Query to search the examples for"),
    limit: int = Field(
        default=5,
        description="Maximum number of results to return",
        ge=1,
        le=50,
    ),
    language: Optional[LanguageType] = Field(
        default=None, description="Programming language/SDK to filter examples by. If None, searches all languages."
    ),
    service: Optional[ServiceType] = Field(
        default=None, description="AWS service name to search examples for. If None, searches all services."
    ),
    version: Optional[VersionType] = Field(
        default=None, 
        description="SDK version to filter by. If None, searches all versions. Only use this filter if explicitly requested."
    ),
    category: Optional[CategoryType] = Field(
        default=None, description="Example category to filter by. If None, searches all categories. Only use this filter if explicitly requested."
    )
) -> List[CodeExampleResult]:
    """Searches for code examples in the aws-doc-sdk-examples repository using the provided metadata.
    Returns a list of examples that match the search criteria.

    ## Usage
    Use this tool to get a list of the available code examples based on search criteria.
    You can optionally filter by service, language, and/or category.

    Args:
        ctx: MCP context for logging and error handling
        query: Text to search for in the examples
        service: Optional AWS service to filter by
        limit: Maximum number of results to return
        language: Optional programming language to filter by
        version: Optional version to filter by
        category: Optional category to filter by
    Returns:
        List of code examples matching the criteria, along with their metadata.
    """
    logger.debug(
        f"Searching code examples with query: {query}, service: {service}, "
        f"language: {language}, category: {category}"
    )

    # differentiate between code search and semantic search

    try:
        response = bedrock.invoke_model(
            modelId=TEXT_EMBEDDING_MODEL_ID, 
            body=json.dumps({"inputText": query})
        )
        model_response = json.loads(response["body"].read())
        query_embedding = model_response["embedding"]

        # Validate version if specified with language
        if version is not None and language is not None and version not in LANGUAGE_VERSIONS[language]:
            warning_msg = f"Version {version} not available for {language}, skipping version filter"
            logger.warning(warning_msg)
            await ctx.error(warning_msg)
            version = None

        # Build filter conditions
        filter_conditions = []
        if service is not None:
            filter_conditions.append({"service": {"$eq": service}})
        if language is not None:
            filter_conditions.append({"language": {"$eq": language}})
        if version is not None:
            filter_conditions.append({"version": {"$eq": version}})
        if category is not None:
            filter_conditions.append({"category": {"$eq": category}})

        filter_query = {"$and": filter_conditions} if filter_conditions else {}

        response = s3vectors.query_vectors(
            vectorBucketName=CODE_EXAMPLES_S3_BUCKET,
            indexName=CODE_EXAMPLES_S3_INDEX,
            queryVector={"float32": query_embedding},
            filter=filter_query,
            topK=limit,
            returnMetadata=True,
            returnDistance=True,
        )

        # filter by version and category where applicable

        filtered_examples = []
        for i, vector in enumerate(response["vectors"]):
            filtered_examples.append(
                CodeExampleResult(
                    example_id=vector["key"],
                    language=vector["metadata"]["language"],
                    version=vector["metadata"]["version"],
                    service=vector["metadata"]["service"],
                    description=vector["metadata"]["title"],
                    snippet_tags=(
                        vector["metadata"]["snippet_tags"]
                        if vector["metadata"]["snippet_tags"] != "empty"
                        else []
                    ),
                    snippet_files=(
                        vector["metadata"]["snippet_files"]
                        if vector["metadata"]["snippet_files"] != "empty"
                        else []
                    ),
                    category=vector["metadata"]["category"],
                )
            )

        return filtered_examples

    except (KeyError, TypeError) as e:
        error_msg = f"Error accessing example metadata: {e}"
        logger.error(error_msg)
        await ctx.error(error_msg)
        return [
            CodeExampleResult(
                example_id="", 
                language="", 
                version="", 
                description=error_msg,
                service="",
                category="",
            )
        ]

@mcp.tool()
async def read_code_example(
    ctx: Context,
    example_id: str = Field(description="The relevant example ID provided from search_code_examples."),
    from_github: bool = Field(
        default=False, 
        description="Whether to read the full code example directly from the GitHub repository. \
        Only set as True when the code example description explicitly states to use GitHub."
        )
) -> str:
    """Reads and returns the full file contents of one or more code examples.

    ## Usage
    After finding examples using search_code_examples, use this to read the actual code content.
    Accepts either a single example_id or a list of example_ids. When providing multiple examples,
    they must all use the same programming language.

    Args:
        ctx: MCP context for logging and error handling
        example_ids: Single example_id or list of example_ids (must use same language)
        language: Programming language/SDK to read the examples in
    Returns:
        Dictionary mapping example_ids to their code content
    """
    if not example_id:
        error_msg = "No example ID provided."
        logger.error(error_msg)
        await ctx.error(error_msg)
        return {"error": error_msg}

    logger.debug(f"Reading code example {example_id}")

    try:
        response = s3vectors.get_vectors(
            vectorBucketName=CODE_EXAMPLES_S3_BUCKET,
            indexName=CODE_EXAMPLES_S3_INDEX,
            keys=[example_id],
            returnMetadata=True
        )
        
        if not response or 'vectors' not in response or not response['vectors']:
            error_msg = f"No data found for example ID: {example_id}"
            logger.error(error_msg)
            await ctx.error(error_msg)
            return {"error": error_msg}

        if 'metadata' not in response['vectors'][0] or 'code' not in response['vectors'][0]['metadata']:
            error_msg = f"No code content found for example ID: {example_id}"
            logger.error(error_msg)
            await ctx.error(error_msg)
            return {"error": error_msg}

        logger.debug(f"Found code from example ID {example_id}")
        return response['vectors'][0]['metadata']['code']

    except Exception as e:
        error_msg = f"Error reading code example {example_id}: {str(e)}"
        logger.error(error_msg)
        await ctx.error(error_msg)
        return {"error": error_msg}     


@mcp.tool()
async def read_documentation(
    ctx: Context,
    url: str = Field(description="URL of the AWS documentation page to read"),
    max_length: int = Field(
        default=5000,
        description="Maximum number of characters to return.",
        gt=0,
        lt=1000000,
    ),
    start_index: int = Field(
        default=0,
        description="On return output starting at this character index, useful if a previous fetch was truncated and more content is required.",
        ge=0,
    ),
) -> str:
    """Fetch and convert an AWS documentation page to markdown format.

    ## Usage

    This tool retrieves the content of an AWS documentation page and converts it to markdown format.
    For long documents, you can make multiple calls with different start_index values to retrieve
    the entire content in chunks.

    ## URL Requirements

    - Must be from the docs.aws.amazon.com domain
    - Must end with .html

    ## Example URLs

    - https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucketnamingrules.html
    - https://docs.aws.amazon.com/lambda/latest/dg/lambda-invocation.html

    ## Output Format

    The output is formatted as markdown text with:
    - Preserved headings and structure
    - Code blocks for examples
    - Lists and tables converted to markdown format

    ## Handling Long Documents

    If the response indicates the document was truncated, you have several options:

    1. **Continue Reading**: Make another call with start_index set to the end of the previous response
    2. **Stop Early**: For very long documents (>30,000 characters), if you've already found the specific information needed, you can stop reading

    Args:
        ctx: MCP context for logging and error handling
        url: URL of the AWS documentation page to read
        max_length: Maximum number of characters to return
        start_index: On return output starting at this character index

    Returns:
        Markdown content of the AWS documentation
    """
    # Validate that URL is from docs.aws.amazon.com and ends with .html
    url_str = str(url)
    if not re.match(r"^https?://docs\.aws\.amazon\.com/", url_str):
        await ctx.error(
            f"Invalid URL: {url_str}. URL must be from the docs.aws.amazon.com domain"
        )
        raise ValueError("URL must be from the docs.aws.amazon.com domain")
    if not url_str.endswith(".html"):
        await ctx.error(f"Invalid URL: {url_str}. URL must end with .html")
        raise ValueError("URL must end with .html")

    return await read_documentation_impl(
        ctx, url_str, max_length=max_length, start_index=start_index
    )


@mcp.tool()
async def search_documentation(
    ctx: Context,
    search_phrase: str = Field(description="Search phrase to use"),
    limit: int = Field(
        default=10,
        description="Maximum number of results to return",
        ge=1,
        le=50,
    ),
) -> List[SearchResult]:
    """Search AWS documentation using the official AWS Documentation Search API.

    ## Usage

    This tool searches across all AWS documentation for pages matching your search phrase.
    Use it to find relevant documentation when you don't have a specific URL.

    ## Search Tips

    - Use specific technical terms rather than general phrases
    - Include service names to narrow results (e.g., "S3 bucket versioning" instead of just "versioning")
    - Use quotes for exact phrase matching (e.g., "AWS Lambda function URLs")
    - Include abbreviations and alternative terms to improve results

    ## Result Interpretation

    Each result includes:
    - rank_order: The relevance ranking (lower is more relevant)
    - url: The documentation page URL
    - title: The page title
    - context: A brief excerpt or summary (if available)

    Args:
        ctx: MCP context for logging and error handling
        search_phrase: Search phrase to use
        limit: Maximum number of results to return

    Returns:
        List of search results with URLs, titles, and context snippets
    """
    logger.debug(f"Searching AWS documentation for: {search_phrase}")

    request_body = {
        "textQuery": {
            "input": search_phrase,
        },
        "contextAttributes": [{"key": "domain", "value": "docs.aws.amazon.com"}],
        "acceptSuggestionBody": "RawText",
        "locales": ["en_us"],
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                SEARCH_API_URL,
                json=request_body,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": DEFAULT_USER_AGENT,
                },
                timeout=30,
            )
        except httpx.HTTPError as e:
            error_msg = f"Error searching AWS docs: {str(e)}"
            logger.error(error_msg)
            await ctx.error(error_msg)
            return [SearchResult(rank_order=1, url="", title=error_msg, context=None)]

        if response.status_code >= 400:
            error_msg = f"Error searching AWS docs - status code {response.status_code}"
            logger.error(error_msg)
            await ctx.error(error_msg)
            return [
                SearchResult(
                    rank_order=1,
                    url="",
                    title=error_msg,
                    context=None,
                )
            ]

        try:
            data = response.json()
        except json.JSONDecodeError as e:
            error_msg = f"Error parsing search results: {str(e)}"
            logger.error(error_msg)
            await ctx.error(error_msg)
            return [
                SearchResult(
                    rank_order=1,
                    url="",
                    title=error_msg,
                    context=None,
                )
            ]

    results = []
    if "suggestions" in data:
        for i, suggestion in enumerate(data["suggestions"][:limit]):
            if "textExcerptSuggestion" in suggestion:
                text_suggestion = suggestion["textExcerptSuggestion"]
                context = None

                # Add context if available
                if "summary" in text_suggestion:
                    context = text_suggestion["summary"]
                elif "suggestionBody" in text_suggestion:
                    context = text_suggestion["suggestionBody"]

                results.append(
                    SearchResult(
                        rank_order=i + 1,
                        url=text_suggestion.get("link", ""),
                        title=text_suggestion.get("title", ""),
                        context=context,
                    )
                )

    logger.debug(f"Found {len(results)} search results for: {search_phrase}")
    return results


@mcp.tool()
async def recommend(
    ctx: Context,
    url: str = Field(
        description="URL of the AWS documentation page to get recommendations for"
    ),
) -> List[RecommendationResult]:
    """Get content recommendations for an AWS documentation page.

    ## Usage

    This tool provides recommendations for related AWS documentation pages based on a given URL.
    Use it to discover additional relevant content that might not appear in search results.

    ## Recommendation Types

    The recommendations include four categories:

    1. **Highly Rated**: Popular pages within the same AWS service
    2. **New**: Recently added pages within the same AWS service - useful for finding newly released features
    3. **Similar**: Pages covering similar topics to the current page
    4. **Journey**: Pages commonly viewed next by other users

    ## When to Use

    - After reading a documentation page to find related content
    - When exploring a new AWS service to discover important pages
    - To find alternative explanations of complex concepts
    - To discover the most popular pages for a service
    - To find newly released information by using a service's welcome page URL and checking the **New** recommendations

    ## Finding New Features

    To find newly released information about a service:
    1. Find any page belong to that service, typically you can try the welcome page
    2. Call this tool with that URL
    3. Look specifically at the **New** recommendation type in the results

    ## Result Interpretation

    Each recommendation includes:
    - url: The documentation page URL
    - title: The page title
    - context: A brief description (if available)

    Args:
        ctx: MCP context for logging and error handling
        url: URL of the AWS documentation page to get recommendations for

    Returns:
        List of recommended pages with URLs, titles, and context
    """
    url_str = str(url)
    logger.debug(f"Getting recommendations for: {url_str}")

    recommendation_url = f"{RECOMMENDATIONS_API_URL}?path={url_str}"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                recommendation_url,
                headers={"User-Agent": DEFAULT_USER_AGENT},
                timeout=30,
            )
        except httpx.HTTPError as e:
            error_msg = f"Error getting recommendations: {str(e)}"
            logger.error(error_msg)
            await ctx.error(error_msg)
            return [RecommendationResult(url="", title=error_msg, context=None)]

        if response.status_code >= 400:
            error_msg = (
                f"Error getting recommendations - status code {response.status_code}"
            )
            logger.error(error_msg)
            await ctx.error(error_msg)
            return [
                RecommendationResult(
                    url="",
                    title=error_msg,
                    context=None,
                )
            ]

        try:
            data = response.json()
        except json.JSONDecodeError as e:
            error_msg = f"Error parsing recommendations: {str(e)}"
            logger.error(error_msg)
            await ctx.error(error_msg)
            return [RecommendationResult(url="", title=error_msg, context=None)]

    results = parse_recommendation_results(data)
    logger.debug(f"Found {len(results)} recommendations for: {url_str}")
    return results


def main():
    """Run the MCP server with CLI argument support."""
    # Log startup information
    logger.info("Starting AWS Documentation MCP Server")

    # Run server with appropriate transport
    mcp.run()


if __name__ == "__main__":
    main()
