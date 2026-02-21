from pathlib import Path
from typing import Optional, Dict, Any, List
from mermaid import Mermaid
from ..core.exceptions import ConversionError, ConfigurationError
from ..utils.simple import logger
from ..utils.file_utils import TemporaryFileManager
from ..core.validator import SystemValidator, MermaidCodeValidator
from ..core.types import ConversionResult, ConversionStatus
from ..processors.markdown import MarkdownMermaidProcessor


class LocalMermaidConverter:
    """
    Converts Mermaid diagrams to PNG using mermaid-python package.
    No subprocess calls - purely Python implementation.
    """

    # Configuration defaults
    DEFAULT_CONFIG = {
        "width": 1200,
        "height": 800,
        "background-color": "transparent",
        "theme": "default",
    }

    SUPPORTED_THEMES = ["default", "forest", "dark", "neutral"]

    def __init__(
        self,
        timeout: int = 120,
        temp_dir: Optional[str] = None,
        validate_system: bool = True,
    ):
        self.timeout = timeout
        self.temp_manager = TemporaryFileManager()
        self.validator = SystemValidator()
        self.code_validator = MermaidCodeValidator()
        self.config = self.DEFAULT_CONFIG.copy()
        self.mermaid = Mermaid()

        # System validation
        if validate_system:
            self._validate_environment()

        logger.info("LocalMermaidConverter initialized successfully")

    def _validate_environment(self):
        logger.info("Validating system environment...")

        # Check Python environment
        try:
            # Test basic functionality
            test_diagram = "graph TD; A-->B"
            self.mermaid.add_flowchart("test", test_diagram)
            self.mermaid.generate("test.png")
            Path("test.png").unlink()  # Clean up
        except Exception as e:
            raise ConfigurationError(f"Mermaid Python validation failed: {str(e)}")

    def set_config(self, **kwargs):
        """Update configuration parameters."""
        valid_keys = set(self.DEFAULT_CONFIG.keys())
        for key, value in kwargs.items():
            if key in valid_keys:
                self.config[key] = value
            else:
                logger.warning(f"Ignoring invalid config key: {key}")

        # Validate theme
        if "theme" in kwargs and kwargs["theme"] not in self.SUPPORTED_THEMES:
            logger.warning(f"Unsupported theme: {kwargs['theme']}. Using default.")
            self.config["theme"] = "default"

    def convert_to_png(self, mermaid_code: str) -> bytes:
        """
        Convert Mermaid diagram code to PNG bytes.

        Args:
            mermaid_code: Valid Mermaid diagram code

        Returns:
            bytes: PNG image data

        Raises:
            ConversionError: If conversion fails
        """
        logger.info("Starting Mermaid to PNG conversion...")

        try:
            # Validate input
            is_valid, validation_msg = self.code_validator.validate_syntax(mermaid_code)
            if not is_valid:
                raise ConversionError(f"Invalid Mermaid code: {validation_msg}")

            # Sanitize input
            sanitized_code = self.code_validator.sanitize_input(mermaid_code)

            # Create temporary file for output
            output_file = self.temp_manager.create_temp_file(".png")

            # Generate diagram
            self.mermaid.add_flowchart("diagram", sanitized_code)
            self.mermaid.generate(output_file.name)

            # Read output file
            if not output_file.exists():
                raise ConversionError("Output file was not created")

            png_data = output_file.read_bytes()

            if len(png_data) == 0:
                raise ConversionError("Output file is empty")

            logger.info(
                f"Successfully converted Mermaid diagram to PNG ({len(png_data)} bytes)"
            )
            return png_data

        except Exception as e:
            logger.error(f"Conversion failed: {str(e)}")
            raise ConversionError(str(e)) from e

    def convert_and_save(self, mermaid_code: str, output_path: str) -> ConversionResult:
        """
        Convert Mermaid diagram and save to file with detailed result reporting.

        Args:
            mermaid_code: Valid Mermaid diagram code
            output_path: Path where PNG file should be saved

        Returns:
            ConversionResult: Detailed result of the conversion
        """
        import time

        start_time = time.time()
        output_file = Path(output_path)

        try:
            # Ensure output directory exists
            output_file.parent.mkdir(parents=True, exist_ok=True)

            # Perform conversion
            png_data = self.convert_to_png(mermaid_code)

            # Save to file
            output_file.write_bytes(png_data)
            file_size = output_file.stat().st_size

            execution_time = time.time() - start_time

            logger.info(
                f"Diagram saved to {output_path} ({file_size} bytes, {execution_time:.2f}s)"
            )

            return ConversionResult(
                status=ConversionStatus.SUCCESS,
                output_path=output_file,
                file_size=file_size,
                execution_time=execution_time,
            )

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Failed to save diagram to {output_path}: {str(e)}")

            return ConversionResult(
                status=ConversionStatus.FAILED,
                error_message=str(e),
                execution_time=execution_time,
            )

    def batch_convert(
        self, mermaid_files: Dict[str, str]
    ) -> Dict[str, ConversionResult]:
        """
        Convert multiple Mermaid files in batch.

        Args:
            mermaid_files: Dictionary mapping output filenames to Mermaid code

        Returns:
            Dictionary mapping filenames to conversion results
        """
        results = {}

        for filename, mermaid_code in mermaid_files.items():
            try:
                result = self.convert_and_save(mermaid_code, filename)
                results[filename] = result
            except Exception as e:
                results[filename] = ConversionResult(
                    status=ConversionStatus.FAILED, error_message=str(e)
                )

        success_count = sum(
            1 for r in results.values() if r.status == ConversionStatus.SUCCESS
        )
        logger.info(f"Batch conversion completed: {success_count}/{len(results)} successful")

        return results

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup."""
        self.cleanup()

    def cleanup(self):
        """Clean up temporary resources."""
        logger.info("Temporary resources cleaned up")


class EnhancedMermaidConverter:
    """
    Enhanced converter that combines local Mermaid conversion with Markdown processing.
    """

    def __init__(self, **converter_kwargs):
        self.base_converter = LocalMermaidConverter(**converter_kwargs)
        self.markdown_processor = MarkdownMermaidProcessor(self.base_converter)

    def convert_file(
        self,
        input_file: str,
        output_file: Optional[str] = None,
        process_markdown: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Convert input file based on its type.

        Args:
            input_file: Input file path
            output_file: Output file path (optional)
            process_markdown: Whether to process as Markdown file
            **kwargs: Additional options for Markdown processing

        Returns:
            Conversion results
        """
        input_path = Path(input_file)

        # Determine processing mode
        if input_path.suffix.lower() == ".md" or process_markdown:
            return self.markdown_processor.process_markdown_file(
                output_dir=kwargs.get("output_dir"),
                replace_blocks=kwargs.get("replace_blocks", False),
            )
        else:
            # Single Mermaid file conversion
            if output_file is None:
                output_file = input_path.with_suffix(".png")

            with open(input_file, "r", encoding="utf-8") as f:
                mermaid_code = f.read()

            result = self.base_converter.convert_and_save(mermaid_code, output_file)

            return {
                "file": input_file,
                "output_file": output_file,
                "file_size": result.file_size,
                "execution_time": result.execution_time,
            }

    def batch_convert(self, files: List[str], **kwargs) -> Dict[str, Any]:
        results = {}

        for file_path in files:
            try:
                path = Path(file_path)
                if path.suffix.lower() == ".md":
                    results[file_path] = self.convert_file(
                        file_path, process_markdown=True, **kwargs
                    )
                else:
                    results[file_path] = self.convert_file(file_path, **kwargs)
            except Exception as e:
                results[file_path] = {"success": False, "error": str(e)}

        return results

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.base_converter.cleanup()
