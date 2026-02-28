"""File size, memory, and buffer size constants.

These constants provide semantic meaning to commonly-used byte sizes,
improving code readability and reducing magic numbers.
"""

# Byte conversion constants
BYTES_PER_KB = 1024
BYTES_PER_MB = 1024 * 1024
BYTES_PER_GB = 1024 * 1024 * 1024
BYTES_PER_TB = 1024 * 1024 * 1024 * 1024

# Common size limits
SIZE_1KB = 1024
SIZE_4KB = 4096
SIZE_10KB = 10240
SIZE_100KB = 102400
SIZE_1MB = 1024 * 1024
SIZE_10MB = 10 * 1024 * 1024
SIZE_100MB = 100 * 1024 * 1024
SIZE_1GB = 1024 * 1024 * 1024

# Token/secret sizes (bytes)
TOKEN_BYTES_SESSION = 32  # Session token: 32 bytes = 256 bits entropy
TOKEN_BYTES_STATE = 32  # OAuth state: 32 bytes = 256 bits entropy
TOKEN_BYTES_NONCE = 64  # OAuth nonce: 64 bytes = 512 bits entropy

# ID/hash string lengths (characters)
UUID_HEX_SHORT_LENGTH = 12  # Short UUID hex string (12 chars = 48 bits)
