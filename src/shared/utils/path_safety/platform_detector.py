"""
Platform-specific path detection and handling.

This module handles platform-specific path characteristics including:
- Windows system paths (SystemRoot, ProgramFiles, etc.)
- Forbidden system paths across platforms
- Case-sensitive/insensitive filesystem detection
"""
import os
import sys
from typing import List


class PlatformPathDetector:
    """Detects platform-specific forbidden paths and path characteristics."""

    @staticmethod
    def get_windows_system_paths() -> List[str]:
        """Get Windows system paths dynamically using environment variables.

        This handles cases where Windows is installed on drives other than C:
        (e.g., D:, E:, etc.) by reading the actual system root from environment.

        Returns:
            List of Windows system paths if on Windows, empty list otherwise
        """
        if os.name != 'nt':  # Not Windows
            return []

        paths = []

        # Get actual Windows directory (e.g., "C:\Windows", "D:\Windows", etc.)
        system_root = os.environ.get('SystemRoot')
        if system_root:
            paths.append(system_root)

        # Get Program Files directories
        program_files = os.environ.get('ProgramFiles')
        if program_files:
            paths.append(program_files)

        # Get Program Files (x86) on 64-bit systems
        program_files_x86 = os.environ.get('ProgramFiles(x86)')
        if program_files_x86:
            paths.append(program_files_x86)

        return paths

    @classmethod
    def get_forbidden_paths(cls) -> List[str]:
        """Get comprehensive list of forbidden system paths.

        Returns:
            List of forbidden paths for current platform
        """
        forbidden = [
            # Unix/Linux system paths
            "/etc",
            "/sys",
            "/proc",
            "/dev",
            "/boot",
            "/root",
            "/var/log",
            "/usr/bin",
            "/usr/sbin",
        ]

        # Add Windows system paths dynamically
        forbidden.extend(cls.get_windows_system_paths())

        return forbidden

    @staticmethod
    def is_case_insensitive_fs() -> bool:
        """Check if current filesystem is case-insensitive.

        Returns:
            True if filesystem is case-insensitive (Windows, macOS)
        """
        return sys.platform in ("win32", "darwin")

    @staticmethod
    def normalize_path_for_comparison(path: str) -> str:
        """Normalize path for platform-appropriate comparison.

        Args:
            path: Path string to normalize

        Returns:
            Normalized path (lowercase on case-insensitive platforms)
        """
        if PlatformPathDetector.is_case_insensitive_fs():
            return path.lower()
        return path
