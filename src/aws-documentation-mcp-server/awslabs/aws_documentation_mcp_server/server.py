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

import os
import sys
from loguru import logger

log_level = os.getenv('FASTMCP_LOG_LEVEL', 'DEBUG')
log_file = os.getenv('FASTMCP_LOG_FILE')
log_format = '{time:YYYY-MM-DD HH:mm:ss} - {name} - {level} - {message}'

# Set up logging
logger.remove()
# logger.add(log_file, level=log_level, format=log_format)

if log_file:
    try:
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        logger.add(log_file, level=log_level, format=log_format)
        # logger.add(sink=log_file, level=log_level, format=log_format)
        logger.info(f"Logging to file: {log_file}")
    except Exception as e:
        logger.error(f"Failed to set up log file {log_file}: {e}")
else:
    logger.add(sys.stderr, level=log_level, format=log_format)

PARTITION = os.getenv('AWS_DOCUMENTATION_PARTITION', 'aws').lower()


def main():
    """Run the MCP server with CLI argument support."""
    if PARTITION == 'aws':
        from awslabs.aws_documentation_mcp_server.server_aws import main
    elif PARTITION == 'aws-cn':
        from awslabs.aws_documentation_mcp_server.server_aws_cn import main
    else:
        raise ValueError(f'Unsupported AWS documentation partition: {PARTITION}.')

    main()


if __name__ == '__main__':
    main()
